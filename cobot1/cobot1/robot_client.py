#!/usr/bin/env python3
"""
==============================================================================
[Final] 나만의 도련님 도시락 - 로봇 하드웨어 추상 클라이언트 (안정화)
==============================================================================
"""

import time
from typing import List, Optional
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
        self._drs_movej = self._drs_movel = self._drs_amovej = self._drs_amovel = None
        self._drs_mwait = self._drs_set_digital_output = self._drs_get_digital_input = None
        self._drs_wait = self._drs_drl_script_stop = self._drs_check_motion = None
        self._drs_move_stop = self._drs_get_robot_state = None
        self._drs_get_tool_force = self._drs_get_external_torque = None
        self._drs_posj = self._drs_posx = self._drs_DR_BASE = None

    def inject(self, movej, movel, mwait, amovej, amovel,
               set_digital_output, get_digital_input,
               wait, drl_script_stop, check_motion, move_stop,
               get_robot_state, get_tool_force, get_external_torque,
               posj, posx, DR_BASE):
        self._drs_movej = movej; self._drs_movel = movel
        self._drs_mwait = mwait; self._drs_amovej = amovej; self._drs_amovel = amovel
        self._drs_set_digital_output = set_digital_output
        self._drs_get_digital_input = get_digital_input
        self._drs_wait = wait; self._drs_drl_script_stop = drl_script_stop
        self._drs_check_motion = check_motion; self._drs_move_stop = move_stop
        self._drs_get_robot_state = get_robot_state
        self._drs_get_tool_force = get_tool_force
        self._drs_get_external_torque = get_external_torque
        self._drs_posj = posj; self._drs_posx = posx; self._drs_DR_BASE = DR_BASE

    def wait(self, sec: float) -> None:
        time.sleep(sec)

    def do_mwait(self, sec: float = 0) -> None:
        if self._drs_mwait: self._drs_mwait()

    def do_movej(self, coords: List[float], radius: Optional[float] = None) -> None:
        self._drs_movej(self._drs_posj(coords), vel=self.vel, acc=self.acc, radius=radius)
        self.do_mwait()

    def do_movel(self, coords: List[float], radius: Optional[float] = None) -> None:
        self._drs_movel(self._drs_posx(coords), vel=self.vel, acc=self.acc, ref=self._drs_DR_BASE, radius=radius)
        self.do_mwait()

    def do_amovej(self, coords: List[float], radius: Optional[float] = None) -> None:
        self._drs_amovej(self._drs_posj(coords), vel=self.vel, acc=self.acc, radius=radius)

    def do_amovel(self, coords: List[float], radius: Optional[float] = None) -> None:
        self._drs_amovel(self._drs_posx(coords), vel=self.vel, acc=self.acc, ref=self._drs_DR_BASE, radius=radius)

    def set_gripper(self, width_mm: int) -> None:
        if width_mm not in _GRIPPER_MAP: return
        d1, d2, d3 = _GRIPPER_MAP[width_mm]
        self._drs_set_digital_output(1, d1)
        self._drs_set_digital_output(2, d2)
        self._drs_set_digital_output(3, d3)
        time.sleep(GRIPPER_SETTLE_SEC)
        _logger.info(f"그리퍼 {width_mm}mm 설정")

    def check_grip(self) -> bool:
        """OnRobot RG2 파지 확인 (오타 수정됨)"""
        try:
            di_1 = self._drs_get_digital_input(1)
            di_2 = self._drs_get_digital_input(2)
            return (di_1 == 1) 
        except:
            return True

    def wait_motion_done(self) -> bool:
        time.sleep(MOTION_START_DELAY_SEC)
        while self._drs_check_motion() != 0:
            time.sleep(MOTION_CHECK_INTERVAL_SEC)
        return True

    def do_stop(self) -> None:
        if self._drs_move_stop: self._drs_move_stop(3)

    def get_robot_state(self) -> int:
        return self._drs_get_robot_state() if self._drs_get_robot_state else 1

    def get_tool_force(self) -> List[float]:
        return self._drs_get_tool_force(self._drs_DR_BASE) if self._drs_get_tool_force else [0.0]*6

    def get_external_torque(self) -> List[float]:
        return self._drs_get_external_torque() if self._drs_get_external_torque else [0.0]*6