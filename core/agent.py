# plugins/astrbot_plugin_ai_personality/core/agent.py
# -*- coding: utf-8 -*-
"""
Sakiko Native Injection Architecture

Core Design:
- Context Middleware: Retrieve memories/persona, inject into user's message
- Let AstrBot's native agent handle actual LLM generation
- No duplicate LLM configuration
"""
import os
import json
import datetime
from astrbot.api import logger

# Internal Modules
from .memory import MemoryManager
from .prompts import (
    INJECTION_TEMPLATE,
    USER_CONTEXT_TEMPLATE
)

# Topic end keywords
TOPIC_END_KEYWORDS = [
    "好的", "知道了", "明白了", "嗯", "行", "好", "晚安", "再见",
    "拜拜", "那就这样", "就这样吧", "先去忙了"
]


class SakikoAgent:
    def __init__(self, config):
        # config保留用于兼容，但不再初始化自己的LLM
        plugin_dir = getattr(config, "BASE_DIR", None) or os.getenv("PLUGIN_DIR", "/AstrBot/data")
        self.memory = MemoryManager(plugin_dir)

    # ============================================================
    # Context Generation (Main Interface)
    # ============================================================

    def generate_context_string(self, user_id: str, user_name: str, text: str) -> str:
        """
        Generate injection context for AstrBot's native agent.

        Returns:
            Formatted context string to prepend to user's message
        """
        logger.info(f"[Sakiko] Generating context for user {user_id}, text: {text[:50]}...")

        # Retrieve memories and profile
        memories = self.memory.retrieve_all(user_id, text or "chat")

        profile_summary = memories.get("profile", "（用户资料学习中...）")
        insights = memories.get("insights", [])
        insights_str = "\n".join(insights) if insights else "（暂无长期记忆）"
        recent_history = memories.get("recent_raw", "（无近期对话）")

        # Build user context
        user_context = USER_CONTEXT_TEMPLATE.format(
            user_profile=profile_summary,
            memories=insights_str
        )

        # Build full injection context
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        injection_text = INJECTION_TEMPLATE.format(
            user_context=user_context,
            recent_history=recent_history
        )

        logger.info(f"[Sakiko] Context generated, length: {len(injection_text)} chars")

        return injection_text

    # ============================================================
    # Logging Helper
    # ============================================================

    def _log(self, stage: str, content: str):
        """Output internal thinking log"""
        logger.info(f"[Sakiko {stage}] {content}")

    # ============================================================
    # Topic Management (Preserved for future refactoring)
    # ============================================================

    def _is_topic_ended(self, user_input) -> bool:
        """判断话题是否结束"""
        text = user_input.strip()
        if len(text) <= 4:
            for keyword in TOPIC_END_KEYWORDS:
                if keyword in text:
                    return True
        return False

    def _should_consolidate_topic(self, user_input) -> bool:
        """判断是否应该整理当前话题（话题结束时）"""
        return self._is_topic_ended(user_input)

    # Note: _consolidate_topic and related methods are disabled in this version
    # because we no longer have the LLM brain. They are kept for future
    # refactoring when a consolidation trigger mechanism is implemented.

    def _consolidate_topic(self, user_id: str):
        """Disabled: No LLM brain available for consolidation"""
        self._log("Topic", "Consolidation disabled in native injection mode")

    # ============================================================
    # Status Query (Preserved)
    # ============================================================

    def get_status(self, user_id: str) -> str:
        """获取状态面板"""
        s = self.memory.get_state(user_id)
        profile = self.memory.get_user_profile(user_id)

        # 构建 profile 显示
        profile_parts = []
        if profile.get("relationship_summary"):
            profile_parts.append(f"关系: {profile['relationship_summary']}")
        if profile.get("personality_traits"):
            profile_parts.append(f"性格: {', '.join(profile['personality_traits'][-3:])}")

        get_history = getattr(self.memory, "get_recent_history", None)
        memory_str = "\n".join(get_history(user_id, limit=5)) if get_history else "No Data"

        return f"""
📊 [Sakiko Status Panel]
------------------------
🧠 待整理: {s.get('raw_count', 0)}
📚 Insights: {s.get('insight_count', 0)}
⌚ 时间: {datetime.datetime.now().strftime("%H:%M")}

🧬 [User Profile]
{chr(10).join(profile_parts) if profile_parts else '（资料学习中...）'}

📝 [Recent Memories]
{memory_str}
"""
