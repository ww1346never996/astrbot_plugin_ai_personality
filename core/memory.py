# core/memory.py
# -*- coding: utf-8 -*-
import os
import json
import time
import datetime
import chromadb

class MemoryManager:
    def __init__(self, base_dir):
        # 初始化路径
        self.data_dir = os.path.join(base_dir, "data")
        if not os.path.exists(self.data_dir): os.makedirs(self.data_dir)
        
        # 数据库连接
        self.chroma = chromadb.PersistentClient(path=os.path.join(self.data_dir, "chromadb"))
        self.collection = self.chroma.get_or_create_collection(name="soulmate_memory")
        
        # 文件路径
        self.state_file = os.path.join(self.data_dir, "user_states.json")
        self.profile_file = os.path.join(self.data_dir, "dynamic_profiles.json")
        
        # 加载缓存
        self.states = self._load_json(self.state_file)
        self.profiles = self._load_json(self.profile_file)

    def _load_json(self, path):
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                try: return json.load(f)
                except: return {}
        return {}

    def _save_json(self, path, data):
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # === 用户状态管理 ===
    def get_state(self, user_id):
        uid = str(user_id)
        if uid not in self.states:
            self.states[uid] = {"intimacy": 10, "mood": "neutral", "raw_count": 0}
        return self.states[uid]

    def update_state(self, user_id, updates):
        state = self.get_state(user_id)
        # 合并更新
        for k, v in updates.items():
            if k == "intimacy": state[k] = max(0, min(100, state[k] + v))
            elif k == "raw_count_delta": state["raw_count"] = max(0, state.get("raw_count", 0) + v)
            else: state[k] = v
        self._save_json(self.state_file, self.states)

    # === 全局人格管理 ===
    def get_profile(self, user_id):
        return self.profiles.get(str(user_id), "默认模式")

    def update_profile(self, user_id, instruction):
        if instruction:
            self.profiles[str(user_id)] = instruction
            self._save_json(self.profile_file, self.profiles)

    # === 向量记忆管理 ===
    def add_log(self, user_id, text, type="raw", importance=1):
        uid = str(user_id)
        self.collection.add(
            documents=[text],
            metadatas=[{"user_id": uid, "type": type, "timestamp": datetime.datetime.now().isoformat(), "importance": importance}],
            ids=[f"{uid}_{type}_{time.time()}"]
        )
        if type == "raw":
            self.update_state(uid, {"raw_count_delta": 1})

    def retrieve(self, user_id, query):
        uid = str(user_id)
        if not query: query = "context"
        try:
            # 混合检索：Insight + Raw
            res_insight = self.collection.query(query_texts=[query], n_results=2, where={"$and": [{"user_id": uid}, {"type": "insight"}]})
            res_raw = self.collection.query(query_texts=[query], n_results=2, where={"$and": [{"user_id": uid}, {"type": "raw"}]})
            merged = []
            if res_insight['documents']: merged.extend(res_insight['documents'][0])
            if res_raw['documents']: merged.extend(res_raw['documents'][0])
            return merged
        except: return []

    def get_raw_logs_for_consolidation(self, user_id, limit=10):
        return self.collection.get(where={"$and": [{"user_id": str(user_id)}, {"type": "raw"}]}, limit=limit)

    def delete_logs(self, ids):
        self.collection.delete(ids=ids)