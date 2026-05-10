"""
test_robot_controller.py
RobotController 명령 수신·주문 큐 단위 테스트.
스레드, DSR, rclpy, Firebase 는 모두 Mock 으로 대체.

변경 이력:
  - 2026-05-09: _handle_command -> _on_command_received API 업데이트
                pause/resume 로직 반영, 새 테스트 클래스 추가
"""
import json
import queue
import threading
import pytest
from unittest.mock import MagicMock, patch

from cobot1.state_manager import RobotStateManager, RobotState
from cobot1.robot_client import RobotClient
from cobot1.repositories.mock_order_repository import MockOrderRepository
from cobot1.robot_controller import RobotController
from cobot1.repositories.order_repository import Order


# ── 픽스처 ──────────────────────────────────────────────────────────────────
@pytest.fixture
def mock_node():
    node = MagicMock()
    node.get_logger.return_value = MagicMock(
        info=MagicMock(), warn=MagicMock(), error=MagicMock()
    )
    node.create_subscription = MagicMock()
    node.create_client = MagicMock(return_value=MagicMock())
    return node


@pytest.fixture
def sm() -> RobotStateManager:
    return RobotStateManager()


@pytest.fixture
def rc() -> RobotClient:
    """DSR inject 된 RobotClient."""
    c = RobotClient(vel=30, acc=30)
    c._drs_movej               = MagicMock()
    c._drs_movel               = MagicMock()
    c._drs_amovej              = MagicMock()
    c._drs_amovel              = MagicMock()
    c._drs_mwait               = MagicMock()
    c._drs_set_digital_output  = MagicMock()
    c._drs_get_digital_input   = MagicMock(return_value=0)
    c._drs_wait                = MagicMock()
    c._drs_drl_script_stop     = MagicMock()
    c._drs_check_motion        = MagicMock(return_value=0)
    c._drs_move_stop           = MagicMock()
    c._drs_get_robot_state     = MagicMock(return_value=1)
    c._drs_get_tool_force      = MagicMock(return_value=[0.0] * 6)
    c._drs_get_external_torque = MagicMock(return_value=[0.0] * 6)
    c._drs_posj                = MagicMock(side_effect=lambda x: x)
    c._drs_posx                = MagicMock(side_effect=lambda x: x)
    c._drs_DR_BASE             = 0
    return c


@pytest.fixture
def cm() -> MagicMock:
    m = MagicMock()
    m.home_joint.return_value        = [0.0, 0.0, 90.0, 0.0, 90.0, 0.0]
    m.tool                           = "Tool Weight_2FG7"
    m.tcp                            = "2FG7"
    m.available_sub_dishes.return_value = ["피클", "단무지"]
    return m


@pytest.fixture
def repo() -> MockOrderRepository:
    return MockOrderRepository()


@pytest.fixture
def ctrl(mock_node, sm, rc, cm, repo) -> RobotController:
    return RobotController(
        node         = mock_node,
        state_mgr    = sm,
        robot_client = rc,
        coord_mgr    = cm,
        order_repo   = repo,
    )


# ── _on_command_received: pause ───────────────────────────────────────────────
class TestCommandReceivedPause:
    def test_pause_sets_paused_state(self, ctrl, sm):
        """pause 명령 → sm.is_paused() == True."""
        ctrl._on_command_received("pause")
        assert sm.is_paused()

    def test_pause_puts_pause_stop_in_cmd_queue(self, ctrl):
        """pause 명령 → 'pause_stop' 이 cmd_queue 에 삽입됨."""
        ctrl._on_command_received("pause")
        assert ctrl._cmd_queue.get_nowait() == "pause_stop"

    def test_pause_updates_state_to_idle(self, ctrl, sm):
        """pause 명령 → 상태가 IDLE 로 전환."""
        ctrl._on_command_received("pause")
        assert sm.status.state == RobotState.IDLE

    def test_pause_does_not_directly_call_do_stop(self, ctrl, rc):
        """pause 명령 → do_stop() 직접 호출 없음 (작업 스레드 위임)."""
        rc.do_stop = MagicMock()
        ctrl._on_command_received("pause")
        rc.do_stop.assert_not_called()


# ── _on_command_received: resume ──────────────────────────────────────────────
class TestCommandReceivedResume:
    def test_resume_clears_paused_state(self, ctrl, sm):
        """resume 명령 → 일시정지 해제."""
        sm.set_pause()
        ctrl._on_command_received("resume")
        assert not sm.is_paused()

    def test_resume_clears_emergency_stop_when_stopped(self, ctrl, sm):
        """비상정지 중 resume → emergency_stop 이벤트 해제."""
        sm.trigger_emergency_stop()
        ctrl._on_command_received("resume")
        assert not sm.is_stopped()

    def test_resume_updates_state_to_moving(self, ctrl, sm):
        """resume → 상태가 MOVING 으로 전환."""
        ctrl._on_command_received("resume")
        assert sm.status.state == RobotState.MOVING

    def test_resume_when_not_paused_no_exception(self, ctrl, sm):
        """정상 상태에서 resume → 예외 없음."""
        ctrl._on_command_received("resume")
        assert sm.status.state == RobotState.MOVING


# ── _on_command_received: cmd_queue 위임 명령 ─────────────────────────────────
class TestCommandReceivedQueueDelegation:
    def test_emergency_stop_enqueued_to_cmd_queue(self, ctrl):
        """emergency_stop → _cmd_queue 에 위임."""
        ctrl._on_command_received("emergency_stop")
        assert ctrl._cmd_queue.get_nowait() == "emergency_stop"

    def test_move_home_enqueued_to_cmd_queue(self, ctrl):
        """move_home → _cmd_queue 에 위임 (Rule 7)."""
        ctrl._on_command_received("move_home")
        assert ctrl._cmd_queue.get_nowait() == "move_home"

    def test_gripper_open_enqueued(self, ctrl):
        """gripper_open → _cmd_queue 에 위임 (Rule 7)."""
        ctrl._on_command_received("gripper_open")
        assert ctrl._cmd_queue.get_nowait() == "gripper_open"

    def test_gripper_close_enqueued(self, ctrl):
        ctrl._on_command_received("gripper_close")
        assert ctrl._cmd_queue.get_nowait() == "gripper_close"

    def test_gripper_full_open_enqueued(self, ctrl):
        ctrl._on_command_received("gripper_full_open")
        assert ctrl._cmd_queue.get_nowait() == "gripper_full_open"

    def test_unknown_command_enqueued(self, ctrl):
        """알 수 없는 명령도 cmd_queue 에 위임."""
        ctrl._on_command_received("unknown_xyz")
        assert ctrl._cmd_queue.get_nowait() == "unknown_xyz"

    def test_pause_converts_to_pause_stop_in_queue(self, ctrl):
        """pause 는 cmd_queue 에 'pause_stop' 으로 변환 삽입."""
        ctrl._on_command_received("pause")
        cmd = ctrl._cmd_queue.get_nowait()
        assert cmd == "pause_stop"

    def test_resume_does_not_enqueue_to_cmd_queue(self, ctrl):
        """resume 은 즉시 처리 → cmd_queue 에 아무것도 삽입되지 않음."""
        ctrl._on_command_received("resume")
        assert ctrl._cmd_queue.empty()


# ── _on_order_received: 중복 방지 ─────────────────────────────────────────────
class TestOrderReceived:
    def test_first_order_enqueued(self, ctrl):
        """첫 주문은 _order_queue 에 삽입."""
        order = Order(key="ord-001", sub_dishes=[], main_dish="불고기")
        ctrl._on_order_received(order)
        assert not ctrl._order_queue.empty()

    def test_duplicate_order_not_enqueued(self, ctrl):
        """같은 key 의 주문은 중복 방지."""
        order = Order(key="ord-001", sub_dishes=[], main_dish="불고기")
        ctrl._on_order_received(order)
        ctrl._on_order_received(order)
        assert ctrl._order_queue.qsize() == 1

    def test_different_orders_both_enqueued(self, ctrl):
        """다른 key 의 주문 두 개는 각각 큐에 삽입."""
        ctrl._on_order_received(Order(key="ord-001", sub_dishes=[], main_dish="불고기"))
        ctrl._on_order_received(Order(key="ord-002", sub_dishes=[], main_dish="돈까스"))
        assert ctrl._order_queue.qsize() == 2

    def test_order_marked_processed_after_receive(self, ctrl, sm):
        """수신된 주문은 즉시 processed 로 마킹."""
        order = Order(key="ord-001", sub_dishes=[], main_dish="불고기")
        ctrl._on_order_received(order)
        assert sm.is_order_processed("ord-001")

    def test_concurrent_order_deduplication(self, ctrl):
        """동일 주문을 여러 스레드에서 동시에 수신해도 1건만 큐에 적재."""
        order = Order(key="race-001", sub_dishes=[], main_dish="비빔밥")
        threads = [threading.Thread(target=ctrl._on_order_received, args=(order,))
                   for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert ctrl._order_queue.qsize() == 1


# ── _on_ros_order_msg: JSON 파싱 ──────────────────────────────────────────────
class TestRosOrderMsg:
    def _make_msg(self, data: str):
        msg = MagicMock()
        msg.data = data
        return msg

    def test_valid_json_order_enqueued(self, ctrl):
        """유효한 JSON 주문 메시지 → 큐 적재."""
        payload = json.dumps({"_key": "ros-001", "sub_dishes": ["피클"], "main_dish": "불고기"})
        ctrl._on_ros_order_msg(self._make_msg(payload))
        assert not ctrl._order_queue.empty()

    def test_invalid_json_does_not_raise(self, ctrl):
        """잘못된 JSON → 예외 없음 (로거 오류 출력만)."""
        ctrl._on_ros_order_msg(self._make_msg("invalid{json"))

    def test_empty_key_order_not_enqueued(self, ctrl):
        """key 가 빈 문자열인 주문 → 큐에 넣지 않음."""
        payload = json.dumps({"_key": "", "sub_dishes": [], "main_dish": "불고기"})
        ctrl._on_ros_order_msg(self._make_msg(payload))
        assert ctrl._order_queue.empty()

    def test_missing_key_field_not_enqueued(self, ctrl):
        """_key 필드 없는 주문 → 큐에 넣지 않음."""
        payload = json.dumps({"sub_dishes": ["피클"], "main_dish": "불고기"})
        ctrl._on_ros_order_msg(self._make_msg(payload))
        assert ctrl._order_queue.empty()

    def test_ros_order_sub_dishes_parsed_correctly(self, ctrl):
        """sub_dishes 목록이 Order 객체에 올바르게 파싱."""
        payload = json.dumps({"_key": "ros-002", "sub_dishes": ["피클", "단무지"], "main_dish": "돈까스"})
        ctrl._on_ros_order_msg(self._make_msg(payload))
        order = ctrl._order_queue.get_nowait()
        assert order.sub_dishes == ["피클", "단무지"]
