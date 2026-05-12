#!/usr/bin/env python3
"""
==============================================================================
[Final] 나만의 도련님 도시락 - 로봇 하드웨어 추상 클라이언트 (안정화)
==============================================================================
"""

import time
from typing import Any, Callable, List, Optional
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
        self._drs_movej:                  Optional[Callable[..., Any]] = None
        self._drs_movel:                  Optional[Callable[..., Any]] = None
        self._drs_amovej:                 Optional[Callable[..., Any]] = None
        self._drs_amovel:                 Optional[Callable[..., Any]] = None
        self._drs_mwait:                  Optional[Callable[..., Any]] = None
        self._drs_set_digital_output:     Optional[Callable[..., Any]] = None
        self._drs_get_digital_input:      Optional[Callable[..., Any]] = None
        self._drs_wait:                   Optional[Callable[..., Any]] = None
        self._drs_drl_script_stop:        Optional[Callable[..., Any]] = None
        self._drs_check_motion:           Optional[Callable[..., Any]] = None
        self._drs_move_stop:              Optional[Callable[..., Any]] = None
        self._drs_get_robot_state:        Optional[Callable[..., Any]] = None
        self._drs_get_tool_force:         Optional[Callable[..., Any]] = None
        self._drs_get_external_torque:    Optional[Callable[..., Any]] = None
        self._drs_posj:                   Optional[Callable[..., Any]] = None
        self._drs_posx:                   Optional[Callable[..., Any]] = None
        self._drs_DR_BASE:                Optional[Any] = None
        self._drs_task_compliance_ctrl:   Optional[Callable[..., Any]] = None
        self._drs_release_compliance_ctrl:Optional[Callable[..., Any]] = None
        self._drs_set_desired_force:      Optional[Callable[..., Any]] = None
        self._drs_release_force:          Optional[Callable[..., Any]] = None
        self._drs_move_periodic:          Optional[Callable[..., Any]] = None
        self._drs_set_singular_handling:  Optional[Callable[..., Any]] = None
        self._drs_DR_VAR_VEL:             Optional[Any] = None
        self._drs_DR_AVOID:               Optional[Any] = None

    def inject(self, movej, movel, mwait, amovej, amovel,
               set_digital_output, get_digital_input,
               wait, drl_script_stop, check_motion, move_stop,
               get_robot_state, get_tool_force, get_external_torque,
               posj, posx, DR_BASE,
               task_compliance_ctrl=None, release_compliance_ctrl=None,
               set_desired_force=None, release_force=None, move_periodic=None,
               set_singular_handling=None, DR_VAR_VEL=None, DR_AVOID=None):
        """DSR_ROBOT2 함수들을 내부 속성에 주입한다. 로봇 노드 시작 시 한 번만 호출.

        Args:
            movej: 관절 공간 이동.
            movel: 작업 공간 직선 이동.
            mwait: 이동 완료 대기.
            amovej: 비동기 관절 이동.
            amovel: 비동기 직선 이동.
            set_digital_output: DO 핀 제어 (그리퍼).
            get_digital_input: DI 핀 읽기 (파지 확인).
            wait / drl_script_stop / check_motion / move_stop: 기타 DSR 제어 함수.
            get_robot_state: 로봇 상태 코드 반환.
            get_tool_force: TCP 외력 6축 반환.
            get_external_torque: 외부 토크 6축 반환.
            posj / posx: 좌표 변환 함수.
            DR_BASE: 베이스 프레임 상수.
            task_compliance_ctrl / release_compliance_ctrl: 순응제어 (선택).
            set_desired_force / release_force: 힘제어 (선택).
        Returns:
            None
        """
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
        self._drs_task_compliance_ctrl = task_compliance_ctrl
        self._drs_release_compliance_ctrl = release_compliance_ctrl
        self._drs_set_desired_force = set_desired_force
        self._drs_release_force = release_force
        self._drs_move_periodic = move_periodic
        self._drs_set_singular_handling = set_singular_handling
        self._drs_DR_VAR_VEL = DR_VAR_VEL
        self._drs_DR_AVOID = DR_AVOID
    def wait(self, sec: float) -> None:
        """sec초만큼 현재 스레드를 블로킹한다.

        Args:
            sec (float): 대기 시간(초).
        Returns:
            None
        """
        time.sleep(sec)

    def do_mwait(self, sec: float = 0) -> None:
        """DSR mwait()를 호출해 로봇 이동이 완료될 때까지 대기한다. inject 전이면 실행되지 않음.

        Args:
            sec (float): mwait 인자 (가업).
        Returns:
            None
        """
        if self._drs_mwait: self._drs_mwait()

    def do_movej(self, coords: List[float], radius: Optional[float] = None) -> None:
        """posj 변환 후 관절 공간 이동(movej)하고 완료를 대기한다.

        Args:
            coords (List[float]): 목표 관절 각도 [J1~J6] (deg).
            radius (float | None): 변환 원호 반경(mm). None = 블랜딩 없음.
        Returns:
            None
        """
        assert self._drs_movej is not None and self._drs_posj is not None
        self._drs_movej(self._drs_posj(coords), vel=self.vel, acc=self.acc, radius=radius)
        self.do_mwait()

    def do_movel(self, coords: List[float], radius: Optional[float] = None) -> None:
        """posx 변환 후 베이스 프레임 기준 직선 이동(movel)하고 완료를 대기한다.

        Args:
            coords (List[float]): 목표 TCP 좌표 [X,Y,Z,Rx,Ry,Rz] (mm/deg).
            radius (float | None): 변환 원호 반경(mm).
        Returns:
            None
        """
        assert self._drs_movel is not None and self._drs_posx is not None
        self._drs_movel(self._drs_posx(coords), vel=self.vel, acc=self.acc, ref=self._drs_DR_BASE, radius=radius)
        self.do_mwait()

    def do_amovej(self, coords: List[float], radius: Optional[float] = None) -> None:
        """posj 변환 후 비동기 관절 이동(amovej)을 시작한다. 완료를 대기하지 않음.

        Args:
            coords (List[float]): 목표 관절 각도 [J1~J6] (deg).
            radius (float | None): 변환 원호 반경(mm).
        Returns:
            None
        """
        assert self._drs_amovej is not None and self._drs_posj is not None
        self._drs_amovej(self._drs_posj(coords), vel=self.vel, acc=self.acc, radius=radius)

    def do_amovel(self, coords: List[float], radius: Optional[float] = None) -> None:
        """posx 변환 후 베이스 프레임 기준 비동기 직선 이동(amovel)을 시작한다.

        Args:
            coords (List[float]): 목표 TCP 좌표 [X,Y,Z,Rx,Ry,Rz] (mm/deg).
            radius (float | None): 변환 원호 반경(mm).
        Returns:
            None
        """
        assert self._drs_amovel is not None and self._drs_posx is not None
        self._drs_amovel(self._drs_posx(coords), vel=self.vel, acc=self.acc, ref=self._drs_DR_BASE, radius=radius)

    def set_gripper(self, width_mm: int) -> None:
        """_GRIPPER_MAP DO 핀 조합으로 그리퍼를 지정 폭으로 조절한다.

        Args:
            width_mm (int): 목표 그리퍼 폭 (5|20|30|50|100 mm).
                            맵에 없는 값이면 조용히 무시됨.
        Returns:
            None
        """
        if width_mm not in _GRIPPER_MAP: return
        if self._drs_set_digital_output is None: return
        d1, d2, d3 = _GRIPPER_MAP[width_mm]
        self._drs_set_digital_output(1, d1)
        self._drs_set_digital_output(2, d2)
        self._drs_set_digital_output(3, d3)
        time.sleep(GRIPPER_SETTLE_SEC)
        _logger.info(f"그리퍼 {width_mm}mm 설정")

    def get_gripper(self) -> Optional[int]:
        """DI 1~3 조합을 _GRIPPER_MAP과 비교해 현재 그리퍼 폭(mm)을 반환한다.

        Returns:
            int | None: 현재 폭(5|20|30|50|100 mm).
                        맵에 없는 조합이면 None, inject 전이면 None.
        """
        if self._drs_get_digital_input is None: return None
        d1 = self._drs_get_digital_input(1)
        d2 = self._drs_get_digital_input(2)
        d3 = self._drs_get_digital_input(3)
        for width_mm, (g1, g2, g3) in _GRIPPER_MAP.items():
            if (d1, d2, d3) == (g1, g2, g3):
                return width_mm
        return None

    def check_grip(self) -> bool:
        """DI1 핀 값으로 그리퍼 파지 성공 여부를 확인한다.

        Returns:
            bool: DI1 = 1이면 True(파지 성공), 0이면 False.
                  DI 오류 또는 inject 전이면 True(안전 fallback).
        """
        try:
            if self._drs_get_digital_input is None:
                return True
            return bool(self._drs_get_digital_input(1))
        except Exception:
            return True

    def wait_motion_done(self, stop_check: Optional[Callable[[], bool]] = None) -> bool:
        """check_motion이 0이 될 때까지 폴링하며 이동 완료를 기다린다.

        Args:
            stop_check (Callable[[], bool] | None): 매 폴링마다 호출해 True이면
                (비상정지 등) 즉시 False를 반환한다. None이면 체크 없음.
        Returns:
            bool: 정상 완료면 True, 정지 감지 시 False.
        """
        if self._drs_check_motion is None:
            return True
        time.sleep(MOTION_START_DELAY_SEC)
        while self._drs_check_motion() != 0:
            if stop_check and stop_check():
                return False
            time.sleep(MOTION_CHECK_INTERVAL_SEC)
        return True

    def do_stop(self) -> None:
        """move_stop(3)을 호출해 로봇 이동을 즉시 중단한다.

        Returns:
            None  (inject 전이면 아무 동작 없음)
        """
        if self._drs_move_stop: self._drs_move_stop(3)

    def get_robot_state(self) -> int:
        """DSR 로봇 상태 코드를 반환한다.

        Returns:
            int: DSR 상태 코드 (1=STANDBY, 3=충돌 등).
                 inject 전이면 1 반환.
        """
        return self._drs_get_robot_state() if self._drs_get_robot_state else 1

    def get_tool_force(self) -> List[float]:
        """DR_BASE 기준 TCP 외력 6축 값을 반환한다.

        Returns:
            List[float]: [Fx,Fy,Fz,Mx,My,Mz] (N/Nm). inject 전이면 [0.0]*6.
        """
        return self._drs_get_tool_force(self._drs_DR_BASE) if self._drs_get_tool_force else [0.0]*6

    def get_external_torque(self) -> List[float]:
        """6개 관절의 외부 토크를 반환한다.

        Returns:
            List[float]: [J1~J6 토크] (Nm). inject 전이면 [0.0]*6.
        """
        return self._drs_get_external_torque() if self._drs_get_external_torque else [0.0]*6

    def start_compliance_ctrl(self, stx: Optional[List[float]] = None) -> None:
        """TCP 순응제어를 활성화한다. 집기/놓기 직전 표면 접촉 동작에 사용한다.

        Args:
            stx (List[float] | None): 스티프니스 벡터 [Kx,Ky,Kz,Rx,Ry,Rz].
                                      None이면 기본값 [1000,1000,500,100,100,100] 사용.
        Returns:
            None
        """
        if self._drs_task_compliance_ctrl is None:
            return
        if stx is None:
            stx = [1000, 1000, 500, 100, 100, 100]  # XY 강성 유지, Z 유연
        self._drs_task_compliance_ctrl(stx, time=0)

    def stop_compliance_ctrl(self) -> None:
        """TCP 순응제어를 해제한다.

        Returns:
            None
        """
        if self._drs_release_compliance_ctrl:
            self._drs_release_compliance_ctrl()

    def set_force_ctrl(self, fd_z: float = -10.0) -> None:
        """Z축 내방향으로 지정한 힘을 유지하는 힘제어를 활성화한다.

        순응제어(start_compliance_ctrl) 활성화 후 호출해야 효과적이다.

        Args:
            fd_z (float): Z축 목표힘(N). 음수=아래방향. 기본 -10.0N.
        Returns:
            None
        """
        if self._drs_set_desired_force is None:
            return
        fd  = [0.0, 0.0, fd_z, 0.0, 0.0, 0.0]
        dir = [0,   0,   1,    0,   0,   0  ]  # Z축만 힘제어, XY는 위치제어
        self._drs_set_desired_force(fd=fd, dir=dir, mod=0)  # mod=0: DR_FC_MOD_ABS

    def release_force_ctrl(self) -> None:
        """TCP 힘제어를 해제한다.

        Returns:
            None
        """
        if self._drs_release_force:
            self._drs_release_force()

    def do_move_periodic(self, amp: List[float], period_ms: float, atime: float, count: int) -> None:
        """주기적 이동(move_periodic)을 시작한다. inject 전이면 아무 동작 없음.

        Args:
            amp (List[float]): 진폭 벡터 [X,Y,Z,Rx,Ry,Rz] (mm/deg).
            period_ms (float): 이동 주기(ms).
            atime (float): 이동 시간(s).
            count (int): 이동 횟수.
        Returns:
            None
        """
        if self._drs_move_periodic:
            self._drs_move_periodic(amp, period_ms, atime, count)

    def do_set_singular_handling(self, enable: bool) -> None:
        """특이점 회피 설정을 켜거나 끈다. inject 전이면 아무 동작 없음.

        Args:
            enable (bool): True면 켜고 False면 끈다.
        Returns:
            None
        """
        if self._drs_set_singular_handling:
            self._drs_set_singular_handling(self._drs_DR_VAR_VEL, self._drs_DR_AVOID, 1 if enable else 0)