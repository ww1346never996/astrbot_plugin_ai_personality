# plugins/astrbot_plugin_ai_personality/core/memory.py
# -*- coding: utf-8 -*-
import os
import json
import time
import uuid
import chromadb
from astrbot.api import logger

class MemoryManager:
    def __init__(self, plugin_dir):
        # 数据持久化路径 (宿主机挂载)
        self.data_dir = "/AstrBot/data/soulmate_data"
        
        # 自动修复权限/创建目录
        if not os.path.exists(self.data_dir):
            try:
                os.makedirs(self.data_dir, exist_ok=True)
                os.chmod(self.data_dir, 0o777)
            except Exception as e:
                logger.warning(f"[Sakiko Memory] 目录创建/赋权失败: {e}")

        self.profile_path = os.path.join(self.data_dir, "dynamic_profiles.json")
        self.state_path = os.path.join(self.data_dir, "user_states.json")
        self.chroma_path = os.path.join(self.data_dir, "chromadb")
        
        logger.info(f"[Sakiko Memory] ChromaDB Path: {self.chroma_path}")
        try:
            self.chroma = chromadb.PersistentClient(path=self.chroma_path)
        except Exception as e:
            logger.error(f"[Sakiko Memory] DB Init Failed: {e}")
            if "readonly" in str(e):
                logger.error("!!! 请在宿主机执行: sudo chmod -R 777 ./data/soulmate_data !!!")
            raise e

        self.profiles = self._load_json(self.profile_path)
        self.states = self._load_json(self.state_path)

    def _load_json(self, path):
        if not os.path.exists(path): return {}
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except: return {}

    def _save_json(self, path, data):
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            try: os.chmod(path, 0o666)
            except: pass
        except Exception as e:
            logger.error(f"Save JSON failed: {e}")
            
    # === 请将此方法添加到 MemoryManager 类中 ===
    def get_recent_raw_logs(self, user_id, limit=5):
        """获取最近 N 条原始对话记录用于上下文连贯性"""
        coll = self.chroma.get_or_create_collection("soulmate_memory")
        try:
            results = coll.get(
                where={"$and": [{"user_id": str(user_id)}, {"type": "raw"}]},
                include=["metadatas", "documents"],
                limit=limit + 5  # 多取一些用于排序
            )

            if not results['ids']:
                return []

            # 组装并按时间倒序
            logs = []
            for i in range(len(results['ids'])):
                meta = results['metadatas'][i]
                doc = results['documents'][i]
                timestamp = float(meta.get("timestamp", 0))
                logs.append({"ts": timestamp, "content": doc})

            logs.sort(key=lambda x: x['ts'], reverse=True)
            recent = logs[:limit]

            return "\n".join([item['content'] for item in recent])
        except Exception as e:
            logger.error(f"[Memory Get Recent Raw Error] {e}")
            return ""

    def get_recent_history(self, user_id, limit=3):
        """获取最近 N 条记忆用于 Status 展示"""
        coll = self.chroma.get_or_create_collection("soulmate_memory")
        try:
            # 获取该用户的所有 raw log (为了排序，这里取稍微多一点，比如最近 10 条，然后截取)
            # 注意：Chroma 的 get 性能通常很快
            results = coll.get(
                where={"user_id": str(user_id)},
                # 只获取 metadata 和 document，不需要 embedding
                include=["metadatas", "documents"]
            )
            
            if not results['ids']:
                return ["(暂无记忆)"]

            # 组装数据列表
            logs = []
            for i in range(len(results['ids'])):
                meta = results['metadatas'][i]
                doc = results['documents'][i]
                timestamp = float(meta.get("timestamp", 0))
                logs.append({"ts": timestamp, "content": doc, "type": meta.get("type", "unknown")})

            # 按时间倒序排序 (最新的在前面)
            logs.sort(key=lambda x: x['ts'], reverse=True)
            
            # 取前 N 条
            recent = logs[:limit]
            
            # 格式化输出
            formatted = []
            for item in recent:
                # 转换时间戳为可读时间
                time_str = time.strftime("%H:%M:%S", time.localtime(item['ts']))
                formatted.append(f"[{time_str}] {item['content']}")
                
            return formatted

        except Exception as e:
            logger.error(f"[Memory Get History Error] {e}")
            return [f"读取失败: {e}"]

    def get_state(self, user_id):
        user_id = str(user_id)
        if user_id not in self.states:
            self.states[user_id] = {"intimacy": 50, "mood": "calm", "raw_count": 0}
        return self.states[user_id]

    def update_state(self, user_id, updates):
        s = self.get_state(user_id)
        if "intimacy" in updates:
            s['intimacy'] = max(0, min(100, s['intimacy'] + updates['intimacy']))
        if "mood" in updates:
            s['mood'] = updates['mood']
        if "raw_count_delta" in updates:
            s['raw_count'] = max(0, s.get('raw_count', 0) + updates['raw_count_delta'])
        if "raw_count" in updates:
            s['raw_count'] = max(0, updates['raw_count'])
        self._save_json(self.state_path, self.states)

    def get_profile(self, user_id):
        return self.profiles.get(str(user_id), "普通用户")

    def update_profile(self, user_id, instruction):
        self.profiles[str(user_id)] = instruction
        self._save_json(self.profile_path, self.profiles)

    def add_log(self, user_id, content, type="raw"):
        coll = self.chroma.get_or_create_collection("soulmate_memory")
        try:
            coll.add(
                documents=[content],
                metadatas=[{"type": type, "timestamp": str(time.time()), "user_id": str(user_id)}],
                ids=[str(uuid.uuid4())]
            )
            if type == "raw":
                self.update_state(user_id, {"raw_count_delta": 1})
        except Exception as e:
            logger.error(f"[Memory Add Error] {e}")

    def retrieve(self, user_id, query_text, n_results=5):
        coll = self.chroma.get_or_create_collection("soulmate_memory")
        try:
            # 如果 query 为空（比如只发图没说话），则不检索或检索最近
            if not query_text or not query_text.strip():
                return []

            # 构建增强的检索查询，包含语义扩展
            # 提取关键情绪词和动作词
            enhanced_query = self._enhance_query(query_text)

            # 并行检索：原始查询 + 增强查询，取并集去重
            all_results = []
            for q in [query_text, enhanced_query]:
                if q and q != query_text:  # 避免重复检索
                    results = coll.query(
                        query_texts=[q],
                        n_results=n_results,
                        where={"user_id": str(user_id)}
                    )
                    if results['documents']:
                        all_results.extend(results['documents'][0])

            # 如果增强查询没结果，用原始查询
            if not all_results:
                results = coll.query(
                    query_texts=[query_text],
                    n_results=n_results,
                    where={"user_id": str(user_id)}
                )
                all_results = results['documents'][0] if results['documents'] else []

            # 去重并保持顺序
            seen = set()
            unique_results = []
            for doc in all_results:
                if doc not in seen:
                    seen.add(doc)
                    unique_results.append(doc)

            return unique_results[:n_results]
        except Exception as e:
            logger.error(f"[Memory Retrieve Error] {e}")
            return []

    def _enhance_query(self, query_text):
        """
        语义扩展查询：提取情绪词、工作相关、疲劳相关等关键词
        用于捕捉同一语义的不同表达方式
        """
        import re
        # 定义关键词映射
        keyword_map = {
            "累": ["工作", "疲劳", "忙", "困", "疲倦", "劳累"],
            "忙": ["工作", "加班", "赶工", "紧急", "deadline"],
            "懒": ["休息", "放松", "空闲", "摸鱼"],
            "工作": ["上班", "任务", "项目", "demo", "急活"],
            "疲劳": ["累", "困", "没精神", "疲惫"],
            "抱怨": ["吐槽", "牢骚", "不满"],
        }

        enhanced = []
        for word in keyword_map:
            if word in query_text:
                enhanced.extend(keyword_map[word])

        # 如果没有匹配，返回空
        if not enhanced:
            return ""

        # 合并原始查询和扩展词
        return " ".join([query_text] + list(set(enhanced)))

    def get_raw_logs_for_consolidation(self, user_id):
        coll = self.chroma.get_or_create_collection("soulmate_memory")
        res = coll.get(where={"$and": [{"user_id": str(user_id)}, {"type": "raw"}]}, limit=15)
        return {"ids": res['ids'], "documents": res['documents']}

    def delete_logs(self, ids):
        if not ids: return
        coll = self.chroma.get_or_create_collection("soulmate_memory")
        coll.delete(ids=ids)