#!/usr/bin/env python3
"""
==============================================================================
[Phase 4] 나만의 도련님 도시락 - 주문 저장소 인터페이스
==============================================================================
OrderRepository ABC → FirebaseOrderRepository / MockOrderRepository 구현.
로봇 로직은 인터페이스에만 의존하므로 Firebase 교체나 테스트가 자유로움.
==============================================================================
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable, List, Optional


# ============================================================================
# 도메인 객체
# ============================================================================
@dataclass
class Order:
    """Firebase /orders/{key} 한 건을 표현."""
    key:          str
    sub_dishes:   List[str]
    main_dish:    str
    target_stage: int  = 0      # 0 = 전체 실행
    run_mode:     str  = "from" # "from" | "only"
    status:       str  = "pending"


# ============================================================================
# 인터페이스
# ============================================================================
class OrderRepository(ABC):
    """주문 / 명령 저장소 추상 인터페이스."""

    # ── 주문 CRUD ─────────────────────────────────────────────────
    @abstractmethod
    def listen_orders(self, callback: Callable[[Order], None]):
        """pending 주문 수신 시 callback(order) 호출."""
        ...

    @abstractmethod
    def mark_processing(self, order_key: str):
        ...

    @abstractmethod
    def mark_completed(self, order_key: str):
        ...

    @abstractmethod
    def mark_error(self, order_key: str):
        ...

    # ── 명령 ──────────────────────────────────────────────────────
    @abstractmethod
    def listen_commands(self, callback: Callable[[str], None]):
        """명령 수신 시 callback(cmd_type) 호출."""
        ...

    # ── 로봇 상태 업로드 ──────────────────────────────────────────
    @abstractmethod
    def upload_robot_status(self, payload: dict):
        ...
