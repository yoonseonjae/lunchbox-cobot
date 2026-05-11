"""
Two-Stage Hierarchical Torque Classification Pipeline (NumPy-only)
  Stage 1: KNN(k=1, Euclidean) → 4 macro-classes
           '집게류' = 빈그리퍼 + 집게 + 집게+돈까스
  Stage 2: Weighted LDA-direction 분류 → 3 fine-classes
           빈그리퍼 / 집게 / 집게+돈까스
"""

import yaml
import numpy as np
from pathlib import Path


# ── 데이터 로드 ────────────────────────────────────────────────────────────────

def load_data(yaml_path: str) -> dict:
    with open(yaml_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    data = {}
    for cls_name, info in raw["classes"].items():
        data[cls_name] = np.array(info["samples"], dtype=np.float64)
    return data


# ── Stage 1: KNN(k=1) Macro-Classifier ───────────────────────────────────────

MACRO_MAP = {
    "빈그리퍼":       "집게류",
    "집게":          "집게류",
    "집게+돈까스":    "집게류",
    "스팸":          "스팸",
    "책받침":        "책받침",
    "책받침+가득식판": "책받침+가득식판",
}

MICRO_CLASSES = {"빈그리퍼", "집게", "집게+돈까스"}


class KNN1Classifier:
    """K=1 최근접 이웃 분류기 (순수 NumPy)"""

    def fit(self, X: np.ndarray, y: list):
        self.X_train = X.copy()
        self.y_train = list(y)
        return self

    def predict(self, x: np.ndarray) -> str:
        dists = np.linalg.norm(self.X_train - x, axis=1)
        return self.y_train[int(np.argmin(dists))]


def build_stage1(data: dict) -> KNN1Classifier:
    X, y = [], []
    for cls_name, samples in data.items():
        macro = MACRO_MAP[cls_name]
        for s in samples:
            X.append(s)
            y.append(macro)

    clf = KNN1Classifier()
    clf.fit(np.array(X), y)
    return clf


# ── Stage 2: 3-class Micro-Classifier (집게류 내부) ───────────────────────────
#
#  전략: OVR (One-vs-Rest) 방식으로 LDA 방향벡터 기반 바이너리 분류기 3개 구성.
#  각 분류기의 decision score를 비교해 가장 높은 클래스 반환.

class LDABinaryClassifier:
    """두 클래스 평균을 잇는 방향벡터 기반 이진 분류기 (순수 NumPy)"""

    def fit(self, X_pos: np.ndarray, X_neg: np.ndarray):
        mu_pos = X_pos.mean(axis=0)
        mu_neg = X_neg.mean(axis=0)
        direction = mu_pos - mu_neg
        norm = np.linalg.norm(direction)
        self.w = direction / norm if norm > 0 else direction
        self.b = -self.w @ ((mu_pos + mu_neg) / 2)
        return self

    def score(self, x: np.ndarray) -> float:
        return float(x @ self.w + self.b)


def compute_weights(data: dict) -> np.ndarray:
    """세 fine-class의 pairwise 평균 차이를 합산해 joint 가중치 산출"""
    classes = ["빈그리퍼", "집게", "집게+돈까스"]
    means = {c: data[c].mean(axis=0) for c in classes}

    total_diff = np.zeros(6)
    pairs = [(a, b) for i, a in enumerate(classes) for b in classes[i+1:]]
    for a, b in pairs:
        total_diff += np.abs(means[a] - means[b])

    weight_sum = total_diff.sum()
    return total_diff / weight_sum if weight_sum > 0 else np.ones(6) / 6


class MicroClassifier:
    """
    계층적 3-class 분류기 (집게류 내부)

    Step A: 빈그리퍼 vs (집게 + 집게+돈까스)
            → J2가 핵심: 빈그리퍼는 J2 ≈ -1.7, 집게류는 J2 ≈ -1.5/-1.35

    Step B: 빈그리퍼가 아닌 경우에만
            집게 vs 집게+돈까스 (J2, J3 위주 가중치)
    """

    def fit(self, data: dict):
        # Step A 가중치: 빈그리퍼 vs 나머지
        X_bg  = data["빈그리퍼"]
        X_rest = np.vstack([data["집게"], data["집게+돈까스"]])
        diff_a = np.abs(X_bg.mean(axis=0) - X_rest.mean(axis=0))
        self.weights_a = diff_a / diff_a.sum()
        self.clf_a = LDABinaryClassifier().fit(X_bg * self.weights_a,
                                               X_rest * self.weights_a)

        # Step B: J2 경계값 = 집게/집게+돈까스 J2 평균의 중간
        X_jg  = data["집게"]
        X_dgk = data["집게+돈까스"]
        self.j2_boundary = float((X_jg[:, 1].mean() + X_dgk[:, 1].mean()) / 2)
        return self

    def predict(self, x: np.ndarray) -> str:
        # Step A
        score_a = self.clf_a.score(x * self.weights_a)
        if score_a >= 0:
            return "빈그리퍼"

        # Step B: J2 직접 비교 (경계값 _J2_BOUNDARY)
        return "집게+돈까스" if x[1] > self.j2_boundary else "집게"


def build_stage2(data: dict) -> MicroClassifier:
    return MicroClassifier().fit(data)


# ── 통합 파이프라인 ────────────────────────────────────────────────────────────

class TorqueClassifier:
    def __init__(self, yaml_path: str):
        self.data = load_data(yaml_path)
        self.stage1 = build_stage1(self.data)
        self.stage2 = build_stage2(self.data)

    def predict_class(self, new_torque_array) -> str:
        x = np.array(new_torque_array, dtype=np.float64).flatten()

        macro = self.stage1.predict(x)
        if macro != "집게류":
            return macro

        return self.stage2.predict(x)


# ── 메인 ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    yaml_path = Path(__file__).parent / "torque_data.yaml"
    clf = TorqueClassifier(str(yaml_path))

    print("=== Stage 2 Step-A weights (빈그리퍼 vs 나머지) ===")
    for i, w in enumerate(clf.stage2.weights_a, 1):
        print(f"  J{i}: {w:.4f}")
    print()
    print("=== Stage 2 Step-B weights (집게 vs 집게+돈까스) ===")
    for i, w in enumerate(clf.stage2.weights_b, 1):
        print(f"  J{i}: {w:.4f}")
    print()

    # ── 학습 데이터 전체 재분류 검증 ──
    print("=== 학습 데이터 재분류 결과 ===")
    correct = 0
    total = 0
    for cls_name, samples in clf.data.items():
        for i, s in enumerate(samples):
            pred = clf.predict_class(s)
            ok = "O" if pred == cls_name else "X"
            if pred == cls_name:
                correct += 1
            total += 1
            print(f"  [{ok}] {cls_name} sample[{i}] → {pred}")

    print()
    print(f"정확도: {correct}/{total} ({100*correct/total:.1f}%)")
    print()

    # ── 더미 입력 테스트 ──
    test_cases = [
        ([-0.690, -1.720, -0.390, -0.255, 0.330, 0.462], "빈그리퍼 유사"),
        ([-0.681, -0.874,  0.293, -0.249, 0.328, 0.467], "스팸 유사"),
        ([-0.691, -1.545, -0.253, -0.252, 0.325, 0.467], "집게 유사"),
        ([-0.715, -1.380, -0.125, -0.263, 0.308, 0.499], "집게+돈까스 유사"),
        ([-0.678, -0.613,  0.533, -0.251, 0.441, 0.465], "책받침 유사"),
        ([-0.650,  1.232,  2.548, -0.197, 0.872, 0.466], "책받침+가득식판 유사"),
    ]

    print("=== 더미 입력 테스트 ===")
    for torque, desc in test_cases:
        result = clf.predict_class(torque)
        print(f"  {desc:22s} → {result}")
