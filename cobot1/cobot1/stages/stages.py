#!/usr/bin/env python3
"""
==============================================================================
[Fix2] 나만의 도련님 도시락 - 5개 스테이지 구현체
==============================================================================
변경 요약 (이전 버전 대비):
  ★ 재귀 재시도 (return self.execute()) 제거
    → 충돌 감지 시 처음부터 다시 실행하면 이미 했던 동작을 또 하게 되어 위험
    → StageResult.ERROR 를 반환하여 상위 _process_order 가 처리
  ★ 충돌 감지 시 적절한 로그만 남기고 ERROR 반환
==============================================================================
"""

import time
from .base_stage import BaseStage, StageResult
from typing import Dict, List


def _is_generator_busy(e: Exception) -> bool:
    """DSR service generator 충돌 식별"""
    return "generator already executing" in str(e)


# ============================================================================
# Stage 1 : 식판 세팅
# ============================================================================
class TraySetupStage(BaseStage):
    def __init__(self, state_manager, robot_client, coord_manager):
        super().__init__(state_manager, robot_client, coord_manager, "TraySetup")

    def execute(self) -> StageResult:
        self.sm.update_status(current_task="🍱 [1/5] 식판 세팅")
        c1 = self.cm.stage(1)
        home = self.cm.home_joint()

        try:
            if not self._movej(home,                                  "🍱 [1/5] 홈 이동"):           return StageResult.STOPPED
            self._gripper(50)

            if not self._movej(c1["tray_storage"]["upper"],           "🍱 [1/5] 보관소 상단"):        return StageResult.STOPPED
            if not self._movej(c1["tray_storage"]["lower"],           "🍱 [1/5] 보관소 하단"):        return StageResult.STOPPED

            self._gripper(5)
            self.rc.wait(1.0)
            self._tick("🍱 [1/5] 식판 파지", done=True)

            if not self._movej(c1["tray_storage"]["upper"],           "🍱 [1/5] 식판 들어올림"):      return StageResult.STOPPED

            if not self._movej(c1["setting"]["upper"],                "🍱 [1/5] 세팅 상단"):         return StageResult.STOPPED
            if not self._movej(c1["setting"]["lower_1"],              "🍱 [1/5] 세팅 하단1"):        return StageResult.STOPPED
            if not self._movej(c1["setting"]["lower_2"],              "🍱 [1/5] 세팅 하단2"):        return StageResult.STOPPED

            self._gripper(50)
            self.rc.wait(1.0)
            self._tick("🍱 [1/5] 식판 안착", done=True)

            if not self._movej(c1["setting"]["lower_3"],              "🍱 [1/5] 그리퍼 후퇴"):       return StageResult.STOPPED
            self._gripper(100)
            self.rc.wait(1.0)

            self._movej(home, "🍱 [1/5] 홈 복귀")
            self._tick("🍱 [1/5] 식판 세팅 완료", done=True)
            return StageResult.SUCCESS

        except Exception as e:
            if _is_generator_busy(e):
                self._logger.error(f"executor 충돌 - 재시도하지 않고 에러 반환: {e}")
                self.sm.add_step_log("🚨 [1/5] DSR 통신 충돌 - 1단계 중단")
            else:
                self._logger.error(f"오류: {e}")
            return StageResult.ERROR


# ============================================================================
# Stage 2 : 서브 반찬
# ============================================================================
class SubDishStage(BaseStage):
    def __init__(self, state_manager, robot_client, coord_manager,
                 dish_name: str, slot_index: int, seg_publish_fn=None):
        super().__init__(state_manager, robot_client, coord_manager,
                         f"SubDish-{dish_name}", seg_publish_fn=seg_publish_fn)
        self.dish_name = dish_name
        self.slot_index = slot_index

    def execute(self) -> StageResult:
        self.sm.update_status(current_task=f"🥗 [2/5] 서브 반찬 - [{self.dish_name}]")
        home = self.cm.home_joint()
        d = self.dish_name

        try:
            pick_wp  = self.cm.sub_dish_pick(d)
            place_wp = self.cm.sub_dish_place(self.slot_index)
        except KeyError as e:
            self._logger.error(f"SubDish 좌표 없음: {e}")
            return StageResult.ERROR

        seg_sync  = f"sub_sync_{d}_{self.slot_index}"
        seg_async = f"sub_async_{d}_{self.slot_index}"

        try:
            self._seg_start(seg_sync, 'sync', f'{d} 픽 접근(동기)')

            if not self._movej(home,                 f"🥗 [{d}] 홈 이동"):  return StageResult.STOPPED
            self._gripper(100)
            if not self._movej(pick_wp["pre_pick_j"],f"🥗 [{d}] 픽 준비", radius=20): return StageResult.STOPPED
            if not self._movel(pick_wp["pick_l"],    f"🥗 [{d}] 픽 위치", radius=20): return StageResult.STOPPED

            self._seg_end(seg_sync)

            self._gripper(50)
            self.rc.wait(0.5)
            if not self._check_grip():
                return StageResult.ERROR
            self._tick(f"🥗 [{d}] 집기", done=True)

            self._seg_start(seg_async, 'async', f'{d} 이송(비동기·radius=40)')

            if not self._amovel(pick_wp["up_pick_l"],    f"🥗 [{d}] 들어올림", radius=10):  return StageResult.STOPPED
            if not self._amovej(place_wp["pre_place_j"], f"🥗 [{d}] 슬롯 접근", radius=10): return StageResult.STOPPED

            self._seg_end(seg_async)

            if not self._movel(place_wp["place_l"], f"🥗 [{d}] 놓기"): return StageResult.STOPPED

            self._gripper(100)
            self._tick(f"🥗 [{d}] 완료", done=True)
            self._movej(home, f"🥗 [{d}] 홈 복귀")
            return StageResult.SUCCESS

        except Exception as e:
            if _is_generator_busy(e):
                self._logger.error(f"executor 충돌 - 재시도하지 않고 에러 반환: {e}")
                self.sm.add_step_log(f"🚨 [2/5] [{d}] DSR 통신 충돌 - 중단")
            else:
                self._logger.error(f"오류: {e}")
            return StageResult.ERROR


# ============================================================================
# Stage 3 : 메인 반찬
# ============================================================================
class MainDishStage(BaseStage):
    def __init__(self, state_manager, robot_client, coord_manager, main_dish: str):
        super().__init__(state_manager, robot_client, coord_manager, "MainDish")
        self.main_dish = main_dish

    def execute(self) -> StageResult:
        self.sm.update_status(current_task=f"🍖 [3/5] 메인 반찬 - [{self.main_dish}]")
        c3   = self.cm.stage(3)
        home = self.cm.home_joint()

        try:
            if not self._movej(home,                          "🍖 [3/5] 홈 이동"):            return StageResult.STOPPED
            self._gripper(100)

            if not self._movel(c3["tong_approach_l"],         "🍖 [3/5] 집게 위 접근"):       return StageResult.STOPPED

            self._gripper(30)
            self._tick("🍖 [3/5] 집게 파지", done=True)

            if not self._movel(c3["tong_lift_l"],             "🍖 [3/5] 집게 들어올림"):      return StageResult.STOPPED

            # if not self._movel(c3["main_dish_transit_l"], "🍖 [3/5] 메인반찬 상단"): 
            #     return StageResult.STOPPED

            if not self._movel(c3["main_dish_lift_l"], "🍖 [3/5] baseline 측정 위치"):
                return StageResult.STOPPED

            # ★ 집게만 쥔 상태에서 J2 baseline 동적 측정 (lift_l)
            import numpy as np
            baseline_j2 = self._measure_j2_baseline(n=5, interval=0.1)

            # 반찬 집기
            if not self._movel(c3["main_dish_pick_l"], "🍖 [3/5] 메인반찬 집기 위치"):
                return StageResult.STOPPED
            self._gripper(20)
            self._tick("🍖 [3/5] 메인반찬 집기", done=True)

            # 들어올림
            if not self._movel(c3["main_dish_lift_l"], "🍖 [3/5] 반찬 들어올림"):
                return StageResult.STOPPED

            # ★ lift_l 위치에서 동적 baseline 기반 판별

            self._tick("🍖 [3/5] 토크 측정 중", done=False)
            torque_cls = self._sample_torque_class_dynamic(
                n=3, interval=0.15, baseline_j2=baseline_j2
            )
            self._logger.info(f"반찬 파지 판별: {torque_cls}")

            # ★ 미파지 시 성공할 때까지 재시도
            retry_count = 0
            while torque_cls != "집게+돈까스":
                retry_count += 1
                self.sm.add_step_log(f"⚠️ [3/5] 반찬 미파지 → 재시도 #{retry_count}", completed=False)
                self._gripper(30)
                if not self._movel(c3["main_dish_pick_l"],     f"🍖 [3/5] 재시도#{retry_count}: 집기 위치"): return StageResult.STOPPED
                self._gripper(20)
                self._tick(f"🍖 [3/5] 재시도#{retry_count}: 메인반찬 집기", done=True)
                if not self._movel(c3["main_dish_lift_l"],     f"🍖 [3/5] 재시도#{retry_count}: 들어올림"):  return StageResult.STOPPED


                self._tick(f"🍖 [3/5] 재시도#{retry_count}: 토크 측정 중", done=False)
                torque_cls = self._sample_torque_class_dynamic(
                    n=3, interval=0.15, baseline_j2=baseline_j2
                )
                self._logger.info(f"재시도#{retry_count} 반찬 파지 판별: {torque_cls}")

            if not self._movel(c3["tray_approach_l"],         "🍖 [3/5] 식판 앞 접근"):       return StageResult.STOPPED
            if not self._movel(c3["tray_approach2_l"],         "🍖 [3/5] 식판 앞 접근"):       return StageResult.STOPPED
            self._gripper(30)
            if not self._movel(c3["tray_release_l"],          "🍖 [3/5] 반찬 투하"):          return StageResult.STOPPED

            if not self._movel(c3["tong_return_above_l"],     "🍖 [3/5] 집게 복귀 상단"):     return StageResult.STOPPED
            if not self._movel(c3["tong_return_l"],           "🍖 [3/5] 집게 복귀 하단"):     return StageResult.STOPPED
            self._gripper(100)

            self._movej(home, "🍖 [3/5] 홈 복귀")
            self._tick("🍖 [3/5] 메인 반찬 완료", done=True)
            return StageResult.SUCCESS

        except Exception as e:
            if _is_generator_busy(e):
                self._logger.error(f"executor 충돌 - 재시도하지 않고 에러 반환: {e}")
                self.sm.add_step_log("🚨 [3/5] DSR 통신 충돌 - 중단")
            else:
                self._logger.error(f"오류: {e}")
            return StageResult.ERROR


# ============================================================================
# Stage 4 : 밥 담기
# ============================================================================
class RiceStage(BaseStage):
    def __init__(self, state_manager, robot_client, coord_manager):
        super().__init__(state_manager, robot_client, coord_manager, "Rice")

    def execute(self) -> StageResult:
        self.sm.update_status(current_task="🍚 [4/5] 밥 담기")
        c4   = self.cm.stage(4)
        home = self.cm.home_joint()

        scoop_seq = [
            ("scoop_1_l", "🍚 스쿱1"),
            ("scoop_2_l", "🍚 스쿱2"),
            ("scoop_3_l", "🍚 스쿱3"),
            ("scoop_4_l", "🍚 스쿱4"),
            ("scoop_5_l", "🍚 스쿱5"),
            ("scoop_6_l", "🍚 스쿱6"),
        ]

        try:
            if not self._movej(home,                   "🍚 [4/5] 홈 이동"):        return StageResult.STOPPED
            self._gripper(50)

            if not self._movel(c4["above_l"],          "🍚 [4/5] 밥솥 위"):        return StageResult.STOPPED

            self._gripper(5)
            self.rc.wait(0.5)
            self._tick("🍚 [4/5] 스쿱 파지", done=True)

            for key, label in scoop_seq:
                if not self._movel(c4[key], label):
                    return StageResult.STOPPED

            # 밥 털기 (흔들기)
            if not self._move_periodic(amp=[0,5,20,0,0,8], period=0.5, atime=0.2, repeat=10,  label="🍚 [4/5] 밥 털기 1"):  return StageResult.STOPPED
            self.rc.wait(1)
            if not self._move_periodic(amp=[0,5,20,0,0,8], period=1.0, atime=0.2, repeat=15, label="🍚 [4/5] 밥 털기 2"):  return StageResult.STOPPED

            # ─────────────────────────────────────────────────────────────
            # [특이점 가변속도 모드 ON] 식판 이송 구간 - 손목 특이점 빈발
            # 경로는 유지하고 속도만 자동 조절 → 스쿱 안의 밥 안정 유지
            # ─────────────────────────────────────────────────────────────
            from DSR_ROBOT2 import set_singular_handling, DR_VAR_VEL, DR_AVOID
            set_singular_handling(DR_VAR_VEL)
            self._logger.info("🔧 특이점 모드: DR_VAR_VEL (가변속도) 진입")

            try:
                # 식판으로 이동 (특이점 통과 구간)
                if not self._movel(c4["transit_l"],   "🍚 [4/5] 식판으로 이동"):
                    set_singular_handling(DR_AVOID)
                    return StageResult.STOPPED
                if not self._movel(c4["place_pre_l"], "🍚 [4/5] 밥칸 접근"):
                    set_singular_handling(DR_AVOID)
                    return StageResult.STOPPED
                if not self._movel(c4["place_down_l"],     "🍚 [4/5] 밥칸 하강"):      
                    set_singular_handling(DR_AVOID)
                    return StageResult.STOPPED
                if not self._movel(c4["place_pre2_l"], "🍚 [4/5] 밥칸 하강2"):
                    set_singular_handling(DR_AVOID)
                    return StageResult.STOPPED
                if not self._movel(c4["home_ready_l"], "🍚 [4/5] 밥칸 하강home"):
                    set_singular_handling(DR_AVOID)
                    return StageResult.STOPPED
                # if not self._movel(c4["place_down_l"],     "🍚 [4/5] 밥칸 하강"):  
                #     set_singular_handling(DR_AVOID)
                #     return StageResult.STOPPED
                if not self._movel(c4["place_up_l"],       "🍚 [4/5] 스쿱 복귀"):   
                    set_singular_handling(DR_AVOID)   
                    return StageResult.STOPPED
                if not self._movel(c4["back_l"],           "🍚 [4/5] 밥솥 복귀"):      
                    set_singular_handling(DR_AVOID)
                    return StageResult.STOPPED
                if not self._movel(c4["back_lean_l"],      "🍚 [4/5] 밥솥 복귀"):    
                    set_singular_handling(DR_AVOID)  
                    return StageResult.STOPPED

            finally:
                # 어떤 경우든 특이점 모드 복원 (자동회피)
                set_singular_handling(DR_AVOID)
                self._logger.info("🔧 특이점 모드: DR_AVOID (자동회피) 복원")
            # ─────────────────────────────────────────────────────────────

            # if not self._movel(c4["place_down_l"],     "🍚 [4/5] 밥칸 하강"):      return StageResult.STOPPED

            # # 스쿱 복귀
            # if not self._movel(c4["place_up_l"],       "🍚 [4/5] 스쿱 복귀"):      return StageResult.STOPPED
            # if not self._movel(c4["back_l"],           "🍚 [4/5] 밥솥 복귀"):      return StageResult.STOPPED
            # if not self._movel(c4["back_lean_l"],      "🍚 [4/5] 밥솥 복귀"):      return StageResult.STOPPED

            self._gripper(100)
            self._tick("🍚 [4/5] 스쿱 내려놓기", done=True)

            if not self._movel(c4["home_ready_l"],     "🍚 [4/5] 대기 자세"):      return StageResult.STOPPED
            self._tick("🍚 [4/5] 밥 담기 완료", done=True)

            self._movej(home, "🍚 [4/5] 홈 복귀")
            return StageResult.SUCCESS

        except Exception as e:
            if _is_generator_busy(e):
                self._logger.error(f"executor 충돌 - 재시도하지 않고 에러 반환: {e}")
                self.sm.add_step_log("🚨 [4/5] DSR 통신 충돌 - 중단")
            else:
                self._logger.error(f"오류: {e}")
            return StageResult.ERROR


# ============================================================================
# Stage 5 : 식판 배달
# ============================================================================
class DeliveryStage(BaseStage):
    def __init__(self, state_manager, robot_client, coord_manager):
        super().__init__(state_manager, robot_client, coord_manager, "Delivery")

    def execute(self) -> StageResult:
        self.sm.update_status(current_task="📦 [5/5] 식판 배달")
        c5   = self.cm.stage(5)
        home = self.cm.home_joint()

        try:
            if not self._movel(c5["p004_l"],  "📦 [5/5] 접근"):          return StageResult.STOPPED
            if not self._movej(c5["p005_j"],  "📦 [5/5] 파지 준비1"):     return StageResult.STOPPED
            if not self._movej(c5["p006_j"],  "📦 [5/5] 파지 위치"):      return StageResult.STOPPED

            self._gripper(5)
            self.rc.wait(1.0)
            self._tick("📦 [5/5] 식판홀더 파지", done=True)

            if not self._movel(c5["p007_l"],  "📦 [5/5] 들어올림"):       return StageResult.STOPPED
            if not self._movej(c5["p008_j"],  "📦 [5/5] 이동1"):          return StageResult.STOPPED
            if not self._movel(c5["p009_l"],  "📦 [5/5] 픽업장소 접근"):   return StageResult.STOPPED
            if not self._movej(c5["p010_j"],  "📦 [5/5] 이동2"):          return StageResult.STOPPED
            if not self._movel(c5["p011_l"],  "📦 [5/5] 안착 준비"):      return StageResult.STOPPED
            if not self._movej(c5["p012_j"],  "📦 [5/5] 안착 위치"):      return StageResult.STOPPED

            self._gripper(50)
            self._tick("📦 [5/5] 식판 안착", done=True)

            result = self._movel(c5["p013_l"], "📦 [5/5] 후퇴")
            if not result:
                self._logger.warn("후퇴 미완료 (비상정지 가능성)")

            self._tick("📦 [5/5] 식판 배달 완료", done=True)
            return StageResult.SUCCESS

        except Exception as e:
            if _is_generator_busy(e):
                self._logger.error(f"executor 충돌 - 재시도하지 않고 에러 반환: {e}")
                self.sm.add_step_log("🚨 [5/5] DSR 통신 충돌 - 중단")
            else:
                self._logger.error(f"오류: {e}")
            return StageResult.ERROR

    def execute_after_estop_resume(self) -> StageResult:
        self.sm.update_status(current_task="📦 [5/5] 비상정지 재개 - 파지 상태 확인 중")
        c5   = self.cm.stage(5)
        home = self.cm.home_joint()

        self._tick("📦 [5/5] 재개 후 토크 측정 중", done=False)
        torque_cls = self._sample_torque_class(n=5, interval=0.15)
        self._logger.info(f"비상정지 재개 파지 판별: {torque_cls}")

        try:
            if torque_cls == "빈그리퍼":
                self.sm.add_step_log("📦 빈 그리퍼 감지 → 홈 복귀 (1단계부터 재시작)")
                self._gripper(100)
                self._movej(home, "📦 [5/5] 홈 복귀")
                return StageResult.STOPPED

            if torque_cls == "책받침+가득식판":
                self.sm.add_step_log("📦 식판홀더+식판 감지 → 홀더 초기 위치 복귀 진행")
            else:
                self.sm.add_step_log("📦 식판홀더만 감지 → 홀더 초기 위치 복귀 진행")

            self._gripper(5)
            self.rc.wait(0.5)

            if not self._movej(c5["p012_j"],  "📦 [5/5] 재개: 안착위치 재확인"): return StageResult.STOPPED
            if not self._movel(c5["p011_l"],  "📦 [5/5] 재개: 안착준비 복귀"):   return StageResult.STOPPED
            if not self._movej(c5["p010_j"],  "📦 [5/5] 재개: 이동2 복귀"):      return StageResult.STOPPED
            if not self._movel(c5["p009_l"],  "📦 [5/5] 재개: 픽업접근 복귀"):   return StageResult.STOPPED
            if not self._movej(c5["p008_j"],  "📦 [5/5] 재개: 이동1 복귀"):      return StageResult.STOPPED
            if not self._movel(c5["p007_l"],  "📦 [5/5] 재개: 홀더 하강"):       return StageResult.STOPPED
            if not self._movej(c5["p006_j"],  "📦 [5/5] 재개: 홀더 초기위치"):   return StageResult.STOPPED

            self._gripper(50)
            self.rc.wait(0.5)
            self._tick("📦 [5/5] 홀더 초기위치 안착", done=True)

            self._gripper(100)
            self._movej(home, "📦 [5/5] 홈 복귀")
            self._tick("📦 [5/5] 비상정지 재개 완료", done=True)
            return StageResult.SUCCESS

        except Exception as e:
            if _is_generator_busy(e):
                self._logger.error(f"executor 충돌 - 재시도하지 않고 에러 반환: {e}")
                self.sm.add_step_log("🚨 [5/5] DSR 통신 충돌 - 재개 중단")
            else:
                self._logger.error(f"비상정지 재개 오류: {e}")
            return StageResult.ERROR