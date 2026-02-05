# plugins/astrbot_plugin_ai_personality/core/agent.py
# -*- coding: utf-8 -*-
"""
Sakiko Native Injection Architecture

Core Design:
- Context Middleware: Retrieve memories/persona, inject into user's message
- Handle images via MCP understand_image
- Let AstrBot's native agent handle actual LLM generation
"""
import os
import json
import datetime
import asyncio
from astrbot.api import logger

# MCP Client
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

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
        plugin_dir = getattr(config, "BASE_DIR", None) or os.getenv("PLUGIN_DIR", "/AstrBot/data")
        self.api_key = os.getenv("MINIMAX_API_KEY") or "sk-cp-你的key"
        self.host = os.getenv("MINIMAX_API_HOST", "https://api.minimaxi.com")

        # MCP server for image understanding
        self.server_params = StdioServerParameters(
            command="uvx",
            args=["minimax-coding-plan-mcp"],
            env={
                "MINIMAX_API_KEY": self.api_key,
                "MINIMAX_API_HOST": self.host,
                "PATH": os.environ.get("PATH", ""),
                "MINIMAX_MCP_BASE_PATH": "/AstrBot/data"
            }
        )

        self.memory = MemoryManager(plugin_dir)

    # ============================================================
    # MCP Tool Calls
    # ============================================================

    async def _call_mcp_tool(self, tool_name, arguments):
        """调用 MCP 工具"""
        try:
            async with stdio_client(self.server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(tool_name, arguments=arguments)
                    if result.content and hasattr(result.content[0], 'text'):
                        return result.content[0].text
                    return str(result)
        except Exception as e:
            logger.warning(f"[MCP Tool Error] {tool_name}: {e}")
            return f"（工具调用失败：{e}）"

    def _understand_image(self, image_path: str) -> str:
        """同步方式调用图像理解"""
        try:
            result = asyncio.run(self._call_mcp_tool(
                "understand_image",
                {"prompt": "Describe this image in detail.", "image_source": image_path}
            ))
            return result
        except Exception as e:
            logger.error(f"[Sakiko] Image understanding failed: {e}")
            return ""

    # ============================================================
    # Context Generation (Main Interface)
    # ============================================================

    def generate_context_string(self, user_id: str, user_name: str, text: str, image_path: str = None) -> str:
        """
        Generate injection context for AstrBot's native agent.

        Args:
            user_id: User identifier
            user_name: User name
            text: User message text
            image_path: Path to local image file (optional)

        Returns:
            Formatted context string to prepend to user's message
        """
        logger.info(f"[Sakiko] Generating context for user {user_id}, text: {text[:50] if text else '(no text)'}...")

        # === 图像理解 ===
        observation_parts = []
        if image_path:
            logger.info(f"[Sakiko] Understanding image: {image_path}")
            image_desc = self._understand_image(image_path)
            if image_desc:
                observation_parts.append(f"【视觉数据】: {image_desc}")
                logger.info(f"[Sakiko] Image description length: {len(image_desc)}")

        full_observation = "\n".join(observation_parts) if observation_parts else ""

        # === 检索记忆 ===
        search_query = text if text else "image"
        memories = self.memory.retrieve_all(user_id, search_query)
        memories["observation"] = full_observation

        # === 构建上下文 ===
        profile_summary = memories.get("profile", "（用户资料学习中...）")
        insights = memories.get("insights", [])
        insights_str = "\n".join(insights) if insights else "（暂无长期记忆）"
        recent_history = memories.get("recent_raw", "（无近期对话）")
        observation = memories.get("observation", "")

        # Build user context with observation
        user_context_parts = [USER_CONTEXT_TEMPLATE.format(
            user_profile=profile_summary,
            memories=insights_str
        )]

        if observation:
            user_context_parts.append(f"\n### Visual/Observation Data\n{observation}")

        user_context = "\n".join(user_context_parts)

        # Build full injection context
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
