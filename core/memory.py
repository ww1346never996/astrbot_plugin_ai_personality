# plugins/astrbot_plugin_ai_personality/core/memory.py
# -*- coding: utf-8 -*-
"""
Memory System Architecture (三层架构):
├── Layer 1: Raw Logs (短期对话)
│   └── ephemeral, auto-cleaned after consolidation
├── Layer 2: Insights (长期记忆)
│   └── facts, preferences, important events
└── Layer 3: Dynamic Profile (人格配置)
    └── condensed interaction patterns, user preferences
"""
import os
import json
import time
import uuid
import chromadb
from astrbot.api import logger

class MemoryManager:
    def __init__(self, plugin_dir):
        self.data_dir = "/AstrBot/data/soulmate_data"

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

    # ============================================================
    # Layer 3: Dynamic Profile (人格配置)
    # ============================================================

    def get_user_profile(self, user_id):
        """
        获取用户的人格配置，包含交互模式、偏好、敏感话题等
        """
        user_id = str(user_id)
        default_profile = {
            "communication_style": "balanced",  # formal / casual / balanced / playful
            "humor_level": "moderate",  # low / moderate / high
            "caring_frequency": "moderate",  # infrequent / moderate / frequent
            "sensitive_topics": [],  # 敏感话题列表
            "preferred_topics": [],  # 用户感兴趣的话题
            "interaction_patterns": [],  # 交互模式描述
            "personality_traits": [],  # 用户性格特征观察
            "last_context": "",  # 最近的情境描述
            "relationship_summary": "",  # 关系总结
            "total_conversations": 0,
            "last_interaction_time": 0
        }
        return self.profiles.get(user_id, default_profile)

    def update_user_profile(self, user_id, profile_updates):
        """
        增量更新用户人格配置
        """
        user_id = str(user_id)
        current = self.get_user_profile(user_id)

        # 直接覆盖更新
        for key, value in profile_updates.items():
            if key in current:
                if isinstance(current[key], list) and isinstance(value, list):
                    # 列表类型去重合并
                    current[key] = list(set(current[key] + value))
                else:
                    current[key] = value

        current["last_interaction_time"] = time.time()
        self.profiles[user_id] = current
        self._save_json(self.profile_path, self.profiles)
        logger.info(f"[Profile Updated] User {user_id}: {list(profile_updates.keys())}")

    def get_profile_summary(self, user_id):
        """
        获取人格配置的简洁摘要，用于 prompt 注入
        """
        profile = self.get_user_profile(user_id)

        parts = []
        if profile.get("relationship_summary"):
            parts.append(f"【关系定位】{profile['relationship_summary']}")
        if profile.get("personality_traits"):
            traits = ", ".join(profile["personality_traits"][-5:])  # 只取最近5个
            parts.append(f"【用户性格】{traits}")
        if profile.get("communication_style") != "balanced":
            parts.append(f"【沟通风格】{profile['communication_style']}")
        if profile.get("humor_level") != "moderate":
            parts.append(f"【幽默程度】{profile['humor_level']}")
        if profile.get("sensitive_topics"):
            parts.append(f"【敏感话题】{', '.join(profile['sensitive_topics'])}")

        return "\n".join(parts) if parts else "（用户资料正在学习中...）"

    # ============================================================
    # Layer 2: Insights (长期记忆)
    # ============================================================

    def get_insights_for_consolidation(self, user_id, limit=20):
        """
        获取待整理的长期记忆
        """
        coll = self.chroma.get_or_create_collection("soulmate_memory")
        res = coll.get(
            where={"$and": [{"user_id": str(user_id)}, {"type": "insight"}]},
            include=["metadatas", "documents"],
            limit=limit
        )
        return {"ids": res['ids'], "documents': res['documents']}

    def retrieve_insights(self, user_id, query_text, n_results=5):
        """
        检索长期记忆
        """
        coll = self.chroma.get_or_create_collection("soulmate_memory")
        try:
            if not query_text or not query_text.strip():
                return []

            results = coll.query(
                query_texts=[query_text],
                n_results=n_results,
                where={"$and": [{"user_id": str(user_id)}, {"type": "insight"}]}
            )
            return results['documents'][0] if results['documents'] else []
        except Exception as e:
            logger.error(f"[Memory Retrieve Insights Error] {e}")
            return []

    def delete_insights(self, ids):
        """删除指定的 insight"""
        if not ids: return
        coll = self.chroma.get_or_create_collection("soulmate_memory")
        coll.delete(ids=ids)

    # ============================================================
    # Layer 1: Raw Logs (短期对话)
    # ============================================================

    def get_recent_raw_logs(self, user_id, limit=5):
        """获取最近 N 条原始对话记录用于上下文连贯性"""
        coll = self.chroma.get_or_create_collection("soulmate_memory")
        try:
            results = coll.get(
                where={"$and": [{"user_id": str(user_id)}, {"type": "raw"}]},
                include=["metadatas", "documents"],
                limit=limit + 5
            )

            if not results['ids']:
                return ""

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

    def get_recent_history(self, user_id, limit=5):
        """获取最近 N 条记忆用于 Status 展示（包含 raw + insight）"""
        coll = self.chroma.get_or_create_collection("soulmate_memory")
        try:
            results = coll.get(
                where={"user_id": str(user_id)},
                include=["metadatas", "documents"]
            )

            if not results['ids']:
                return ["(暂无记忆)"]

            logs = []
            for i in range(len(results['ids'])):
                meta = results['metadatas'][i]
                doc = results['documents'][i]
                timestamp = float(meta.get("timestamp", 0))
                logs.append({"ts": timestamp, "content": doc, "type": meta.get("type", "unknown")})

            logs.sort(key=lambda x: x['ts'], reverse=True)
            recent = logs[:limit]

            formatted = []
            for item in recent:
                time_str = time.strftime("%m-%d %H:%M", time.localtime(item['ts']))
                type_hint = "💭" if item['type'] == "raw" else "📌"
                formatted.append(f"{type_hint} [{time_str}] {item['content']}")

            return formatted

        except Exception as e:
            logger.error(f"[Memory Get History Error] {e}")
            return [f"读取失败: {e}"]

    # ============================================================
    # Unified Retrieval (统一检索接口)
    # ============================================================

    def retrieve_all(self, user_id, query_text, n_results=5):
        """
        统一检索：profile摘要 + 长期记忆 + 短期对话历史
        返回结构化数据供 agent 使用
        """
        profile_summary = self.get_profile_summary(user_id)
        insights = self.retrieve_insights(user_id, query_text, n_results)
        recent_raw = self.get_recent_raw_logs(user_id, limit=5)

        return {
            "profile": profile_summary,
            "insights": insights,
            "recent_raw": recent_raw
        }

    # ============================================================
    # State Management
    # ============================================================

    def get_state(self, user_id):
        user_id = str(user_id)
        if user_id not in self.states:
            self.states[user_id] = {"intimacy": 50, "mood": "calm", "raw_count": 0, "insight_count": 0}
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
        if "insight_count" in updates:
            s['insight_count'] = max(0, updates['insight_count'])
        self._save_json(self.state_path, self.states)

    # ============================================================
    # Legacy Interface (向后兼容)
    # ============================================================

    def get_profile(self, user_id):
        """向后兼容：获取简化的 profile 字符串"""
        profile = self.get_user_profile(user_id)
        parts = []
        if profile.get("relationship_summary"):
            parts.append(profile["relationship_summary"])
        if profile.get("personality_traits"):
            parts.append("用户特征: " + ", ".join(profile["personality_traits"][-3:]))
        return "\n".join(parts) if parts else "普通用户"

    def update_profile(self, user_id, instruction):
        """向后兼容：简化的 profile 更新"""
        self.update_user_profile(user_id, {"relationship_summary": instruction})

    def add_log(self, user_id, content, type="raw"):
        """添加日志：raw 或 insight"""
        coll = self.chroma.get_or_create_collection("soulmate_memory")
        try:
            coll.add(
                documents=[content],
                metadatas=[{"type": type, "timestamp": str(time.time()), "user_id": str(user_id)}],
                ids=[str(uuid.uuid4())]
            )
            if type == "raw":
                self.update_state(user_id, {"raw_count_delta": 1})
            elif type == "insight":
                self.update_state(user_id, {"insight_count_delta": 1})
        except Exception as e:
            logger.error(f"[Memory Add Error] {e}")

    def retrieve(self, user_id, query_text, n_results=5):
        """向后兼容：保持原有 retrieve 接口"""
        return self.retrieve_insights(user_id, query_text, n_results)

    def get_raw_logs_for_consolidation(self, user_id):
        coll = self.chroma.get_or_create_collection("soulmate_memory")
        res = coll.get(where={"$and": [{"user_id": str(user_id)}, {"type": "raw"}]}, limit=15)
        return {"ids": res['ids'], "documents": res['documents']}

    def delete_logs(self, ids):
        if not ids: return
        coll = self.chroma.get_or_create_collection("soulmate_memory")
        coll.delete(ids=ids)

    def _enhance_query(self, query_text):
        """语义扩展查询"""
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

        if not enhanced:
            return ""
        return " ".join([query_text] + list(set(enhanced)))
