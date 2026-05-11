#!/usr/bin/env python3
"""
==============================================================================
[Final] 나만의 도련님 도시락 - 로봇 하드웨어 추상 클라이언트 (Lock 동기화 버전)
==============================================================================
변경 요약:
  - threading.RLock 추가: 모든 DSR API 호출(write + read)을 단일 락으로 직렬화
  - write API (movej/movel/amovej/amovel/move_periodic/set_digital_output/move_stop)
  - read API  (get_robot_state / get_tool_force / get_external_torque /
              get_current_posx / get_current_posj / get_digital_input / check_motion)
  → 모두 같은 락 안에서만 실행되므로 두 스레드가 동시에 service generator를
    건드릴 일이 사라짐("generator already executing" 충돌 근본 해결).

  - wait_motion_done() 은 sleep 구간에서 락을 풀어, 모니터 스레드가
    중간에 read 한 번씩 할 기회를 보장 (락 점유로 모니터 굶주리는 일 방지).

  - get_current_posx / get_current_posj 신규 메서드 (status_upload 용도).
  - 0.05초 cooldown 같은 의미 없는 magic sleep 제거.
==============================================================================
"""

import threading
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
    def __init__(self, vel: int = 50, acc: int = 50):
        self.vel = vel
        self.acc = acc

        # ★★★ 핵심: 모든 DSR API 호출을 직렬화하는 단일 락
        # RLock 을 쓰는 이유: 향후 같은 스레드가 중첩 호출해도 안전.
        self._lock = threading.RLock()

        # write API
        self._drs_movej = self._drs_movel = self._drs_amovej = self._drs_amovel = None
        self._drs_mwait = self._drs_set_digital_output = self._drs_get_digital_input = None
        self._drs_wait = self._drs_drl_script_stop = self._drs_check_motion = None
        self._drs_move_stop = self._drs_get_robot_state = None
        self._drs_get_tool_force = self._drs_get_external_torque = None
        self._drs_posj = self._drs_posx = self._drs_DR_BASE = self._drs_DR_TOOL = None
        self._drs_move_periodic = None

        # read API (status_upload 용도, lunchbox_robot_node 에서 inject)
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
    # 유틸 (락 불필요)
    # ──────────────────────────────────────────────────────────────
    def wait(self, sec: float) -> None:
        time.sleep(sec)

    def do_mwait(self, sec: float = 0) -> None:
        # mwait 는 단순 동기 대기로 service generator 와 무관하지만
        # 같은 락 안에서 일관성 있게 처리.
        with self._lock:
            if self._drs_mwait:
                self._drs_mwait()

    # ──────────────────────────────────────────────────────────────
    # 모션 명령 (write) — 모두 락 안에서
    # ──────────────────────────────────────────────────────────────
    def do_movej(self, coords: List[float], radius: Optional[float] = None) -> None:
        with self._lock:
            self._drs_movej(self._drs_posj(coords),
                            vel=self.vel, acc=self.acc, radius=radius)
            if self._drs_mwait:
                self._drs_mwait()

    def do_movel(self, coords: List[float], radius: Optional[float] = None) -> None:
        with self._lock:
            self._drs_movel(self._drs_posx(coords),
                            vel=self.vel, acc=self.acc,
                            ref=self._drs_DR_BASE, radius=radius)
            if self._drs_mwait:
                self._drs_mwait()

    def do_amovej(self, coords: List[float], radius: Optional[float] = None) -> None:
        with self._lock:
            self._drs_amovej(self._drs_posj(coords),
                             vel=self.vel, acc=self.acc, radius=radius)

    def do_amovel(self, coords: List[float], radius: Optional[float] = None) -> None:
        with self._lock:
            self._drs_amovel(self._drs_posx(coords),
                             vel=self.vel, acc=self.acc,
                             ref=self._drs_DR_BASE, radius=radius)

    def do_move_periodic(self, amp: List[float], period: List[float],
                         atime: float, repeat: int) -> None:
        with self._lock:
            self._drs_move_periodic(amp=amp, period=period, atime=atime,
                                    repeat=repeat, ref=self._drs_DR_TOOL)
        # 완료 대기는 락을 풀고 폴링 (긴 시간 락 점유 방지)
        self.wait_motion_done()

    # ──────────────────────────────────────────────────────────────
    # 그리퍼 (DO 핀 제어)
    # ──────────────────────────────────────────────────────────────
    def set_gripper(self, width_mm: int) -> None:
        if width_mm not in _GRIPPER_MAP:
            return
        d1, d2, d3 = _GRIPPER_MAP[width_mm]
        with self._lock:
            self._drs_set_digital_output(1, d1)
            self._drs_set_digital_output(2, d2)
            self._drs_set_digital_output(3, d3)
        # settle 은 락 밖에서 sleep (모니터가 read 할 기회 제공)
        time.sleep(GRIPPER_SETTLE_SEC)
        _logger.info(f"그리퍼 {width_mm}mm 설정")

    def check_grip(self) -> bool:
        """OnRobot RG2 파지 확인"""
        try:
            with self._lock:
                di_1 = self._drs_get_digital_input(1)
            return (di_1 == 1)
        except Exception:
            return True

    # ──────────────────────────────────────────────────────────────
    # 모션 완료 대기 — 핵심: sleep 구간은 락 밖에서!
    # ──────────────────────────────────────────────────────────────
    def wait_motion_done(self) -> bool:
        """
        check_motion() 폴링 루프.
        락 점유 시간을 최소화하기 위해 check_motion 호출 순간만 락을 잡고,
        sleep 은 락 밖에서 수행 → 모니터/상태 스레드가 굶지 않음.
        """
        time.sleep(MOTION_START_DELAY_SEC)
        while True:
            with self._lock:
                state = self._drs_check_motion()
            if state == 0:
                return True
            time.sleep(MOTION_CHECK_INTERVAL_SEC)

    # ──────────────────────────────────────────────────────────────
    # 정지
    # ──────────────────────────────────────────────────────────────
    def do_stop(self) -> None:
        if self._drs_move_stop:
            with self._lock:
                self._drs_move_stop(3)

    # ──────────────────────────────────────────────────────────────
    # Read API — 모두 락 안에서 (모니터 스레드용)
    # ──────────────────────────────────────────────────────────────
    def get_robot_state(self) -> int:
        if not self._drs_get_robot_state:
            return 1
        try:
            with self._lock:
                return self._drs_get_robot_state()
        except Exception:
            return 1

    def get_tool_force(self) -> List[float]:
        if not self._drs_get_tool_force:
            return [0.0] * 6
        try:
            with self._lock:
                return self._drs_get_tool_force(self._drs_DR_BASE)
        except Exception:
            return [0.0] * 6

    def get_external_torque(self) -> List[float]:
        if not self._drs_get_external_torque:
            return [0.0] * 6
        try:
            with self._lock:
                return self._drs_get_external_torque()
        except Exception:
            return [0.0] * 6

    def get_current_posx(self) -> Optional[List[float]]:
        """현재 TCP 위치 (status_upload 용)."""
        if not self._drs_get_current_posx:
            return None
        try:
            with self._lock:
                result = self._drs_get_current_posx(self._drs_DR_BASE)
            # DSR 의 get_current_posx 는 (posx, sol_space) 튜플 반환
            if isinstance(result, (tuple, list)) and len(result) >= 1:
                return list(result[0])
            return list(result) if result else None
        except Exception:
            return None

    def get_current_posj(self) -> Optional[List[float]]:
        """현재 관절 각도 (status_upload 용, 라디안)."""
        if not self._drs_get_current_posj:
            return None
        try:
            with self._lock:
                result = self._drs_get_current_posj()
            return list(result) if result else None
        except Exception:
            return None