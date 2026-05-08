#!/usr/bin/env python3
"""
==============================================================================
[Phase 4] 나만의 도련님 도시락 - Mock 주문 저장소 (테스트/오프라인용)
==============================================================================
Firebase 없이 로봇 로직만 테스트할 때 사용.
inject_order() 로 주문을 직접 삽입할 수 있음.
==============================================================================
"""

import queue
import threading
import time
from typing import Callable, List

from rclpy.logging import get_logger

from .order_repository import Order, OrderRepository

_logger = get_logger('mock_order_repository')


class MockOrderRepository(OrderRepository):
    """
    인메모리 주문 저장소.
    - inject_order() 로 테스트 주문 삽입
    - inject_command() 로 테스트 명령 삽입
    - upload_robot_status() 는 stdout 출력만 함
    """

    def __init__(self):
        self._order_q:   queue.Queue      = queue.Queue()
        self._cmd_q:     queue.Queue      = queue.Queue()
        self._order_cb:  Callable         = None
        self._cmd_cb:    Callable         = None
        self._statuses:  List[dict]       = []
        self._lock       = threading.Lock()

    # ── 주문 리스닝 ───────────────────────────────────────────────
    def listen_orders(self, callback: Callable[[Order], None]):
        self._order_cb = callback
        t = threading.Thread(target=self._order_dispatch_loop, daemon=True)
        t.start()
        _logger.info("주문 리스너 시작 (inject_order 로 삽입)")

    def _order_dispatch_loop(self):
        while True:
            try:
                order = self._order_q.get(timeout=0.5)
                if self._order_cb:
                    self._order_cb(order)
            except queue.Empty:
                continue

    def inject_order(self, order: Order = None):
        """테스트 주문 삽입. order=None 이면 기본 주문 사용."""
        if order is None:
            order = Order(
                key          = f"mock_{int(time.time())}",
                sub_dishes   = ["피클", "단무지", "김치"],
                main_dish    = "돈까스",
                target_stage = 0,
                run_mode     = "from",
            )
        self._order_q.put(order)
        _logger.info(f"주문 삽입: {order.key}")

    # ── 주문 상태 변경 (로그 출력) ─────────────────────────────────
    def mark_processing(self, order_key: str) -> None:
        _logger.info(f"{order_key} → processing")

    def mark_completed(self, order_key: str) -> None:
        _logger.info(f"{order_key} → completed")

    def mark_error(self, order_key: str) -> None:
        _logger.info(f"{order_key} → error")

    # ── 명령 리스닝 ───────────────────────────────────────────────
    def listen_commands(self, callback: Callable[[str], None]):
        self._cmd_cb = callback
        t = threading.Thread(target=self._cmd_dispatch_loop, daemon=True)
        t.start()
        _logger.info("명령 리스너 시작 (inject_command 로 삽입)")

    def _cmd_dispatch_loop(self):
        while True:
            try:
                cmd = self._cmd_q.get(timeout=0.5)
                if self._cmd_cb:
                    self._cmd_cb(cmd)
            except queue.Empty:
                continue

    def inject_command(self, cmd_type: str):
        """테스트 명령 삽입. 예: inject_command('emergency_stop')"""
        self._cmd_q.put(cmd_type)
        _logger.info(f"명령 삽입: {cmd_type}")

    # ── 로봇 상태 업로드 ──────────────────────────────────────────
    def upload_robot_status(self, payload: dict) -> None:
        with self._lock:
            self._statuses.append(payload)
        state = payload.get("state", "?")
        task  = payload.get("current_task", "?")
        _logger.info(f"상태 업로드: state={state} | task={task}")
