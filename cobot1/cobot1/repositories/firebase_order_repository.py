#!/usr/bin/env python3
"""
==============================================================================
[Phase 4] 나만의 도련님 도시락 - Firebase 주문 저장소 (Mode AB)
==============================================================================
OrderRepository 의 Firebase 통합 구현체.

Realtime DB + Firestore 를 동시에 리스닝한다 (Mode AB).
각 주문의 출처(rtdb / firestore)를 _order_source 에 기록하여
상태 업데이트를 올바른 DB 로 자동 라우팅한다.

  Realtime DB (/orders)        → sub_dishes / main_dish 직접 포함
  Firestore   (orders 컬렉션)  → items[] 배열 → 서브/메인 자동 분류
==============================================================================
"""

import os
import time
from typing import Callable, Dict, Set

from rclpy.logging import get_logger

from .order_repository import Order, OrderRepository

_logger = get_logger('firebase_order_repository')

# Firebase 선택적 import
_FIREBASE_OK = False
try:
    import firebase_admin
    from firebase_admin import credentials, db as firebase_db
    _FIREBASE_OK = True
except ImportError:
    _logger.warn("firebase_admin 없음 - 오프라인 모드")


VALID_COMMANDS = {
    "emergency_stop", "resume", "pause", "reset_and_restart",
    "move_home",
    "gripper_open", "gripper_close", "gripper_full_open",
    "test_cancel",
}

_SUB_DISH_NAMES = {'김치', '단무지', '피클', '샐러드'}


class FirebaseOrderRepository(OrderRepository):
    """
    Firebase Mode AB 구현체.

    Realtime DB  : /orders → pending 주문 리스닝
                   /command, /test_command → 명령 리스닝
                   /robot_status → 상태 업로드
    Firestore    : orders 컬렉션 → status=pending on_snapshot 리스닝

    두 DB 주문을 동시에 수신하며, 출처에 따라 상태 업데이트 DB를 자동 선택.
    """

    def __init__(self, credentials_path: str, database_url: str):
        self._available: bool           = False
        self._last_cmd_ts: int          = int(time.time())
        self._processed: Set[str]       = set()
        self._order_source: Dict[str, str] = {}   # key → "rtdb" | "firestore"
        self._fs_db                     = None

        if not _FIREBASE_OK:
            return
        if not os.path.exists(credentials_path):
            _logger.error(f"키 파일 없음: {credentials_path}")
            return

        try:
            cred = credentials.Certificate(credentials_path)
            try:
                firebase_admin.initialize_app(cred, {"databaseURL": database_url})
            except ValueError:
                pass  # 이미 초기화됨

            # Firestore 클라이언트도 항상 초기화
            try:
                from firebase_admin import firestore as _fs
                self._fs_db = _fs.client()
                _logger.info("✅ Firestore 클라이언트 초기화 완료")
            except Exception as e:
                _logger.warn(f"Firestore 초기화 실패 (RTDB 만 사용): {e}")

            self._available = True
            _logger.info("✅ Firebase 초기화 완료 [Realtime DB + Firestore]")
        except Exception as e:
            _logger.error(f"Firebase 초기화 실패: {e}")

    @property
    def available(self) -> bool:
        return self._available

    # ── 주문 리스닝 (RTDB + Firestore 동시) ──────────────────────
    def listen_orders(self, callback: Callable[[Order], None]):
        if not self._available:
            return
        self._listen_orders_rtdb(callback)
        if self._fs_db is not None:
            self._listen_orders_firestore(callback)

    # ── Realtime DB 리스닝 ────────────────────────────────────────
    def _listen_orders_rtdb(self, callback: Callable[[Order], None]):
        def _on_event(event):
            if event.data is None:
                return
            if event.path == "/":
                if isinstance(event.data, dict):
                    for key, data in event.data.items():
                        self._try_enqueue_rtdb(key, data, callback)
            else:
                key = event.path.lstrip("/").split("/")[0]
                if isinstance(event.data, dict):
                    self._try_enqueue_rtdb(key, event.data, callback)

        firebase_db.reference("/orders").listen(_on_event)
        _logger.info("/orders 리스너 등록 [Realtime DB]")

    def _try_enqueue_rtdb(self, key: str, data: dict, callback):
        if not data or data.get("status") != "pending":
            return
        if key in self._processed:
            return
        self._processed.add(key)
        self._order_source[key] = "rtdb"
        order = Order(
            key          = key,
            sub_dishes   = data.get("sub_dishes", []),
            main_dish    = data.get("main_dish", ""),
            target_stage = data.get("target_stage", 0),
            run_mode     = data.get("run_mode", "from"),
        )
        _logger.info(f"주문 수신 [RTDB]: {key}")
        callback(order)

    # ── Firestore 리스닝 ─────────────────────────────────────────
    def _listen_orders_firestore(self, callback: Callable[[Order], None]):
        from google.cloud.firestore_v1.base_query import FieldFilter
        query = self._fs_db.collection('orders').where(
            filter=FieldFilter('status', '==', 'pending')
        )

        def _on_snapshot(col_snapshot, changes, read_time):
            for change in changes:
                if change.type.name != 'ADDED':
                    continue
                doc_id = change.document.id
                if doc_id in self._processed:
                    continue
                self._processed.add(doc_id)
                self._order_source[doc_id] = "firestore"

                data  = change.document.to_dict()
                items = data.get('items', [])
                sub_dishes: list = []
                main_dish: str   = ""
                for item in items:
                    name = item.get('name', '')
                    if name in _SUB_DISH_NAMES:
                        sub_dishes.append(name)
                    elif name:
                        main_dish = name

                _logger.info(f"주문 수신 [Firestore]: {doc_id} 메인={main_dish} 서브={sub_dishes}")
                self._update_order(doc_id, {"status": "cooking"})   # 중복 방지
                callback(Order(key=doc_id, sub_dishes=sub_dishes, main_dish=main_dish))

        query.on_snapshot(_on_snapshot)
        _logger.info("orders 리스너 등록 [Firestore]")

    # ── 주문 상태 변경 ─────────────────────────────────────────────
    def mark_processing(self, order_key: str):
        src = self._order_source.get(order_key, "rtdb")
        status = "cooking" if src == "firestore" else "processing"
        self._update_order(order_key, {"status": status})

    def mark_completed(self, order_key: str):
        self._update_order(order_key, {"status": "completed"})

    def mark_error(self, order_key: str):
        self._update_order(order_key, {"status": "error"})

    def _update_order(self, key: str, payload: dict):
        if not self._available:
            return
        try:
            src = self._order_source.get(key, "rtdb")
            if src == "firestore" and self._fs_db is not None:
                self._fs_db.collection('orders').document(key).update(payload)
                _logger.info(f"Firestore 주문 {key} → {payload}")
            else:
                firebase_db.reference(f"/orders/{key}").update(payload)
        except Exception as e:
            _logger.error(f"주문 업데이트 실패({key}): {e}")

    # ── 명령 리스닝 (RTDB) ────────────────────────────────────────
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
                _logger.warn(f"알 수 없는 명령 '{cmd_type}' → 무시")
                return
            self._last_cmd_ts = ts
            _logger.info(f"명령 수신: {cmd_type}")
            callback(cmd_type)

        firebase_db.reference("/command").listen(_on_cmd)
        _logger.info("/command 리스너 등록")

    # ── 테스트 커맨드 리스닝 (RTDB) ──────────────────────────────
    def listen_test_command(self, callback: Callable[[dict], None]):
        if not self._available:
            return

        self._last_test_ts: int = int(time.time())

        def _on_test_cmd(event):
            if event.data is None or not isinstance(event.data, dict):
                return
            ts = event.data.get("timestamp", 0)
            if ts <= self._last_test_ts:
                _logger.info(f"테스트 커맨드 무시 (ts {ts} <= {self._last_test_ts})")
                return
            self._last_test_ts = ts
            _logger.info(f"테스트 커맨드 수신: {event.data}")
            callback(event.data)

        firebase_db.reference("/test_command").listen(_on_test_cmd)
        _logger.info("/test_command 리스너 등록")

    # ── 로봇 상태 업로드 (RTDB) ───────────────────────────────────
    def upload_robot_status(self, payload: dict):
        if not self._available:
            return
        try:
            firebase_db.reference("/robot_status").update(payload)
        except Exception as e:
            _logger.error(f"상태 업로드 실패: {e}")
