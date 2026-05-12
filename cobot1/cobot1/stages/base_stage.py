#!/usr/bin/env python3
"""
==============================================================================
[Phase 3] 나만의 도련님 도시락 - 스테이지 기본 클래스 (Lock 동기화 버전)
==============================================================================
변경 요약:
  - RobotClient 가 모든 DSR API 를 락으로 직렬화하므로 더 이상
    "generator already executing" 충돌이 발생하지 않음.
  - 따라서 무한 재시도 while-loop / time.sleep(0.05) 같은 magic cooldown 제거.
  - 코드가 훨씬 읽기 쉬워지고, 비상정지 분기도 명확해짐.

  - _movej/_movel : sync 함수이므로 RobotClient 가 mwait 까지 처리. 별도 wait 불필요.
  - _amovej/_amovel : 비동기 → wait_motion_done() 호출 (락은 짧게 잡고 풀어가며 폴링).
  - _move_periodic : RobotClient.do_move_periodic 내부에서 wait_motion_done 처리.
==============================================================================
"""

import time
import numpy as np
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
        # robot_controller 에서 주입되는 세그먼트 publish 콜백
        self._seg_publish_fn: Optional[Callable[[dict], None]] = seg_publish_fn

    @abstractmethod
    def execute(self) -> StageResult:
        ...

    def _ok(self) -> bool:
        return not self.sm.is_stopped()

    # ──────────────────────────────────────────────────────────────
    # 모션 헬퍼 — RobotClient 락이 직렬화하므로 단순한 호출 구조
    # ──────────────────────────────────────────────────────────────
    def _movej(self, coords: List[float], label: str = "",
               radius: Optional[float] = None) -> bool:
        if not self._ok(): return False
        self.sm.wait_if_paused()
        if not self._ok(): return False
        try:
            self.rc.do_movej(coords, radius=radius)
        except Exception as e:
            self._logger.error(f"_movej 오류: {e}")
            return False
        if label: self._tick(label)
        return self._ok()

    def _movel(self, coords: List[float], label: str = "",
               radius: Optional[float] = None) -> bool:
        if not self._ok(): return False
        self.sm.wait_if_paused()
        if not self._ok(): return False
        try:
            self.rc.do_movel(coords, radius=radius)
        except Exception as e:
            self._logger.error(f"_movel 오류: {e}")
            return False
        if label: self._tick(label)
        return self._ok()

    def _amovej(self, coords: List[float], label: str = "",
                radius: Optional[float] = None) -> bool:
        if not self._ok(): return False
        self.sm.wait_if_paused()
        if not self._ok(): return False
        try:
            self.rc.do_amovej(coords, radius=radius)
            if not self.rc.wait_motion_done():
                return False
        except Exception as e:
            self._logger.error(f"_amovej 오류: {e}")
            return False
        if label: self._tick(label)
        return self._ok()

    def _amovel(self, coords: List[float], label: str = "",
                radius: Optional[float] = None) -> bool:
        if not self._ok(): return False
        self.sm.wait_if_paused()
        if not self._ok(): return False
        try:
            self.rc.do_amovel(coords, radius=radius)
            if not self.rc.wait_motion_done():
                return False
        except Exception as e:
            self._logger.error(f"_amovel 오류: {e}")
            return False
        if label: self._tick(label)
        return self._ok()

    def _move_periodic(self, amp: list, period: list, atime: float, repeat: int,
                       label: str = "") -> bool:
        if not self._ok(): return False
        self.sm.wait_if_paused()
        if not self._ok(): return False
        try:
            self.rc.do_move_periodic(amp=amp, period=period,
                                     atime=atime, repeat=repeat)
        except Exception as e:
            self._logger.error(f"_move_periodic 오류: {e}")
            return False
        if label: self._tick(label)
        return self._ok()

    # ──────────────────────────────────────────────────────────────
    # 그리퍼
    # ──────────────────────────────────────────────────────────────
    def _gripper(self, width_mm: int) -> None:
        self.sm.wait_if_paused()
        self.rc.set_gripper(width_mm)

    def _check_grip(self) -> bool:
        try:
            return self.rc.check_grip()
        except Exception as e:
            self._logger.error(f"_check_grip 오류: {e}")
            return False

    # ──────────────────────────────────────────────────────────────
    # 진행 로그
    # ──────────────────────────────────────────────────────────────
    def _tick(self, label: str, done: bool = False) -> None:
        self.sm.tick(label)
        self.sm.add_step_log(label, completed=done)

    # ──────────────────────────────────────────────────────────────
    # 모션 세그먼트 publish (대시보드 비교 분석용)
    # ──────────────────────────────────────────────────────────────
    def _seg_start(self, seg_id: str, motion: str, label: str) -> None:
        """motion: 'sync' | 'async'"""
        if self._seg_publish_fn:
            self._seg_publish_fn({
                'type':   'seg_start',
                'seg_id': seg_id,
                'motion': motion,
                'label':  label,
            })

    def _seg_end(self, seg_id: str) -> None:
        if self._seg_publish_fn:
            self._seg_publish_fn({'type': 'seg_end', 'seg_id': seg_id})

    # ──────────────────────────────────────────────────────────────
    # 토크 분류 (n샘플 평균 → 페이로드 클래스)
    # ──────────────────────────────────────────────────────────────
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

        import numpy as np
        arr = np.array(samples, dtype=np.float64)
        mean = arr.mean(axis=0)
        self._logger.info(
            f"토크 평균 J1~J6: {[round(float(v),4) for v in mean]}"
        )
        self._logger.info(f"  → J2 = {mean[1]:.4f}")

        result = get_classifier().predict_class_from_mean(samples)
        self._logger.info(f"토크 분류 결과: {result} (샘플 {len(samples)}개)")
        return result
    
    def _measure_j2_baseline(self, n: int = 5, interval: float = 0.1) -> float:
        """
        현재 자세에서 J2 토크 평균을 측정해 동적 baseline 반환.
        로봇이 정지 상태일 때 호출할 것.
        """
        samples = []
        for _ in range(n):
            try:
                t = self.rc.get_external_torque()
                if t and len(t) == 6:
                    samples.append(t[1])  # J2만
            except Exception:
                pass
            time.sleep(interval)

        if not samples:
            self._logger.warn("baseline 측정 실패 → 기본값 -3.4 사용")
            return -3.4  # 폴백

        baseline = float(np.mean(samples))
        self._logger.info(f"J2 baseline 측정: {baseline:.4f} (샘플 {len(samples)}개)")
        return baseline


    def _sample_torque_class_dynamic(
        self, n: int, interval: float, baseline_j2: float
    ) -> str:
        """
        동적 baseline 기반 판별.
        DELTA ≈ 0.325 (집게 → 집게+돈까스 J2 변화량 실측 평균)
        """
        DELTA = 0.25
        boundary = baseline_j2 + DELTA / 2  # baseline보다 DELTA/2 위

        samples = []
        for _ in range(n):
            try:
                t = self.rc.get_external_torque()
                if t and len(t) == 6:
                    samples.append(t[1])
            except Exception:
                pass
            time.sleep(interval)

        if not samples:
            self._logger.warn("토크 샘플 없음 → 빈그리퍼 처리")
            return "빈그리퍼"

        mean_j2 = float(np.mean(samples))
        self._logger.info(
            f"[동적 판별] J2 측정={mean_j2:.4f} | baseline={baseline_j2:.4f} "
            f"| boundary={boundary:.4f}"
        )

        # baseline과 측정값 차이가 너무 작으면 미파지
        if mean_j2 < boundary:
            return "집게"
        return "집게+돈까스"