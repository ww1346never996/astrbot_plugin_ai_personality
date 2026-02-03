import os
import json
import chromadb
from openai import OpenAI
import datetime

# 自动获取当前文件所在的目录/data
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

class SoulmateCore:
    # 修改 __init__ 接收参数
    def __init__(self, api_key, base_url, model_name):
        self.model = model_name # 保存模型名
        
        # 使用传入的 key 初始化 OpenAI
        self.client = OpenAI(
            api_key=api_key, 
            base_url=base_url
        )
        
        # 下面保持不变
        self.chroma_client = chromadb.PersistentClient(path=os.path.join(DATA_DIR, "chromadb"))
        self.collection = self.chroma_client.get_or_create_collection(name="soulmate_memory")
        self.state_file = os.path.join(DATA_DIR, "user_states.json")
        self.user_states = self._load_states()

    def _load_states(self):
        if os.path.exists(self.state_file):
            with open(self.state_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}
    
    def _save_states(self):
        with open(self.state_file, 'w', encoding='utf-8') as f:
            json.dump(self.user_states, f, ensure_ascii=False, indent=2)

    # ... process_chat 等其他方法保持不变 ...
    # ... 请确保 process_chat 里调用 self.client.chat.completions 时使用的是 self.model ...
    
    # 示例 process_chat 片段
    def process_chat(self, user_id, user_input, user_name):
        # ... (省略 RAG 检索部分) ...
        # system_prompt = ...
        
        try:
            response = self.client.chat.completions.create(
                model=self.model, # 使用配置的模型
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_input}
                ],
                response_format={"type": "json_object"}
            )
            # ... (省略后续处理) ...