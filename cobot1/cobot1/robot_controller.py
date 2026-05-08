#!/usr/bin/env python3
"""
==============================================================================
[Phase 5] 나만의 도련님 도시락 - 로봇 컨트롤러 (스레드 통합)
==============================================================================
RobotStateManager / RobotClient / OrderRepository / Stage 들을 조합.
스레드 라이프사이클을 명확히 관리.

스레드 구조:
  ┌─ ros_spin_thread      : ROS2 executor.spin()
  ├─ task_thread          : 주문 큐 소비 + 5 Stage 실행  (DSR API 호출)
  ├─ status_upload_thread : 1초마다 Firebase 상태 업로드
  └─ collision_monitor    : 0.5초마다 로봇 상태 감시
==============================================================================
"""

import queue
import threading
import time
import math
from typing import Optional

import json

import rclpy
from rclpy.executors import MultiThreadedExecutor
from std_msgs.msg import String

# 🚨 [추가됨] rqt 하드웨어 자동 복구 서비스
from dsr_msgs2.srv import SetRobotControl

from .state_manager     import RobotStateManager, RobotState
from .robot_client      import RobotClient
from .coordinate_manager import CoordinateManager
from .repositories       import Order, OrderRepository
from .stages import (
    TraySetupStage,
    SubDishStage,
    MainDishStage,
    RiceStage,
    DeliveryStage,
    StageResult,
)

# ── 상수 ──────────────────────────────────────────────────────────────────
STATUS_UPLOAD_INTERVAL_SEC:     float = 1.0
STATUS_ERROR_RETRY_SEC:         float = 5.0
COLLISION_MONITOR_INTERVAL_SEC: float = 0.3   # 충돌 감시 주기 (조금 더 빠르게)
TASK_ERROR_RETRY_SEC:           float = 1.0
ROS_EXECUTOR_THREADS:           int   = 4
COLLISION_STATES                      = {3, 5, 6, 7}
ROBOT_STATE_STANDBY:            int   = 1


class RobotController:
    def __init__(
        self,
        node,
        state_mgr:    RobotStateManager,
        robot_client: RobotClient,
        coord_mgr:    CoordinateManager,
        order_repo:   OrderRepository,
    ):
        self.node    = node
        self.sm      = state_mgr
        self.rc      = robot_client
        self.cm      = coord_mgr
        self.repo    = order_repo

        self._order_queue: queue.Queue  = queue.Queue()
        self._cmd_queue:   queue.Queue  = queue.Queue()
        self._running      = threading.Event()
        self._init_event   = threading.Event()
        self._init_ok:     bool         = False

        # 🚨 [추가됨] 일시정지, 주문 복구, 복구 클라이언트
        self.last_failed_order = None
        self.last_failed_order = None
        self.recover_client = self.node.create_client(SetRobotControl, '/dsr01/system/set_robot_control')

        self._t_spin:    Optional[threading.Thread] = None
        self._t_task:    Optional[threading.Thread] = None
        self._t_status:  Optional[threading.Thread] = None
        self._t_monitor: Optional[threading.Thread] = None

    def start(self) -> bool:
        self._running.set()
        self._t_spin = threading.Thread(target=self._ros_spin_loop, name="ros_spin", daemon=False)
        self._t_spin.start()

        self.node.create_subscription(String, '/robot_order', self._on_ros_order_msg, 10)
        self.node.get_logger().info("/robot_order 토픽 구독 등록")

        self.repo.listen_commands(self._on_command_received)

        self._t_task = threading.Thread(target=self._task_loop, name="task", daemon=False)
        self._t_status = threading.Thread(target=self._status_upload_loop, name="status_upload", daemon=True)
        self._t_monitor = threading.Thread(target=self._collision_monitor_loop, name="collision_monitor", daemon=True)

        self._t_task.start()
        self._t_status.start()
        self._t_monitor.start()

        if not self._init_event.wait(timeout=30.0):
            self.node.get_logger().error("초기화 타임아웃 (30초) → 종료")
            self.stop()
            return False
        if not self._init_ok:
            self.stop()
            return False

        self.node.get_logger().info("✅ 모든 스레드 시작 완료")
        return True

    def join(self) -> None:
        if self._t_task: self._t_task.join()
        if self._t_spin: self._t_spin.join()

    def stop(self) -> None:
        self._running.clear()
        if rclpy.ok(): rclpy.shutdown()

    def _on_ros_order_msg(self, msg: String) -> None:
        try:
            data = json.loads(msg.data)
            order = Order(
                key        = data.get('_key', ''),
                sub_dishes = data.get('sub_dishes', []),
                main_dish  = data.get('main_dish', ''),
            )
            if order.key:
                self._on_order_received(order)
        except Exception as e:
            self.node.get_logger().error(f"/robot_order 파싱 오류: {e}")

    def _on_order_received(self, order: Order) -> None:
        if self.sm.is_order_processed(order.key): return
        self.sm.mark_order_processed(order.key)
        self._order_queue.put(order)
        self.node.get_logger().info(f"주문 큐 추가: {order.key}")

    def _on_command_received(self, cmd_type: str) -> None:
        self.node.get_logger().info(f"명령 수신: {cmd_type}")
        self._handle_command(cmd_type)

    def _handle_command(self, cmd_type: str) -> None:
        if cmd_type == "emergency_stop":
            self.rc.do_stop()
            self.sm.trigger_emergency_stop()

        # 🚨 [추가됨] 일시정지 및 자동 복구 로직
        elif cmd_type == "pause":
            self.node.get_logger().info("⏸️ 시스템 일시 정지")
            self.sm.set_pause() # 🚨 변경됨
            self.rc.do_stop()
            self.sm.update_status(state=RobotState.IDLE, current_task="⏸️ 일시 정지됨")

        elif cmd_type == "resume":
            self.node.get_logger().info("▶️ 작업 재개")
            self.sm.clear_pause() # 🚨 변경됨
            if self.sm.is_stopped():
                self.sm.clear_emergency_stop()
            self.sm.update_status(state=RobotState.MOVING, current_task="작업 재개 중...")

        elif cmd_type == "reset_and_restart":
            self.node.get_logger().info("🔄 충돌 해제 및 주문 1단계부터 재시작 시도")
            
            if self.recover_client.wait_for_service(timeout_sec=1.0):
                req = SetRobotControl.Request()
                req.robot_control = 2
                self.recover_client.call_async(req)
                time.sleep(1.0)
            
            self.sm.clear_emergency_stop()
            self.is_paused = False
            
            if self.last_failed_order:
                self.node.get_logger().info(f"🚀 재시작할 주문 큐에 삽입: {self.last_failed_order.key}")
                self.last_failed_order.target_stage = 1
                self._order_queue.put(self.last_failed_order)
                self.last_failed_order = None
            
            self.sm.update_status(state=RobotState.IDLE, current_task="대기 중")

        elif cmd_type in ("move_home", "gripper_open", "gripper_close", "gripper_full_open"):
            self._cmd_queue.put(cmd_type)

    def _process_order(self, order: Order) -> None:
        key = order.key
        self.node.get_logger().info(f"===== 주문 시작: {key} =====")
        valid_subs = [d for d in order.sub_dishes[:4] if d in self.cm.available_sub_dishes()]
        n_sub = len(valid_subs)
        self.sm.reset_progress(8 + (7 * n_sub) + 11 + 13 + 10)
        self.sm.update_status(state=RobotState.MOVING, current_task="주문 처리 시작")
        self.repo.mark_processing(key)

        def should_run(stage_num: int) -> bool:
            if order.target_stage == 0: return True
            if order.run_mode == "only": return stage_num == order.target_stage
            return stage_num >= order.target_stage

        # 🚨 [추가됨] 실행 전 정지 검사 함수
        def check_stop():
            if self.sm.is_stopped():
                raise InterruptedError("외력 감지로 인한 강제 취소")
            while getattr(self, 'is_paused', False):
                time.sleep(0.5)

        try:
            if should_run(1):
                check_stop()
                result = TraySetupStage(self.sm, self.rc, self.cm).execute()
                if result == StageResult.STOPPED: check_stop()
                if result != StageResult.SUCCESS: raise RuntimeError(f"Stage1 실패: {result}")
            else:
                self.sm.add_step_log("⏭️ [1/5] 식판 세팅 건너뜀", completed=True)

            if should_run(2):
                for idx, dish in enumerate(valid_subs):
                    check_stop()
                    self.sm.update_status(current_task=f"🥗 [2/5] 서브 {idx+1}/{n_sub} - [{dish}]")
                    result = SubDishStage(self.sm, self.rc, self.cm, dish).execute()
                    if result == StageResult.STOPPED: check_stop()
                    if result != StageResult.SUCCESS: raise RuntimeError(f"Stage2 실패: {dish} {result}")
            else:
                self.sm.add_step_log("⏭️ [2/5] 서브 반찬 건너뜀", completed=True)

            if should_run(3):
                check_stop()
                result = MainDishStage(self.sm, self.rc, self.cm, order.main_dish).execute()
                if result == StageResult.STOPPED: check_stop()
                if result != StageResult.SUCCESS: raise RuntimeError(f"Stage3 실패: {result}")
            else:
                self.sm.add_step_log("⏭️ [3/5] 메인 반찬 건너뜀", completed=True)

            if should_run(4):
                check_stop()
                result = RiceStage(self.sm, self.rc, self.cm).execute()
                if result == StageResult.STOPPED: check_stop()
                if result != StageResult.SUCCESS: raise RuntimeError(f"Stage4 실패: {result}")
            else:
                self.sm.add_step_log("⏭️ [4/5] 밥 담기 건너뜀", completed=True)

            if should_run(5):
                check_stop()
                result = DeliveryStage(self.sm, self.rc, self.cm).execute()
                if result == StageResult.STOPPED: check_stop()
                if result != StageResult.SUCCESS: raise RuntimeError(f"Stage5 실패: {result}")
            else:
                self.sm.add_step_log("⏭️ [5/5] 식판 배달 건너뜀", completed=True)

            self.sm.update_status(state=RobotState.IDLE, current_task="대기 중", progress=100, current_step="완료")
            self.sm.add_step_log("🎉 주문 완료!", completed=True)
            self.repo.mark_completed(key)
            self.node.get_logger().info(f"✅ 주문 완료: {key}")

        # 🚨 [추가됨] 예외 시 실패 주문 저장
        except InterruptedError:
            self.node.get_logger().warn(f"🛑 충돌로 인해 주문 취소됨. 임시 저장합니다.")
            self.sm.add_step_log("🛑 외력 감지/일시정지로 주문이 중단되었습니다.")
            self.repo.mark_error(key)
            self.last_failed_order = order 

        except Exception as e:
            self.node.get_logger().error(f"❌ 주문 오류: {e}")
            self.sm.add_step_log(f"❌ 오류: {e}")
            self.repo.mark_error(key)
            self.sm.update_status(state=RobotState.ERROR, current_task=f"오류: {e}")

    def _execute_cmd(self, cmd_type: str) -> None:
        if cmd_type == "move_home":
            self.sm.update_status(state=RobotState.MOVING, current_task="홈 이동 중")
            self.rc.do_movej(self.cm.home_joint())
            self.sm.update_status(state=RobotState.IDLE, current_task="대기 중")
        elif cmd_type == "gripper_open":
            self.rc.set_gripper(50)
        elif cmd_type == "gripper_close":
            self.rc.set_gripper(5)
        elif cmd_type == "gripper_full_open":
            self.rc.set_gripper(100)

    def _task_loop(self) -> None:
        self.node.get_logger().info("홈 위치 초기화 중...")
        try:
            from DSR_ROBOT2 import set_tool, set_tcp
            set_tool(self.cm.tool)
            set_tcp(self.cm.tcp)
            self.rc.do_movej(self.cm.home_joint())
            self.rc.set_gripper(100)
            self.node.get_logger().info("✅ 홈 이동 완료")
            self._init_ok = True
        except Exception as e:
            self.node.get_logger().error(f"❌ 홈 이동 실패: {e}")
            self._init_ok = False
        finally:
            self._init_event.set() 

        if not self._init_ok: return

        self.node.get_logger().info("작업 스레드 시작")
        self.sm.update_status(state=RobotState.IDLE, current_task="대기 중")

        while rclpy.ok() and self._running.is_set():
            while not self._cmd_queue.empty():
                try: self._execute_cmd(self._cmd_queue.get_nowait())
                except queue.Empty: break

            try:
                order = self._order_queue.get(timeout=0.5)
                self._process_order(order)
            except queue.Empty: continue
            except Exception as e:
                self.node.get_logger().error(f"작업 루프 오류: {e}")
                self.sm.update_status(state=RobotState.ERROR, current_task=f"오류: {e}")
                time.sleep(TASK_ERROR_RETRY_SEC)

    def _ros_spin_loop(self) -> None:
        self.node.get_logger().info("spin 스레드 시작")
        try:
            executor = MultiThreadedExecutor(num_threads=ROS_EXECUTOR_THREADS)
            executor.add_node(self.node)
            executor.spin()
        except Exception as e:
            if rclpy.ok(): self.node.get_logger().error(f"spin 오류: {e}")

    def _status_upload_loop(self) -> None:
        while rclpy.ok() and self._running.is_set():
            try:
                payload = self.sm.get_status_dict()
                
                # 🚨 변경됨: sm.is_paused() 사용
                if self.sm.is_paused():
                    payload['state'] = 'paused'
                elif self.sm.is_stopped():
                    payload['state'] = 'collision'

                self.repo.upload_robot_status(payload)
            except Exception as e:
                self.node.get_logger().error(f"상태 업로드 오류: {e}")
                time.sleep(STATUS_ERROR_RETRY_SEC)
                continue
            time.sleep(STATUS_UPLOAD_INTERVAL_SEC)

    def _collision_monitor_loop(self) -> None:
        _in_collision = False
        COLLISION_THRESHOLD = 20.0
        FORCE_THRESHOLD     = 20.0
        FORCE_Z_THRESHOLD   = 15.0

        while rclpy.ok() and self._running.is_set():
            try:
                state = self.rc.get_robot_state()
                hard_collision = state in COLLISION_STATES
                soft_collision = False
                collision_reason = ""

                # 🚨 [추가됨] 능동형 외력 감지 (get_tool_force 방어코드 포함)
                if not hard_collision and not _in_collision:
                    force = getattr(self.rc, 'get_tool_force', lambda: [])()
                    if force and len(force) >= 3:
                        f_tot = math.sqrt(force[0]**2 + force[1]**2 + force[2]**2)
                        if f_tot > FORCE_THRESHOLD:
                            soft_collision, collision_reason = True, f"TCP 합력 초과 ({f_tot:.1f}N)"
                        elif abs(force[2]) > FORCE_Z_THRESHOLD:
                            soft_collision, collision_reason = True, f"Z축 외력 초과 ({force[2]:.1f}N)"

                    if not soft_collision:
                        torque = getattr(self.rc, 'get_external_torque', lambda: [])()
                        if torque:
                            for i, v in enumerate(torque):
                                if abs(v) > COLLISION_THRESHOLD:
                                    soft_collision, collision_reason = True, f"J{i+1} 토크 초과 ({v:.1f}Nm)"
                                    break

                if (hard_collision or soft_collision) and not _in_collision:
                    _in_collision = True
                    reason = collision_reason if soft_collision else f"하드웨어 정지 (state={state})"

                    self.node.get_logger().error(f"🚨 충돌 감지: {reason}")
                    self.rc.do_stop()
                    self.sm.trigger_emergency_stop()

                    self.sm.update_status(state=RobotState.ERROR, current_task=f"🚨 충돌 감지: {reason}")
                    
                    payload = self.sm.get_status_dict()
                    payload['state'] = 'collision'
                    self.repo.upload_robot_status(payload)

                    self.node.get_logger().info("⏳ 외력 감지! 3초 뒤에 홈(Home) 자세로 복귀합니다...")
                    time.sleep(3.0)
                    self.node.get_logger().info("🏠 홈(Home) 자세로 대피를 시작합니다.")

                    # 대피 전 안전을 위해 제어기 에러 리셋 시도
                    if hard_collision and self.recover_client.wait_for_service(timeout_sec=0.5):
                        req = SetRobotControl.Request()
                        req.robot_control = 2
                        self.recover_client.call_async(req)
                        time.sleep(0.5)

                    self.rc.do_movej(self.cm.home_joint())

                elif state == ROBOT_STATE_STANDBY and not soft_collision and _in_collision:
                    self.node.get_logger().info("✅ 로봇 STANDBY 복귀")
                    _in_collision = False

            except Exception as e:
                pass
            time.sleep(COLLISION_MONITOR_INTERVAL_SEC)