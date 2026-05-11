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
        """식판 세팅 스테이지를 생성한다.

        Args:
            state_manager: RobotStateManager 인스턴스.
            robot_client: RobotClient 인스턴스.
            coord_manager: CoordinateManager 인스턴스.
        """
        super().__init__(state_manager, robot_client, coord_manager, "TraySetup")

    def execute(self) -> StageResult:
        """식판 보관소 이동 선택 미주한 후 세팅 지점에 내려놓는 시퀀스를 실행한다.

        Returns:
            StageResult: SUCCESS | STOPPED | ERROR.
        """
        self.sm.update_status(current_task="🍱 [1/5] 식판 세팅")
        c1 = self.cm.stage(1)
        home = self.cm.home_joint()

        try:
            # 홈
            if not self._movej(home,                                  "🍱 [1/5] 홈 이동"):           return StageResult.STOPPED
            self._gripper(50)

            # 보관소 상단 → 하단 (순응+힘제어: 식판 접촉 시 -10N 아래방향 유지)
            if not self._movej(c1["tray_storage"]["upper"],           "🍱 [1/5] 보관소 상단"):        return StageResult.STOPPED
            self._start_compliance()
            self._start_force_ctrl(-10.0)
            if not self._movej(c1["tray_storage"]["lower"],           "🍱 [1/5] 보관소 하단"):
                self._stop_force_ctrl(); self._stop_compliance()
                return StageResult.STOPPED

            # 식판 파지
            self._gripper(5)
            self.rc.wait(1.0)
            self._stop_force_ctrl()
            self._stop_compliance()
            self._tick("🍱 [1/5] 식판 파지", done=True)

            # 들어올림
            if not self._movej(c1["tray_storage"]["upper"],           "🍱 [1/5] 식판 들어올림"):      return StageResult.STOPPED

            # 세팅 장소 이동 (순응+힘제어: 식판 안착 시 -10N 아래방향 유지)
            if not self._movej(c1["setting"]["upper"],                "🍱 [1/5] 세팅 상단"):         return StageResult.STOPPED
            if not self._movej(c1["setting"]["lower_1"],              "🍱 [1/5] 세팅 하단1"):        return StageResult.STOPPED
            self._start_compliance()
            self._start_force_ctrl(-10.0)
            if not self._movej(c1["setting"]["lower_2"],              "🍱 [1/5] 세팅 하단2"):
                self._stop_force_ctrl(); self._stop_compliance()
                return StageResult.STOPPED

            # 식판 내려놓기
            self._gripper(50)
            self.rc.wait(1.0)
            self._stop_force_ctrl()
            self._stop_compliance()
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
            self._logger.error(f"오류: {e}")
            return StageResult.ERROR


# ============================================================================
# Stage 2 : 서브 반찬 (씔0)
class SubDishStage(BaseStage):
    """서브 반찬 1종의 Pick & Place 스테이지. dish_name에 따라 좌표를 가져온다."""

    def __init__(self, state_manager, robot_client, coord_manager, dish_name: str, slot_index: int):
        """서브 반찬 스테이지를 생성한다.

        Args:
            state_manager: RobotStateManager 인스턴스.
            robot_client: RobotClient 인스턴스.
            coord_manager: CoordinateManager 인스턴스.
            dish_name (str): 반찬 이름 (예: 피클, 단무지). YAML에 등록되어 있어야 한다.
            slot_index (int): 식판의 몇 번째 칸에 놓을지 결정하는 인덱스.
        """
        super().__init__(state_manager, robot_client, coord_manager, f"SubDish-{dish_name}")
        self.dish_name = dish_name
        self.slot_index = slot_index  # 식판의 몇 번째 칸에 놓을지 결정하는 인덱스

    def execute(self) -> StageResult:
        """지정한 반찬을 집어서 식판 슬롯에 놓는 시퀀스를 실행한다.

        Returns:
            StageResult: SUCCESS | STOPPED | ERROR.
        """
        self.sm.update_status(current_task=f"🥗 [2/5] 서브 반찬 - [{self.dish_name}]")
        home = self.cm.home_joint()

        try:
            pick_wp = self.cm.sub_dish_pick(self.dish_name)
            place_wp = self.cm.sub_dish_place(self.slot_index)
        except KeyError as e:
            self._logger.error(f"SubDish 좌표 없음: {e}")
            return StageResult.ERROR

        try:
            # 홈
            if not self._movej(home,                    f"🥗 [{self.dish_name}] 홈 이동"):     return StageResult.STOPPED
            self._gripper(100)

            # 반찬통 접근 (관절) → 픽 위치 (직선)
            if not self._movej(pick_wp["pre_pick_j"],        f"🥗 [{self.dish_name}] 픽 준비", radius=40):      return StageResult.STOPPED
            # 순응+힘제어: 반찬통 접촉 시 -10N 아래방향 유지
            self._start_compliance()
            self._start_force_ctrl(-10.0)
            if not self._movel(pick_wp["pick_l"],            f"🥗 [{self.dish_name}] 픽 위치", radius=40):
                self._stop_force_ctrl(); self._stop_compliance()
                return StageResult.STOPPED

            # 집기
            self._gripper(50)
            self.rc.wait(0.5)
            self._stop_force_ctrl()
            self._stop_compliance()
            if not self._check_grip():
                return StageResult.ERROR

            self._tick(f"🥗 [{self.dish_name}] 집기", done=True)

            # 들어올림
            if not self._amovel(pick_wp["up_pick_l"],         f"🥗 [{self.dish_name}] 들어올림", radius=40):     return StageResult.STOPPED

            # 식판 슬롯 이동 (관절) → 놓기 (직선)
            if not self._amovej(place_wp["pre_place_j"],       f"🥗 [{self.dish_name}] 슬롯 접근", radius=40):    return StageResult.STOPPED
            # 순응+힘제어: 식판 슬롯 안착 시 -10N 아래방향 유지
            self._start_compliance()
            self._start_force_ctrl(-10.0)
            if not self._movel(place_wp["place_l"],           f"🥗 [{self.dish_name}] 놓기"):
                self._stop_force_ctrl(); self._stop_compliance()
                return StageResult.STOPPED

            # 놓기
            self._gripper(100)
            self._stop_force_ctrl()
            self._stop_compliance()
            self._tick(f"🥗 [{self.dish_name}] 완료", done=True)

            # 홈 복귀
            self._movej(home, f"🥗 [{self.dish_name}] 홈 복귀")
            return StageResult.SUCCESS

        except Exception as e:
            self._logger.error(f"오류: {e}")
            return StageResult.ERROR


# ============================================================================
# Stage 3 : 메인 반찬
# ============================================================================
class MainDishStage(BaseStage):
    """메인 반찬을 집게로 집어 식판에 담고 소스를 뒤리는 스테이지."""

    def __init__(self, state_manager, robot_client, coord_manager, main_dish: str):
        """메인 반찬 스테이지를 생성한다.

        Args:
            state_manager: RobotStateManager 인스턴스.
            robot_client: RobotClient 인스턴스.
            coord_manager: CoordinateManager 인스턴스.
            main_dish (str): 메인 반찬 이름 (예: 불고기, 생선구이). 로그 식별에 사용.
        """
        super().__init__(state_manager, robot_client, coord_manager, "MainDish")
        self.main_dish = main_dish

    def execute(self) -> StageResult:
        """집게로 메인 반찬을 집어 식판에 담는 시퀀스를 실행한다.

        Returns:
            StageResult: SUCCESS | STOPPED | ERROR.
        """
        self.sm.update_status(current_task=f"🍖 [3/5] 메인 반찬 - [{self.main_dish}]")
        c3   = self.cm.stage(3)
        home = self.cm.home_joint()

        try:
            # 홈
            if not self._movej(home,                          "🍖 [3/5] 홈 이동"):            return StageResult.STOPPED
            self._gripper(100)

            # 집게 위 접근
            if not self._movel(c3["tong_approach_l"],         "🍖 [3/5] 집게 위 접근"):       return StageResult.STOPPED

            # 집게 잡기
            self._gripper(30)
            self._tick("🍖 [3/5] 집게 파지", done=True)

            # 집게 들고 위로
            if not self._movel(c3["tong_lift_l"],             "🍖 [3/5] 집게 들어올림"):      return StageResult.STOPPED

            # 메인 반찬 용기 상단 → 집기 위치
            if not self._movel(c3["main_dish_transit_l"],     "🍖 [3/5] 메인반찬 상단"):      return StageResult.STOPPED
            if not self._movel(c3["main_dish_pick_l"],        "🍖 [3/5] 메인반찬 집기 위치"): return StageResult.STOPPED

            # 메인 반찬 집기
            self._gripper(20)
            self._tick("🍖 [3/5] 메인반찬 집기", done=True)

            # 반찬 집고 위로
            if not self._movel(c3["main_dish_lift_l"],        "🍖 [3/5] 반찬 들어올림"):      return StageResult.STOPPED

            # 식판 앞으로 이동 → 반찬 내려놓기
            if not self._movel(c3["tray_approach_l"],         "🍖 [3/5] 식판 앞 접근"):       return StageResult.STOPPED
            self._gripper(30)
            if not self._movel(c3["tray_release_l"],          "🍖 [3/5] 반찬 투하"):          return StageResult.STOPPED

            # 집게 원위치
            if not self._movel(c3["tong_return_above_l"],     "🍖 [3/5] 집게 복귀 상단"):     return StageResult.STOPPED
            if not self._movel(c3["tong_return_l"],           "🍖 [3/5] 집게 복귀 하단"):     return StageResult.STOPPED
            self._gripper(100)

            # 홈 복귀
            self._movej(home, "🍖 [3/5] 홈 복귀")
            self._tick("🍖 [3/5] 메인 반찬 완료", done=True)
            return StageResult.SUCCESS

        except Exception as e:
            self._logger.error(f"오류: {e}")
            return StageResult.ERROR


# ============================================================================
# Stage 4 : 밥 담기
# ============================================================================
class RiceStage(BaseStage):
    """스쿱을 이용해 밥솥에서 밥을 퍼 식판에 담는 스테이지."""

    def __init__(self, state_manager, robot_client, coord_manager):        
        super().__init__(state_manager, robot_client, coord_manager, "Rice")
        """밥 담기 스테이지를 생성한다.
        Args:
            state_manager: RobotStateManager 인스턴스.
            robot_client: RobotClient 인스턴스.
            coord_manager: CoordinateManager 인스턴스.
        """        

    def execute(self) -> StageResult:
        """스쿠로 밥을 퍼서 식판 밥칸에 담는 시퀀스를 실행한다.

        Returns:
            StageResult: SUCCESS | STOPPED | ERROR.
        """
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
            if not self._movel(c4["above_l"],          "🍚 [4/5] 밥솥 위"):        return StageResult.STOPPED

            # 스쿱 집기
            self._gripper(5)
            self.rc.wait(0.5)
            self._tick("🍚 [4/5] 스쿱 파지", done=True)

            # 스쿱 동작
            for key, label in scoop_seq:
                if not self._movel(c4[key], label):
                    return StageResult.STOPPED
                
            if not self._move_periodic(c4["scoop_move_periodic_1"], 0.5, 0.2, 15, "🍚 [4/5] 강하게 흔들기"):
                return StageResult.STOPPED
            if not self._move_periodic(c4["scoop_move_periodic_2"], 1.0, 0.2, 15, "🍚 [4/5] 약하게 흔들기"):
                return StageResult.STOPPED

            # 식판으로 이동
            if not self._movel(c4["transit_l"],        "🍚 [4/5] 식판으로 이동"):   return StageResult.STOPPED
            if not self._movel(c4["place_pre_l"],      "🍚 [4/5] 밥칸 접근"):      return StageResult.STOPPED
            if not self._movel(c4["place_down_l"],     "🍚 [4/5] 밥칸 하강"):      return StageResult.STOPPED

            # 스쿱 복귀
            if not self._movel(c4["place_up_l"],       "🍚 [4/5] 스쿱 복귀"):      return StageResult.STOPPED
            if not self._movel(c4["back_l"],           "🍚 [4/5] 밥솥 복귀"):      return StageResult.STOPPED
            if not self._movel(c4["back_lean_l"],           "🍚 [4/5] 밥솥 복귀"):      return StageResult.STOPPED


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
            self._logger.error(f"오류: {e}")
            return StageResult.ERROR


# ============================================================================
# Stage 5 : 식판 배달
# ============================================================================
class DeliveryStage(BaseStage):
    """완성된 식판을 픽업 장소로 배달하는 스테이지."""

    def __init__(self, state_manager, robot_client, coord_manager):
        """식판 배달 스테이지를 생성한다.

        Args:
            state_manager: RobotStateManager 인스턴스.
            robot_client: RobotClient 인스턴스.
            coord_manager: CoordinateManager 인스턴스.
        """
        super().__init__(state_manager, robot_client, coord_manager, "Delivery")

    def execute(self) -> StageResult:
        """완성된 식판을 파지해 픽업 지점에 안속하는 시퀀스를 실행한다.

        Returns:
            StageResult: SUCCESS | STOPPED | ERROR.
        """
        self.sm.update_status(current_task="📦 [5/5] 식판 배달")
        c5 = self.cm.stage(5)

        try:
            # 식판 파지 준비 (순응+힘제어: 식판 파지 시 -10N 아래방향 유지)
            if not self._movel(c5["p004_l"],  "📦 [5/5] 접근"):          return StageResult.STOPPED
            if not self._movej(c5["p005_j"],  "📦 [5/5] 파지 준비1"):     return StageResult.STOPPED
            self._start_compliance()
            self._start_force_ctrl(-10.0)
            if not self._movej(c5["p006_j"],  "📦 [5/5] 파지 위치"):
                self._stop_force_ctrl(); self._stop_compliance()
                return StageResult.STOPPED

            # 식판 파지
            self._gripper(5)
            self.rc.wait(1.0)
            self._stop_force_ctrl()
            self._stop_compliance()
            self._tick("📦 [5/5] 식판 파지", done=True)

            # 픽업 장소로 이동
            if not self._movel(c5["p007_l"],  "📦 [5/5] 들어올림"):       return StageResult.STOPPED
            if not self._movej(c5["p008_j"],  "📦 [5/5] 이동1"):          return StageResult.STOPPED
            if not self._movel(c5["p009_l"],  "📦 [5/5] 픽업장소 접근"):   return StageResult.STOPPED
            if not self._movej(c5["p010_j"],  "📦 [5/5] 이동2"):          return StageResult.STOPPED
            if not self._movel(c5["p011_l"],  "📦 [5/5] 안착 준비"):      return StageResult.STOPPED
            # 순응+힘제어: 식판 안착 시 -10N 아래방향 유지
            self._start_compliance()
            self._start_force_ctrl(-10.0)
            if not self._movej(c5["p012_j"],  "📦 [5/5] 안착 위치"):
                self._stop_force_ctrl(); self._stop_compliance()
                return StageResult.STOPPED

            # 식판 내려놓기
            self._gripper(50)
            self._stop_force_ctrl()
            self._stop_compliance()
            self._tick("📦 [5/5] 식판 안착", done=True)

            # 후퇴 (실패해도 배달 완료로 처리)
            result = self._movel(c5["p013_l"], "📦 [5/5] 후퇴")
            if not result:
                self._logger.warn("후퇴 미완료 (비상정지 가능성)")

            self._tick("📦 [5/5] 식판 배달 완료", done=True)
            return StageResult.SUCCESS

        except Exception as e:
            self._logger.error(f"오류: {e}")
            return StageResult.ERROR
