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
        "get_tool_force":     MagicMock(return_value=[0.0] * 6),
        "get_external_torque": MagicMock(return_value=[0.0] * 6),
        "posj":               MagicMock(side_effect=lambda x: x),
        "posx":               MagicMock(side_effect=lambda x: x),
        "DR_BASE":            0,
        "move_periodic":      MagicMock(),
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
        mock_dsr["get_tool_force"], mock_dsr["get_external_torque"],
        mock_dsr["posj"], mock_dsr["posx"], mock_dsr["DR_BASE"],
        move_periodic=mock_dsr["move_periodic"],
    )
    return c


# ── 초기화 테스트 ───────────────────────────────────────────────────────────
class TestRobotClientInit:
    def test_default_vel_acc(self):
        c = RobotClient()
        assert c.vel == 50
        assert c.acc == 50

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
        mock_dsr["movej"].assert_called_once_with(coords, vel=30, acc=30, radius=None)
        mock_dsr["mwait"].assert_called_once()

    def test_do_movel_calls_movel_with_dr_base_and_mwait(self, client, mock_dsr):
        coords = [400.0, 0.0, 300.0, 0.0, 180.0, 0.0]
        client.do_movel(coords)
        mock_dsr["movel"].assert_called_once_with(
            coords, vel=30, acc=30, ref=mock_dsr["DR_BASE"], radius=None
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

    def test_returns_true_after_polling(self, client, mock_dsr):
        """Busy(2) → Idle(0) 전환 후 True 반환."""
        mock_dsr["check_motion"].side_effect = [2, 0]
        with patch("time.sleep"):
            result = client.wait_motion_done()
        assert result is True


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

    def test_set_gripper_calls_time_sleep_with_settle_sec(self, client, mock_dsr):
        with patch("time.sleep") as mock_sleep:
            client.set_gripper(50)
        mock_sleep.assert_called_once_with(GRIPPER_SETTLE_SEC)

    def test_invalid_gripper_width_silently_ignored(self, client, mock_dsr):
        """지원하지 않는 폭은 조용히 무시 (DO 출력 없음)."""
        client.set_gripper(999)
        mock_dsr["set_digital_output"].assert_not_called()

    def test_gripper_map_covers_all_widths(self):
        assert set(_GRIPPER_MAP.keys()) == {5, 20, 30, 50, 100}


# ── 정지 테스트 ─────────────────────────────────────────────────────────────
class TestStopMethods:
    def test_do_stop_calls_move_stop_3(self, client, mock_dsr):
        client.do_stop()
        mock_dsr["move_stop"].assert_called_once_with(3)

    def test_do_stop_no_error_when_not_injected(self):
        """inject 전 do_stop() 호출 시 예외 없음."""
        c = RobotClient()
        c.do_stop()  # _drs_move_stop is None → 조용히 무시

    def test_do_stop_propagates_dsr_error(self, client, mock_dsr):
        """DSR move_stop 예외는 호출자에게 그대로 전파됨 (소스 동작 확인)."""
        mock_dsr["move_stop"].side_effect = RuntimeError("stop error")
        with pytest.raises(RuntimeError, match="stop error"):
            client.do_stop()


# ── 상수 테스트 ─────────────────────────────────────────────────────────────
class TestConstants:
    def test_on_off_values(self):
        assert ON == 1
        assert OFF == 0

    def test_timing_constants_are_positive(self):
        assert GRIPPER_SETTLE_SEC > 0
        assert MOTION_START_DELAY_SEC > 0
        assert MOTION_CHECK_INTERVAL_SEC > 0


# ── 파지 확인(check_grip) 테스트 ─────────────────────────────────────────────
class TestCheckGrip:
    def test_check_grip_returns_true_when_di1_is_1(self, client, mock_dsr):
        """DI1 = 1 → 파지 성공."""
        mock_dsr["get_digital_input"].return_value = 1
        assert client.check_grip() is True

    def test_check_grip_returns_false_when_di1_is_0(self, client, mock_dsr):
        """DI1 = 0 → 파지 실패."""
        mock_dsr["get_digital_input"].return_value = 0
        assert client.check_grip() is False

    def test_check_grip_returns_true_on_exception(self, client, mock_dsr):
        """DI 오류 시 True 반환 (안전 fallback)."""
        mock_dsr["get_digital_input"].side_effect = RuntimeError("DI error")
        assert client.check_grip() is True


# ── 로봇 상태 조회 테스트 ────────────────────────────────────────────────────
class TestGetRobotState:
    def test_get_robot_state_delegates_to_dsr(self, client, mock_dsr):
        mock_dsr["get_robot_state"].return_value = 3
        assert client.get_robot_state() == 3

    def test_get_robot_state_returns_1_when_not_injected(self):
        """inject 전 호출 시 기본값 1 (STANDBY) 반환."""
        c = RobotClient()
        assert c.get_robot_state() == 1

    def test_get_robot_state_returns_standby_by_default(self, client, mock_dsr):
        """inject 직후 DSR 기본값 1 확인."""
        mock_dsr["get_robot_state"].return_value = 1
        assert client.get_robot_state() == 1


# ── 외력/토크 조회 테스트 ────────────────────────────────────────────────────
class TestGetForce:
    def test_get_tool_force_returns_6_element_list(self, client, mock_dsr):
        mock_dsr["get_tool_force"].return_value = [1.0, 2.0, 3.0, 0.1, 0.2, 0.3]
        result = client.get_tool_force()
        assert isinstance(result, list)
        assert len(result) == 6

    def test_get_tool_force_returns_zeros_when_not_injected(self):
        c = RobotClient()
        assert c.get_tool_force() == [0.0] * 6

    def test_get_external_torque_returns_6_element_list(self, client, mock_dsr):
        mock_dsr["get_external_torque"].return_value = [0.1, 0.2, 0.3, 0.0, 0.0, 0.0]
        result = client.get_external_torque()
        assert len(result) == 6

    def test_get_external_torque_returns_zeros_when_not_injected(self):
        c = RobotClient()
        assert c.get_external_torque() == [0.0] * 6


# ── radius 파라미터 전달 테스트 ──────────────────────────────────────────────
class TestMotionWithRadius:
    def test_do_movej_with_radius_passed_to_dsr(self, client, mock_dsr):
        """radius 파라미터가 DSR movej 에 그대로 전달되는지 확인."""
        client.do_movej([0, 0, 90, 0, 90, 0], radius=50.0)
        call_kwargs = mock_dsr["movej"].call_args[1]
        assert call_kwargs.get("radius") == 50.0

    def test_do_movel_with_radius_passed_to_dsr(self, client, mock_dsr):
        client.do_movel([400.0, 0.0, 300.0, 0.0, 180.0, 0.0], radius=30.0)
        call_kwargs = mock_dsr["movel"].call_args[1]
        assert call_kwargs.get("radius") == 30.0

    def test_do_movej_radius_none_by_default(self, client, mock_dsr):
        """radius 미지정 시 None 으로 전달."""
        client.do_movej([0, 0, 90, 0, 90, 0])
        call_kwargs = mock_dsr["movej"].call_args[1]
        assert call_kwargs.get("radius") is None

    def test_do_amovej_with_radius(self, client, mock_dsr):
        client.do_amovej([0, 0, 90, 0, 90, 0], radius=20.0)
        call_kwargs = mock_dsr["amovej"].call_args[1]
        assert call_kwargs.get("radius") == 20.0


# ── do_move_periodic 테스트 ─────────────────────────────────────────────
class TestDoMovePeriodic:
    AMP = [0.0, 5.0, 20.0, 0.0, 0.0, 8.0]

    def test_calls_dsr_move_periodic_with_correct_args(self, client, mock_dsr):
        """호출 시 DSR move_periodic이 올바른 인수로 호출되는지 확인."""
        client.do_move_periodic(self.AMP, period_ms=1.0, atime=0.2, count=15)
        mock_dsr["move_periodic"].assert_called_once_with(
            self.AMP, 1.0, 0.2, 15
        )

    def test_does_nothing_before_inject(self):
        """inject 전에는 DSR 호출 없이 조용히 리턴."""
        c = RobotClient()
        c.do_move_periodic([0.0] * 6, period_ms=0.5, atime=0.2, count=10)

    def test_period_ms_forwarded_as_period_kwarg(self, client, mock_dsr):
        """period_ms 인수가 DSR에 두 번째 positional 인수로 전달되는지 확인."""
        client.do_move_periodic(self.AMP, period_ms=0.5, atime=0.1, count=10)
        args, _ = mock_dsr["move_periodic"].call_args
        assert args[1] == 0.5

    def test_count_forwarded_correctly(self, client, mock_dsr):
        """count 인수가 DSR에 네 번째 positional 인수로 전달되는지 확인."""
        client.do_move_periodic(self.AMP, period_ms=1.0, atime=0.2, count=7)
        args, _ = mock_dsr["move_periodic"].call_args
        assert args[3] == 7

    def test_amp_forwarded_correctly(self, client, mock_dsr):
        """amp 벡터가 DSR에 첫 번째 positional 인수로 전달되는지 확인."""
        amp = [1.0, 2.0, 3.0, 0.0, 0.0, 0.0]
        client.do_move_periodic(amp, period_ms=1.0, atime=0.2, count=5)
        args, _ = mock_dsr["move_periodic"].call_args
        assert args[0] == amp

    def test_called_only_once_per_invocation(self, client, mock_dsr):
        """do_move_periodic 중복 호출 없이 1회만 DSR을 부르는지 확인."""
        client.do_move_periodic(self.AMP, period_ms=1.0, atime=0.2, count=10)
        assert mock_dsr["move_periodic"].call_count == 1
