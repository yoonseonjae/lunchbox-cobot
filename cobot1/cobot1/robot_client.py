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

ON, OFF = 1, 0

# 그리퍼 폭 → DO 핀 설정 테이블
_GRIPPER_MAP = {
    5:   (ON,  OFF, OFF),
    20:  (ON,  OFF, ON),
    30:  (ON,  ON,  OFF),
    50:  (OFF, OFF, ON),
    100: (OFF, ON,  OFF),
}


class RobotClient:
    """
    DSR_ROBOT2 / DR_common2 API 를 래핑.
    main() 에서 DSR import 후 inject() 로 함수를 주입해야 함.

    사용 패턴::

        client = RobotClient(vel=30, acc=30)
        client.inject(movej, movel, mwait, set_digital_output,
                      get_digital_input, wait, drl_script_stop,
                      posj, posx, DR_BASE)
    """

    def __init__(self, vel: int = 30, acc: int = 30):
        self.vel = vel
        self.acc = acc

        # DSR 함수들 (inject 전까지 None)
        self._movej              = None
        self._movel              = None
        self._mwait              = None
        self._set_digital_output = None
        self._get_digital_input  = None
        self._wait               = None
        self._drl_script_stop    = None
        self._posj               = None
        self._posx               = None
        self._DR_BASE            = None

    def inject(self,
               movej, movel, mwait, amovej, amovel,
               set_digital_output, get_digital_input,
               wait, drl_script_stop,
               posj, posx, DR_BASE):
        """main() 내부에서 DSR import 후 호출."""
        self._movej              = movej
        self._movel              = movel
        self._mwait              = mwait
        self._amovej             = amovej
        self._amovel             = amovel
        self._set_digital_output = set_digital_output
        self._get_digital_input  = get_digital_input
        self._wait               = wait
        self._drl_script_stop    = drl_script_stop
        self._posj               = posj
        self._posx               = posx
        self._DR_BASE            = DR_BASE

    # ── 이동 ──────────────────────────────────────────────────────
    def movej(self, coords: List[float]):
        """관절 이동 (동기)."""
        self._movej(self._posj(coords), vel=self.vel, acc=self.acc)
        self._mwait()

    def amovej(self, coords: List[float]):
        """관절 이동 (비동기 발행 후 mwait). plate_finish_a [010] 구간에 사용."""
        self._amovej(self._posj(coords), vel=self.vel, acc=self.acc)
        self._mwait()

    def movel(self, coords: List[float]):
        """직선(Cartesian) 이동 (동기)."""
        self._movel(
            self._posx(coords),
            vel=self.vel, acc=self.acc,
            ref=self._DR_BASE,
        )
        self._mwait()
    def amovel(self, coords: List[float]):
        """직선(Cartesian) 이동 (비동기)"""
        self._amovel(self._posx(coords), vel=self.vel, acc=self.acc)
        self._mwait()

    # ── 그리퍼 ───────────────────────────────────────────────────
    def set_gripper(self, width_mm: int):
        """그리퍼 폭 설정 (5 / 20 / 30 / 50 / 100 mm)."""
        if width_mm not in _GRIPPER_MAP:
            raise ValueError(f"[RobotClient] 지원하지 않는 그리퍼 폭: {width_mm}mm")
        d1, d2, d3 = _GRIPPER_MAP[width_mm]
        self._set_digital_output(1, d1)
        self._set_digital_output(2, d2)
        self._set_digital_output(3, d3)
        self._wait(2.0)
        print(f"[GRIPPER] {width_mm}mm  DO1={d1} DO2={d2} DO3={d3}")

    # ── 유틸 ──────────────────────────────────────────────────────
    def wait(self, sec: float):
        self._wait(sec)

    def stop(self):
        """비상 정지 (감속)."""
        try:
            self._drl_script_stop(1)
        except Exception as e:
            print(f"[RobotClient] stop 오류: {e}")

    def get_robot_state(self) -> int:
        """로봇 상태값 반환 (충돌 감시용)."""
        from DSR_ROBOT2 import get_robot_state
        return get_robot_state()
