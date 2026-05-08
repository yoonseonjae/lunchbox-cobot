"""
test_robot_client.py
RobotClient 단위 테스트.
DSR_ROBOT2 는 conftest.py 의 stub 으로 대체.
"""
import pytest
from unittest.mock import MagicMock, call, patch
import time

# conftest.py 가 sys.modules 에 stub 을 등록한 뒤 import
from cobot1.robot_client import (
    RobotClient,
    GRIPPER_SETTLE_SEC,
    MOTION_START_DELAY_SEC,
    MOTION_CHECK_INTERVAL_SEC,
    ON, OFF,
    _GRIPPER_MAP,
)


# ── 공통 픽스처 ─────────────────────────────────────────────────────────────
@pytest.fixture
def mock_dsr():
    """DSR API 함수를 모두 MagicMock 으로 반환."""
    return {
        "movej":              MagicMock(),
        "movel":              MagicMock(),
        "mwait":              MagicMock(),
        "amovej":             MagicMock(),
        "amovel":             MagicMock(),
        "set_digital_output": MagicMock(),
        "get_digital_input":  MagicMock(return_value=0),
        "wait":               MagicMock(),
        "drl_script_stop":    MagicMock(),
        "check_motion":       MagicMock(return_value=0),  # 기본 Idle
        "move_stop":          MagicMock(),
        "get_robot_state":    MagicMock(return_value=1),  # STANDBY
        "posj":               MagicMock(side_effect=lambda x: x),
        "posx":               MagicMock(side_effect=lambda x: x),
        "DR_BASE":            0,
    }


@pytest.fixture
def client(mock_dsr) -> RobotClient:
    """inject() 완료된 RobotClient."""
    c = RobotClient(vel=30, acc=30)
    c.inject(
        mock_dsr["movej"], mock_dsr["movel"], mock_dsr["mwait"],
        mock_dsr["amovej"], mock_dsr["amovel"],
        mock_dsr["set_digital_output"], mock_dsr["get_digital_input"],
        mock_dsr["wait"], mock_dsr["drl_script_stop"],
        mock_dsr["check_motion"], mock_dsr["move_stop"],
        mock_dsr["get_robot_state"],
        mock_dsr["posj"], mock_dsr["posx"], mock_dsr["DR_BASE"],
    )
    return c


# ── 초기화 테스트 ───────────────────────────────────────────────────────────
class TestRobotClientInit:
    def test_default_vel_acc(self):
        c = RobotClient()
        assert c.vel == 30
        assert c.acc == 30

    def test_custom_vel_acc(self):
        c = RobotClient(vel=60, acc=60)
        assert c.vel == 60
        assert c.acc == 60

    def test_inject_not_called_dsr_is_none(self):
        c = RobotClient()
        assert c._drs_movej is None
        assert c._drs_move_stop is None

    def test_inject_sets_all_dsr_functions(self, client, mock_dsr):
        assert client._drs_movej            is mock_dsr["movej"]
        assert client._drs_movel            is mock_dsr["movel"]
        assert client._drs_amovej           is mock_dsr["amovej"]
        assert client._drs_amovel           is mock_dsr["amovel"]
        assert client._drs_mwait            is mock_dsr["mwait"]
        assert client._drs_set_digital_output is mock_dsr["set_digital_output"]
        assert client._drs_check_motion     is mock_dsr["check_motion"]
        assert client._drs_move_stop        is mock_dsr["move_stop"]
        assert client._drs_get_robot_state  is mock_dsr["get_robot_state"]
        assert client._drs_DR_BASE          == mock_dsr["DR_BASE"]


# ── 이동 테스트 ─────────────────────────────────────────────────────────────
class TestRobotClientMotion:
    def test_do_movej_calls_movej_and_mwait(self, client, mock_dsr):
        coords = [0, 0, 90, 0, 90, 0]
        client.do_movej(coords)
        mock_dsr["movej"].assert_called_once_with(coords, vel=30, acc=30)
        mock_dsr["mwait"].assert_called_once()

    def test_do_movel_calls_movel_with_dr_base_and_mwait(self, client, mock_dsr):
        coords = [400.0, 0.0, 300.0, 0.0, 180.0, 0.0]
        client.do_movel(coords)
        mock_dsr["movel"].assert_called_once_with(
            coords, vel=30, acc=30, ref=mock_dsr["DR_BASE"]
        )
        mock_dsr["mwait"].assert_called_once()

    def test_do_amovej_no_mwait(self, client, mock_dsr):
        """비동기 이동은 mwait 를 직접 호출하지 않아야 함."""
        client.do_amovej([0, 0, 90, 0, 90, 0])
        mock_dsr["amovej"].assert_called_once()
        mock_dsr["mwait"].assert_not_called()

    def test_do_amovel_no_mwait(self, client, mock_dsr):
        client.do_amovel([400.0, 0.0, 300.0, 0.0, 180.0, 0.0])
        mock_dsr["amovel"].assert_called_once()
        mock_dsr["mwait"].assert_not_called()

    def test_posj_called_in_movej(self, client, mock_dsr):
        coords = [1, 2, 3, 4, 5, 6]
        client.do_movej(coords)
        mock_dsr["posj"].assert_called_once_with(coords)

    def test_posx_called_in_movel(self, client, mock_dsr):
        coords = [100.0, 200.0, 300.0, 0.0, 180.0, 0.0]
        client.do_movel(coords)
        mock_dsr["posx"].assert_called_once_with(coords)


# ── check_motion / wait_motion_done 테스트 ──────────────────────────────────
class TestWaitMotionDone:
    def test_returns_true_when_already_idle(self, client, mock_dsr):
        """check_motion이 처음부터 0이면 즉시 True."""
        mock_dsr["check_motion"].return_value = 0
        with patch("time.sleep"):
            result = client.wait_motion_done()
        assert result is True

    def test_polls_until_idle(self, client, mock_dsr):
        """Busy(2) → Busy(2) → Idle(0) 패턴을 올바르게 대기."""
        mock_dsr["check_motion"].side_effect = [2, 2, 0]
        with patch("time.sleep"):
            result = client.wait_motion_done()
        assert result is True
        assert mock_dsr["check_motion"].call_count == 3

    def test_returns_false_when_rclpy_stops(self, client, mock_dsr):
        """rclpy.ok() 가 False 가 되면 False 반환."""
        import sys
        sys.modules["rclpy"].ok = MagicMock(return_value=False)
        mock_dsr["check_motion"].return_value = 2  # 항상 Busy
        with patch("time.sleep"):
            result = client.wait_motion_done()
        assert result is False
        # 복원
        sys.modules["rclpy"].ok = MagicMock(return_value=True)


# ── 그리퍼 테스트 ───────────────────────────────────────────────────────────
class TestGripper:
    @pytest.mark.parametrize("width_mm, expected", [
        (5,   (ON,  OFF, OFF)),
        (20,  (ON,  OFF, ON)),
        (30,  (ON,  ON,  OFF)),
        (50,  (OFF, OFF, ON)),
        (100, (OFF, ON,  OFF)),
    ])
    def test_set_gripper_do_pins(self, client, mock_dsr, width_mm, expected):
        """각 폭에 대한 DO 핀 조합이 올바르게 출력되는지 확인."""
        d1, d2, d3 = expected
        client.set_gripper(width_mm)
        calls = mock_dsr["set_digital_output"].call_args_list
        assert calls[0] == call(1, d1)
        assert calls[1] == call(2, d2)
        assert calls[2] == call(3, d3)

    def test_set_gripper_calls_wait_with_settle_sec(self, client, mock_dsr):
        client.set_gripper(50)
        mock_dsr["wait"].assert_called_once_with(GRIPPER_SETTLE_SEC)

    def test_invalid_gripper_width_raises_valueerror(self, client):
        with pytest.raises(ValueError, match="지원하지 않는"):
            client.set_gripper(999)

    def test_gripper_map_covers_all_widths(self):
        assert set(_GRIPPER_MAP.keys()) == {5, 20, 30, 50, 100}


# ── 정지 테스트 ─────────────────────────────────────────────────────────────
class TestStopMethods:
    def test_do_stop_calls_move_stop_3(self, client, mock_dsr):
        client.do_stop()
        mock_dsr["move_stop"].assert_called_once_with(3)

    def test_move_stop_with_immediate_mode(self, client, mock_dsr):
        client.move_stop(stop_mode=0)
        mock_dsr["move_stop"].assert_called_once_with(0)

    def test_move_stop_exception_is_caught(self, client, mock_dsr):
        """move_stop 에서 예외가 발생해도 상위로 전파되지 않아야 함."""
        mock_dsr["move_stop"].side_effect = RuntimeError("stop error")
        client.move_stop()  # 예외 전파 없음


# ── 상수 테스트 ─────────────────────────────────────────────────────────────
class TestConstants:
    def test_on_off_values(self):
        assert ON == 1
        assert OFF == 0

    def test_timing_constants_are_positive(self):
        assert GRIPPER_SETTLE_SEC > 0
        assert MOTION_START_DELAY_SEC > 0
        assert MOTION_CHECK_INTERVAL_SEC > 0
