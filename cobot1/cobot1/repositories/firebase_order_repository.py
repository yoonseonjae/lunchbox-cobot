#!/usr/bin/env python3
"""
==============================================================================
[Phase 4] 나만의 도련님 도시락 - Firebase 주문 저장소
==============================================================================
OrderRepository 의 Firebase Realtime DB 구현체.
기존 lunchbox_robot_node.py 의 리스너 로직을 이 클래스로 이전.
==============================================================================
"""

import os
import time
from typing import Callable, Set

from .order_repository import Order, OrderRepository

# Firebase 선택적 import
_FIREBASE_OK = False
try:
    import firebase_admin
    from firebase_admin import credentials, db as firebase_db
    _FIREBASE_OK = True
except ImportError:
    print("[Firebase] ⚠️ firebase_admin 없음 - 오프라인 모드")


VALID_COMMANDS = {
    "emergency_stop", "resume",
    "move_home",
    "gripper_open", "gripper_close", "gripper_full_open",
}


class FirebaseOrderRepository(OrderRepository):
    """
    Firebase Realtime DB 연동 구현체.

    /orders  → pending 주문 리스닝
    /command → 명령 리스닝
    /robot_status → 로봇 상태 업로드
    """

    def __init__(self, credentials_path: str, database_url: str):
        self._available         = False
        self._last_cmd_ts: int  = 0
        self._processed: Set[str] = set()

        if not _FIREBASE_OK:
            return
        if not os.path.exists(credentials_path):
            print(f"[Firebase] ❌ 키 파일 없음: {credentials_path}")
            return

        try:
            cred = credentials.Certificate(credentials_path)
            firebase_admin.initialize_app(cred, {"databaseURL": database_url})
            self._available = True
            print("[Firebase] ✅ 초기화 완료")
        except ValueError:
            # 이미 초기화됨
            self._available = True
            print("[Firebase] 이미 초기화됨")
        except Exception as e:
            print(f"[Firebase] 초기화 실패: {e}")

    @property
    def available(self) -> bool:
        return self._available

    # ── 주문 리스닝 ───────────────────────────────────────────────
    def listen_orders(self, callback: Callable[[Order], None]):
        if not self._available:
            return

        def _on_event(event):
            if event.data is None:
                return

            if event.path == "/":
                # 초기 스냅샷 전체
                if isinstance(event.data, dict):
                    for key, data in event.data.items():
                        self._try_enqueue(key, data, callback)
            else:
                # 단건 변경
                key = event.path.lstrip("/").split("/")[0]
                if isinstance(event.data, dict):
                    self._try_enqueue(key, event.data, callback)

        firebase_db.reference("/orders").listen(_on_event)
        print("[Firebase] /orders 리스너 등록")

    def _try_enqueue(self, key: str, data: dict, callback):
        if not data or data.get("status") != "pending":
            return
        if key in self._processed:
            return
        self._processed.add(key)

        order = Order(
            key          = key,
            sub_dishes   = data.get("sub_dishes", []),
            main_dish    = data.get("main_dish", ""),
            target_stage = data.get("target_stage", 0),
            run_mode     = data.get("run_mode", "from"),
        )
        print(f"[Firebase] 주문 수신: {key}")
        callback(order)

    # ── 주문 상태 변경 ─────────────────────────────────────────────
    def mark_processing(self, order_key: str):
        self._update_order(order_key, {"status": "processing"})

    def mark_completed(self, order_key: str):
        self._update_order(order_key, {"status": "completed"})

    def mark_error(self, order_key: str):
        self._update_order(order_key, {"status": "error"})

    def _update_order(self, key: str, payload: dict):
        if not self._available:
            return
        try:
            firebase_db.reference(f"/orders/{key}").update(payload)
        except Exception as e:
            print(f"[Firebase] 주문 업데이트 실패({key}): {e}")

    # ── 명령 리스닝 ───────────────────────────────────────────────
    def listen_commands(self, callback: Callable[[str], None]):
        if not self._available:
            return

        def _on_cmd(event):
            if event.data is None or not isinstance(event.data, dict):
                return
            cmd_type = event.data.get("type", "")
            ts       = event.data.get("timestamp", 0)

            if not cmd_type or ts <= self._last_cmd_ts:
                return
            if cmd_type not in VALID_COMMANDS:
                print(f"[Firebase] ⚠️ 알 수 없는 명령 '{cmd_type}' → 무시")
                return

            self._last_cmd_ts = ts
            print(f"[Firebase] 명령 수신: {cmd_type}")
            callback(cmd_type)

        firebase_db.reference("/command").listen(_on_cmd)
        print("[Firebase] /command 리스너 등록")

    # ── 로봇 상태 업로드 ──────────────────────────────────────────
    def upload_robot_status(self, payload: dict):
        if not self._available:
            return
        try:
            firebase_db.reference("/robot_status").update(payload)
        except Exception as e:
            print(f"[Firebase] 상태 업로드 실패: {e}")
