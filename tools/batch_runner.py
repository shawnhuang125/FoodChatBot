import os
import sys
import subprocess
from dotenv import load_dotenv
from dataset_manifest import BATCH_PRODUCTION_PLAN
from format_dataset import process_dataset
from shuffle_dataset import shuffle_dataset

# 載入 .env 檔案
load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.env'))

def generate_test_set(selected_task, output_path):
    """ 強制使用 FT_TEST_SEED 產生測試集 """
    test_seed = int(os.getenv("FT_TEST_SEED", 91))
    print(f"\n🧪 [測試集模式] 強制使用種子: {test_seed}")
    run_pipeline(selected_task, output_path, is_test=True, seed=test_seed)

def generate_train_set(selected_task, output_path):
    """ 使用 FT_SHUFFLE_SEED 產生訓練集 """
    train_seed = int(os.getenv("FT_SHUFFLE_SEED", 42))
    print(f"\n🏋️ [訓練集模式] 使用種子: {train_seed}")
    run_pipeline(selected_task, output_path, is_test=False, seed=train_seed)

def run_pipeline(selected_task, output_path, is_test, seed):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    # 執行前確保清空舊資料，保證筆數精準
    if os.path.exists(output_path):
        del_choice = input(f"\n⚠️ 發現已存在檔案 {output_path}，是否要先刪除以確保筆數精準？(y/n): ").strip().lower()
        if del_choice == 'y':
            os.remove(output_path)
            print(f"🗑️ 已清理舊資料：{output_path}")

    # 🎯 核心過濾邏輯：只挑出符合目標任務的產線
    scenarios = []
    for seq in BATCH_PRODUCTION_PLAN:
        if selected_task == "1" and seq[0] in ["A", "B", "C", "D"]:
            scenarios.append(seq)
        elif selected_task == "2" and seq[0] == "E":
            scenarios.append(seq)
        elif selected_task == "3" and seq[0] == "F":
            scenarios.append(seq)
        elif selected_task == "ALL":
            scenarios.append(seq)

    if not scenarios:
        print("❌ 找不到匹配的產線！")
        return

    print(f"\n🚀 啟動自動化生產模式 - 總計 {len(scenarios)} 條產線")
    failed_seqs = []
    auto_dataset_path = os.path.join(base_dir, "auto_dataset.py")

    for i, seq in enumerate(scenarios):
        print(f"\n⏳ 正在執行場景 {i+1}/{len(scenarios)}: 序列 {seq}")
        mode = seq[0]
        count = seq[-1]
        sequence = ",".join(seq[1:-1]) if len(seq) > 2 else ""

        cmd = [sys.executable, auto_dataset_path, "--output", output_path, "--mode", mode, "--count", str(count), "--seed", str(seed)]
        if sequence:
            cmd.extend(["--sequence", sequence])
            
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as e:
            print(f"❌ 執行失敗: {seq}, 錯誤: {e}")
            failed_seqs.append(seq)
            
    print(f"\n✅ Task {selected_task} 所有批次生產完成！原始資料已生成。")
    
    # --- 生成即處理 Pipeline ---
    if not os.path.exists(output_path):
        print("\n⚠️ 注意：沒有產生任何原始資料檔案，跳過格式轉換。")
    else:
        print("\n🔄 開始進行格式轉換...")
        dir_name, file_name = os.path.split(output_path)
        file_root, file_ext = os.path.splitext(file_name)
        
        prefix = "test_" if is_test else "train_"
        formatted_output_path = os.path.join(dir_name, f"{prefix}{file_root}{file_ext}")
        shuffled_output_path = os.path.join(dir_name, f"{prefix}{file_root}_shuffled{file_ext}")

        if process_dataset(output_path, formatted_output_path):
            print("\n🔀 開始進行資料打亂...")
            if shuffle_dataset(formatted_output_path, shuffled_output_path):
                print("\n🎉 所有流程執行完畢！")
                print("="*50)
                print("📦 產出檔案總結：")
                print(f"  [1] 原始資料: {output_path}")
                print(f"  [2] {'測試' if is_test else '訓練'}格式: {formatted_output_path}")
                print(f"  [3] 打亂成品: {shuffled_output_path}")
                print("="*50)
            else:
                print("\n❌ 資料打亂失敗。")
        else:
            print("\n❌ 格式轉換失敗。")

    if failed_seqs:
        print("\n⚠️ 以下序列執行失敗：")
        for f in failed_seqs:
            print(f"   - {f}")

def main():
    """ [Pipeline 任務編排器] 負責調度資料生成、格式轉換與資料打亂的三階段自動化流程。 """
    # 🎯 提供互動式選單讓開發者選擇
    print("="*40)
    print("請選擇要生產的任務資料：")
    print("[1] Task 1: Parser (意圖解析 JSON)")
    print("[2] Task 2: Slot-Filler (槽位補問)")
    print("[3] Task 3: Recommender (美食推薦推坑)")
    print("[A] All: 全部生產 (不推薦混雜)")
    print("="*40)
    
    choice = input("輸入選項 (1/2/3/A): ").strip().upper()
    task_map = {"1": "1", "2": "2", "3": "3", "A": "ALL"}
    selected_task = task_map.get(choice, "1") # 預設防呆為 1

    # 🎯 動態決定存檔名稱
    file_name_mapping = {
        "1": "task1.json",
        "2": "task2.json",
        "3": "task3.json",
        "ALL": "all_tasks.json"
    }

    default_file = file_name_mapping[selected_task]
    
    print(f"\n📝 該任務預設輸出檔名為: {default_file}")
    print("[1] 使用預設檔名")
    print("[2] 自訂新檔名")
    name_choice = input("請選擇 (1/2): ").strip()
    
    if name_choice == "2":
        custom_name = input("請輸入新檔名 (例如: my_dataset.json): ").strip()
        if custom_name:
            if not custom_name.endswith('.json'):
                custom_name += '.json'
            default_file = custom_name
        
    # 🎯 統一目錄管理：從 .env 讀取 dataset 資料夾路徑
    base_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(base_dir, '..'))
    dataset_dir_name = os.getenv("FT_DATASET_DIR", "dataset")
    dataset_dir = os.path.join(project_root, dataset_dir_name)
    os.makedirs(dataset_dir, exist_ok=True)
    output_path = os.path.abspath(os.path.join(dataset_dir, default_file))

    print("\n🎯 請選擇要生成的資料集類型：")
    print("[1] 訓練集 (Train Set)")
    print("[2] 測試集 (Test Set)")
    type_choice = input("輸入選項 (1/2): ").strip()

    if type_choice == "2":
        generate_test_set(selected_task, output_path)
    else:
        generate_train_set(selected_task, output_path)

if __name__ == "__main__":
    main()