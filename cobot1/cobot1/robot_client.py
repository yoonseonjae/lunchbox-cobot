#!/usr/bin/env python3
"""
==============================================================================
[Fix2] 나만의 도련님 도시락 - 로봇 클라이언트 (모션 중 read 차단판)
==============================================================================
변경 요약 (Fix1 대비):
  ★ _motion_active: threading.Event 추가
  ★ 모든 write API (movej/movel/amovej/amovel/move_periodic) 가 진입 시 set,
    완료 시 clear → 모니터 스레드들이 is_motion_active() 로 read 스킵 가능
  → DSR_ROBOT2 service client 의 generator 가 모션 중에는 write 전용으로 점유되어
    monitor read 와의 충돌이 원천 차단됨.

  ★ get_robot_state / get_tool_force / get_external_torque /
    get_current_posx / get_current_posj 는 모션 중이면 즉시 None/기본값 반환.
==============================================================================
"""

import threading
import time
from typing import List, Optional

from rclpy.logging import get_logger

GRIPPER_SETTLE_SEC:        float = 2.0
MOTION_START_DELAY_SEC:    float = 0.2
MOTION_CHECK_INTERVAL_SEC: float = 0.15  # 0.1 → 0.15 살짝 완화

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
    def __init__(self, vel: int = 50, acc: int = 50):
        self.vel = vel
        self.acc = acc

        # ★ 모든 DSR API 호출 직렬화 락
        self._lock = threading.RLock()

        # ★★★ 신규: 모션 진행 중 플래그
        # set 상태이면 monitor read 는 skip 해야 함
        self._motion_active = threading.Event()

        # write API
        self._drs_movej = self._drs_movel = self._drs_amovej = self._drs_amovel = None
        self._drs_mwait = self._drs_set_digital_output = self._drs_get_digital_input = None
        self._drs_wait = self._drs_drl_script_stop = self._drs_check_motion = None
        self._drs_move_stop = self._drs_get_robot_state = None
        self._drs_get_tool_force = self._drs_get_external_torque = None
        self._drs_posj = self._drs_posx = self._drs_DR_BASE = self._drs_DR_TOOL = None
        self._drs_move_periodic = None

        # read API
        self._drs_get_current_posx = None
        self._drs_get_current_posj = None

    def inject(self, movej, movel, mwait, amovej, amovel,
               set_digital_output, get_digital_input,
               wait, drl_script_stop, check_motion, move_stop,
               get_robot_state, get_tool_force, get_external_torque,
               posj, posx, DR_BASE,
               move_periodic=None, DR_TOOL=None,
               get_current_posx=None, get_current_posj=None):
        self._drs_movej = movej
        self._drs_movel = movel
        self._drs_mwait = mwait
        self._drs_amovej = amovej
        self._drs_amovel = amovel
        self._drs_set_digital_output = set_digital_output
        self._drs_get_digital_input = get_digital_input
        self._drs_wait = wait
        self._drs_drl_script_stop = drl_script_stop
        self._drs_check_motion = check_motion
        self._drs_move_stop = move_stop
        self._drs_get_robot_state = get_robot_state
        self._drs_get_tool_force = get_tool_force
        self._drs_get_external_torque = get_external_torque
        self._drs_posj = posj
        self._drs_posx = posx
        self._drs_DR_BASE = DR_BASE
        self._drs_move_periodic = move_periodic
        self._drs_DR_TOOL = DR_TOOL
        self._drs_get_current_posx = get_current_posx
        self._drs_get_current_posj = get_current_posj

    # ──────────────────────────────────────────────────────────────
    # 모션 활성 플래그 (모니터 스레드용)
    # ──────────────────────────────────────────────────────────────
    def is_motion_active(self) -> bool:
        return self._motion_active.is_set()

    # ──────────────────────────────────────────────────────────────
    # 유틸
    # ──────────────────────────────────────────────────────────────
    def wait(self, sec: float) -> None:
        time.sleep(sec)

    def do_mwait(self, sec: float = 0) -> None:
        with self._lock:
            if self._drs_mwait:
                self._drs_mwait()

    # ──────────────────────────────────────────────────────────────
    # 모션 명령 (write) — 진입 시 motion_active set, 완료 시 clear
    # ──────────────────────────────────────────────────────────────
    def do_movej(self, coords: List[float], radius: Optional[float] = None) -> None:
        self._motion_active.set()
        try:
            with self._lock:
                self._drs_movej(self._drs_posj(coords),
                                vel=self.vel, acc=self.acc, radius=radius)
                if self._drs_mwait:
                    self._drs_mwait()
        finally:
            self._motion_active.clear()

    def do_movel(self, coords: List[float], radius: Optional[float] = None) -> None:
        self._motion_active.set()
        try:
            with self._lock:
                self._drs_movel(self._drs_posx(coords),
                                vel=self.vel, acc=self.acc,
                                ref=self._drs_DR_BASE, radius=radius)
                if self._drs_mwait:
                    self._drs_mwait()
        finally:
            self._motion_active.clear()

    def do_amovej(self, coords: List[float], radius: Optional[float] = None) -> None:
        # 비동기: motion_active 는 wait_motion_done 완료 시 clear 되도록 set 만 함
        self._motion_active.set()
        try:
            with self._lock:
                self._drs_amovej(self._drs_posj(coords),
                                 vel=self.vel, acc=self.acc, radius=radius)
        except Exception:
            self._motion_active.clear()
            raise

    def do_amovel(self, coords: List[float], radius: Optional[float] = None) -> None:
        self._motion_active.set()
        try:
            with self._lock:
                self._drs_amovel(self._drs_posx(coords),
                                 vel=self.vel, acc=self.acc,
                                 ref=self._drs_DR_BASE, radius=radius)
        except Exception:
            self._motion_active.clear()
            raise

    def do_move_periodic(self, amp: List[float], period: List[float],
                         atime: float, repeat: int) -> None:
        self._motion_active.set()
        try:
            with self._lock:
                self._drs_move_periodic(amp=amp, period=period, atime=atime,
                                        repeat=repeat, ref=self._drs_DR_TOOL)
            self.wait_motion_done()
        finally:
            self._motion_active.clear()

    # ──────────────────────────────────────────────────────────────
    # 그리퍼
    # ──────────────────────────────────────────────────────────────
    def set_gripper(self, width_mm: int) -> None:
        if width_mm not in _GRIPPER_MAP:
            return
        d1, d2, d3 = _GRIPPER_MAP[width_mm]
        with self._lock:
            self._drs_set_digital_output(1, d1)
            self._drs_set_digital_output(2, d2)
            self._drs_set_digital_output(3, d3)
        time.sleep(GRIPPER_SETTLE_SEC)
        _logger.info(f"그리퍼 {width_mm}mm 설정")

    def check_grip(self) -> bool:
        try:
            with self._lock:
                di_1 = self._drs_get_digital_input(1)
            return (di_1 == 1)
        except Exception:
            return True

    # ──────────────────────────────────────────────────────────────
    # 모션 완료 대기 — 비동기 모션 완료 시 motion_active clear
    # ──────────────────────────────────────────────────────────────
    def wait_motion_done(self) -> bool:
        time.sleep(MOTION_START_DELAY_SEC)
        try:
            while True:
                with self._lock:
                    state = self._drs_check_motion()
                if state == 0:
                    return True
                time.sleep(MOTION_CHECK_INTERVAL_SEC)
        finally:
            # 비동기 모션도 여기서 완료되므로 clear
            self._motion_active.clear()

    # ──────────────────────────────────────────────────────────────
    # 정지
    # ──────────────────────────────────────────────────────────────
    def do_stop(self) -> None:
        if self._drs_move_stop:
            with self._lock:
                self._drs_move_stop(3)
        self._motion_active.clear()

    # ──────────────────────────────────────────────────────────────
    # Read API — 모션 중이면 read 자체를 스킵
    # ──────────────────────────────────────────────────────────────
    def get_robot_state(self) -> int:
        if self._motion_active.is_set():
            return 1  # STANDBY 로 간주 (충돌 감지 트리거 X)
        if not self._drs_get_robot_state:
            return 1
        try:
            with self._lock:
                return self._drs_get_robot_state()
        except Exception:
            return 1

    def get_tool_force(self) -> List[float]:
        if self._motion_active.is_set():
            return [0.0] * 6  # 모션 중에는 무력 (충돌 감지 보조 비활성)
        if not self._drs_get_tool_force:
            return [0.0] * 6
        try:
            with self._lock:
                return self._drs_get_tool_force(self._drs_DR_BASE)
        except Exception:
            return [0.0] * 6

    def get_external_torque(self) -> List[float]:
        if self._motion_active.is_set():
            return [0.0] * 6
        if not self._drs_get_external_torque:
            return [0.0] * 6
        try:
            with self._lock:
                return self._drs_get_external_torque()
        except Exception:
            return [0.0] * 6

    def get_current_posx(self) -> Optional[List[float]]:
        if self._motion_active.is_set():
            return None  # 모션 중 status 업로드는 좌표 생략
        if not self._drs_get_current_posx:
            return None
        try:
            with self._lock:
                result = self._drs_get_current_posx(self._drs_DR_BASE)
            if isinstance(result, (tuple, list)) and len(result) >= 1:
                return list(result[0])
            return list(result) if result else None
        except Exception:
            return None

    def get_current_posj(self) -> Optional[List[float]]:
        if self._motion_active.is_set():
            return None
        if not self._drs_get_current_posj:
            return None
        try:
            with self._lock:
                result = self._drs_get_current_posj()
            return list(result) if result else None
        except Exception:
            return None