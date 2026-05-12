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

import time
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
            if not self._movej(c1["tray_storage"]["lower"],           "🍱 [1/5] 보관소 하단"):        return StageResult.STOPPED

                
            # 식판 파지
            self._gripper(5)
            self.rc.wait(1.0)
            self._tick("🍱 [1/5] 식판 파지", done=True)

            # 들어올림
            if not self._movej(c1["tray_storage"]["upper"],           "🍱 [1/5] 식판 들어올림"):      return StageResult.STOPPED

            # 세팅 장소 이동 (순응+힘제어: 식판 안착 시 -10N 아래방향 유지)
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
            if "generator already executing" in str(e):
                self._logger.warn(f"executor 충돌 감지, 재시도: {e}")
                time.sleep(0.5)
                return self.execute()
            self._logger.error(f"오류: {e}")
            return StageResult.ERROR


# ============================================================================
# Stage 2 : 서브 반찬 (씔0)
class SubDishStage(BaseStage):
    """서브 반찬 1종의 Pick & Place 스테이지. dish_name에 따라 좌표를 가져온다."""

    def __init__(self, state_manager, robot_client, coord_manager,
                 dish_name: str, slot_index: int, seg_publish_fn=None):
        super().__init__(state_manager, robot_client, coord_manager,
                         f"SubDish-{dish_name}", seg_publish_fn=seg_publish_fn)
        self.dish_name = dish_name
        self.slot_index = slot_index

    def execute(self) -> StageResult:
        """지정한 반찬을 집어서 식판 슬롯에 놓는 시퀀스를 실행한다.

        Returns:
            StageResult: SUCCESS | STOPPED | ERROR.
        """
        self.sm.update_status(current_task=f"🥗 [2/5] 서브 반찬 - [{self.dish_name}]")
        home = self.cm.home_joint()
        d = self.dish_name

        try:
            pick_wp  = self.cm.sub_dish_pick(d)
            place_wp = self.cm.sub_dish_place(self.slot_index)
        except KeyError as e:
            self._logger.error(f"SubDish 좌표 없음: {e}")
            return StageResult.ERROR

        # 세그먼트 ID: 반찬명 + 슬롯으로 구분
        seg_sync  = f"sub_sync_{d}_{self.slot_index}"
        seg_async = f"sub_async_{d}_{self.slot_index}"

        try:
            # ── [동기 구간 시작] 홈 → 픽 위치 ────────────────────────────────
            self._seg_start(seg_sync, 'sync', f'{d} 픽 접근(동기)')

            if not self._movej(home,                 f"🥗 [{d}] 홈 이동"):  return StageResult.STOPPED
            self._gripper(100)
            if not self._movej(pick_wp["pre_pick_j"],f"🥗 [{d}] 픽 준비", radius=40): return StageResult.STOPPED
            if not self._movel(pick_wp["pick_l"],    f"🥗 [{d}] 픽 위치", radius=40): return StageResult.STOPPED

            self._seg_end(seg_sync)
            # ── [동기 구간 종료] ─────────────────────────────────────────────

            # 집기 (동작 없음, 타이밍 제외)
            self._gripper(50)
            self.rc.wait(0.5)
            
            
            if not self._check_grip():
                return StageResult.ERROR
            self._tick(f"🥗 [{d}] 집기", done=True)

            # ── [비동기 구간 시작] 들어올림 → 슬롯 접근 (radius 블렌딩) ────────
            self._seg_start(seg_async, 'async', f'{d} 이송(비동기·radius=40)')

            if not self._amovel(pick_wp["up_pick_l"],    f"🥗 [{d}] 들어올림", radius=40):  return StageResult.STOPPED
            if not self._amovej(place_wp["pre_place_j"], f"🥗 [{d}] 슬롯 접근", radius=40): return StageResult.STOPPED

            self._seg_end(seg_async)
            # ── [비동기 구간 종료] ────────────────────────────────────────────

            if not self._movel(place_wp["place_l"], f"🥗 [{d}] 놓기"): return StageResult.STOPPED

            self._gripper(100)
            self._tick(f"🥗 [{d}] 완료", done=True)
            self._movej(home, f"🥗 [{d}] 홈 복귀")
            return StageResult.SUCCESS

        except Exception as e:
            if "generator already executing" in str(e):
                self._logger.warn(f"executor 충돌 감지, 재시도: {e}")
                time.sleep(0.5)
                return self.execute()
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

            # ── 토크 기반 반찬 파지 여부 판별 ─────────────────────────────
            self._tick("🍖 [3/5] 토크 측정 중", done=False)
            torque_cls = self._sample_torque_class(n=3, interval=0.15)
            self._logger.info(f"반찬 파지 판별: {torque_cls}")


            if torque_cls == "집게":
                # 반찬 미파지 → 다시 pick 위치로 돌아가 재시도
                self.sm.add_step_log("⚠️ [3/5] 반찬 미파지 → 재시도", completed=False)
                self._gripper(30)
                if not self._movel(c3["main_dish_transit_l"],  "🍖 [3/5] 재시도: 상단 경유"): return StageResult.STOPPED
                if not self._movel(c3["main_dish_pick_l"],     "🍖 [3/5] 재시도: 집기 위치"): return StageResult.STOPPED
                self._gripper(20)
                self._tick("🍖 [3/5] 재시도: 메인반찬 집기", done=True)
                if not self._movel(c3["main_dish_lift_l"],     "🍖 [3/5] 재시도: 들어올림"):  return StageResult.STOPPED

            # 정상 1개 파지 또는 그 외 → 식판에 투하
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
            if "generator already executing" in str(e):
                self._logger.warn(f"executor 충돌 감지, 재시도: {e}")
                time.sleep(0.5)
                return self.execute()
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
        self._set_singularity_handling(enable=True)
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
            if "generator already executing" in str(e):
                self._logger.warn(f"executor 충돌 감지, 재시도: {e}")
                time.sleep(0.5)
                return self.execute()
            self._logger.error(f"오류: {e}")
            return StageResult.ERROR
        finally:
            self._set_singularity_handling(enable=False)


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
        c5   = self.cm.stage(5)
        home = self.cm.home_joint()

        try:
            # 식판 파지 준비 (순응+힘제어: 식판 파지 시 -10N 아래방향 유지)
            if not self._movel(c5["p004_l"],  "📦 [5/5] 접근"):          return StageResult.STOPPED
            if not self._movej(c5["p005_j"],  "📦 [5/5] 파지 준비1"):     return StageResult.STOPPED
            
            if not self._movej(c5["p006_j"],  "📦 [5/5] 파지 위치"):
                return StageResult.STOPPED

            # 식판홀더 파지
            self._gripper(5)
            self.rc.wait(1.0)
            self._tick("📦 [5/5] 식판홀더 파지", done=True)

            # 픽업 장소로 이동
            if not self._movel(c5["p007_l"],  "📦 [5/5] 들어올림"):       return StageResult.STOPPED
            if not self._movej(c5["p008_j"],  "📦 [5/5] 이동1"):          return StageResult.STOPPED
            if not self._movel(c5["p009_l"],  "📦 [5/5] 픽업장소 접근"):   return StageResult.STOPPED
            if not self._movej(c5["p010_j"],  "📦 [5/5] 이동2"):          return StageResult.STOPPED
            if not self._movel(c5["p011_l"],  "📦 [5/5] 안착 준비"):      return StageResult.STOPPED
            # 순응+힘제어: 식판 안착 시 -10N 아래방향 유지
            
            if not self._movej(c5["p012_j"],  "📦 [5/5] 안착 위치"):
                return StageResult.STOPPED

            # 식판 내려놓기
            self._gripper(50)
            
            
            self._tick("📦 [5/5] 식판 안착", done=True)

            # 후퇴 (실패해도 배달 완료로 처리)
            result = self._movel(c5["p013_l"], "📦 [5/5] 후퇴")
            if not result:
                self._logger.warn("후퇴 미완료 (비상정지 가능성)")

            self._tick("📦 [5/5] 식판 배달 완료", done=True)
            return StageResult.SUCCESS

        except Exception as e:
            if "generator already executing" in str(e):
                self._logger.warn(f"executor 충돌 감지, 재시도: {e}")
                time.sleep(0.5)
                return self.execute()
            self._logger.error(f"오류: {e}")
            return StageResult.ERROR

    def execute_after_estop_resume(self) -> StageResult:
        """
        배달 중 비상정지(외력 60N 초과 또는 state=3 에러) 후 재개 버튼을 눌렀을 때 호출.

        토크를 측정해 현재 그리퍼 파지 상태를 판별하고 다음 중 하나를 수행:
          - 빈그리퍼          → 그리퍼 열고 홈 복귀 (처음 단계부터 재시작은 상위 컨트롤러가 담당)
          - 책받침            → 식판홀더만 잡고 있음 → 홀더 초기 위치 복귀 후 홈
          - 책받침+가득식판    → 홀더+식판 그대로 → 홀더 초기 위치 복귀 후 홈
        """
        self.sm.update_status(current_task="📦 [5/5] 비상정지 재개 - 파지 상태 확인 중")
        c5   = self.cm.stage(5)
        home = self.cm.home_joint()

        # ── 토크 측정 ─────────────────────────────────────────────────────────
        self._tick("📦 [5/5] 재개 후 토크 측정 중", done=False)
        torque_cls = self._sample_torque_class(n=5, interval=0.15)
        self._logger.info(f"비상정지 재개 파지 판별: {torque_cls}")

        try:
            if torque_cls == "빈그리퍼":
                # 그리퍼에 아무것도 없음 → 그리퍼 열고 홈 복귀
                self.sm.add_step_log("📦 빈 그리퍼 감지 → 홈 복귀 (1단계부터 재시작)")
                self._gripper(100)
                self._movej(home, "📦 [5/5] 홈 복귀")
                # StageResult.STOPPED를 반환해 상위 컨트롤러가 1단계 재시작을 인지하게 함
                return StageResult.STOPPED

            # 책받침 또는 책받침+가득식판 → 5단계 마지막 파트 (홀더 초기위치 복귀) 진행
            if torque_cls == "책받침+가득식판":
                self.sm.add_step_log("📦 식판홀더+식판 감지 → 홀더 초기 위치 복귀 진행")
            else:
                self.sm.add_step_log("📦 식판홀더만 감지 → 홀더 초기 위치 복귀 진행")

            # p012_j (안착 위치) 기준으로 재개: 그리퍼를 닫고 홀더를 초기 위치로 복귀
            self._gripper(5)
            self.rc.wait(0.5)

            # 홀더 초기 위치 복귀 경로 (역방향: p012 → p011 → p010 → p009 → p008 → p007 → p006)
            if not self._movej(c5["p012_j"],  "📦 [5/5] 재개: 안착위치 재확인"): return StageResult.STOPPED
            if not self._movel(c5["p011_l"],  "📦 [5/5] 재개: 안착준비 복귀"):   return StageResult.STOPPED
            if not self._movej(c5["p010_j"],  "📦 [5/5] 재개: 이동2 복귀"):      return StageResult.STOPPED
            if not self._movel(c5["p009_l"],  "📦 [5/5] 재개: 픽업접근 복귀"):   return StageResult.STOPPED
            if not self._movej(c5["p008_j"],  "📦 [5/5] 재개: 이동1 복귀"):      return StageResult.STOPPED
            if not self._movel(c5["p007_l"],  "📦 [5/5] 재개: 홀더 하강"):       return StageResult.STOPPED
            if not self._movej(c5["p006_j"],  "📦 [5/5] 재개: 홀더 초기위치"):   return StageResult.STOPPED

            # 홀더 내려놓기
            self._gripper(50)
            self.rc.wait(0.5)
            self._tick("📦 [5/5] 홀더 초기위치 안착", done=True)

            # 그리퍼 완전히 열고 홈 복귀
            self._gripper(100)
            self._movej(home, "📦 [5/5] 홈 복귀")
            self._tick("📦 [5/5] 비상정지 재개 완료", done=True)
            return StageResult.SUCCESS

        except Exception as e:
            if "generator already executing" in str(e):
                self._logger.warn(f"executor 충돌, 재시도: {e}")
                time.sleep(0.5)
                return self.execute_after_estop_resume()
            self._logger.error(f"비상정지 재개 오류: {e}")
            return StageResult.ERROR
