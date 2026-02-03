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
    def __init__(self, api_key, base_url, model_name):
        self.model = model_name
        
        # 初始化 OpenAI
        self.client = OpenAI(
            api_key=api_key, 
            base_url=base_url
        )
        
        # 初始化 ChromaDB (持久化存储)
        self.chroma_client = chromadb.PersistentClient(path=os.path.join(DATA_DIR, "chromadb"))
        self.collection = self.chroma_client.get_or_create_collection(name="soulmate_memory")
        
        # 加载用户状态
        self.state_file = os.path.join(DATA_DIR, "user_states.json")
        self.user_states = self._load_states()

    def _load_states(self):
        if os.path.exists(self.state_file):
            with open(self.state_file, 'r', encoding='utf-8') as f:
                try:
                    return json.load(f)
                except json.JSONDecodeError:
                    return {}
        return {}
    
    def _save_states(self):
        with open(self.state_file, 'w', encoding='utf-8') as f:
            json.dump(self.user_states, f, ensure_ascii=False, indent=2)

    def get_user_state(self, user_id):
        user