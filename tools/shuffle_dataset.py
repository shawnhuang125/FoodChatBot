import json
import random
import os
from dotenv import load_dotenv

def shuffle_dataset(input_path: str, output_path: str, seed: int = None) -> bool:
    """ 讀取 JSON 資料集並進行隨機打亂，確保結果具備可複現性 """
    if seed is None:
        seed = int(os.getenv("FT_SHUFFLE_SEED", 42))

    try:
        print(f"正在讀取檔案: {input_path}...")
        with open(input_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"❌ 錯誤：找不到輸入檔案 {input_path}")
        return False
    except json.JSONDecodeError as e:
        print(f"❌ 錯誤：輸入檔案 JSON 解析失敗 {input_path}，詳細資訊: {e}")
        return False
    except Exception as e:
        print(f"❌ 錯誤：讀取檔案時發生例外狀況 - {e}")
        return False
        
    print(f"✅ 成功讀取，總筆數: {len(data)}")

    # 打亂資料 (設定 seed 確保結果可複現)
    random.seed(seed)
    random.shuffle(data)
    print("🔄 資料打亂完成！")

    try:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"💾 已儲存打亂後的資料至: {output_path}")
        return True
    except Exception as e:
        print(f"❌ 錯誤：寫入輸出檔案失敗 {output_path}，詳細資訊: {e}")
        return False

if __name__ == "__main__":
    # 作為測試用途時，從 .env 動態讀取設定
    load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.env'))
    PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    
    test_input = os.path.join(PROJECT_ROOT, "dataset", "train_task3.json") 
    test_output = os.path.join(PROJECT_ROOT, "dataset", "train_task3_shuffled.json")
    
    shuffle_dataset(test_input, test_output)