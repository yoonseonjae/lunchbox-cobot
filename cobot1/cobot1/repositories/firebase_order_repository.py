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


class FirebaseOrderRepository(OrderRepository):
    """
    Firebase Realtime DB 연동 구현체.

    /orders  → pending 주문 리스닝
    /command → 명령 리스닝
    /robot_status → 로봇 상태 업로드
    """

    def __init__(self, credentials_path: str, database_url: str):
        """지정한 시스타인 파일로 Firebase 앱을 초기화한다.

        Args:
            credentials_path (str): Firebase 서비스 계정 JSON 키 파일 경로.
            database_url (str): Firebase Realtime DB URL.
        """
        self._available         = False
        self._last_cmd_ts: int  = int(time.time())  # 부팅 이전 커맨드 무시
        self._processed: Set[str] = set()

        if not _FIREBASE_OK:
            return
        if not os.path.exists(credentials_path):
            _logger.error(f"키 파일 없음: {credentials_path}")
            return

        try:
            cred = credentials.Certificate(credentials_path)
            firebase_admin.initialize_app(cred, {"databaseURL": database_url})
            self._available = True
            _logger.info("✅ Firebase 초기화 완료")
        except ValueError:
            # 이미 초기화됨
            self._available = True
            _logger.info("Firebase 이미 초기화됨")
        except Exception as e:
            _logger.error(f"Firebase 초기화 실패: {e}")

    @property
    def available(self) -> bool:
        """Firebase 초기화 성공 여부를 반환한다.

        Returns:
            bool: 초기화되면 True, 실패 또는 오프라인이면 False.
        """
        return self._available

    # ── 주문 리스닝 ───────────────────────────────────────────────
    def listen_orders(self, callback: Callable[[Order], None]):
        """/orders 노드를 실시간 리스닝하며 pending 주문을 콜백으로 전달한다.

        Args:
            callback (Callable[[Order], None]): 주문 수신 시 호출할 콜백.
        Returns:
            None
        """
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
        _logger.info("/orders 리스너 등록")

    def _try_enqueue(self, key: str, data: dict, callback):
        """데이터가 pending이고 미수신 주문이면 Order를 생성해 콜백에 넘기는 한다.

        Args:
            key (str): Firebase 주문 키.
            data (dict): Firebase에서 읽은 주문 데이터.
            callback: 주문 전달 콜백.
        Returns:
            None
        """
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
        _logger.info(f"주문 수신: {key}")
        callback(order)

    # ── 주문 상태 변경 ─────────────────────────────────────────────
    def mark_processing(self, order_key: str):
        """주문 상태를 'processing'으로 Firebase에 업데이트한다.

        Args:
            order_key (str): 타겟 주문 키.
        Returns:
            None
        """
        self._update_order(order_key, {"status": "processing"})

    def mark_completed(self, order_key: str):
        """주문 상태를 'completed'로 Firebase에 업데이트한다.

        Args:
            order_key (str): 타겟 주문 키.
        Returns:
            None
        """
        self._update_order(order_key, {"status": "completed"})

    def mark_error(self, order_key: str):
        """주문 상태를 'error'로 Firebase에 업데이트한다.

        Args:
            order_key (str): 타겟 주문 키.
        Returns:
            None
        """
        self._update_order(order_key, {"status": "error"})

    def _update_order(self, key: str, payload: dict):
        """Firebase /orders/{key}를 payload로 부분 업데이트한다.

        Args:
            key (str): 업데이트할 주문 키.
            payload (dict): 업데이트할 필드와 값.
        Returns:
            None
        """
        if not self._available:
            return
        try:
            firebase_db.reference(f"/orders/{key}").update(payload)
        except Exception as e:
            _logger.error(f"주문 업데이트 실패({key}): {e}")

    # ── 명령 리스닝 ───────────────────────────────────────────────
    def listen_commands(self, callback: Callable[[str], None]):
        """/command 노드를 실시간 리스닝하며 유효한 명령을 콜백에 전달한다.

        Args:
            callback (Callable[[str], None]): 명령 유형 문자열을 인수로 받는 콜백.
        Returns:
            None
        """
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

    # ── 테스트 커맨드 리스닝 (/test_command) ─────────────────────
    def listen_test_command(self, callback: Callable[[dict], None]):
        """/test_command 노드를 리스닝하며 부팅 이후 도착한 테스트 커맨드를 콜백에 전달한다.

        Args:
            callback (Callable[[dict], None]): 테스트 커맨드 dict를 인수로 받는 콜백.
        Returns:
            None
        """
        if not self._available:
            return

        # 노드 시작 시각 기준으로 이전 커맨드는 모두 무시
        _boot_ts: int = int(time.time())
        self._last_test_ts: int = _boot_ts

        def _on_test_cmd(event):
            if event.data is None or not isinstance(event.data, dict):
                return
            ts = event.data.get("timestamp", 0)
            if ts <= self._last_test_ts:
                _logger.info(f"테스트 커맨드 무시 (오래된 timestamp {ts} <= {self._last_test_ts})")
                return
            self._last_test_ts = ts
            _logger.info(f"테스트 커맨드 수신: {event.data}")
            callback(event.data)

        firebase_db.reference("/test_command").listen(_on_test_cmd)
        _logger.info("/test_command 리스너 등록")

    # ── 로봇 상태 업로드 ──────────────────────────────────────────
    def upload_robot_status(self, payload: dict):
        """로봇 상태를 Firebase /robot_status에 업로드한다.

        Args:
            payload (dict): 업로드할 로봇 상태 데이터.
        Returns:
            None
        """
        if not self._available:
            return
        try:
            firebase_db.reference("/robot_status").update(payload)
        except Exception as e:
            _logger.error(f"상태 업로드 실패: {e}")
