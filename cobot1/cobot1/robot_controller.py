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
from typing import Optional

import json

import rclpy
from rclpy.executors import MultiThreadedExecutor
from std_msgs.msg import String

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


class RobotController:
    """
    의존성 주입으로 구성된 로봇 컨트롤러.

    Args:
        node        : rclpy 노드 (ROS spin 용)
        state_mgr   : RobotStateManager
        robot_client: RobotClient
        coord_mgr   : CoordinateManager
        order_repo  : OrderRepository (Firebase or Mock)
    """

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

        self._order_queue: queue.Queue = queue.Queue()
        self._running      = threading.Event()

        self._t_spin:    Optional[threading.Thread] = None
        self._t_task:    Optional[threading.Thread] = None
        self._t_status:  Optional[threading.Thread] = None
        self._t_monitor: Optional[threading.Thread] = None

    # ── 시작 / 종료 ───────────────────────────────────────────────
    def start(self):
        """모든 스레드 시작. 초기 홈 이동 성공 후에만 Firebase 리스너 등록."""
        self._running.set()

        # 1) ROS spin 먼저
        self._t_spin = threading.Thread(
            target=self._ros_spin_loop, name="ros_spin", daemon=False
        )
        self._t_spin.start()

        # 2) 초기 홈 이동
        print("[Controller] 홈 위치 초기화 중...")
        try:
            from DSR_ROBOT2 import set_tool, set_tcp
            set_tool(self.cm.tool)
            set_tcp(self.cm.tcp)
            self.rc.movej(self.cm.home_joint())
            self.rc.set_gripper(100)
            print("[Controller] ✅ 홈 이동 완료")
        except Exception as e:
            print(f"[Controller] ❌ 홈 이동 실패: {e} → 종료")
            self.stop()
            return False

        # 3) ROS 토픽 구독 (/robot_order from lunchbox_database_node)
        self.node.create_subscription(
            String, '/robot_order', self._on_ros_order_msg, 10
        )
        print("[Controller] /robot_order 토픽 구독 등록")

        # 4) Firebase 명령 리스너 등록 (명령은 Firebase 직접 유지)
        self.repo.listen_commands(self._on_command_received)

        # 5) 나머지 스레드 시작
        self._t_task = threading.Thread(
            target=self._task_loop, name="task", daemon=False
        )
        self._t_status = threading.Thread(
            target=self._status_upload_loop, name="status_upload", daemon=True
        )
        self._t_monitor = threading.Thread(
            target=self._collision_monitor_loop, name="collision_monitor", daemon=True
        )

        self._t_task.start()
        self._t_status.start()
        self._t_monitor.start()

        print("[Controller] ✅ 모든 스레드 시작 완료")
        return True

    def join(self):
        """task / spin 스레드 종료 대기."""
        if self._t_task:
            self._t_task.join()
        if self._t_spin:
            self._t_spin.join()

    def stop(self):
        self._running.clear()
        if rclpy.ok():
            rclpy.shutdown()

    # ── ROS 토픽 콜백 (/robot_order) ─────────────────────────────
    def _on_ros_order_msg(self, msg: String):
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
            print(f"[Controller] /robot_order 파싱 오류: {e}")

    # ── 콜백 (주문 수신 공통) ──────────────────────────────────────
    def _on_order_received(self, order: Order):
        if self.sm.is_order_processed(order.key):
            return
        self.sm.mark_order_processed(order.key)
        self._order_queue.put(order)
        print(f"[Controller] 주문 큐 추가: {order.key}")

    def _on_command_received(self, cmd_type: str):
        print(f"[Controller] 명령 수신: {cmd_type}")
        self._handle_command(cmd_type)

    # ── 명령 처리 ─────────────────────────────────────────────────
    def _handle_command(self, cmd_type: str):
        if cmd_type == "emergency_stop":
            self.rc.stop()
            self.sm.trigger_emergency_stop()

        elif cmd_type == "resume":
            if self.sm.is_stopped():
                self.sm.clear_emergency_stop()
                print("[Controller] ✅ 비상정지 해제 - 작업 재개 가능")

        elif cmd_type == "move_home":
            self.sm.update_status(
                state=RobotState.MOVING, current_task="홈 이동 중"
            )
            self.rc.movej(self.cm.home_joint())
            self.sm.update_status(state=RobotState.IDLE, current_task="대기 중")

        elif cmd_type == "gripper_open":
            self.rc.set_gripper(50)

        elif cmd_type == "gripper_close":
            self.rc.set_gripper(5)

        elif cmd_type == "gripper_full_open":
            self.rc.set_gripper(100)

    # ── 주문 처리 ─────────────────────────────────────────────────
    def _process_order(self, order: Order):
        key = order.key
        print(f"\n[Controller] ===== 주문 시작: {key} =====")
        print(f"  sub={order.sub_dishes}  main={order.main_dish}")

        valid_subs = [
            d for d in order.sub_dishes[:4]
            if d in self.cm.available_sub_dishes()
        ]

        # 진행률 계산 (스텝 수 합산)
        n_sub = len(valid_subs)
        total_steps = 8 + (7 * n_sub) + 11 + 13 + 10
        self.sm.reset_progress(total_steps)
        self.sm.update_status(
            state=RobotState.MOVING, current_task="주문 처리 시작"
        )
        self.repo.mark_processing(key)

        # 실행 여부 판별
        def should_run(stage_num: int) -> bool:
            if order.target_stage == 0:
                return True
            if order.run_mode == "only":
                return stage_num == order.target_stage
            return stage_num >= order.target_stage

        try:
            # ── Stage 1 : 식판 세팅 ──────────────────────────────
            if should_run(1):
                result = TraySetupStage(self.sm, self.rc, self.cm).execute()
                if result != StageResult.SUCCESS:
                    raise RuntimeError(f"Stage1 실패: {result}")
            else:
                self.sm.add_step_log("⏭️ [1/5] 식판 세팅 건너뜀", completed=True)

            # ── Stage 2 : 서브 반찬 ──────────────────────────────
            if should_run(2):
                for idx, dish in enumerate(valid_subs):
                    self.sm.update_status(
                        current_task=f"🥗 [2/5] 서브 {idx+1}/{n_sub} - [{dish}]"
                    )
                    result = SubDishStage(self.sm, self.rc, self.cm, dish).execute()
                    if result != StageResult.SUCCESS:
                        raise RuntimeError(f"Stage2 실패: {dish} {result}")
            else:
                self.sm.add_step_log("⏭️ [2/5] 서브 반찬 건너뜀", completed=True)

            # ── Stage 3 : 메인 반찬 ──────────────────────────────
            if should_run(3):
                result = MainDishStage(
                    self.sm, self.rc, self.cm, order.main_dish
                ).execute()
                if result != StageResult.SUCCESS:
                    raise RuntimeError(f"Stage3 실패: {result}")
            else:
                self.sm.add_step_log("⏭️ [3/5] 메인 반찬 건너뜀", completed=True)

            # ── Stage 4 : 밥 담기 ───────────────────────────────
            if should_run(4):
                result = RiceStage(self.sm, self.rc, self.cm).execute()
                if result != StageResult.SUCCESS:
                    raise RuntimeError(f"Stage4 실패: {result}")
            else:
                self.sm.add_step_log("⏭️ [4/5] 밥 담기 건너뜀", completed=True)

            # ── Stage 5 : 식판 배달 ──────────────────────────────
            if should_run(5):
                result = DeliveryStage(self.sm, self.rc, self.cm).execute()
                if result != StageResult.SUCCESS:
                    raise RuntimeError(f"Stage5 실패: {result}")
            else:
                self.sm.add_step_log("⏭️ [5/5] 식판 배달 건너뜀", completed=True)

            # ── 완료 ─────────────────────────────────────────────
            self.sm.update_status(
                state=RobotState.IDLE,
                current_task="대기 중",
                progress=100,
                current_step="완료",
            )
            self.sm.add_step_log("🎉 주문 완료!", completed=True)
            self.repo.mark_completed(key)
            print(f"[Controller] ✅ 주문 완료: {key}")

        except Exception as e:
            print(f"[Controller] ❌ 주문 오류: {e}")
            self.sm.add_step_log(f"❌ 오류: {e}")
            self.repo.mark_error(key)
            self.sm.update_status(
                state=RobotState.ERROR,
                current_task=f"오류: {e}",
            )

    # ── 작업 스레드 ───────────────────────────────────────────────
    def _task_loop(self):
        print("[Task] 작업 스레드 시작")
        self.sm.update_status(state=RobotState.IDLE, current_task="대기 중")

        while rclpy.ok() and self._running.is_set():
            try:
                order = self._order_queue.get(timeout=0.5)
                self._process_order(order)
            except queue.Empty:
                continue
            except Exception as e:
                print(f"[Task] 루프 오류: {e}")
                self.sm.update_status(
                    state=RobotState.ERROR, current_task=f"오류: {e}"
                )
                time.sleep(1.0)

        print("[Task] 작업 스레드 종료")

    # ── ROS spin 스레드 ───────────────────────────────────────────
    def _ros_spin_loop(self):
        print("[ROS] spin 스레드 시작")
        try:
            executor = MultiThreadedExecutor(num_threads=4)
            executor.add_node(self.node)
            executor.spin()
        except Exception as e:
            if rclpy.ok():
                self.node.get_logger().error(f"[ROS] spin 오류: {e}")
        finally:
            print("[ROS] spin 스레드 종료")

    # ── 상태 업로드 스레드 ────────────────────────────────────────
    def _status_upload_loop(self):
        while rclpy.ok() and self._running.is_set():
            try:
                payload = self.sm.get_status_dict()
                self.repo.upload_robot_status(payload)
            except Exception as e:
                print(f"[StatusUpload] 오류: {e}")
                time.sleep(5.0)
                continue
            time.sleep(1.0)

    # ── 충돌 감시 스레드 ──────────────────────────────────────────
    def _collision_monitor_loop(self):
        _in_collision = False
        while rclpy.ok() and self._running.is_set():
            try:
                state = self.rc.get_robot_state()
                if state in [3, 5, 6, 7]:
                    if not _in_collision:
                        print(f"🚨 충돌/비상정지 감지 state={state}")
                        _in_collision = True
                        self.sm.trigger_emergency_stop()
                        self.sm.update_status(
                            current_task="🚨 충돌 감지",
                        )
                elif state == 1 and _in_collision:
                    print("✅ 로봇 STANDBY 복귀 - 웹 재개 대기")
                    _in_collision = False
            except Exception:
                pass
            time.sleep(0.5)
