#!/usr/bin/env python3
"""
==============================================================================
[Phase 2] 나만의 도련님 도시락 - 좌표 관리자
==============================================================================
robot_coordinates.yaml 을 읽어 각 스테이지 / 서브 반찬 좌표를 제공.
코드에 하드코딩된 좌표를 모두 이 클래스를 통해 접근.
==============================================================================
"""

import os
from typing import Dict, List, Any

import yaml
from rclpy.logging import get_logger

_logger = get_logger('coordinate_manager')


class CoordinateManager:
    """
    YAML 설정 파일에서 좌표를 로드.

    사용 예::

        cm = CoordinateManager()               # 기본 경로 자동 탐색
        cm.home_joint()                        # [0.002, -0.043, ...]
        cm.sub_dish("피클")["pick_l"]          # [697.47, ...]
        cm.stage(1)["tray_storage"]["upper"]   # [-81.953, ...]
    """

    # 패키지 루트 config 우선, 없으면 모듈 내 config fallback
    _PACKAGE_ROOT = os.path.dirname(os.path.dirname(__file__))  # cobot1/ 패키지 루트
    _DEFAULT_CONFIG = os.path.join(_PACKAGE_ROOT, "config", "robot_coordinates.yaml")
    _FALLBACK_CONFIG = os.path.join(os.path.dirname(__file__), "config", "robot_coordinates.yaml")

    def __init__(self, config_path: str = None):
        """YAML 설정 파일을 로드하여 코디네이트 매니저를 초기화한다.

        Args:
            config_path (str | None): YAML 파일 절대 경로.
                                      None이면 cobot1/config/robot_coordinates.yaml 자동 탐색.
        Raises:
            FileNotFoundError: 파일이 존재하지 않으면.
        """
        if config_path:
            path = config_path
        elif os.path.exists(self._DEFAULT_CONFIG):
            path = self._DEFAULT_CONFIG
        elif os.path.exists(self._FALLBACK_CONFIG):
            path = self._FALLBACK_CONFIG
            _logger.warn(f"패키지 루트 config 없음, fallback 사용: {path}")
        else:
            raise FileNotFoundError(
                f"[CoordinateManager] 설정 파일 없음: {self._DEFAULT_CONFIG}"
            )
        if not os.path.exists(path):
            raise FileNotFoundError(f"[CoordinateManager] 설정 파일 없음: {path}")
        with open(path, "r", encoding="utf-8") as f:
            self._cfg = yaml.safe_load(f)
        _logger.info(f"설정 로드 완료: {path}")

    # ── 로봇 기본 설정 ────────────────────────────────────────────
    @property
    def robot_cfg(self) -> dict:
        """YAML robot 섹션의 전체 dict를 반환한다.

        Returns:
            dict: velocity, acceleration, tool, tcp 등이 포함된 로봇 설정 dict.
        """
        return self._cfg["robot"]

    @property
    def velocity(self) -> int:
        """YAML에 설정된 기본 이동 속도를 반환한다.

        Returns:
            int: 이동 속도 (%).
        """
        return self.robot_cfg["velocity"]

    @property
    def acceleration(self) -> int:
        """YAML에 설정된 기본 가속도를 반환한다.

        Returns:
            int: 가속도 (%).
        """
        return self.robot_cfg["acceleration"]

    @property
    def tool(self) -> str:
        """YAML에 설정된 툴 이름을 반환한다.

        Returns:
            str: 툴 이름 문자열.
        """
        return self.robot_cfg["tool"]

    @property
    def tcp(self) -> str:
        """YAML에 설정된 TCP 이름을 반환한다.

        Returns:
            str: TCP 이름 문자열.
        """
        return self.robot_cfg["tcp"]

    # ── 좌표 접근 ─────────────────────────────────────────────────
    def home_joint(self) -> List[float]:
        """YAML에 정의된 홈 자세의 관절 각도를 반환한다.

        Returns:
            List[float]: [J1~J6] 관절 각도 (deg).
        """
        return self._cfg["coordinates"]["home"]["joint"]

    def stage(self, num: int) -> Dict[str, Any]:
        """지정한 스테이지의 전체 좌표 dict를 반환한다.

        Args:
            num (int): 스테이지 번호 (1~5).
        Returns:
            Dict[str, Any]: 해당 스테이지의 웨이포인트 좌표 dict.
        Raises:
            KeyError: YAML에 stage_{num}이 없으면.
        """
        key = f"stage_{num}"
        coords = self._cfg.get("coordinates", {})
        if key not in coords:
            raise KeyError(f"[CoordinateManager] 스테이지 {num} 없음")
        return coords[key]

    def sub_dish_pick(self, dish_name: str) -> Dict[str, List[float]]:
        """선택된 반찬의 집기(Pick) 관련 웨이포인트를 반환한다.

        Args:
            dish_name (str): 반찬 이름 (예: 피클, 단무지).
        Returns:
            Dict[str, List[float]]: {pre_pick_j, pick_l, up_pick_l} 좌표.
        Raises:
            KeyError: YAML에 등록되지 않은 반찬이면.
        """
        dishes = self._cfg["coordinates"]["stage_2_picks"]
        if dish_name not in dishes:
            raise KeyError(f"반찬 '{dish_name}' 없음.")
        return dishes[dish_name]

    def sub_dish_place(self, slot_index: int) -> Dict[str, List[float]]:
        """식판 칸 순서(Index)에 따른 놓기(Place) 웨이포인트를 반환한다.

        Args:
            slot_index (int): 식판 슬롯 인덱스 (0부터 시작).
        Returns:
            Dict[str, List[float]]: {pre_place_j, place_l} 좌표.
        Raises:
            KeyError: YAML에 slot_{slot_index}가 없으면.
        """
        # config에 slot_0, slot_1, slot_2 등으로 저장
        slots = self._cfg["coordinates"]["stage_2_places"]
        slot_key = f"slot_{slot_index}"
        if slot_key not in slots:
            raise KeyError(f"식판 슬롯 '{slot_key}' 없음.")
        return slots[slot_key]
    
    def available_sub_dishes(self) -> List[str]:
        """설정 파일에 등록된 서브 반찬 이름 목록을 반환한다.

        Returns:
            List[str]: YAML stage_2_picks 콘픽 목록.
        """
        return list(self._cfg["coordinates"]["stage_2_picks"].keys())
