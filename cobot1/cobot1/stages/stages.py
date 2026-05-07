#!/usr/bin/env python3
"""
==============================================================================
[Phase 3] 나만의 도련님 도시락 - 5개 스테이지 구현체
==============================================================================
각 스테이지는 BaseStage 를 상속하고 execute() 를 구현.
로봇 동작 순서는 lunchbox_robot_node.py 실측 시퀀스와 동일.

  Stage1 : TraySetupStage     - 식판 보관소 → 세팅 장소
  Stage2 : SubDishStage       - 서브 반찬 1종 Pick & Place (반찬마다 인스턴스)
  Stage3 : MainDishStage      - 메인 반찬 집게로 집어 식판에 올리기 + 소스
  Stage4 : RiceStage          - 스쿱으로 밥 퍼서 식판에 담기
  Stage5 : DeliveryStage      - 완성된 식판을 픽업 장소로 배달
==============================================================================
"""

from .base_stage import BaseStage, StageResult
from typing import Dict, List


# ============================================================================
# Stage 1 : 식판 세팅
# ============================================================================
class TraySetupStage(BaseStage):
    """식판 보관소에서 식판을 꺼내 세팅 장소에 내려놓는 스테이지."""

    def __init__(self, state_manager, robot_client, coord_manager):
        super().__init__(state_manager, robot_client, coord_manager, "TraySetup")

    def execute(self) -> StageResult:
        self.sm.update_status(current_task="🍱 [1/5] 식판 세팅")
        c1 = self.cm.stage(1)
        home = self.cm.home_joint()

        try:
            # 홈
            if not self._movej(home,                                  "🍱 [1/5] 홈 이동"):           return StageResult.STOPPED
            self._gripper(50)

            # 보관소 상단 → 하단
            if not self._movej(c1["tray_storage"]["upper"],           "🍱 [1/5] 보관소 상단"):        return StageResult.STOPPED
            if not self._movej(c1["tray_storage"]["lower"],           "🍱 [1/5] 보관소 하단"):        return StageResult.STOPPED

            # 식판 파지
            self._gripper(5)
            self.rc.wait(1.0)
            self._tick("🍱 [1/5] 식판 파지", done=True)

            # 들어올림
            if not self._movej(c1["tray_storage"]["upper"],           "🍱 [1/5] 식판 들어올림"):      return StageResult.STOPPED

            # 세팅 장소 이동
            if not self._movej(c1["setting"]["upper"],                "🍱 [1/5] 세팅 상단"):         return StageResult.STOPPED
            if not self._movej(c1["setting"]["lower_1"],              "🍱 [1/5] 세팅 하단1"):        return StageResult.STOPPED
            if not self._movej(c1["setting"]["lower_2"],              "🍱 [1/5] 세팅 하단2"):        return StageResult.STOPPED

            # 식판 내려놓기
            self._gripper(50)
            self.rc.wait(1.0)
            self._tick("🍱 [1/5] 식판 안착", done=True)

            # 그리퍼 후퇴
            if not self._movej(c1["setting"]["lower_3"],              "🍱 [1/5] 그리퍼 후퇴"):       return StageResult.STOPPED
            self._gripper(100)
            self.rc.wait(1.0)

            # 홈 복귀
            self._movej(home, "🍱 [1/5] 홈 복귀")
            self._tick("🍱 [1/5] 식판 세팅 완료", done=True)
            return StageResult.SUCCESS

        except Exception as e:
            print(f"[TraySetup] 오류: {e}")
            return StageResult.ERROR


# ============================================================================
# Stage 2 : 서브 반찬 (1종)
# ============================================================================
class SubDishStage(BaseStage):
    """
    서브 반찬 1종의 Pick & Place 스테이지.
    dish_name 에 따라 좌표를 CoordinateManager 에서 가져옴.
    """

    def __init__(self, state_manager, robot_client, coord_manager, dish_name: str):
        super().__init__(state_manager, robot_client, coord_manager, f"SubDish-{dish_name}")
        self.dish_name = dish_name

    def execute(self) -> StageResult:
        self.sm.update_status(current_task=f"🥗 [2/5] 서브 반찬 - [{self.dish_name}]")
        home = self.cm.home_joint()

        try:
            wp = self.cm.sub_dish(self.dish_name)
        except KeyError as e:
            print(f"[SubDish] 좌표 없음: {e}")
            return StageResult.ERROR

        try:
            # 홈
            if not self._movej(home,                    f"🥗 [{self.dish_name}] 홈 이동"):     return StageResult.STOPPED
            self._gripper(100)

            # 반찬통 접근 (관절) → 픽 위치 (직선)
            if not self._movej(wp["pre_pick_j"],        f"🥗 [{self.dish_name}] 픽 준비"):      return StageResult.STOPPED
            if not self._movel(wp["pick_l"],            f"🥗 [{self.dish_name}] 픽 위치"):      return StageResult.STOPPED

            # 집기
            self._gripper(20)
            self.rc.wait(0.5)
            self._tick(f"🥗 [{self.dish_name}] 집기", done=True)

            # 들어올림
            if not self._movel(wp["up_pick_l"],         f"🥗 [{self.dish_name}] 들어올림"):     return StageResult.STOPPED

            # 식판 슬롯 이동 (관절) → 놓기 (직선)
            if not self._movej(wp["pre_place_j"],       f"🥗 [{self.dish_name}] 슬롯 접근"):    return StageResult.STOPPED
            if not self._movel(wp["place_l"],           f"🥗 [{self.dish_name}] 놓기"):         return StageResult.STOPPED

            # 놓기
            self._gripper(100)
            self._tick(f"🥗 [{self.dish_name}] 완료", done=True)

            # 홈 복귀
            self._movej(home, f"🥗 [{self.dish_name}] 홈 복귀")
            return StageResult.SUCCESS

        except Exception as e:
            print(f"[SubDish-{self.dish_name}] 오류: {e}")
            return StageResult.ERROR


# ============================================================================
# Stage 3 : 메인 반찬
# ============================================================================
class MainDishStage(BaseStage):
    """
    메인 반찬을 집게로 집어 식판에 담고 소스를 뿌리는 스테이지.
    main_dish 파라미터 확장 시 stage_3 아래에 종류별 좌표를 추가하면 됨.
    """

    def __init__(self, state_manager, robot_client, coord_manager, main_dish: str):
        super().__init__(state_manager, robot_client, coord_manager, "MainDish")
        self.main_dish = main_dish

    def execute(self) -> StageResult:
        self.sm.update_status(current_task=f"🍖 [3/5] 메인 반찬 - [{self.main_dish}]")
        c3   = self.cm.stage(3)
        home = self.cm.home_joint()

        try:
            # 홈
            if not self._movej(home,                     "🍖 [3/5] 홈 이동"):       return StageResult.STOPPED
            self._gripper(100)

            # 집게 상단 → 하단
            if not self._movel(c3["approach_l"],         "🍖 [3/5] 집게 상단"):     return StageResult.STOPPED
            if not self._movel(c3["above_l"],            "🍖 [3/5] 집게 하단"):     return StageResult.STOPPED

            # 반찬 집기
            self._gripper(30)
            self._tick("🍖 [3/5] 반찬 집기", done=True)

            # 들어올려 식판으로 이동
            if not self._movel(c3["up_l"],               "🍖 [3/5] 집어올림"):      return StageResult.STOPPED
            if not self._movel(c3["transit_l"],          "🍖 [3/5] 식판 상단"):     return StageResult.STOPPED
            if not self._movel(c3["place_above_l"],      "🍖 [3/5] 식판 하단"):     return StageResult.STOPPED

            # 투하
            self._gripper(20)
            self._tick("🍖 [3/5] 반찬 투하", done=True)

            # 소스 뿌리기 시퀀스
            if not self._movel(c3["place_up2_l"],        "🍖 [3/5] 소스 상단"):     return StageResult.STOPPED
            if not self._movel(c3["sauce_above_l"],      "🍖 [3/5] 소스 접근"):     return StageResult.STOPPED
            self._gripper(30)
            if not self._movel(c3["sauce_pour_l"],       "🍖 [3/5] 소스 붓기"):     return StageResult.STOPPED

            # 집게 원위치
            if not self._movel(c3["ret1_l"],             "🍖 [3/5] 집게 복귀 상단"): return StageResult.STOPPED
            if not self._movel(c3["ret2_l"],             "🍖 [3/5] 집게 복귀 하단"): return StageResult.STOPPED
            self._gripper(100)

            # 홈 복귀
            self._movej(home, "🍖 [3/5] 홈 복귀")
            self._tick("🍖 [3/5] 메인 반찬 완료", done=True)
            return StageResult.SUCCESS

        except Exception as e:
            print(f"[MainDish] 오류: {e}")
            return StageResult.ERROR


# ============================================================================
# Stage 4 : 밥 담기
# ============================================================================
class RiceStage(BaseStage):
    """스쿱을 이용해 밥솥에서 밥을 퍼 식판에 담는 스테이지."""

    def __init__(self, state_manager, robot_client, coord_manager):
        super().__init__(state_manager, robot_client, coord_manager, "Rice")

    def execute(self) -> StageResult:
        self.sm.update_status(current_task="🍚 [4/5] 밥 담기")
        c4   = self.cm.stage(4)
        home = self.cm.home_joint()

        # 스쿱 동작 순서 정의
        scoop_seq = [
            ("scoop_1_l", "🍚 스쿱1"),
            ("scoop_2_l", "🍚 스쿱2"),
            ("scoop_3_l", "🍚 스쿱3"),
            ("scoop_4_l", "🍚 스쿱4"),
            ("scoop_5_l", "🍚 스쿱5"),
            ("scoop_6_l", "🍚 스쿱6"),
        ]

        try:
            # 홈
            if not self._movej(home,                   "🍚 [4/5] 홈 이동"):        return StageResult.STOPPED
            self._gripper(50)

            # 밥솥 접근
            if not self._movel(c4["approach_l"],       "🍚 [4/5] 밥솥 접근"):      return StageResult.STOPPED
            if not self._movel(c4["above_l"],          "🍚 [4/5] 밥솥 위"):        return StageResult.STOPPED

            # 스쿱 집기
            self._gripper(5)
            self.rc.wait(0.5)
            self._tick("🍚 [4/5] 스쿱 파지", done=True)

            # 스쿱 동작
            for key, label in scoop_seq:
                if not self._movel(c4[key], label):
                    return StageResult.STOPPED

            # 식판으로 이동
            if not self._movel(c4["transit_l"],        "🍚 [4/5] 식판으로 이동"):   return StageResult.STOPPED
            if not self._movel(c4["place_pre_l"],      "🍚 [4/5] 밥칸 접근"):      return StageResult.STOPPED
            if not self._movel(c4["place_down_l"],     "🍚 [4/5] 밥칸 하강"):      return StageResult.STOPPED

            # 스쿱 복귀
            if not self._movel(c4["place_up_l"],       "🍚 [4/5] 스쿱 복귀"):      return StageResult.STOPPED
            if not self._movel(c4["back_l"],           "🍚 [4/5] 밥솥 복귀"):      return StageResult.STOPPED

            # 스쿱 내려놓기
            self._gripper(100)
            self._tick("🍚 [4/5] 스쿱 내려놓기", done=True)

            # 대기 자세
            if not self._movel(c4["home_ready_l"],     "🍚 [4/5] 대기 자세"):      return StageResult.STOPPED
            self._tick("🍚 [4/5] 밥 담기 완료", done=True)

            # 홈 복귀
            self._movej(home, "🍚 [4/5] 홈 복귀")
            return StageResult.SUCCESS

        except Exception as e:
            print(f"[Rice] 오류: {e}")
            return StageResult.ERROR


# ============================================================================
# Stage 5 : 식판 배달
# ============================================================================
class DeliveryStage(BaseStage):
    """완성된 식판을 픽업 장소로 배달하는 스테이지."""

    def __init__(self, state_manager, robot_client, coord_manager):
        super().__init__(state_manager, robot_client, coord_manager, "Delivery")

    def execute(self) -> StageResult:
        self.sm.update_status(current_task="📦 [5/5] 식판 배달")
        c5 = self.cm.stage(5)

        try:
            # 식판 파지 준비
            if not self._movel(c5["p004_l"],  "📦 [5/5] 접근"):          return StageResult.STOPPED
            if not self._movej(c5["p005_j"],  "📦 [5/5] 파지 준비1"):     return StageResult.STOPPED
            if not self._movej(c5["p006_j"],  "📦 [5/5] 파지 위치"):      return StageResult.STOPPED

            # 식판 파지
            self._gripper(5)
            self.rc.wait(1.0)
            self._tick("📦 [5/5] 식판 파지", done=True)

            # 픽업 장소로 이동
            if not self._movel(c5["p007_l"],  "📦 [5/5] 들어올림"):       return StageResult.STOPPED
            if not self._movej(c5["p008_j"],  "📦 [5/5] 이동1"):          return StageResult.STOPPED
            if not self._movel(c5["p009_l"],  "📦 [5/5] 픽업장소 접근"):   return StageResult.STOPPED
            if not self._amovej(c5["p010_j"], "📦 [5/5] 이동2"):          return StageResult.STOPPED
            if not self._movel(c5["p011_l"],  "📦 [5/5] 안착 준비"):      return StageResult.STOPPED
            if not self._movej(c5["p012_j"],  "📦 [5/5] 안착 위치"):      return StageResult.STOPPED

            # 식판 내려놓기
            self._gripper(50)
            self._tick("📦 [5/5] 식판 안착", done=True)

            # 후퇴 (실패해도 배달 완료로 처리)
            result = self._movel(c5["p013_l"], "📦 [5/5] 후퇴")
            if not result:
                print("[Delivery] ⚠️ 후퇴 미완료 (비상정지 가능성)")

            self._tick("📦 [5/5] 식판 배달 완료", done=True)
            return StageResult.SUCCESS

        except Exception as e:
            print(f"[Delivery] 오류: {e}")
            return StageResult.ERROR
