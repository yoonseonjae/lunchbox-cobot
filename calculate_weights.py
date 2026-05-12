import numpy as np
import matplotlib.pyplot as plt

# 1. 실제 데이터 로드 ('빈그리퍼' vs '집게')
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

# 2. 특징 분리도 측정: Fisher's Discriminant Ratio (FDR) 계산
mean_empty = np.mean(tongs_raw, axis=0)
var_empty = np.var(tongs_raw, axis=0)

mean_tongs = np.mean(pork_raw, axis=0)
var_tongs = np.var(pork_raw, axis=0)

# 0으로 나누는 것을 방지하기 위해 아주 작은 값(1e-6)을 더해줍니다.
fdr_scores = (mean_empty - mean_tongs)**2 / (var_empty + var_tongs + 1e-6)

# 3. 가중치 정규화 (전체 합을 100%로 맞춤)
weights = (fdr_scores / np.sum(fdr_scores)) * 100

# 4. 시각화 (그래프 그리기)
axes_labels = ['J1', 'J2', 'J3', 'J4', 'J5', 'J6']

plt.figure(figsize=(10, 6))
bars = plt.bar(axes_labels, weights, color='#8b949e', edgecolor='black', alpha=0.7)

# J2와 J4에 색상 하이라이트
bars[1].set_color('#f0883e') # J2 주황색
bars[3].set_color('#3fb950') # J4 초록색

plt.title("Feature Importance (Weight Allocation via Fisher's Ratio)", fontsize=16, fontweight='bold')
plt.ylabel("Optimal Weight (%)", fontsize=12)
plt.xlabel("Joint Axes (J1~J6)", fontsize=12)

# 각 바 위에 퍼센트 텍스트 표시
for bar in bars:
    yval = bar.get_height()
    plt.text(bar.get_x() + bar.get_width()/2.0, yval + 1, f"{yval:.1f}%", ha='center', va='bottom', fontweight='bold')

plt.grid(axis='y', linestyle='--', alpha=0.6)
plt.tight_layout()
plt.show()

# 터미널 출력용
print("\n" + "="*50)
print("📊 [머신러닝 기반 축별 최적 가중치 산출 결과]")
print("="*50)
for i, w in enumerate(weights):
    print(f"J{i+1} 가중치: {w:>5.1f}%")
print("="*50 + "\n")
