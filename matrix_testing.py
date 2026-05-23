import numpy as np
import re

# 模擬 4 家餐廳，在 3 個獨立向量通道計算出來的餘弦相似度 (0~1)
# 通道 0: 飲料語意 | 通道 1: 適合看書語意 | 通道 2: 燒肉語意
S_matrix = np.array([
    [0.85, 0.90, 0.15],  # 餐廳 A: 飲料強、看書強、燒肉弱
    [0.20, 0.88, 0.10],  # 餐廳 B: 飲料弱、看書強、燒肉弱
    [0.90, 0.15, 0.20],  # 餐廳 C: 飲料強、看書弱、燒肉弱
    [0.10, 0.20, 0.95]   # 餐廳 D: 飲料弱、看書弱、燒肉強
])

# 餐廳對應的名稱（轉換為 NumPy Array 方便進行矩陣遮罩過濾）
restaurants = np.array([
    "餐廳 A (飲料+看書)", 
    "餐廳 B (純看書/高人氣)", 
    "餐廳 C (純飲料/無座位)", 
    "餐廳 D (純燒肉店)"
])

# 後續的非對數排序矩陣 R (Rating, Popularity)
R = np.array([
    [4.5, 1500],  # 餐廳 A
    [4.8, 9000],  # 餐廳 B
    [4.1, 800],   # 餐廳 C
    [4.6, 5000]   # 餐廳 D
])

def soft_gate(similarity, threshold=0.5, steepness=12, epsilon=0.01):
    activated = 1.0 / (1.0 + np.exp(-steepness * (similarity - threshold)))
    return np.maximum(activated, epsilon)

# 1. 預先將整張相似度矩陣過飽和函數轉為門控信號
G = soft_gate(S_matrix)

# ==========================================
# 核心：動態邏輯閘運算解析器 (Dynamic Logic Parser)
# ==========================================
def evaluate_logic_expression(expr_str, G_matrix):
    expr = expr_str.upper()
    expr = re.sub(r'\b(\d+)\b', r'G_matrix[:, \1]', expr)
    expr = re.compile(r'NOT\s+([A-Za-z0-9_:.\[\]\,\s]+)').sub(r'(1.0 - \1)', expr)
    expr = expr.replace('AND', '*')
    expr = expr.replace('OR', '+')
    
    try:
        result_mask = eval(expr, {"G_matrix": G_matrix, "np": np})
        # 這裡移除 np.clip，讓邏輯不符的分數直接趨近於 0，以便進行過濾
        return result_mask
    except Exception as e:
        raise ValueError(f"邏輯運算式解析失敗: {e}")

# ==========================================
# 2. 測試你的動態邏輯閘搭配
# ==========================================

# 測試情境 A: 必須是 (飲料 AND 適合看書) AND (不能是燒肉) -> 只有 A 會出來
current_logic = "(0 AND 1) AND (NOT 2)"

# 測試情境 B: 只要是 飲料 OR 適合看書 就可以 -> A, B, C 都會出來
# current_logic = "0 OR 1"

# 計算邏輯閘遮罩
final_gate_mask = evaluate_logic_expression(current_logic, G)

# ==========================================
# 3. 矩陣硬過濾 (Hard Filter) 
# ==========================================
# 設定一個硬門檻門檻值（例如：綜合邏輯分數必須高於 0.30）
HARD_THRESHOLD = 0.30

# 產生一個布林遮罩向量 (例如: [True, False, False, False])
valid_indices = final_gate_mask >= HARD_THRESHOLD

# 利用 NumPy 矩陣特性，直接將不符合結果的店家「一刀切除」
filtered_restaurants = restaurants[valid_indices]
filtered_S = S_matrix[valid_indices]
filtered_R = R[valid_indices]
filtered_masks = final_gate_mask[valid_indices]

# ==========================================
# 4. 計算並排序符合條件的店家
# ==========================================
# 計算通過過濾的店家的基礎排序分
ranking_base = filtered_R[:, 0] * filtered_R[:, 1]
# 結合邏輯閘分數，算出最終總分
final_scores = ranking_base * filtered_masks

# 依最終總分進行「降冪排序」（分數高的排前面）
sort_indices = np.argsort(final_scores)[::-1]

# ==========================================
# 5. 輸出最終符合結果
# ==========================================
print(f"輸入的動態邏輯閘: {current_logic}")
print(f"過濾門檻值: {HARD_THRESHOLD}")
print(f"符合結果的店家數量: {len(filtered_restaurants)} 家")
print("=" * 80)

if len(filtered_restaurants) == 0:
    print("沒有任何店家符合此邏輯條件。")
else:
    for idx in sort_indices:
        print(f"【{filtered_restaurants[idx]}】")
        print(f" ├─ 通道相似度(飲料/看書/燒肉): {filtered_S[idx]}")
        print(f" ├─ 評分(Rating): {filtered_R[idx, 0]} | 流行度(Popularity): {filtered_R[idx, 1]}")
        print(f" ├─ 基礎排序分: {ranking_base[idx]:.1f} | 邏輯閘分數: {filtered_masks[idx]:.4f}")
        print(f" └─ 最終排序總分: {final_scores[idx]:.1f}")
        print("-" * 80)