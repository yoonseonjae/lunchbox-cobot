#!/usr/bin/env python3
"""
==============================================================================
[Phase 3] 나만의 도련님 도시락 - 스테이지 기본 클래스 (API 안정화 버전)
==============================================================================
"""

import time
from abc import ABC, abstractmethod
from enum import Enum
from typing import Callable, List, Optional

from rclpy.logging import get_logger
from ..torque_classifier import get_classifier

class StageResult(Enum):
    SUCCESS = "success"
    STOPPED = "stopped"
    ERROR   = "error"

class BaseStage(ABC):
    def __init__(self, state_manager, robot_client, coord_manager, name: str,
                 seg_publish_fn: Optional[Callable[[dict], None]] = None):
        self.sm   = state_manager
        self.rc   = robot_client
        self.cm   = coord_manager
        self.name = name
        self._logger = get_logger(name)
        # robot_controller에서 주입되는 세그먼트 publish 콜백
        # 형식: fn({"type": "seg_start"|"seg_end", "seg_id": str, ...})
        self._seg_publish_fn: Optional[Callable[[dict], None]] = seg_publish_fn

    @abstractmethod
    def execute(self) -> StageResult:
        """스테이지 동작을 실행한다. 하위 클래스에서 반드시 구현해야 한다.

        Returns:
            StageResult: SUCCESS | STOPPED | ERROR.
        """
        ...

    def _ok(self) -> bool:
        """비상정지(Emergency Stop)이 활성화되지 않았으면 True를 반환한다.

        Returns:
            bool: 정지 중이 아닼 경우 True, 정지 중이면 False.
        """
        return not self.sm.is_stopped()

    # ── 🛡️ API 간섭 방지 및 자동 재시도 로직 적용 ──────────────────

    def _movej(self, coords: List[float], label: str = "", radius: Optional[float] = None) -> bool:
        """관절 공간 이동(do_movej)을 실행하며 일시정지/재시도를 자동 처리한다.

        Args:
            coords (List[float]): 목표 관절 각도 [J1~J6] (deg).
            label (str): 완료 시 tick에 기록할 레이블. 비어있으면 tick 안 함.
            radius (float | None): 블렌딩 반경 (mm). None이면 기본값.
        Returns:
            bool: 이동 완료 시 True, 정지되었으면 False.
        """
        if not self._ok(): return False
        while True:
            self.sm.wait_if_paused() 
            if not self._ok(): return False
            try:
                time.sleep(0.05) # 🚨 API 냉각 시간
                self.rc.do_movej(coords, radius=radius)
                break 
            except Exception as e:
                if "generator already executing" in str(e):
                    time.sleep(0.5) # 🚨 에러 시 잠시 대기 후 루프 재실행(재시도)
                    continue
                if self.sm.is_paused():
                    self.sm.wait_if_paused()
                    continue 
                self._logger.error(f"_movej 오류: {e}")
                return False
        if label: self._tick(label)
        return self._ok()

    def _movel(self, coords: List[float], label: str = "", radius: Optional[float] = None) -> bool:
        """작업 공간 직선 이동(do_movel)을 실행하며 일시정지/재시도를 자동 처리한다.

        Args:
            coords (List[float]): 목표 TCP 좌표 [X,Y,Z,Rx,Ry,Rz].
            label (str): 완료 시 tick에 기록할 레이블.
            radius (float | None): 블렌딩 반경 (mm).
        Returns:
            bool: 이동 완료 시 True, 정지되었으면 False.
        """
        if not self._ok(): return False
        while True:
            self.sm.wait_if_paused()
            if not self._ok(): return False
            try:
                time.sleep(0.05)
                self.rc.do_movel(coords, radius=radius)
                break
            except Exception as e:
                if "generator already executing" in str(e):
                    time.sleep(0.5)
                    continue
                if self.sm.is_paused():
                    self.sm.wait_if_paused()
                    continue
                self._logger.error(f"_movel 오류: {e}")
                return False
        if label: self._tick(label)
        return self._ok()
    
    def _amovej(self, coords: List[float], label: str = "", radius: Optional[float] = None) -> bool:
        """비동기 관절 이동(do_amovej)을 실행하고 완료를 폴링으로 대기한다.

        Args:
            coords (List[float]): 목표 관절 각도 [J1~J6] (deg).
            label (str): 완료 시 tick에 기록할 레이블.
            radius (float | None): 블렌딩 반경 (mm).
        Returns:
            bool: 이동 완료 시 True, 정지되었으면 False.
        """
        if not self._ok(): return False
        while True:
            self.sm.wait_if_paused()
            if not self._ok(): return False
            try:
                time.sleep(0.05)
                self.rc.do_amovej(coords, radius=radius)
                if not self.rc.wait_motion_done(stop_check=self.sm.is_stopped): return False
                if self.sm.is_paused():
                    self.sm.wait_if_paused()
                    continue 
                break
            except Exception as e:
                if "generator already executing" in str(e):
                    time.sleep(0.5)
                    continue
                if self.sm.is_paused():
                    self.sm.wait_if_paused()
                    continue
                self._logger.error(f"_amovej 오류: {e}")
                return False
        if label: self._tick(label)
        return self._ok()
    
    def _amovel(self, coords: List[float], label: str = "", radius: Optional[float] = None) -> bool:
        """비동기 작업 공간 직선 이동(do_amovel)을 실행하고 완료를 폴링으로 대기한다.

        Args:
            coords (List[float]): 목표 TCP 좌표 [X,Y,Z,Rx,Ry,Rz].
            label (str): 완료 시 tick에 기록할 레이블.
            radius (float | None): 블렌딩 반경 (mm).
        Returns:
            bool: 이동 완료 시 True, 정지되었으면 False.
        """
        if not self._ok(): return False
        while True:
            self.sm.wait_if_paused()
            if not self._ok(): return False
            try:
                time.sleep(0.05) # 🚨 API 간섭 방지
                self.rc.do_amovel(coords, radius=radius)
                if not self.rc.wait_motion_done(stop_check=self.sm.is_stopped): return False
                if self.sm.is_paused():
                    self.sm.wait_if_paused()
                    continue
                break
            except Exception as e:
                if "generator already executing" in str(e):
                    time.sleep(0.5) # 🚨 에러 시 자동 재시도
                    continue
                if self.sm.is_paused():
                    self.sm.wait_if_paused()
                    continue
                self._logger.error(f"_amovel 오류: {e}")
                return False
        if label: self._tick(label)
        return self._ok()
    
    def _move_periodic(self, coords: List[float], period_ms: float, atime: float, count: int, label: str = "") -> bool: 
        """주기적 이동(move_periodic)을 실행하며 일시정지/재시도를 자동 처리한다.

        Args:
            coords (List[float]): 목표 TCP 좌표 [X,Y,Z,Rx,Ry,Rz].
            period_ms (float): 이동 주기 (ms).
            atime (float): 이동 시간 (s).
            count (int): 이동 횟수.
            label (str): 완료 시 tick에 기록할 레이블.
        Returns:
            bool: 이동 완료 시 True, 정지되었으면 False.
        """
        if not self._ok(): return False
        while True:
            self.sm.wait_if_paused()
            if not self._ok(): return False
            try:
                time.sleep(0.05)
                self.rc.do_move_periodic(coords, period_ms, atime, count)
                if not self.rc.wait_motion_done(stop_check=self.sm.is_stopped): return False
                if self.sm.is_paused():
                    self.sm.wait_if_paused()
                    continue
                break
            except Exception as e:
                if "generator already executing" in str(e):
                    time.sleep(0.5)
                    continue
                if self.sm.is_paused():
                    self.sm.wait_if_paused()
                    continue
                self._logger.error(f"_move_periodic 오류: {e}")
                return False
        if label: self._tick(label)
        return self._ok()

    def _start_compliance(self, stx=None) -> None:
        """TCP 순응제어를 활성화한다. 집기/놓기 직전 표면 접촉 동작에 사용한다.

        Args:
            stx (List[float] | None): 스티프니스 벡터. None이면 기본값 적용.
        Returns:
            None
        """
        try:
            self.rc.start_compliance_ctrl(stx)
        except Exception as e:
            self._logger.warn(f"순응제어 활성화 실패: {e}")

    def _stop_compliance(self) -> None:
        """TCP 순응제어를 해제한다.

        Returns:
            None
        """
        try:
            self.rc.stop_compliance_ctrl()
        except Exception as e:
            self._logger.warn(f"순응제어 해제 실패: {e}")

    def _start_force_ctrl(self, newton: float = -10.0) -> None:
        """TCP 힘제어를 활성화한다. 순응제어 활성화 후 호출해야 효과적이다.

        Args:
            newton (float): Z축 목표힘(N). 음수=아래방향. 기본 -10.0N.
        Returns:
            None
        """
        try:
            self.rc.set_force_ctrl(newton)
        except Exception as e:
            self._logger.warn(f"힘제어 활성화 실패: {e}")

    def _stop_force_ctrl(self) -> None:
        """TCP 힘제어를 해제한다.

        Returns:
            None
        """
        try:
            self.rc.release_force_ctrl()
        except Exception as e:
            self._logger.warn(f"힘제어 해제 실패: {e}")

    def _gripper(self, width_mm: int) -> None:
        """일시정지를 확인한 뒤 그리퍼를 지정한 폭으로 조작한다.

        Args:
            width_mm (int): 목표 그리퍼 폭 (mm). 예: 5, 20, 30, 50, 100.
        Returns:
            None
        """
        self.sm.wait_if_paused() 
        self.rc.set_gripper(width_mm)

    def _check_grip(self) -> bool:
        """그리퍼가 물체를 융커 있는지 확인한다. DI 신호를 콴어 폭 > 0 인지 검사한다.

        Returns:
            bool: 움켜진 상태(>0mm)면 True, 완전히 열린 상태면 False.
        """
        while True:
            try:
                return self.rc.get_gripper() is not None and self.rc.get_gripper() > 0
            except Exception as e:
                if "generator already executing" in str(e):
                    time.sleep(0.5)
                    continue
                self._logger.error(f"_check_grip 오류: {e}")
                return False
        
    def _tick(self, label: str, done: bool = False) -> None:
        """단계 레이블을 스탭로그와 진행단계에 기록한다.

        Args:
            label (str): 스톡 이름 (예: '트레이 공지 이동 완료').
            done (bool): True면 add_step_log에 completed=True 전달.
        Returns:
            None
        """
        self.sm.tick(label)
        self.sm.add_step_log(label, completed=done)

    def _seg_start(self, seg_id: str, motion: str, label: str) -> None:
        """모션 세그먼트 시작을 브리지에 알림. motion: 'sync' | 'async'"""
        if self._seg_publish_fn:
            self._seg_publish_fn({
                'type':   'seg_start',
                'seg_id': seg_id,
                'motion': motion,
                'label':  label,
            })

    def _seg_end(self, seg_id: str) -> None:
        """모션 세그먼트 종료를 브리지에 알림."""
        if self._seg_publish_fn:
            self._seg_publish_fn({'type': 'seg_end', 'seg_id': seg_id})

    def _sample_torque_class(self, n: int = 5, interval: float = 0.15) -> str:
        """
        n개 토크 샘플을 interval 간격으로 수집하고 평균으로 페이로드 클래스를 반환.
        로봇이 정지 상태일 때 호출할 것.
        """
        samples = []
        for _ in range(n):
            try:
                t = self.rc.get_external_torque()
                if t and len(t) == 6:
                    samples.append(t)
            except Exception:
                pass
            time.sleep(interval)

        if not samples:
            self._logger.warn("토크 샘플 수집 실패 - 빈그리퍼로 처리")
            return "빈그리퍼"

        result = get_classifier().predict_class_from_mean(samples)
        self._logger.info(f"토크 분류 결과: {result} (샘플 {len(samples)}개)")
        return result