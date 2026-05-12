#!/usr/bin/env python3
"""
==============================================================================
[Phase 5] 나만의 도련님 도시락 - 로봇 컨트롤러 (최종 통합본)
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

# 🚨 rqt 하드웨어 자동 복구 서비스
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
COLLISION_MONITOR_INTERVAL_SEC: float = 0.3   
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

        # 🚨 [수정] 일시정지 상태 및 복구 클라이언트 초기화
        self._test_cancel = threading.Event()  # 테스트 전용 중단 플래그
        self.last_failed_order = None
        self._in_delivery_stage5 = False  # Stage 5 배달 진행 중 여부 (비상정지 재개 분기용)
        self.recover_client = self.node.create_client(SetRobotControl, '/dsr01/system/set_robot_control')
        self._status_pub      = self.node.create_publisher(String, '/robot_status', 10)
        self._tcp_pub         = self.node.create_publisher(String, '/robot_tcp_posx', 10)
        self._target_posj_pub = self.node.create_publisher(String, '/robot_target_posj', 10)
        self._torque_pub      = self.node.create_publisher(String, '/robot_torque', 10)
        self._seg_pub         = self.node.create_publisher(String, '/robot_motion_segment', 10)
        self._order_status_pub = self.node.create_publisher(String, '/order_status', 10)

        self._t_spin:    Optional[threading.Thread] = None
        self._t_task:    Optional[threading.Thread] = None
        self._t_status:  Optional[threading.Thread] = None
        self._t_monitor: Optional[threading.Thread] = None

    def start(self) -> bool:
        """ROS2 스핀·작업·상태업로드·충돌감지 스레드를 모두 시작하고 초기화 완료를 기다린다.

        Returns:
            bool: 초기화(홈 이동 포함) 성공 시 True, 타임아웃 또는 실패 시 False.
        """
        self._running.set()
        self._t_spin = threading.Thread(target=self._ros_spin_loop, name="ros_spin", daemon=False)
        self._t_spin.start()

        self.node.create_subscription(String, '/robot_order', self._on_ros_order_msg, 10)
        self.node.get_logger().info("/robot_order 토픽 구독 등록")

        self.repo.listen_commands(self._on_command_received)

        if hasattr(self.repo, 'listen_test_command'):
            self.repo.listen_test_command(self._on_test_command_received)

        self._t_task = threading.Thread(target=self._task_loop, name="task", daemon=False)
        self._t_status = threading.Thread(target=self._status_upload_loop, name="status_upload", daemon=True)
        self._t_monitor = threading.Thread(target=self._collision_monitor_loop, name="collision_monitor", daemon=True)
        self._t_torque = threading.Thread(target=self._torque_publish_loop, name="torque_pub", daemon=True)

        self._t_task.start()
        self._t_status.start()
        self._t_monitor.start()
        self._t_torque.start()

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
        """작업 스레드와 ROS 스핀 스레드가 종료될 때까지 블로킹 대기한다.

        Returns:
            None
        """
        if self._t_task: self._t_task.join()
        if self._t_spin: self._t_spin.join()

    def stop(self) -> None:
        """실행 플래그를 해제하고 rclpy를 종료해 모든 루프를 중단시킨다.

        Returns:
            None
        """
        self._running.clear()
        if rclpy.ok(): rclpy.shutdown()

    def _on_ros_order_msg(self, msg: String) -> None:
        """'/robot_order' ROS 토픽 콜백 — JSON 문자열을 Order 객체로 파싱해 큐에 적재한다.

        Args:
            msg (String): JSON 형식의 주문 데이터 ({_key, sub_dishes, main_dish}).
        Returns:
            None
        """
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
        """중복 수신을 방지하며 Order를 처리 큐에 삽입한다.

        Args:
            order (Order): 수신된 주문 객체.
        Returns:
            None  (이미 처리된 key면 즉시 반환)
        """
        if self.sm.is_order_processed(order.key): return
        self.sm.mark_order_processed(order.key)
        self._order_queue.put(order)
        self.node.get_logger().info(f"주문 큐 추가: {order.key}")

    def _on_command_received(self, cmd_type: str) -> None:
        """Firebase 명령 콜백 — pause/resume은 즉시 처리하고 나머지는 작업 스레드(cmd_queue)에 위임한다.

        Args:
            cmd_type (str): 명령 문자열 (예: 'pause', 'resume', 'emergency_stop', 'move_home' 등).
        Returns:
            None
        """
        self.node.get_logger().info(f"명령 수신: {cmd_type}")
        # pause/resume 플래그는 즉시 세팅해야 진행 중인 스테이지가 wait_if_paused()에서 멈춤.
        # do_stop() 등 rclpy spin을 유발하는 호출은 _cmd_queue로 task 스레드에 위임.
        if cmd_type == "pause":
            self.sm.set_pause()
            self.sm.update_status(state=RobotState.IDLE, current_task="⏸️ 일시 정지됨")
            self._cmd_queue.put("pause_stop")  # do_stop()만 task 스레드에서 처리
        elif cmd_type == "resume":
            self.sm.clear_pause()
            if self.sm.is_stopped():
                self.sm.clear_emergency_stop()
            # Stage 5 배달 중 비상정지였으면 토크 판별 재개 경로로 분기
            if self._in_delivery_stage5:
                self.sm.update_status(state=RobotState.MOVING, current_task="📦 배달 재개 - 파지 상태 확인 중")
                self._cmd_queue.put("delivery_estop_resume")
            else:
                self.sm.update_status(state=RobotState.MOVING, current_task="작업 재개 중...")
        else:
            self._cmd_queue.put(cmd_type)

    # ── 테스트 모드 ───────────────────────────────────────────────
    def _on_test_command_received(self, payload: dict) -> None:
        """테스트 전용 커맨드 콜백 — 초기화 완료 후 테스트 시나리오를 주문 큐에 삽입한다.

        Args:
            payload (dict): 시나리오 정보 (scenario, repeat, stage_from, stage_to, main_dish, sub_dishes).
        Returns:
            None
        """
        self._init_event.wait()
        if not self._init_ok:
            self.node.get_logger().warn("테스트 커맨드 무시: 초기화 실패 상태")
            return
        self.node.get_logger().info(f"테스트 커맨드 처리: {payload}")
        self._order_queue.put(("__test__", payload))

    def _run_test_scenario(self, payload: dict) -> None:
        """payload에 명시된 시나리오를 repeat 횟수만큼 반복 실행한다.

        Args:
            payload (dict): {scenario, repeat, stage_from, stage_to, main_dish, sub_dishes}.
        Returns:
            None  (중단 또는 오류 시 홈 복귀 후 IDLE 상태로 전환)
        """
        scenario    = payload.get("scenario", "stage_only")
        repeat      = max(1, int(payload.get("repeat", 1)))
        stage_from  = int(payload.get("stage_from", 1))
        stage_to    = int(payload.get("stage_to", 5))
        main_dish   = payload.get("main_dish", "돈까스")
        sub_dishes  = payload.get("sub_dishes", ["피클", "단무지", "김치"])

        self._test_cancel.clear()
        self.sm.update_status(state=RobotState.MOVING,
                              current_task=f"🧪 테스트모드: {scenario} × {repeat}회")
        self.node.get_logger().info(f"🧪 테스트 시작: {scenario} × {repeat}회")

        cancelled = False
        try:
            for i in range(repeat):
                if self._test_cancel.is_set():
                    cancelled = True
                    break
                self.sm.add_step_log(f"🧪 [{i+1}/{repeat}] {scenario} 시작")
                self.sm.wait_if_paused()

                if scenario == "stage_only":
                    dummy_order = Order(
                        key=f"__test_{i}__",
                        sub_dishes=sub_dishes,
                        main_dish=main_dish,
                        target_stage=stage_from,
                        run_mode="only" if stage_from == stage_to else "from",
                        status="pending",
                    )
                    self._process_test_stages(dummy_order, stage_from, stage_to)

                elif scenario == "tong_pick_place":
                    self._run_tong_pick_place()

                elif scenario == "main_dish_full":
                    self._run_main_dish_full(main_dish)

                elif scenario == "rice_full":
                    dummy_order = Order(
                        key=f"__test_{i}__",
                        sub_dishes=[], main_dish="",
                        target_stage=4, run_mode="only",
                    )
                    self._process_test_stages(dummy_order, 4, 4)

                elif scenario == "delivery_full":
                    dummy_order = Order(
                        key=f"__test_{i}__",
                        sub_dishes=[], main_dish="",
                        target_stage=5, run_mode="only",
                    )
                    self._process_test_stages(dummy_order, 5, 5)

                if self._test_cancel.is_set():
                    cancelled = True
                    break

                self.sm.add_step_log(f"✅ [{i+1}/{repeat}] 완료")

        except Exception as e:
            self.node.get_logger().error(f"테스트 오류: {e}")
            self.sm.add_step_log(f"❌ 테스트 오류: {e}")
            cancelled = True

        if cancelled:
            self.node.get_logger().info("🧪 테스트 중단 → 홈 복귀")
            self.sm.add_step_log("🛑 테스트 중단 → 홈 복귀 중...")
            self.sm.update_status(state=RobotState.MOVING, current_task="🛑 테스트 중단 - 홈 복귀 중")
            try:
                self.rc.do_movej(self.cm.home_joint())
                self.rc.set_gripper(100)
            except Exception:
                pass
            self.sm.add_step_log("🏠 홈 복귀 완료")
        else:
            self.node.get_logger().info("🧪 테스트 완료")

        self._test_cancel.clear()
        self.sm.update_status(state=RobotState.IDLE, current_task="대기 중")

    def _process_test_stages(self, order: Order, stage_from: int, stage_to: int) -> None:
        """stage_from~stage_to 범위의 스테이지만 선택적으로 실행한다.

        Args:
            order (Order): 실행할 주문 객체 (sub_dishes, main_dish 포함).
            stage_from (int): 시작 스테이지 번호 (1~5).
            stage_to (int): 종료 스테이지 번호 (1~5).
        Returns:
            None  (실패 시 RuntimeError 발생)
        """
        valid_subs = [d for d in order.sub_dishes[:4] if d in self.cm.available_sub_dishes()]

        def should_run(n):
            return stage_from <= n <= stage_to

        def check_stop():
            if self._test_cancel.is_set(): raise InterruptedError("테스트 중단 요청")
            if self.sm.is_stopped(): raise InterruptedError("테스트 중단")
            self.sm.wait_if_paused()

        if should_run(1):
            check_stop()
            result = TraySetupStage(self.sm, self.rc, self.cm).execute()
            if result != StageResult.SUCCESS: raise RuntimeError(f"Stage1 실패")
        if should_run(2):
            for idx, dish in enumerate(valid_subs):
                check_stop()
                result = SubDishStage(self.sm, self.rc, self.cm, dish, slot_index=idx,
                                     seg_publish_fn=self._seg_publish).execute()
                if result != StageResult.SUCCESS: raise RuntimeError(f"Stage2 실패: {dish}")
        if should_run(3):
            check_stop()
            result = MainDishStage(self.sm, self.rc, self.cm, order.main_dish).execute()
            if result != StageResult.SUCCESS: raise RuntimeError(f"Stage3 실패")
        if should_run(4):
            check_stop()
            result = RiceStage(self.sm, self.rc, self.cm).execute()
            if result != StageResult.SUCCESS: raise RuntimeError(f"Stage4 실패")
        if should_run(5):
            check_stop()
            result = DeliveryStage(self.sm, self.rc, self.cm).execute()
            if result != StageResult.SUCCESS: raise RuntimeError(f"Stage5 실패")

    def _run_tong_pick_place(self) -> None:
        """집게를 집어 들고 다시 원위치에 내려놓는 동작만 수행한다 (Stage3 부분 모션 검증용).

        Args:
            없음
        Returns:
            None
        """
        c3   = self.cm.stage(3)
        home = self.cm.home_joint()
        self.sm.update_status(current_task="🧪 집게 Pick & Place")
        self.rc.do_movej(home)
        self.rc.set_gripper(100)
        self.rc.do_movel(c3["tong_approach_l"])   # 집게 위 접근
        self.rc.set_gripper(30)                    # 집게 잡기
        self.rc.do_movel(c3["tong_lift_l"])        # 집게 들고 위로
        self.rc.do_movel(c3["tong_return_above_l"]) # 집게 복귀 상단
        self.rc.do_movel(c3["tong_return_l"])      # 집게 내려놓기
        self.rc.set_gripper(100)
        self.rc.do_movej(home)

    def _run_main_dish_full(self, main_dish: str) -> None:
        """집게 집기부터 메인반찬 담기, 식판 투하, 집게 복귀까지 Stage3 전체를 실행한다.

        Args:
            main_dish (str): 담을 메인반찬 이름 (예: '돈까스').
        Returns:
            None  (실패 시 RuntimeError 발생)
        """
        result = MainDishStage(self.sm, self.rc, self.cm, main_dish).execute()
        if result != StageResult.SUCCESS:
            raise RuntimeError("Main dish 테스트 실패")

    def _process_order(self, order: Order) -> None:
        """단일 주문을 Stage 1~5 순서로 실행하고 완료/오류 상태를 Firebase에 반영한다.

        Args:
            order (Order): 처리할 주문 객체 (key, sub_dishes, main_dish, target_stage, run_mode).
        Returns:
            None  (충돌·예외 발생 시 mark_error 후 last_failed_order에 보존)
        """
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

        def check_stop():
            if self.sm.is_stopped():
                raise InterruptedError("외력 감지로 인한 강제 취소")
            # StateManager의 이벤트를 통해 대기
            self.sm.wait_if_paused()

        try:
            # ── Stage 1 : 식판 세팅 ──────────────────────────────
            if should_run(1):
                check_stop()
                result = TraySetupStage(self.sm, self.rc, self.cm).execute()
                if result == StageResult.STOPPED: check_stop()
                if result != StageResult.SUCCESS: raise RuntimeError(f"Stage1 실패: {result}")
            else:
                self.sm.add_step_log("⏭️ [1/5] 식판 세팅 건너뜀", completed=True)

            # ── Stage 2 : 서브 반찬 ──────────────────────────────
            if should_run(2):
                # 🚨 [수정] idx를 사용하여 slot_index 파라미터 전달
                for idx, dish in enumerate(valid_subs):
                    check_stop()
                    self.sm.update_status(current_task=f"🥗 [2/5] 서브 {idx+1}/{n_sub} - [{dish}]")
                    
                    result = SubDishStage(self.sm, self.rc, self.cm, dish, slot_index=idx,
                                         seg_publish_fn=self._seg_publish).execute()
                    
                    if result == StageResult.STOPPED: check_stop()
                    if result != StageResult.SUCCESS: raise RuntimeError(f"Stage2 실패: {dish} {result}")
            else:
                self.sm.add_step_log("⏭️ [2/5] 서브 반찬 건너뜀", completed=True)

            # ── Stage 3 : 메인 반찬 ──────────────────────────────
            if should_run(3):
                check_stop()
                result = MainDishStage(self.sm, self.rc, self.cm, order.main_dish).execute()
                if result == StageResult.STOPPED: check_stop()
                if result != StageResult.SUCCESS: raise RuntimeError(f"Stage3 실패: {result}")
            else:
                self.sm.add_step_log("⏭️ [3/5] 메인 반찬 건너뜀", completed=True)

            # ── Stage 4 : 밥 담기 ───────────────────────────────
            if should_run(4):
                check_stop()
                result = RiceStage(self.sm, self.rc, self.cm).execute()
                if result == StageResult.STOPPED: check_stop()
                if result != StageResult.SUCCESS: raise RuntimeError(f"Stage4 실패: {result}")
            else:
                self.sm.add_step_log("⏭️ [4/5] 밥 담기 건너뜀", completed=True)

            # ── Stage 5 : 식판 배달 ──────────────────────────────
            if should_run(5):
                check_stop()
                self._in_delivery_stage5 = True
                result = DeliveryStage(self.sm, self.rc, self.cm).execute()
                self._in_delivery_stage5 = False
                if result == StageResult.STOPPED: check_stop()
                if result != StageResult.SUCCESS: raise RuntimeError(f"Stage5 실패: {result}")
            else:
                self.sm.add_step_log("⏭️ [5/5] 식판 배달 건너뜀", completed=True)

            self.sm.update_status(state=RobotState.IDLE, current_task="대기 중", progress=100, current_step="완료")
            self.sm.add_step_log("🎉 주문 완료!", completed=True)
            self.repo.mark_completed(key)
            self._publish_order_status(key, 'completed')
            self.node.get_logger().info(f"✅ 주문 완료: {key}")

        except InterruptedError:
            self.node.get_logger().warn(f"🛑 충돌로 인해 주문 취소됨. 임시 저장합니다.")
            self.sm.add_step_log("🛑 외력 감지/일시정지로 주문이 중단되었습니다.")
            self.repo.mark_error(key)
            self._publish_order_status(key, 'error')
            self.last_failed_order = order 

        except Exception as e:
            self.node.get_logger().error(f"❌ 주문 오류: {e}")
            self.sm.add_step_log(f"❌ 오류: {e}")
            self.repo.mark_error(key)
            self._publish_order_status(key, 'error')
            self.sm.update_status(state=RobotState.ERROR, current_task=f"오류: {e}")

    def _seg_publish(self, payload: dict) -> None:
        """모션 세그먼트 이벤트를 /robot_motion_segment 토픽으로 발행."""
        msg = String()
        msg.data = json.dumps(payload, ensure_ascii=False)
        self._seg_pub.publish(msg)

    def _publish_order_status(self, key: str, status: str) -> None:
        """주문 처리 결과를 /order_status 토픽으로 발행 (lunchbox_database_node.py 모드 B 연동)."""
        msg = String()
        msg.data = json.dumps({'_key': key, 'status': status}, ensure_ascii=False)
        self._order_status_pub.publish(msg)

    def _handle_delivery_estop_resume(self) -> None:
        """
        Stage 5 배달 중 비상정지(외력 60N / state=3) 후 재개 버튼을 눌렀을 때 실행.
        토크 분류 결과에 따라:
          - 빈그리퍼          → 홈 복귀 후 last_failed_order를 1단계부터 재시작
          - 책받침 / 책받침+가득식판 → 홀더 초기위치 복귀 후 홈
        """
        self._in_delivery_stage5 = False
        stage = DeliveryStage(self.sm, self.rc, self.cm)
        result = stage.execute_after_estop_resume()

        if result == StageResult.STOPPED:
            # 빈그리퍼 → 1단계부터 재시작
            self.node.get_logger().info("📦 배달 재개: 빈그리퍼 → 1단계 재시작")
            if self.last_failed_order:
                self.last_failed_order.target_stage = 1
                self._order_queue.put(self.last_failed_order)
                self.last_failed_order = None
            self.sm.update_status(state=RobotState.IDLE, current_task="대기 중")
        elif result == StageResult.SUCCESS:
            self.node.get_logger().info("📦 배달 재개: 홀더 복귀 완료")
            if self.last_failed_order:
                self.repo.mark_error(self.last_failed_order.key)
                self.last_failed_order = None
            self.sm.update_status(state=RobotState.IDLE, current_task="대기 중")
        else:
            self.node.get_logger().error("📦 배달 재개 오류")
            self.sm.update_status(state=RobotState.ERROR, current_task="배달 재개 오류")

    def _execute_cmd(self, cmd_type: str) -> None:
        """작업 스레드에서 cmd_queue 아이템을 꺼내 해당 동작을 직접 실행한다 (DSR Rule 7).

        Args:
            cmd_type (str): 실행할 명령 문자열
                (emergency_stop | pause_stop | reset_and_restart |
                 test_cancel | move_home | gripper_open | gripper_close | gripper_full_open).
        Returns:
            None
        """
        if cmd_type == "emergency_stop":
            self.rc.do_stop()
            # collision monitor에서 큐로 보낸 경우 홈 복귀까지 처리
            time.sleep(3.0)
            try:
                self.rc.do_movej(self.cm.home_joint())
            except Exception:
                pass

        elif cmd_type == "pause_stop":
            # 플래그는 _on_command_received에서 이미 세팅됨. do_stop()만 여기서 처리.
            self.node.get_logger().info("⏸️ 로봇 정지 명령")
            self.rc.do_stop()

        elif cmd_type == "reset_and_restart":
            self.node.get_logger().info("🔄 충돌 해제 및 주문 1단계부터 재시작 시도")
            if self.recover_client.wait_for_service(timeout_sec=1.0):
                req = SetRobotControl.Request()
                req.robot_control = 2
                self.recover_client.call_async(req)
                time.sleep(1.0)
            self.sm.clear_emergency_stop()
            self.sm.clear_pause()
            if self.last_failed_order:
                self.node.get_logger().info(f"🚀 재시작할 주문 큐에 삽입: {self.last_failed_order.key}")
                self.last_failed_order.target_stage = 1
                self._order_queue.put(self.last_failed_order)
                self.last_failed_order = None
            self.sm.update_status(state=RobotState.IDLE, current_task="대기 중")

        elif cmd_type == "test_cancel":
            self.node.get_logger().info("🧪 테스트 중단 요청")
            self._test_cancel.set()
            self.rc.do_stop()

        elif cmd_type == "delivery_estop_resume":
            self._handle_delivery_estop_resume()

        elif cmd_type == "move_home":
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
        """홈 이동 초기화 후 주문 큐와 명령 큐를 순환 처리하는 메인 작업 스레드 루프.

        Args:
            없음  (self._order_queue, self._cmd_queue를 내부적으로 소비)
        Returns:
            None  (rclpy 종료 또는 _running 해제 시 자동 탈출)
        """
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
                item = self._order_queue.get(timeout=0.5)
                if isinstance(item, tuple) and item[0] == "__test__":
                    self._run_test_scenario(item[1])
                else:
                    self._process_order(item)
            except queue.Empty: continue
            except Exception as e:
                self.node.get_logger().error(f"작업 루프 오류: {e}")
                self.sm.update_status(state=RobotState.ERROR, current_task=f"오류: {e}")
                time.sleep(TASK_ERROR_RETRY_SEC)

    def _ros_spin_loop(self) -> None:
        """MultiThreadedExecutor로 ROS2 콜백을 전담 처리하는 스핀 스레드.

        Args:
            없음
        Returns:
            None  (rclpy 종료 시 자동 탈출)
        """
        self.node.get_logger().info("spin 스레드 시작")
        try:
            executor = MultiThreadedExecutor(num_threads=ROS_EXECUTOR_THREADS)
            executor.add_node(self.node)
            executor.spin()
        except Exception as e:
            if rclpy.ok(): self.node.get_logger().error(f"spin 오류: {e}")

    def _status_upload_loop(self) -> None:
        """1초 주기로 로봇 상태를 Firebase에 업로드하는 데몬 스레드.

        Args:
            없음  (sm.get_status_dict()로 상태를 수집, pause/collision 오버라이드 포함)
        Returns:
            None  (rclpy 종료 또는 _running 해제 시 자동 탈출)
        """
        while rclpy.ok() and self._running.is_set():
            try:
                payload = self.sm.get_status_dict()

                if self.sm.is_paused():
                    payload['state'] = 'paused'
                elif self.sm.is_stopped():
                    payload['state'] = 'collision'

                self.repo.upload_robot_status(payload)

                # /robot_status 토픽으로도 발행 (대시보드 브릿지용)
                msg = String()
                msg.data = json.dumps(payload, ensure_ascii=False)
                self._status_pub.publish(msg)

                # TCP 위치 퍼블리시
                try:
                    from DSR_ROBOT2 import get_current_posx, DR_BASE
                    posx = get_current_posx(DR_BASE)[0]
                    tcp_msg = String()
                    tcp_msg.data = json.dumps(list(posx))
                    self._tcp_pub.publish(tcp_msg)
                except Exception:
                    pass

                # target_posj 퍼블리시 (현재 actual을 target으로 근사)
                try:
                    from DSR_ROBOT2 import get_current_posj
                    posj = get_current_posj()
                    tj_msg = String()
                    tj_msg.data = json.dumps([math.degrees(v) for v in posj])
                    self._target_posj_pub.publish(tj_msg)
                except Exception:
                    pass

                # 토크는 _torque_publish_loop에서 0.1초마다 별도 처리

            except Exception as e:
                self.node.get_logger().error(f"상태 업로드 오류: {e}")
                time.sleep(STATUS_ERROR_RETRY_SEC)
                continue
            time.sleep(STATUS_UPLOAD_INTERVAL_SEC)

    def _torque_publish_loop(self) -> None:
        while rclpy.ok() and self._running.is_set():
            try:
                torque = self.rc.get_external_torque()
                if torque:
                    safe = [0.0 if (v != v) else v for v in torque]
                    t_msg = String()
                    t_msg.data = json.dumps(safe)
                    self._torque_pub.publish(t_msg)
            except Exception:
                pass
            time.sleep(0.1)

    def _collision_monitor_loop(self) -> None:
        """0.3초 주기로 DSR 상태·TCP 힘·외부 토크를 감시하고 충돌 시 비상정지를 발동한다.

        Args:
            없음  (COLLISION_THRESHOLD=80Nm, FORCE_THRESHOLD=80N, FORCE_Z_THRESHOLD=60N 기준)
        Returns:
            None  (충돌 해제 후 홈 복귀 → _in_collision 플래그 초기화)
        """
        _in_collision = False
        COLLISION_THRESHOLD = 80.0
        FORCE_THRESHOLD     = 80.0
        FORCE_Z_THRESHOLD   = 60.0

        while rclpy.ok() and self._running.is_set():
            try:
                state = self.rc.get_robot_state()
                hard_collision = state in COLLISION_STATES
                soft_collision = False
                collision_reason = ""

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
                    # do_stop()/do_movej()는 drl_script_stop → rclpy.spin을 유발하므로
                    # collision monitor 스레드에서 직접 호출하지 않고 task 스레드 큐에 위임.
                    self.sm.trigger_emergency_stop()
                    self._cmd_queue.put("emergency_stop")

                    self.sm.update_status(state=RobotState.ERROR, current_task=f"🚨 충돌 감지: {reason}")

                    payload = self.sm.get_status_dict()
                    payload['state'] = 'collision'
                    self.repo.upload_robot_status(payload)

                elif state == ROBOT_STATE_STANDBY and not soft_collision and _in_collision:
                    self.node.get_logger().info("✅ 로봇 STANDBY 복귀")
                    _in_collision = False

            except Exception:
                pass
            time.sleep(COLLISION_MONITOR_INTERVAL_SEC)