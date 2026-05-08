#!/usr/bin/env python3
"""
==============================================================================
[Phase 4.5] 나만의 도련님 도시락 - 로봇 하드웨어 추상 클라이언트
==============================================================================
DSR_ROBOT2 API 를 직접 호출하는 유일한 계층.
Stage 클래스들은 이 클라이언트만 통해 로봇을 움직임.

그리퍼 (OnRobot RG2 - WebLogic DO 매핑):
  5mm   : DO1=ON,  DO2=OFF, DO3=OFF
  20mm  : DO1=ON,  DO2=OFF, DO3=ON
  30mm  : DO1=ON,  DO2=ON,  DO3=OFF
  50mm  : DO1=OFF, DO2=OFF, DO3=ON
  100mm : DO1=OFF, DO2=ON,  DO3=OFF
==============================================================================
"""

import time
from typing import List
from rclpy.logging import get_logger

GRIPPER_SETTLE_SEC:        float = 2.0   
MOTION_START_DELAY_SEC:    float = 0.2   
MOTION_CHECK_INTERVAL_SEC: float = 0.1   

ON, OFF = 1, 0

_logger = get_logger('robot_client')

_GRIPPER_MAP = {
    5:   (ON,  OFF, OFF),
    20:  (ON,  OFF, ON),
    30:  (ON,  ON,  OFF),
    50:  (OFF, OFF, ON),
    100: (OFF, ON,  OFF),
}

class RobotClient:
    def __init__(self, vel: int = 30, acc: int = 30):
        self.vel = vel
        self.acc = acc
        self.ref = None  

        self._drs_movej              = None
        self._drs_movel              = None
        self._drs_amovej             = None
        self._drs_amovel             = None
        self._drs_mwait              = None
        self._drs_set_digital_output = None
        self._drs_get_digital_input  = None
        self._drs_wait               = None
        self._drs_drl_script_stop    = None
        self._drs_check_motion       = None
        self._drs_move_stop          = None
        self._drs_get_robot_state    = None
        # 🚨 [복구됨] 초기화 변수 추가
        self._drs_get_tool_force     = None
        self._drs_get_external_torque= None
        self._drs_posj               = None
        self._drs_posx               = None
        self._drs_DR_BASE            = None

    def inject(self,
               movej, movel, mwait, amovej, amovel,
               set_digital_output, get_digital_input,
               wait, drl_script_stop,
               check_motion, move_stop,
               get_robot_state,
               # 🚨 [복구됨] inject 파라미터 추가
               get_tool_force, get_external_torque,
               posj, posx, DR_BASE):
               
        self._drs_movej              = movej
        self._drs_movel              = movel
        self._drs_amovej             = amovej
        self._drs_amovel             = amovel
        self._drs_mwait              = mwait
        self._drs_set_digital_output = set_digital_output
        self._drs_get_digital_input  = get_digital_input
        self._drs_wait               = wait
        self._drs_drl_script_stop    = drl_script_stop
        self._drs_check_motion       = check_motion
        self._drs_move_stop          = move_stop
        self._drs_get_robot_state    = get_robot_state
        # 🚨 [복구됨] 할당
        self._drs_get_tool_force     = get_tool_force
        self._drs_get_external_torque= get_external_torque
        self._drs_posj               = posj
        self._drs_posx               = posx
        self._drs_DR_BASE            = DR_BASE

    def do_movej(self, coords: List[float]) -> None:
        self._drs_movej(self._drs_posj(coords), vel=self.vel, acc=self.acc)
        self._drs_mwait()

    def do_movel(self, coords: List[float]) -> None:
        self._drs_movel(
            self._drs_posx(coords),
            vel=self.vel, acc=self.acc,
            ref=self._drs_DR_BASE,
        )
        self._drs_mwait()

    def do_amovej(self, coords: List[float]) -> None:
        self._drs_amovej(self._drs_posj(coords), vel=self.vel, acc=self.acc)

    def do_amovel(self, coords: List[float]) -> None:
        self._drs_amovel(
            self._drs_posx(coords),
            vel=self.vel, acc=self.acc,
            ref=self._drs_DR_BASE,
        )

    def set_gripper(self, width_mm: int) -> None:
        if width_mm not in _GRIPPER_MAP:
            raise ValueError(f"지원하지 않는 그리퍼 폭: {width_mm}mm")
        d1, d2, d3 = _GRIPPER_MAP[width_mm]
        self._drs_set_digital_output(1, d1)
        self._drs_set_digital_output(2, d2)
        self._drs_set_digital_output(3, d3)
        self._drs_wait(GRIPPER_SETTLE_SEC)
        _logger.info(f"그리퍼 {width_mm}mm 설정  DO1={d1} DO2={d2} DO3={d3}")

    def wait(self, sec: float) -> None:
        self._drs_wait(sec)

    def do_wait(self, sec: float) -> None:
        self._drs_wait(sec)

    def do_mwait(self, sec: float = 0) -> None:
        self._drs_mwait()

    def check_motion(self) -> int:
        return self._drs_check_motion()

    def wait_motion_done(self) -> bool:
        import rclpy
        time.sleep(MOTION_START_DELAY_SEC)
        while self._drs_check_motion() != 0:
            time.sleep(MOTION_CHECK_INTERVAL_SEC)
            if not rclpy.ok():
                return False
        return True

    def move_stop(self, stop_mode: int = 3) -> None:
        try:
            self._drs_move_stop(stop_mode)
        except Exception as e:
            _logger.error(f"move_stop 오류: {e}")

    def do_stop(self) -> None:
        self.move_stop(3)

    def get_robot_state(self) -> int:
        return self._drs_get_robot_state()

    # 🚨 [복구됨] 능동형 외력 감지를 위한 센서 리턴 함수들
    def get_tool_force(self) -> List[float]:
        """TCP에 가해지는 힘/모멘트 반환"""
        if self._drs_get_tool_force:
            return self._drs_get_tool_force(self._drs_DR_BASE)
        return []

    def get_external_torque(self) -> List[float]:
        """각 관절 외부 토크 반환"""
        if self._drs_get_external_torque:
            return self._drs_get_external_torque()
        return []