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


class CoordinateManager:
    """
    YAML 설정 파일에서 좌표를 로드.

    사용 예::

        cm = CoordinateManager()               # 기본 경로 자동 탐색
        cm.home_joint()                        # [0.002, -0.043, ...]
        cm.sub_dish("피클")["pick_l"]          # [697.47, ...]
        cm.stage(1)["tray_storage"]["upper"]   # [-81.953, ...]
    """

    _DEFAULT_CONFIG = os.path.join(
        os.path.dirname(__file__), "config", "robot_coordinates.yaml"
    )

    def __init__(self, config_path: str = None):
        path = config_path or self._DEFAULT_CONFIG
        if not os.path.exists(path):
            raise FileNotFoundError(f"[CoordinateManager] 설정 파일 없음: {path}")
        with open(path, "r", encoding="utf-8") as f:
            self._cfg = yaml.safe_load(f)
        print(f"[CoordinateManager] 설정 로드 완료: {path}")

    # ── 로봇 기본 설정 ────────────────────────────────────────────
    @property
    def robot_cfg(self) -> dict:
        return self._cfg["robot"]

    @property
    def velocity(self) -> int:
        return self.robot_cfg["velocity"]

    @property
    def acceleration(self) -> int:
        return self.robot_cfg["acceleration"]

    @property
    def tool(self) -> str:
        return self.robot_cfg["tool"]

    @property
    def tcp(self) -> str:
        return self.robot_cfg["tcp"]

    # ── 좌표 접근 ─────────────────────────────────────────────────
    def home_joint(self) -> List[float]:
        return self._cfg["coordinates"]["home"]["joint"]

    def stage(self, num: int) -> Dict[str, Any]:
        """스테이지 전체 좌표 dict 반환."""
        key = f"stage_{num}"
        coords = self._cfg.get("coordinates", {})
        if key not in coords:
            raise KeyError(f"[CoordinateManager] 스테이지 {num} 없음")
        return coords[key]

    def sub_dish_pick(self, dish_name: str) -> Dict[str, List[float]]:
        """선택된 반찬의 집기(Pick) 관련 좌표만 반환 (pre_pick, pick, up_pick)"""
        dishes = self._cfg["coordinates"]["stage_2_picks"]
        if dish_name not in dishes:
            raise KeyError(f"반찬 '{dish_name}' 없음.")
        return dishes[dish_name]

    def sub_dish_place(self, slot_index: int) -> Dict[str, List[float]]:
        """식판의 칸 순서(Index)에 따른 놓기(Place) 좌표 반환 (pre_place, place)"""
        # config에 slot_0, slot_1, slot_2 등으로 저장
        slots = self._cfg["coordinates"]["stage_2_places"]
        slot_key = f"slot_{slot_index}"
        if slot_key not in slots:
            raise KeyError(f"식판 슬롯 '{slot_key}' 없음.")
        return slots[slot_key]
    
    def available_sub_dishes(self) -> List[str]:
        """설정 파일에 등록된 서브 반찬 이름 목록."""
        return list(self._cfg["coordinates"]["stage_2"].keys())
