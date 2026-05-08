"""
test_robot_controller.py
RobotController 의 _handle_command, _execute_cmd 단위 테스트.
스레드, DSR, rclpy, Firebase 는 모두 Mock 으로 대체.
"""
import queue
import threading
import pytest
from unittest.mock import MagicMock, call, patch

from cobot1.state_manager import RobotStateManager, RobotState
from cobot1.robot_client import RobotClient
from cobot1.repositories.mock_order_repository import MockOrderRepository
from cobot1.robot_controller import RobotController


# ── 픽스처 ──────────────────────────────────────────────────────────────────
@pytest.fixture
def mock_node():
    node = MagicMock()
    node.get_logger.return_value = MagicMock(
        info=MagicMock(), warn=MagicMock(), error=MagicMock()
    )
    node.create_subscription = MagicMock()
    return node


@pytest.fixture
def sm() -> RobotStateManager:
    return RobotStateManager()


@pytest.fixture
def rc() -> RobotClient:
    """DSR inject 된 RobotClient."""
    c = RobotClient(vel=30, acc=30)
    c._drs_movej              = MagicMock()
    c._drs_movel              = MagicMock()
    c._drs_amovej             = MagicMock()
    c._drs_amovel             = MagicMock()
    c._drs_mwait              = MagicMock()
    c._drs_set_digital_output = MagicMock()
    c._drs_get_digital_input  = MagicMock(return_value=0)
    c._drs_wait               = MagicMock()
    c._drs_drl_script_stop    = MagicMock()
    c._drs_check_motion       = MagicMock(return_value=0)
    c._drs_move_stop          = MagicMock()
    c._drs_get_robot_state    = MagicMock(return_value=1)
    c._drs_posj               = MagicMock(side_effect=lambda x: x)
    c._drs_posx               = MagicMock(side_effect=lambda x: x)
    c._drs_DR_BASE            = 0
    return c


@pytest.fixture
def cm() -> MagicMock:
    m = MagicMock()
    m.home_joint.return_value    = [0.0, 0.0, 90.0, 0.0, 90.0, 0.0]
    m.tool                       = "Tool Weight_2FG7"
    m.tcp                        = "2FG7"
    m.available_sub_dishes.return_value = ["피클", "단무지"]
    return m


@pytest.fixture
def repo() -> MockOrderRepository:
    return MockOrderRepository()


@pytest.fixture
def ctrl(mock_node, sm, rc, cm, repo) -> RobotController:
    return RobotController(
        node        = mock_node,
        state_mgr   = sm,
        robot_client= rc,
        coord_mgr   = cm,
        order_repo  = repo,
    )


# ── _handle_command: 비상정지 ────────────────────────────────────────────────
class TestHandleCommandEmergencyStop:
    def test_do_stop_called(self, ctrl, rc):
        rc.do_stop = MagicMock()
        ctrl._handle_command("emergency_stop")
        rc.do_stop.assert_called_once()

    def test_state_set_to_emergency_stop(self, ctrl, sm):
        rc_mock = MagicMock()
        ctrl.rc = rc_mock
        ctrl._handle_command("emergency_stop")
        assert sm.status.state == RobotState.EMERGENCY_STOP

    def test_emergency_event_is_set(self, ctrl, sm):
        ctrl.rc = MagicMock()
        ctrl._handle_command("emergency_stop")
        assert sm.is_stopped()


# ── _handle_command: resume ───────────────────────────────────────────────────
class TestHandleCommandResume:
    def test_clears_emergency_stop_when_stopped(self, ctrl, sm):
        sm.trigger_emergency_stop()
        ctrl._handle_command("resume")
        assert not sm.is_stopped()

    def test_state_returns_to_idle_after_resume(self, ctrl, sm):
        sm.trigger_emergency_stop()
        ctrl._handle_command("resume")
        assert sm.status.state == RobotState.IDLE

    def test_resume_when_not_stopped_has_no_effect(self, ctrl, sm):
        # 비상정지 아닌 상태에서 resume → 예외 없음
        ctrl._handle_command("resume")
        assert sm.status.state == RobotState.IDLE


# ── _handle_command: move_home ───────────────────────────────────────────────
class TestHandleCommandMoveHome:
    def test_move_home_enqueued_to_cmd_queue(self, ctrl):
        """move_home 은 Rule 7에 따라 cmd_queue 에 삽입."""
        ctrl._handle_command("move_home")
        assert not ctrl._cmd_queue.empty()
        assert ctrl._cmd_queue.get_nowait() == "move_home"

    def test_move_home_does_not_call_movej_directly(self, ctrl, rc):
        """move_home 은 작업 스레드에 위임하므로 직접 do_movej 호출 없음."""
        rc.do_movej = MagicMock()
        ctrl._handle_command("move_home")
        rc.do_movej.assert_not_called()

    def test_state_not_changed_by_handle_command(self, ctrl, sm):
        """_handle_command 에서는 상태 변경 없음 (작업 스레드가 처리)."""
        ctrl._handle_command("move_home")
        assert sm.status.state.value == "idle"


# ── _handle_command: gripper ─────────────────────────────────────────────────
class TestHandleCommandGripper:
    def test_gripper_open_enqueued(self, ctrl):
        """gripper_open 은 Rule 7에 따라 cmd_queue 에 삽입."""
        ctrl._handle_command("gripper_open")
        assert ctrl._cmd_queue.get_nowait() == "gripper_open"

    def test_gripper_close_enqueued(self, ctrl):
        ctrl._handle_command("gripper_close")
        assert ctrl._cmd_queue.get_nowait() == "gripper_close"

    def test_gripper_full_open_enqueued(self, ctrl):
        ctrl._handle_command("gripper_full_open")
        assert ctrl._cmd_queue.get_nowait() == "gripper_full_open"

    def test_gripper_does_not_call_set_gripper_directly(self, ctrl, rc):
        """gripper 명령은 직접 set_gripper 를 호출하지 않음."""
        rc.set_gripper = MagicMock()
        ctrl._handle_command("gripper_open")
        rc.set_gripper.assert_not_called()

    def test_unknown_command_no_exception(self, ctrl):
        """알 수 없는 명령은 조용히 무시."""
        ctrl._handle_command("unknown_cmd_xyz")  # 예외 없음


# ── _execute_cmd (작업 스레드 용) ────────────────────────────────────────────
class TestExecuteCmd:
    def test_execute_move_home_calls_movej(self, ctrl, rc, cm):
        rc.do_movej = MagicMock()
        ctrl._execute_cmd("move_home")
        rc.do_movej.assert_called_once_with(cm.home_joint.return_value)

    def test_execute_gripper_open(self, ctrl, rc):
        rc.set_gripper = MagicMock()
        ctrl._execute_cmd("gripper_open")
        rc.set_gripper.assert_called_once_with(50)

    def test_execute_gripper_close(self, ctrl, rc):
        rc.set_gripper = MagicMock()
        ctrl._execute_cmd("gripper_close")
        rc.set_gripper.assert_called_once_with(5)

    def test_execute_gripper_full_open(self, ctrl, rc):
        rc.set_gripper = MagicMock()
        ctrl._execute_cmd("gripper_full_open")
        rc.set_gripper.assert_called_once_with(100)

    def test_execute_move_home_updates_state(self, ctrl, sm, rc):
        rc.do_movej = MagicMock()
        ctrl._execute_cmd("move_home")
        assert sm.status.state == RobotState.IDLE


# ── _on_order_received: 중복 방지 ────────────────────────────────────────────
class TestOrderReceived:
    def test_first_order_enqueued(self, ctrl):
        from cobot1.repositories.order_repository import Order
        order = Order(key="ord-001", sub_dishes=[], main_dish="불고기")
        ctrl._on_order_received(order)
        assert not ctrl._order_queue.empty()

    def test_duplicate_order_not_enqueued(self, ctrl):
        from cobot1.repositories.order_repository import Order
        order = Order(key="ord-001", sub_dishes=[], main_dish="불고기")
        ctrl._on_order_received(order)
        ctrl._on_order_received(order)  # 두 번째는 중복
        assert ctrl._order_queue.qsize() == 1
