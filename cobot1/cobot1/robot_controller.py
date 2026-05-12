#!/usr/bin/env python3
"""
==============================================================================
[Fix] 나만의 도련님 도시락 - 로봇 컨트롤러 (generator 충돌 해결판)
==============================================================================
변경 요약 (이전 버전 대비):
  ★ start() 순서 재정렬:
      ① spin 스레드 시작 → 0.5초 대기 (executor 안정화)
      ② subscription / Firebase listener 등록
      ③ task 스레드만 먼저 시작 → 홈 이동 완료까지 대기 (_init_event)
      ④ 홈 이동 성공이 확인된 후에야 monitor/status/torque 스레드 시작
  → 홈 이동(첫 movej) 시점에는 RobotClient 락에 경쟁자가 없으므로 충돌 차단.

  ★ _task_loop 안에서 set_robot_mode(ROBOT_MODE_AUTONOMOUS) 호출
  → 작업 스레드에서만 DSR API 호출하는 규칙 준수.

  ★ _status_upload_loop: shutdown 직후 publish 시도 방지 가드 추가.
  ★ listen_orders 등록도 start()에 추가 (기존에 누락되어 있었음).
==============================================================================
"""

import queue
import threading
import time
import math
import json
from typing import Optional

import rclpy
from rclpy.executors import MultiThreadedExecutor
from std_msgs.msg import String

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
COLLISION_MONITOR_INTERVAL_SEC: float = 1.0   # 0.5 → 1.0 추가 완화
TORQUE_PUBLISH_INTERVAL_SEC:    float = 1.0   # 0.5 → 1.0 추가 완화
TASK_ERROR_RETRY_SEC:           float = 1.0
ROS_EXECUTOR_THREADS:           int   = 4
SPIN_STABILIZE_SEC:             float = 0.5
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

        self._test_cancel = threading.Event()
        self.last_failed_order = None
        self._in_delivery_stage5 = False
        self.recover_client = self.node.create_client(
            SetRobotControl, '/dsr01/system/set_robot_control')

        self._status_pub      = self.node.create_publisher(String, '/robot_status', 10)
        self._tcp_pub         = self.node.create_publisher(String, '/robot_tcp_posx', 10)
        self._target_posj_pub = self.node.create_publisher(String, '/robot_target_posj', 10)
        self._torque_pub      = self.node.create_publisher(String, '/robot_torque', 10)
        self._seg_pub         = self.node.create_publisher(String, '/robot_motion_segment', 10)

        self._t_spin:    Optional[threading.Thread] = None
        self._t_task:    Optional[threading.Thread] = None
        self._t_status:  Optional[threading.Thread] = None
        self._t_monitor: Optional[threading.Thread] = None
        self._t_torque:  Optional[threading.Thread] = None

    # ──────────────────────────────────────────────────────────────
    # 생명주기 (★★★ 핵심 수정 부분 ★★★)
    # ──────────────────────────────────────────────────────────────
    def start(self) -> bool:
        self._running.set()

        # ── ① spin 스레드 먼저 시작 + 안정화 대기 ─────────────────
        self._t_spin = threading.Thread(target=self._ros_spin_loop,
                                        name="ros_spin", daemon=False)
        self._t_spin.start()
        self.node.get_logger().info(
            f"spin 스레드 시작, {SPIN_STABILIZE_SEC}s 안정화 대기"
        )
        time.sleep(SPIN_STABILIZE_SEC)

        # ── ② subscription / listener 등록 (spin 가동 후) ─────────
        self.node.create_subscription(String, '/robot_order',
                                      self._on_ros_order_msg, 10)
        self.node.get_logger().info("/robot_order 토픽 구독 등록")

        # Firebase listener (있다면)
        try:
            self.repo.listen_orders(self._on_order_received)
        except Exception as e:
            self.node.get_logger().warn(f"listen_orders 등록 실패: {e}")

        self.repo.listen_commands(self._on_command_received)

        if hasattr(self.repo, 'listen_test_command'):
            self.repo.listen_test_command(self._on_test_command_received)

        # ── ③ task 스레드만 먼저 시작 → 홈 이동 완료까지 대기 ────
        self._t_task = threading.Thread(target=self._task_loop,
                                        name="task", daemon=False)
        self._t_task.start()

        if not self._init_event.wait(timeout=30.0):
            self.node.get_logger().error("초기화 타임아웃 (30초) → 종료")
            self.stop()
            return False
        if not self._init_ok:
            self.node.get_logger().error("홈 이동 실패 → 종료")
            self.stop()
            return False

        # ── ④ 홈 이동 완료 후에야 monitor/status/torque 스레드 시작 ─
        self.node.get_logger().info("홈 이동 완료 — 모니터 스레드 시작")
        self._t_status  = threading.Thread(target=self._status_upload_loop,
                                           name="status_upload", daemon=True)
        self._t_monitor = threading.Thread(target=self._collision_monitor_loop,
                                           name="collision_monitor", daemon=True)
        self._t_torque  = threading.Thread(target=self._torque_publish_loop,
                                           name="torque_pub", daemon=True)

        self._t_status.start()
        self._t_monitor.start()
        self._t_torque.start()

        self.node.get_logger().info("✅ 모든 스레드 시작 완료")
        return True

    def join(self) -> None:
        if self._t_task: self._t_task.join()
        if self._t_spin: self._t_spin.join()

    def stop(self) -> None:
        self._running.clear()
        if rclpy.ok(): rclpy.shutdown()

    # ──────────────────────────────────────────────────────────────
    # 주문 / 명령 수신
    # ──────────────────────────────────────────────────────────────
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
        if cmd_type == "pause":
            self.sm.set_pause()
            self.sm.update_status(state=RobotState.IDLE, current_task="⏸️ 일시 정지됨")
            self._cmd_queue.put("pause_stop")
        elif cmd_type == "resume":
            self.sm.clear_pause()
            if self.sm.is_stopped():
                self.sm.clear_emergency_stop()
            if self._in_delivery_stage5:
                self.sm.update_status(state=RobotState.MOVING,
                                      current_task="📦 배달 재개 - 파지 상태 확인 중")
                self._cmd_queue.put("delivery_estop_resume")
            else:
                self.sm.update_status(state=RobotState.MOVING, current_task="작업 재개 중...")
        else:
            self._cmd_queue.put(cmd_type)

    # ──────────────────────────────────────────────────────────────
    # 테스트 모드 (기존 그대로)
    # ──────────────────────────────────────────────────────────────
    def _on_test_command_received(self, payload: dict) -> None:
        self._init_event.wait()
        if not self._init_ok:
            self.node.get_logger().warn("테스트 커맨드 무시: 초기화 실패 상태")
            return
        self.node.get_logger().info(f"테스트 커맨드 처리: {payload}")
        self._order_queue.put(("__test__", payload))

    def _run_test_scenario(self, payload: dict) -> None:
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
        c3   = self.cm.stage(3)
        home = self.cm.home_joint()
        self.sm.update_status(current_task="🧪 집게 Pick & Place")
        self.rc.do_movej(home)
        self.rc.set_gripper(100)
        self.rc.do_movel(c3["tong_approach_l"])
        self.rc.set_gripper(30)
        self.rc.do_movel(c3["tong_lift_l"])
        self.rc.do_movel(c3["tong_return_above_l"])
        self.rc.do_movel(c3["tong_return_l"])
        self.rc.set_gripper(100)
        self.rc.do_movej(home)

    def _run_main_dish_full(self, main_dish: str) -> None:
        result = MainDishStage(self.sm, self.rc, self.cm, main_dish).execute()
        if result != StageResult.SUCCESS:
            raise RuntimeError("Main dish 테스트 실패")

    # ──────────────────────────────────────────────────────────────
    # 주문 처리 (기존 그대로)
    # ──────────────────────────────────────────────────────────────
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

        def check_stop():
            if self.sm.is_stopped():
                raise InterruptedError("외력 감지로 인한 강제 취소")
            self.sm.wait_if_paused()

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
                    result = SubDishStage(self.sm, self.rc, self.cm, dish, slot_index=idx,
                                         seg_publish_fn=self._seg_publish).execute()
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
                self._in_delivery_stage5 = True
                result = DeliveryStage(self.sm, self.rc, self.cm).execute()
                self._in_delivery_stage5 = False
                if result == StageResult.STOPPED: check_stop()
                if result != StageResult.SUCCESS: raise RuntimeError(f"Stage5 실패: {result}")
            else:
                self.sm.add_step_log("⏭️ [5/5] 식판 배달 건너뜀", completed=True)

            self.sm.update_status(state=RobotState.IDLE, current_task="대기 중",
                                  progress=100, current_step="완료")
            self.sm.add_step_log("🎉 주문 완료!", completed=True)
            self.repo.mark_completed(key)
            self.node.get_logger().info(f"✅ 주문 완료: {key}")

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

    def _seg_publish(self, payload: dict) -> None:
        if not rclpy.ok():
            return
        msg = String()
        msg.data = json.dumps(payload, ensure_ascii=False)
        self._seg_pub.publish(msg)

    def _handle_delivery_estop_resume(self) -> None:
        self._in_delivery_stage5 = False
        stage = DeliveryStage(self.sm, self.rc, self.cm)
        result = stage.execute_after_estop_resume()

        if result == StageResult.STOPPED:
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
        if cmd_type == "emergency_stop":
            self.rc.do_stop()
            time.sleep(3.0)
            try:
                self.rc.do_movej(self.cm.home_joint())
            except Exception:
                pass

        elif cmd_type == "pause_stop":
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

    # ──────────────────────────────────────────────────────────────
    # 메인 작업 루프 (★ set_robot_mode 호출 위치 변경)
    # ──────────────────────────────────────────────────────────────
    def _task_loop(self) -> None:
        self.node.get_logger().info("홈 위치 초기화 중...")
        try:
            # ★ set_robot_mode 를 작업 스레드에서 호출 (메인 스레드 X)
            from DSR_ROBOT2 import (
                set_tool, set_tcp, set_robot_mode, ROBOT_MODE_AUTONOMOUS,
            )
            try:
                set_robot_mode(ROBOT_MODE_AUTONOMOUS)
                self.node.get_logger().info("set_robot_mode(AUTONOMOUS) 완료")
            except Exception as e:
                self.node.get_logger().warn(f"set_robot_mode 실패 (계속 진행): {e}")

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
        try:
            executor = MultiThreadedExecutor(num_threads=ROS_EXECUTOR_THREADS)
            executor.add_node(self.node)
            executor.spin()
        except Exception as e:
            if rclpy.ok(): self.node.get_logger().error(f"spin 오류: {e}")

    # ──────────────────────────────────────────────────────────────
    # 상태 업로드 (★ motion_active 체크 + shutdown 가드)
    # ──────────────────────────────────────────────────────────────
    def _status_upload_loop(self) -> None:
        while rclpy.ok() and self._running.is_set():
            try:
                if not rclpy.ok():
                    break

                payload = self.sm.get_status_dict()

                if self.sm.is_paused():
                    payload['state'] = 'paused'
                elif self.sm.is_stopped():
                    payload['state'] = 'collision'

                # Firebase 업로드와 /robot_status publish 는 모션과 무관 → 항상 진행
                self.repo.upload_robot_status(payload)

                if not rclpy.ok():
                    break

                msg = String()
                msg.data = json.dumps(payload, ensure_ascii=False)
                self._status_pub.publish(msg)

                # ★ posx / posj 는 모션 중에는 None 반환 (robot_client 에서 skip)
                #   → 모션 중 publish 가 자연스럽게 생략됨
                posx = self.rc.get_current_posx()
                if posx and rclpy.ok():
                    tcp_msg = String()
                    tcp_msg.data = json.dumps(list(posx))
                    self._tcp_pub.publish(tcp_msg)

                posj = self.rc.get_current_posj()
                if posj and rclpy.ok():
                    tj_msg = String()
                    tj_msg.data = json.dumps([math.degrees(v) for v in posj])
                    self._target_posj_pub.publish(tj_msg)

            except Exception as e:
                if rclpy.ok():
                    self.node.get_logger().error(f"상태 업로드 오류: {e}")
                time.sleep(STATUS_ERROR_RETRY_SEC)
                continue
            time.sleep(STATUS_UPLOAD_INTERVAL_SEC)

    # ──────────────────────────────────────────────────────────────
    # 토크 publish (★ motion_active 체크)
    # ──────────────────────────────────────────────────────────────
    def _torque_publish_loop(self) -> None:
        while rclpy.ok() and self._running.is_set():
            try:
                # 모션 중에는 publish 스킵 (robot_client 에서 어차피 [0]*6 반환)
                if self.rc.is_motion_active():
                    time.sleep(TORQUE_PUBLISH_INTERVAL_SEC)
                    continue

                torque = self.rc.get_external_torque()
                if torque and rclpy.ok():
                    safe = [0.0 if (v != v) else v for v in torque]
                    t_msg = String()
                    t_msg.data = json.dumps(safe)
                    self._torque_pub.publish(t_msg)
            except Exception:
                pass
            time.sleep(TORQUE_PUBLISH_INTERVAL_SEC)

    # ──────────────────────────────────────────────────────────────
    # 충돌 감지 (★ 모션 중에는 read 자체를 스킵)
    # ──────────────────────────────────────────────────────────────
    def _collision_monitor_loop(self) -> None:
        _in_collision = False
        COLLISION_THRESHOLD = 80.0
        FORCE_THRESHOLD     = 80.0
        FORCE_Z_THRESHOLD   = 60.0

        while rclpy.ok() and self._running.is_set():
            try:
                # ★★★ 핵심: 모션 중에는 모든 read 를 건너뛴다
                # robot_client.get_robot_state/force/torque 가 내부적으로
                # is_motion_active() 체크하지만, 여기서도 명시적으로 스킵하여
                # 불필요한 메서드 호출 오버헤드 자체를 제거.
                if self.rc.is_motion_active():
                    time.sleep(COLLISION_MONITOR_INTERVAL_SEC)
                    continue

                state = self.rc.get_robot_state()
                hard_collision = state in COLLISION_STATES
                soft_collision = False
                collision_reason = ""

                if not hard_collision and not _in_collision:
                    force = self.rc.get_tool_force()
                    if force and len(force) >= 3:
                        f_tot = math.sqrt(force[0]**2 + force[1]**2 + force[2]**2)
                        if f_tot > FORCE_THRESHOLD:
                            soft_collision, collision_reason = True, f"TCP 합력 초과 ({f_tot:.1f}N)"
                        elif abs(force[2]) > FORCE_Z_THRESHOLD:
                            soft_collision, collision_reason = True, f"Z축 외력 초과 ({force[2]:.1f}N)"

                    if not soft_collision:
                        torque = self.rc.get_external_torque()
                        if torque:
                            for i, v in enumerate(torque):
                                if abs(v) > COLLISION_THRESHOLD:
                                    soft_collision, collision_reason = True, f"J{i+1} 토크 초과 ({v:.1f}Nm)"
                                    break

                if (hard_collision or soft_collision) and not _in_collision:
                    _in_collision = True
                    reason = collision_reason if soft_collision else f"하드웨어 정지 (state={state})"

                    self.node.get_logger().error(f"🚨 충돌 감지: {reason}")
                    self.sm.trigger_emergency_stop()
                    self._cmd_queue.put("emergency_stop")

                    self.sm.update_status(state=RobotState.ERROR,
                                          current_task=f"🚨 충돌 감지: {reason}")

                    payload = self.sm.get_status_dict()
                    payload['state'] = 'collision'
                    self.repo.upload_robot_status(payload)

                elif state == ROBOT_STATE_STANDBY and not soft_collision and _in_collision:
                    self.node.get_logger().info("✅ 로봇 STANDBY 복귀")
                    _in_collision = False

            except Exception:
                pass
            time.sleep(COLLISION_MONITOR_INTERVAL_SEC)