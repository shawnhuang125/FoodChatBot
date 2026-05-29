import os
import asyncio
import torch 
from threading import Thread
from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig, TextIteratorStreamer
from peft import PeftModel
from dotenv import load_dotenv
from logger_config import setup_logger

load_dotenv()
logger = setup_logger("infer")

# ==========================================
# 1. 初始化全域變數 (延遲載入關鍵)
# ==========================================
model = None
tokenizer = None

# ==========================================
# 推論超參數提取自 .env 檔案
# ==========================================
TASK1_MAX_TOKENS = int(os.getenv("TASK1_MAX_TOKENS", 256))
TASK1_REP_PENALTY = float(os.getenv("TASK1_REP_PENALTY", 1.0))

TASK2_MAX_TOKENS = int(os.getenv("TASK2_MAX_TOKENS", 512))
TASK2_TEMP = float(os.getenv("TASK2_TEMP", 0.7))
TASK2_TOP_P = float(os.getenv("TASK2_TOP_P", 0.9))
TASK2_REP_PENALTY = float(os.getenv("TASK2_REP_PENALTY", 1.1))

TASK3_MAX_TOKENS = int(os.getenv("TASK3_MAX_TOKENS", 1024))
TASK3_TEMP = float(os.getenv("TASK3_TEMP", 0.3))
TASK3_TOP_P = float(os.getenv("TASK3_TOP_P", 0.8))
TASK3_REP_PENALTY = float(os.getenv("TASK3_REP_PENALTY", 1.0))

# ==========================================
# 2. 封裝載入邏輯到函數中
# ==========================================
def load_all_models():
    """ [模型初始化階段] 根據環境變數載入主模型與三個 LoRA Adapter """
    global model, tokenizer
    
    # 從 .env 讀取，並設定預設值
    model_name = os.getenv("BASE_MODEL_NAME", "Qwen/Qwen2.5-7B-Instruct")
    MODELS_BASE = os.getenv("MODELS_BASE_DIR", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models", "qwen2.5-7b"))

    task1_adapter_dir = os.getenv("TASK1_ADAPTER_DIR", os.path.join("task1", "final_lora_adapter"))
    task2_adapter_dir = os.getenv("TASK2_ADAPTER_DIR", os.path.join("task2", "final_lora_adapter"))
    task3_adapter_dir = os.getenv("TASK3_ADAPTER_DIR", os.path.join("task3", "final_lora_adapter"))

    adapter_paths = {
        "task1": os.path.join(MODELS_BASE, task1_adapter_dir), 
        "task2": os.path.join(MODELS_BASE, task2_adapter_dir),
        "task3": os.path.join(MODELS_BASE, task3_adapter_dir)
    }

    bnb_config = BitsAndBytesConfig(
        load_in_8bit=True,
        llm_int8_threshold=6.0,
        llm_int8_has_fp16_weight=False
    )

    logger.info(f"🔄 正在載入 Tokenizer 與 Base Model: {model_name}...")
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    tokenizer.pad_token = tokenizer.eos_token 

    model = AutoModelForCausalLM.from_pretrained(
        model_name, 
        device_map="auto",
        quantization_config=bnb_config,
        dtype=torch.bfloat16
    )

    logger.info("🔄 正在載入 Task 1 主大腦...")
    model = PeftModel.from_pretrained(model, adapter_paths["task1"], adapter_name="task1")

    logger.info("🔄 正在載入 Task 2 & Task 3 附屬大腦...")
    model.load_adapter(adapter_paths["task2"], adapter_name="task2")
    model.load_adapter(adapter_paths["task3"], adapter_name="task3")

    model.eval()
    logger.info("✅ 三核心大腦載入完成，推論引擎啟動！")

# ==========================================
# 3. 推論邏輯
# ==========================================
async def infer(messages, mode="task1"):
    """ [生成推論介面] 根據不同任務模式 (Task1, Task2, Task3) 切換對應的 Adapter 與環境參數 """
    global model, tokenizer
    
    # 如果還沒載入，就在第一次呼叫時自動載入 (雙重保險)
    if model is None or tokenizer is None:
        load_all_models()

    loop = asyncio.get_running_loop()
    streamer = TextIteratorStreamer(tokenizer, skip_prompt=True, skip_special_tokens=True)

    if mode == "base":
        # 避免觸發 transformers 的 ValueError，直接呼叫 PEFT 底層的禁用方法
        if hasattr(model, "base_model") and hasattr(model.base_model, "disable_adapter_layers"):
            model.base_model.disable_adapter_layers()
    else:
        # 重新啟用 LoRA
        if hasattr(model, "base_model") and hasattr(model.base_model, "enable_adapter_layers"):
            model.base_model.enable_adapter_layers()
            
        if hasattr(model, "peft_config") and mode in model.peft_config.keys():
            model.set_adapter(mode)
        elif mode in ["task1", "task2", "task3"]:
            model.set_adapter(mode)
        else:
            model.set_adapter("task1")

    text = tokenizer.apply_chat_template(
        messages,
        add_generation_prompt=True,
        tokenize=False
    )
    inputs = tokenizer(text, return_tensors="pt").to(model.device)

    stop_words = ["<|im_end|>", "<|endoftext|>"]

    if mode.startswith("task1") or mode == "base":
        generation_kwargs = dict(
            **inputs,
            streamer=streamer,
            max_new_tokens=TASK1_MAX_TOKENS,
            do_sample=False,
            repetition_penalty=TASK1_REP_PENALTY,
            stop_strings=stop_words,
            tokenizer=tokenizer 
        )
    elif mode == "task2":
        generation_kwargs = dict(
            **inputs,
            streamer=streamer,
            max_new_tokens=TASK2_MAX_TOKENS,
            do_sample=True,
            temperature=TASK2_TEMP,
            top_p=TASK2_TOP_P,
            repetition_penalty=TASK2_REP_PENALTY,
            stop_strings=stop_words,
            tokenizer=tokenizer
        )        
    else: 
        generation_kwargs = dict(
            **inputs,
            streamer=streamer,
            max_new_tokens=TASK3_MAX_TOKENS,
            do_sample=True,
            temperature=TASK3_TEMP,
            top_p=TASK3_TOP_P,
            repetition_penalty=TASK3_REP_PENALTY,
            stop_strings=stop_words,
            tokenizer=tokenizer
        )    

    thread = Thread(target=model.generate, kwargs=generation_kwargs, daemon=True)
    thread.start()

    def get_next_token():
        try:
            return next(streamer)
        except StopIteration:
            return None

    while True:
        chunk = await loop.run_in_executor(None, get_next_token)
        if chunk is None:
            break
        
        lower_chunk = chunk.lower()
        if any(tag in lower_chunk for tag in ["<|im_start|>", "<|im_end|>", "user:", "assistant:"]): 
            continue
            
        yield chunk