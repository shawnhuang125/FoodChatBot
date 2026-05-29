import os
import sys
import torch
torch.cuda.empty_cache()
import argparse
import subprocess
import json
from dotenv import load_dotenv
from datasets import load_dataset
from transformers import (
    AutoTokenizer, 
    AutoModelForCausalLM, 
    BitsAndBytesConfig,
    DataCollatorForLanguageModeling,
    TrainingArguments,
    TrainerCallback # 🎯 引入 Callback 功能
)
from peft import LoraConfig, TaskType, get_peft_model, prepare_model_for_kbit_training
from trl import SFTTrainer

# 載入位於專案根目錄的 .env 檔案
load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.env'))

# ==========================================
# 0. 自訂 Callback：用於攔截並儲存訓練 Log
# ==========================================
class LogCallback(TrainerCallback):
    """ [訓練回調模組] 攔截 Hugging Face Trainer 的日誌事件，並將其即時寫入 JSON 檔案。 """
    def __init__(self, log_path):
        self.log_path = log_path
        self.logs = []
        # 初始化檔案，確保資料夾存在
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        with open(self.log_path, "w", encoding="utf-8") as f:
            json.dump([], f)

    def on_log(self, args, state, control, logs=None, **kwargs):
        if logs is not None:
            # 將新的 log 加到清單中
            self.logs.append(logs)
            # 即時寫入檔案，確保哪怕中斷也有紀錄
            with open(self.log_path, "w", encoding="utf-8") as f:
                json.dump(self.logs, f, ensure_ascii=False, indent=4)


# ==========================================
# 1. 從 .env 讀取訓練設定
# ==========================================
# --- 路徑設定 ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, ".."))
FT_DATASET_DIR = os.path.join(PROJECT_ROOT, os.getenv("FT_DATASET_DIR", "dataset"))
FT_MODELS_DIR = os.path.join(PROJECT_ROOT, os.getenv("FT_MODELS_DIR", "models/qwen2.5-7b"))

# --- 模型與 Tokenizer ---
FT_BASE_MODEL_NAME = os.getenv("FT_BASE_MODEL_NAME", "Qwen/Qwen2.5-7B-Instruct")
FT_MODEL_MAX_LENGTH = int(os.getenv("FT_MODEL_MAX_LENGTH", 2048))

# --- LoRA 微調參數 ---
FT_LORA_R = int(os.getenv("FT_LORA_R", 16))
FT_LORA_ALPHA = int(os.getenv("FT_LORA_ALPHA", 32))
FT_LORA_DROPOUT = float(os.getenv("FT_LORA_DROPOUT", 0.1))
FT_TARGET_MODULES_STR = os.getenv("FT_TARGET_MODULES", "q_proj,k_proj,v_proj,o_proj,gate_proj,up_proj,down_proj")
FT_TARGET_MODULES = [m.strip() for m in FT_TARGET_MODULES_STR.split(',')]

# --- 訓練參數 (TrainingArguments) ---
FT_BATCH_SIZE = int(os.getenv("FT_BATCH_SIZE", 2))
FT_GRAD_ACCUM_STEPS = int(os.getenv("FT_GRAD_ACCUM_STEPS", 8))
FT_LEARNING_RATE = float(os.getenv("FT_LEARNING_RATE", 1e-4))
FT_EPOCHS = int(os.getenv("FT_EPOCHS", 3))
FT_LOGGING_STEPS = int(os.getenv("FT_LOGGING_STEPS", 10))
FT_SAVE_STEPS = int(os.getenv("FT_SAVE_STEPS", 100))
FT_OPTIM = os.getenv("FT_OPTIM", "paged_adamw_32bit")

# --- 自動化任務配置 ---
TASK_CONFIG = {
    "1": {
        "dataset": os.getenv("FT_TASK1_DATASET", "train_task1_shuffled.json"), 
        "output": os.getenv("FT_TASK1_OUTPUT_DIR", "task1"),
        "base_model": os.getenv("FT_TASK1_BASE_MODEL_NAME", FT_BASE_MODEL_NAME),
        "model_max_length": int(os.getenv("FT_TASK1_MODEL_MAX_LENGTH", FT_MODEL_MAX_LENGTH)),
        "epochs": int(os.getenv("FT_TASK1_EPOCHS", FT_EPOCHS)),
        "learning_rate": float(os.getenv("FT_TASK1_LEARNING_RATE", FT_LEARNING_RATE)),
        "batch_size": int(os.getenv("FT_TASK1_BATCH_SIZE", FT_BATCH_SIZE)),
        "grad_accum_steps": int(os.getenv("FT_TASK1_GRAD_ACCUM_STEPS", FT_GRAD_ACCUM_STEPS)),
        "lora_r": int(os.getenv("FT_TASK1_LORA_R", FT_LORA_R)),
        "lora_alpha": int(os.getenv("FT_TASK1_LORA_ALPHA", FT_LORA_ALPHA)),
        "lora_dropout": float(os.getenv("FT_TASK1_LORA_DROPOUT", FT_LORA_DROPOUT)),
        "target_modules": [m.strip() for m in os.getenv("FT_TASK1_TARGET_MODULES", FT_TARGET_MODULES_STR).split(',')],
        "logging_steps": int(os.getenv("FT_TASK1_LOGGING_STEPS", FT_LOGGING_STEPS)),
        "save_steps": int(os.getenv("FT_TASK1_SAVE_STEPS", FT_SAVE_STEPS)),
        "optim": os.getenv("FT_TASK1_OPTIM", FT_OPTIM)
    },
    "2": {
        "dataset": os.getenv("FT_TASK2_DATASET", "train_task2_shuffled.json"), 
        "output": os.getenv("FT_TASK2_OUTPUT_DIR", "task2"),
        "base_model": os.getenv("FT_TASK2_BASE_MODEL_NAME", FT_BASE_MODEL_NAME),
        "model_max_length": int(os.getenv("FT_TASK2_MODEL_MAX_LENGTH", FT_MODEL_MAX_LENGTH)),
        "epochs": int(os.getenv("FT_TASK2_EPOCHS", FT_EPOCHS)),
        "learning_rate": float(os.getenv("FT_TASK2_LEARNING_RATE", FT_LEARNING_RATE)),
        "batch_size": int(os.getenv("FT_TASK2_BATCH_SIZE", FT_BATCH_SIZE)),
        "grad_accum_steps": int(os.getenv("FT_TASK2_GRAD_ACCUM_STEPS", FT_GRAD_ACCUM_STEPS)),
        "lora_r": int(os.getenv("FT_TASK2_LORA_R", FT_LORA_R)),
        "lora_alpha": int(os.getenv("FT_TASK2_LORA_ALPHA", FT_LORA_ALPHA)),
        "lora_dropout": float(os.getenv("FT_TASK2_LORA_DROPOUT", FT_LORA_DROPOUT)),
        "target_modules": [m.strip() for m in os.getenv("FT_TASK2_TARGET_MODULES", FT_TARGET_MODULES_STR).split(',')],
        "logging_steps": int(os.getenv("FT_TASK2_LOGGING_STEPS", FT_LOGGING_STEPS)),
        "save_steps": int(os.getenv("FT_TASK2_SAVE_STEPS", FT_SAVE_STEPS)),
        "optim": os.getenv("FT_TASK2_OPTIM", FT_OPTIM)
    },
    "3": {
        "dataset": os.getenv("FT_TASK3_DATASET", "train_task3_shuffled.json"),
        "output": os.getenv("FT_TASK3_OUTPUT_DIR", "task3"),
        "base_model": os.getenv("FT_TASK3_BASE_MODEL_NAME", FT_BASE_MODEL_NAME),
        "model_max_length": int(os.getenv("FT_TASK3_MODEL_MAX_LENGTH", FT_MODEL_MAX_LENGTH)),
        "epochs": int(os.getenv("FT_TASK3_EPOCHS", FT_EPOCHS)),
        "learning_rate": float(os.getenv("FT_TASK3_LEARNING_RATE", FT_LEARNING_RATE)),
        "batch_size": int(os.getenv("FT_TASK3_BATCH_SIZE", FT_BATCH_SIZE)),
        "grad_accum_steps": int(os.getenv("FT_TASK3_GRAD_ACCUM_STEPS", FT_GRAD_ACCUM_STEPS)),
        "lora_r": int(os.getenv("FT_TASK3_LORA_R", FT_LORA_R)),
        "lora_alpha": int(os.getenv("FT_TASK3_LORA_ALPHA", FT_LORA_ALPHA)),
        "lora_dropout": float(os.getenv("FT_TASK3_LORA_DROPOUT", FT_LORA_DROPOUT)),
        "target_modules": [m.strip() for m in os.getenv("FT_TASK3_TARGET_MODULES", FT_TARGET_MODULES_STR).split(',')],
        "logging_steps": int(os.getenv("FT_TASK3_LOGGING_STEPS", FT_LOGGING_STEPS)),
        "save_steps": int(os.getenv("FT_TASK3_SAVE_STEPS", FT_SAVE_STEPS)),
        "optim": os.getenv("FT_TASK3_OPTIM", FT_OPTIM)
    }
}

def train_task(task_id):
    """ [核心訓練函數] 負責讀取設定，並對單一任務執行完整的 SFT (Supervised Fine-Tuning) 流程。 """
    print(f"\n{'='*50}")
    print(f"🚀 開始執行 Task {task_id} 的微調訓練...")
    print(f"{'='*50}\n")

    config = TASK_CONFIG[task_id]
    dataset_path = os.path.join(FT_DATASET_DIR, config["dataset"])
    output_dir = os.path.join(FT_MODELS_DIR, config["output"])
    
    # 🎯 設定 Log 檔案的儲存路徑
    log_file_path = os.path.join(output_dir, "training_logs.json")

    if not os.path.exists(dataset_path):
        raise FileNotFoundError(f"❌ 找不到資料集檔案：{dataset_path}")

    # ==========================================
    # 2. 模型與量化配置 (8-bit Int8)
    # ==========================================
    bnb_config = BitsAndBytesConfig(
        load_in_8bit=True,
        llm_int8_threshold=6.0,  
        llm_int8_has_fp16_weight=False
    )

    tokenizer = AutoTokenizer.from_pretrained(config["base_model"])
    tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"
    tokenizer.model_max_length = config["model_max_length"]

    model = AutoModelForCausalLM.from_pretrained(
        config["base_model"], 
        device_map="auto",              
        quantization_config=bnb_config,
        dtype=torch.bfloat16      
    )

    model = prepare_model_for_kbit_training(model)

    # ==========================================
    # 3. PEFT LoRA 配置
    # ==========================================
    peft_config = LoraConfig(
        task_type=TaskType.CAUSAL_LM,
        target_modules=config["target_modules"],
        r=config["lora_r"],               
        lora_alpha=config["lora_alpha"],      
        lora_dropout=config["lora_dropout"],   
        bias="none"
    )

    model = get_peft_model(model, peft_config)

    # ==========================================
    # 4. 資料集與格式化
    # ==========================================
    data_format = "json"
    dataset = load_dataset(data_format, data_files=dataset_path, split="train")

    def formatting_prompts_func(example):
        """ [資料格式化函數] 將資料集中的 'messages' 欄位轉換為模型訓練所需的對話模板格式。 """
        return tokenizer.apply_chat_template(
            example["messages"],
            tokenize=False,
            add_generation_prompt=False
        )

    collator = DataCollatorForLanguageModeling(tokenizer=tokenizer, mlm=False)

    # ==========================================
    # 5. 訓練參數設定
    # ==========================================
    training_args = TrainingArguments(
        output_dir=output_dir,
        per_device_train_batch_size=config["batch_size"],  
        gradient_accumulation_steps=config["grad_accum_steps"],  
        gradient_checkpointing=True,
        learning_rate=config["learning_rate"],             
        lr_scheduler_type="cosine",
        logging_steps=config["logging_steps"],        # 🎯 每 N 步觸發一次 log，會被我們存下來
        warmup_ratio=0.1,
        num_train_epochs=config["epochs"],             
        save_strategy="steps",          
        save_steps=config["save_steps"],                  
        save_total_limit=15,            
        bf16=True,                      
        fp16=False,
        optim=config["optim"],      
        report_to="none",                    
        dataloader_num_workers=0        
    )

    # ==========================================
    # 6. 訓練啟動器
    # ==========================================
    trainer = SFTTrainer(
        model=model,
        train_dataset=dataset,
        args=training_args,
        formatting_func=formatting_prompts_func,
        data_collator=collator,
        callbacks=[LogCallback(log_file_path)] # 🎯 註冊自訂的 Log 儲存器
    )

    print(f"📄 訓練 Log 將被記錄至: {log_file_path}")
    trainer.train()
    trainer.save_model(os.path.join(output_dir, "final_lora_adapter"))
    print(f"\n✅ Task {task_id} 訓練成功！")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="自動化微調排程腳本")
    parser.add_argument("--task", type=str, default="ALL", choices=["1", "2", "3", "ALL"],
                        help="選擇要訓練的 Task (1, 2, 3) 或是 ALL")
    args = parser.parse_args()

    if args.task == "ALL":
        print("🌌 啟動睡眠排程模式：將依序訓練 Task 1, 2, 3")
        for t in ["1", "2", "3"]:
            command = [sys.executable, __file__, "--task", t]
            subprocess.run(command, check=True)
            print(f"🧹 Task {t} 結束，已釋放顯存，準備進入下一個任務...\n")
        print("🎉 全部任務訓練完畢！")
    else:
        train_task(args.task)