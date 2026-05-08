#!/usr/bin/env python3
"""
==============================================================================
[Phase 3] 나만의 도련님 도시락 - 스테이지 기본 클래스
==============================================================================
모든 스테이지(TraySetup / SubDish / MainDish / Rice / Delivery)의
공통 인터페이스와 헬퍼 메서드를 정의.
==============================================================================
"""

import time
from abc import ABC, abstractmethod
from enum import Enum
from typing import List

from rclpy.logging import get_logger

class StageResult(Enum):
    SUCCESS = "success"
    STOPPED = "stopped"
    ERROR   = "error"

class BaseStage(ABC):
    def __init__(self, state_manager, robot_client, coord_manager, name: str):
        self.sm   = state_manager
        self.rc   = robot_client
        self.cm   = coord_manager
        self.name = name
        self._logger = get_logger(name)        

    @abstractmethod
    def execute(self) -> StageResult:
        ...

    def _ok(self) -> bool:
        return not self.sm.is_stopped()

    # 🚨 [수정됨] 이동 중 일시정지가 걸리면 에러를 무시하고 대기 후 재이동
    def _movej(self, coords: List[float], label: str = "") -> bool:
        if not self._ok(): return False
        while True:
            self.sm.wait_if_paused() # 일시정지면 여기서 멈춤
            if not self._ok(): return False
            try:
                self.rc.do_movej(coords)
                break # 무사히 도착하면 루프 탈출
            except Exception as e:
                if self.sm.is_paused():
                    self._logger.warn("⏸️ 이동 중 일시정지됨. 대기합니다...")
                    self.sm.wait_if_paused()
                    self._logger.info("▶️ 재개됨. 남은 궤적을 다시 이동합니다.")
                    continue # 루프를 다시 돌아 movej 재실행
                self._logger.error(f"_movej 오류: {e}")
                return False
        if label: self._tick(label)
        return self._ok()

    def _movel(self, coords: List[float], label: str = "") -> bool:
        if not self._ok(): return False
        while True:
            self.sm.wait_if_paused()
            if not self._ok(): return False
            try:
                self.rc.do_movel(coords)
                break
            except Exception as e:
                if self.sm.is_paused():
                    self._logger.warn("⏸️ 이동 중 일시정지됨. 대기합니다...")
                    self.sm.wait_if_paused()
                    continue
                self._logger.error(f"_movel 오류: {e}")
                return False
        if label: self._tick(label)
        return self._ok()
    
    def _amovej(self, coords: List[float], label: str = "") -> bool:
        if not self._ok(): return False
        while True:
            self.sm.wait_if_paused()
            if not self._ok(): return False
            try:
                self.rc.do_amovej(coords)
                if not self.rc.wait_motion_done():
                    return False
                
                # 비동기 이동 완료 후 일시정지 상태인지 확인
                if self.sm.is_paused():
                    self._logger.warn("⏸️ 비동기 이동 중 정지됨. 대기합니다...")
                    self.sm.wait_if_paused()
                    continue # 못 간 만큼 다시 이동

                break
            except Exception as e:
                if self.sm.is_paused():
                    self.sm.wait_if_paused()
                    continue
                self._logger.error(f"_amovej 오류: {e}")
                return False
        if label: self._tick(label)
        return self._ok()
    
    def _amovel(self, coords: List[float], label: str = "") -> bool:
        if not self._ok(): return False
        while True:
            self.sm.wait_if_paused()
            if not self._ok(): return False
            try:
                self.rc.do_amovel(coords)
                if not self.rc.wait_motion_done():
                    return False
                
                if self.sm.is_paused():
                    self.sm.wait_if_paused()
                    continue
                break
            except Exception as e:
                if self.sm.is_paused():
                    self.sm.wait_if_paused()
                    continue
                self._logger.error(f"_amovel 오류: {e}")
                return False
        if label: self._tick(label)
        return self._ok()

<<<<<<< HEAD
=======
    def _amovel(self, coords: List[float], radius: int = None, label: str = "") -> bool:
        """태스크 비동기 이동 (amovel + mwait). 비상정지 시 False 반환"""
        if not self._ok():
            return False
        try:
            self.rc.amovel(coords, radius)
        except Exception as e:
            print(f"[{self.name}] _amovel 오류: {e}")
            return False
        if label:
            self._tick(label)
        return self._ok()


    # ── 그리퍼 헬퍼 ──────────────────────────────────────────────
>>>>>>> origin/hb_develop
    def _gripper(self, width_mm: int) -> None:
        self.sm.wait_if_paused() # 그리퍼 닫기 전에도 일시정지 검사
        self.rc.set_gripper(width_mm)

<<<<<<< HEAD
    def _tick(self, label: str, done: bool = False) -> None:
=======
    def _check_grip(self):
        """그리퍼 물체 잡기 성공 여부 확인. OUT 1=0, 2=1, 3=0"""
        return self.rc.check_grip()
        
    # ── 진행 로그 ─────────────────────────────────────────────────
    def _tick(self, label: str, done: bool = False):
>>>>>>> origin/hb_develop
        self.sm.tick(label)
        self.sm.add_step_log(label, completed=done)