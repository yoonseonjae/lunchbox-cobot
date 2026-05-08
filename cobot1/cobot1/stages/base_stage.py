#!/usr/bin/env python3
"""
==============================================================================
[Phase 3] 나만의 도련님 도시락 - 스테이지 기본 클래스 (API 안정화 버전)
==============================================================================
"""

import time
from abc import ABC, abstractmethod
from enum import Enum
from typing import List, Optional

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

    # ── 🛡️ API 간섭 방지 및 자동 재시도 로직 적용 ──────────────────

    def _movej(self, coords: List[float], label: str = "", radius: Optional[float] = None) -> bool:
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
        if not self._ok(): return False
        while True:
            self.sm.wait_if_paused()
            if not self._ok(): return False
            try:
                time.sleep(0.05)
                self.rc.do_amovej(coords, radius=radius)
                if not self.rc.wait_motion_done(): return False
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
        if not self._ok(): return False
        while True:
            self.sm.wait_if_paused()
            if not self._ok(): return False
            try:
                time.sleep(0.05) # 🚨 API 간섭 방지
                self.rc.do_amovel(coords, radius=radius)
                if not self.rc.wait_motion_done(): return False
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

    def _gripper(self, width_mm: int) -> None:
        self.sm.wait_if_paused() 
        self.rc.set_gripper(width_mm)

    def _check_grip(self) -> bool:
        return self.rc.check_grip()
        
    def _tick(self, label: str, done: bool = False) -> None:
        self.sm.tick(label)
        self.sm.add_step_log(label, completed=done)