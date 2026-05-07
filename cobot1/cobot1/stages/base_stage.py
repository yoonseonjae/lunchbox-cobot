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


class StageResult(Enum):
    SUCCESS = "success"
    STOPPED = "stopped"   # 비상정지로 중단
    ERROR   = "error"     # 예외 발생


class BaseStage(ABC):
    """
    모든 스테이지의 기본 클래스.

    구현 필수:
        execute() -> StageResult

    헬퍼:
        _movej(coords, label)  : 관절 이동 (DSR movej + mwait)
        _movel(coords, label)  : 직선 이동 (DSR movel + mwait)
        _gripper(width_mm)     : 그리퍼 폭 설정
        _tick(label)           : 진행률 증가 + 로그
    """

    def __init__(self, state_manager, robot_client, coord_manager, name: str):
        """
        Args:
            state_manager : RobotStateManager 인스턴스
            robot_client  : RobotClient 인스턴스 (DSR API 래퍼)
            coord_manager : CoordinateManager 인스턴스
            name          : 스테이지 이름 (로그용)
        """
        self.sm   = state_manager
        self.rc   = robot_client
        self.cm   = coord_manager
        self.name = name

    @abstractmethod
    def execute(self) -> StageResult:
        """스테이지 실행. 반드시 StageResult 반환."""
        ...

    # ── 비상정지 체크 ─────────────────────────────────────────────
    def _ok(self) -> bool:
        """True 이면 계속 진행 가능, False 이면 비상정지 중."""
        return not self.sm.is_stopped()

    # ── 이동 헬퍼 ─────────────────────────────────────────────────
    def _movej(self, coords: List[float], label: str = "") -> bool:
        """관절 이동. 비상정지 시 False 반환."""
        if not self._ok():
            return False
        try:
            self.rc.movej(coords)
        except Exception as e:
            print(f"[{self.name}] _movej 오류: {e}")
            return False
        if label:
            self._tick(label)
        return self._ok()

    def _movel(self, coords: List[float], label: str = "") -> bool:
        """직선(Cartesian) 이동. 비상정지 시 False 반환."""
        if not self._ok():
            return False
        try:
            self.rc.movel(coords)
        except Exception as e:
            print(f"[{self.name}] _movel 오류: {e}")
            return False
        if label:
            self._tick(label)
        return self._ok()

    # ── 그리퍼 헬퍼 ──────────────────────────────────────────────
    def _gripper(self, width_mm: int):
        """그리퍼 폭 설정 (5 / 20 / 30 / 50 / 100 mm)."""
        self.rc.set_gripper(width_mm)

    # ── 진행 로그 ─────────────────────────────────────────────────
    def _tick(self, label: str, done: bool = False):
        self.sm.tick(label)
        self.sm.add_step_log(label, completed=done)
