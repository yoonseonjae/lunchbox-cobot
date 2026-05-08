#!/usr/bin/env python3
"""
==============================================================================
나만의 도련님 도시락 - 사용자 주문 인터페이스 (다른 PC에서 실행)
==============================================================================
역할:
  - 다른 컴퓨터에서 실행하는 사용자용 주문 GUI
  - 서브 4개 중 3개 + 메인 2개 중 1개 선택
  - 주문하기 버튼 누르면 Firebase /orders 에 push()
  - ROS2 / DSR_ROBOT2 의존성 없음 (firebase-admin 만 있으면 됨)

설치:
  pip install firebase-admin

실행:
  python3 user_order_app.py
==============================================================================
"""

import time
import threading
import tkinter as tk
from tkinter import messagebox

import firebase_admin
from firebase_admin import credentials, db

# ============================================================================
# Firebase 설정 (본인 환경에 맞게 수정)
# ============================================================================
SERVICE_ACCOUNT_KEY_PATH = "/home/yoon/cobot_ws/cobot1/config/serviceAccountKey.json"
DATABASE_URL = "https://rokey-d3991-default-rtdb.asia-southeast1.firebasedatabase.app"

# ============================================================================
# 메뉴
# ============================================================================
SUB_DISHES = ["피클", "단무지", "김치", "샐러드"]
MAIN_DISHES = ["돈까스", "제육"]


# ============================================================================
# Firebase 초기화
# ============================================================================
def init_firebase():
    try:
        cred = credentials.Certificate(SERVICE_ACCOUNT_KEY_PATH)
        firebase_admin.initialize_app(cred, {"databaseURL": DATABASE_URL})
        print("[Firebase] 초기화 완료")
        return True
    except ValueError:
        print("[Firebase] 이미 초기화됨")
        return True
    except Exception as e:
        print(f"[Firebase] 초기화 실패: {e}")
        return False


# ============================================================================
# Tkinter 앱
# ============================================================================
class UserOrderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("🍱 도련님 도시락 - 주문")
        self.root.geometry("600x650")
        self.root.configure(bg="white")

        self._build_ui()

    def _build_ui(self):
        # 헤더
        header = tk.Frame(self.root, bg="#1f2937", height=70)
        header.pack(fill="x")
        tk.Label(
            header, text="🍱 나만의 도련님 도시락",
            font=("Arial", 20, "bold"), bg="#1f2937", fg="white"
        ).pack(pady=18)

        # ── 서브 반찬 ──
        sub_frame = tk.LabelFrame(
            self.root, text=" 서브 반찬 (3개 선택) ",
            font=("Arial", 12, "bold"), bg="white", fg="#2563eb",
            padx=15, pady=15
        )
        sub_frame.pack(fill="x", padx=20, pady=(20, 10))

        self.sub_vars = {}
        self.sub_buttons = {}
        for idx, name in enumerate(SUB_DISHES):
            var = tk.BooleanVar(value=False)
            self.sub_vars[name] = var
            btn = tk.Checkbutton(
                sub_frame, text=name, variable=var,
                font=("Arial", 13), bg="white",
                width=10, height=2,
                indicatoron=False, selectcolor="#bfdbfe",
                command=lambda n=name: self._on_sub_toggle(n),
            )
            btn.grid(row=idx // 2, column=idx % 2, padx=8, pady=6)
            self.sub_buttons[name] = btn

        # ── 메인 반찬 ──
        main_frame = tk.LabelFrame(
            self.root, text=" 메인 반찬 (1개 선택) ",
            font=("Arial", 12, "bold"), bg="white", fg="#ea580c",
            padx=15, pady=15
        )
        main_frame.pack(fill="x", padx=20, pady=10)

        self.main_var = tk.StringVar(value="")
        for idx, name in enumerate(MAIN_DISHES):
            btn = tk.Radiobutton(
                main_frame, text=name, variable=self.main_var, value=name,
                font=("Arial", 13), bg="white",
                width=10, height=2,
                indicatoron=False, selectcolor="#fed7aa",
                command=self._update_preview,
            )
            btn.grid(row=0, column=idx, padx=8, pady=6)

        # ── 미리보기 ──
        preview_frame = tk.Frame(self.root, bg="white")
        preview_frame.pack(fill="x", padx=20, pady=10)
        tk.Label(
            preview_frame, text="📋 선택 내역",
            font=("Arial", 11, "bold"), bg="white", fg="#374151"
        ).pack(anchor="w")
        self.preview_label = tk.Label(
            preview_frame,
            text="아직 선택된 항목이 없습니다.",
            font=("Arial", 11), bg="#f3f4f6", fg="#374151",
            padx=12, pady=10, anchor="w", justify="left"
        )
        self.preview_label.pack(fill="x", pady=4)

        # ── 주문 버튼 ──
        self.order_btn = tk.Button(
            self.root, text="🛒  주문하기",
            font=("Arial", 15, "bold"),
            bg="#22c55e", fg="white",
            padx=40, pady=12,
            command=self._on_order_click,
        )
        self.order_btn.pack(pady=15)

        # ── 결과 표시 ──
        self.result_label = tk.Label(
            self.root, text="",
            font=("Consolas", 10), bg="white", fg="#374151",
            padx=12, pady=8, anchor="w", justify="left",
            wraplength=540
        )
        self.result_label.pack(fill="x", padx=20, pady=5)

    # ──────────────────────────────────────────────
    # 이벤트
    # ──────────────────────────────────────────────
    def _on_sub_toggle(self, name):
        selected = [n for n, v in self.sub_vars.items() if v.get()]
        if len(selected) > 3:
            self.sub_vars[name].set(False)
            messagebox.showwarning("선택 제한", "서브 반찬은 최대 3개까지 선택할 수 있어요.")
            return
        self._update_preview()

    def _update_preview(self):
        subs = [n for n, v in self.sub_vars.items() if v.get()]
        main = self.main_var.get()
        if not subs and not main:
            self.preview_label.config(text="아직 선택된 항목이 없습니다.")
            return
        text = (
            f"서브 반찬 ({len(subs)}/3): {', '.join(subs) if subs else '없음'}\n"
            f"메인 반찬: {main if main else '없음'}"
        )
        self.preview_label.config(text=text)

    def _on_order_click(self):
        subs = [n for n, v in self.sub_vars.items() if v.get()]
        main = self.main_var.get()

        if len(subs) != 3:
            messagebox.showwarning(
                "선택 오류", f"서브 반찬은 정확히 3개를 선택해야 해요. (현재 {len(subs)}개)"
            )
            return
        if not main:
            messagebox.showwarning("선택 오류", "메인 반찬을 선택해주세요.")
            return

        # ── 주문 데이터 만들기 (딕셔너리) ──
        order = {
            "timestamp": int(time.time()),
            "sub_dishes": subs,
            "main_dish": main,
            "status": "pending",
        }

        # ── Firebase 에 push (백그라운드 스레드) ──
        self.order_btn.config(state="disabled", text="전송 중...")
        threading.Thread(
            target=self._push_to_firebase, args=(order,), daemon=True
        ).start()

    def _push_to_firebase(self, order):
        try:
            ref = db.reference("/orders")
            new_ref = ref.push(order)
            # push() 가 자동 생성한 키를 order_id 로 다시 update
            new_ref.update({"order_id": new_ref.key})

            order_id_short = new_ref.key[-8:]
            print(f"[Firebase] 주문 push 완료: {new_ref.key}")
            print(f"           data = {order}")

            self.root.after(0, self._on_push_success, order, new_ref.key, order_id_short)

        except Exception as e:
            print(f"[Firebase] 주문 push 실패: {e}")
            self.root.after(0, self._on_push_failed, str(e))

    def _on_push_success(self, order, full_key, short_id):
        self.result_label.config(
            text=(
                f"✅ 주문 전송 완료!\n"
                f"   ORDER_ID : ...{short_id}\n"
                f"   서브     : {', '.join(order['sub_dishes'])}\n"
                f"   메인     : {order['main_dish']}\n"
                f"   상태     : pending"
            ),
            fg="#16a34a"
        )

        # 입력 초기화
        for v in self.sub_vars.values():
            v.set(False)
        self.main_var.set("")
        self._update_preview()

        self.order_btn.config(state="normal", text="🛒  주문하기")

    def _on_push_failed(self, err_msg):
        self.result_label.config(
            text=f"❌ 주문 전송 실패: {err_msg}", fg="#dc2626"
        )
        self.order_btn.config(state="normal", text="🛒  주문하기")


# ============================================================================
# main
# ============================================================================
def main():
    if not init_firebase():
        print("Firebase 초기화에 실패했어요. serviceAccountKey.json 경로를 확인하세요.")
        return

    root = tk.Tk()
    app = UserOrderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
