import numpy as np
import matplotlib.pyplot as plt
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis

# 1. 실제 데이터 로드 (torque_data.yaml 기준)
# 집게 (40g) - 10 samples
tongs_raw = np.array([
    [-1.5453, -3.4213, -0.8936, -0.1162, -0.7382, 0.6762],
    [-1.5477, -3.3866, -0.9145, -0.1117, -0.6909, 0.6710],
    [-1.5629, -3.3379, -0.8278, -0.1117, -0.7485, 0.6735],
    [-1.5631, -3.4305, -0.9766, -0.1119, -0.7464, 0.6718],
    [-1.5455, -3.3975, -1.0361, -0.1146, -0.6931, 0.6656],
    [-1.5495, -3.3503, -0.9459, -0.1143, -0.7086, 0.6716],
    [-1.5383, -3.3430, -0.8361, -0.1057, -0.7532, 0.6666],
    [-1.5463, -3.4010, -0.9383, -0.1053, -0.7371, 0.6680],
    [-1.5453, -3.3534, -1.0442, -0.1082, -0.6930, 0.6678],
    [-1.5339, -3.4077, -0.8931, -0.1006, -0.7436, 0.6679]
])

# 집게+돈까스 (45g) - 10 samples
pork_raw = np.array([
    [-1.5526, -3.0491, -0.7966, -0.0924, -0.7428, 0.6708],
    [-1.5328, -3.0129, -0.8434, -0.0975, -0.7061, 0.6630],
    [-1.5422, -3.1034, -0.6388, -0.0915, -0.7439, 0.6565],
    [-1.5255, -3.0841, -0.7421, -0.0877, -0.7035, 0.6564],
    [-1.5507, -3.0301, -0.8400, -0.0933, -0.6805, 0.6601],
    [-1.5405, -3.0137, -0.8187, -0.0931, -0.7214, 0.6621],
    [-1.5539, -3.0383, -0.6578, -0.0911, -0.7508, 0.6581],
    [-1.5557, -3.0416, -0.6546, -0.0962, -0.7038, 0.6642],
    [-1.5163, -3.0824, -0.7957, -0.0889, -0.6891, 0.6622],
    [-1.5274, -3.0212, -0.8507, -0.0907, -0.7209, 0.6556]
])

# 2. 특징 확장 함수 (6D -> 27D)
def expand_features(data):
    expanded_data = []
    for row in data:
        features = list(row)           # 1. 원래 6축 (6D)
        features.extend(row**2)        # 2. 각 축의 제곱 (6D)
        # 3. 축 간 교차곱 (Cross-product) (15D)
        for i in range(6):
            for j in range(i+1, 6):
                features.append(row[i] * row[j])
        expanded_data.append(features)
    return np.array(expanded_data)

# 데이터 27차원으로 확장
X_target1 = expand_features(tongs_raw)
X_target2 = expand_features(pork_raw)

# X, y 세팅 (y: 집게=1, 집게+돈까스=2)
X_test = np.vstack([X_target1, X_target2])
y_test = np.array([1]*len(X_target1) + [2]*len(X_target2))

# 3. LDA 모델 학습 (27차원을 1차원으로 축소)
lda = LinearDiscriminantAnalysis(n_components=1)
X_lda = lda.fit_transform(X_test, y_test)

# 4. 시각화 (Before vs After)
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))

# [Before] Raw Data에서 분리도가 가장 높았던 J2(인덱스1)와 J3(인덱스2)를 시각화
ax1.scatter(tongs_raw[:, 1], tongs_raw[:, 2], c='orange', label='Target 1 (Tongs 40g)', s=80, alpha=0.8, edgecolors='k')
ax1.scatter(pork_raw[:, 1], pork_raw[:, 2], c='blue', label='Target 2 (Tongs+Pork 45g)', s=80, alpha=0.8, edgecolors='k')
ax1.set_title("Before: Raw Feature Space (J2 vs J3)")
ax1.set_xlabel("J2 Torque")
ax1.set_ylabel("J3 Torque")
ax1.legend()
ax1.grid(True, linestyle='--', alpha=0.6)

# [After] 27D -> 1D LDA 투영 공간 시각화
ax2.scatter(X_lda[y_test==1], np.zeros_like(X_lda[y_test==1]), c='orange', label='Target 1 (Tongs 40g)', marker='o', s=120, edgecolors='k')
ax2.scatter(X_lda[y_test==2], np.zeros_like(X_lda[y_test==2]), c='blue', label='Target 2 (Tongs+Pork 45g)', marker='s', s=120, edgecolors='k')
ax2.set_title("After: LDA Projected Space (27D -> 1D)")
ax2.set_xlabel("LDA Score")
ax2.get_yaxis().set_visible(False) # y축은 의미 없으므로 숨김
ax2.legend()
ax2.grid(True, axis='x', linestyle='--', alpha=0.6)

# 결정 경계선 그리기 (0 지점)
ax2.axvline(x=0, color='red', linestyle='-', linewidth=2, label='Decision Boundary')
ax2.legend()

plt.tight_layout()
plt.show()

# 5. 결과 출력
accuracy = lda.score(X_test, y_test)
b = lda.intercept_[0]

print("\n" + "="*50)
print("🎯 실제 데이터 기반 LDA 분석 결과")
print("="*50)
print(f"총 샘플 수: {len(X_test)}개 (집게 10, 집게+돈까스 10)")
print(f"Test Accuracy: {accuracy * 100:.1f}%")
print(f"Bias term (b): {b:.3f}")
print("="*50 + "\n")
