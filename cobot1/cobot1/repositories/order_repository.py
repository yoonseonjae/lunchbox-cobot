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
    """주문 1건의 데이터를 표현한다. Firebase /orders/{key}에 대응한다.

    Attributes:
        key (str): Firebase 주문 고유 키.
        sub_dishes (List[str]): 주문된 서브 반찬 이름 목록.
        main_dish (str): 메인 반찬 이름.
        target_stage (int): 0이면 전체 시퀀스, 특정 번호면 해당 스테이지에서 시작.
        run_mode (str): 'from' = target_stage부터 끝까지, 'only' = target_stage만.
        status (str): 'pending' | 'processing' | 'completed' | 'error'.
    """
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
        """pending 상태의 주문을 수신하면 callback을 호출한다.

        Args:
            callback (Callable[[Order], None]): 수신한 주문 객체를 인수로 받는 콜백.
        Returns:
            None
        """
        ...

    @abstractmethod
    def mark_processing(self, order_key: str):
        """주문 상태를 'processing'으로 변경한다.

        Args:
            order_key (str): 상태를 변경할 주문의 Firebase 키.
        Returns:
            None
        """
        ...

    @abstractmethod
    def mark_completed(self, order_key: str):
        """주문 상태를 'completed'으로 변경한다.

        Args:
            order_key (str): 상태를 변경할 주묨의 Firebase 키.
        Returns:
            None
        """
        ...

    @abstractmethod
    def mark_error(self, order_key: str):
        """주문 상태를 'error'로 변경한다.

        Args:
            order_key (str): 상태를 변경할 주묨의 Firebase 키.
        Returns:
            None
        """
        ...

    # ── 명령 ──────────────────────────────────────────────────────
    @abstractmethod
    def listen_commands(self, callback: Callable[[str], None]):
        """명령을 수신하면 callback을 호출한다.

        Args:
            callback (Callable[[str], None]): 명령 유형 문자열을 인수로 받는 콜백.
        Returns:
            None
        """
        ...

    # ── 로봇 상태 업로드 ──────────────────────────────────────────
    @abstractmethod
    def upload_robot_status(self, payload: dict):
        """로봇 상태를 외부 저장소에 업로드한다.

        Args:
            payload (dict): 업로드할 로봇 상태 데이터.
        Returns:
            None
        """
        ...
