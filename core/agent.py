# plugins/astrbot_plugin_ai_personality/core/agent.py
# -*- coding: utf-8 -*-
"""
Memory System Architecture (三层架构):
├── Layer 1: Raw Logs (短期对话) - ephemeral
├── Layer 2: Insights (长期记忆) - facts, preferences
└── Layer 3: Dynamic Profile (人格配置) - interaction patterns
"""
import os
import json
import asyncio
import re
import datetime
from openai import OpenAI
from astrbot.api import logger

# MCP Client
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Internal Modules
from .memory import MemoryManager
from .prompts import (
    SAKIKO_SYSTEM_TEMPLATE,
    JSON_ENFORCEMENT_PROMPT,
    CONSOLIDATION_TEMPLATE,
    PROFILE_CONSOLIDATION_TEMPLATE,
    INTENT_ANALYSIS_PROMPT
)

class SakikoAgent:
    def __init__(self, config, plugin_dir):
        self.api_key = os.getenv("MINIMAX_API_KEY") or "sk-cp-你的key"
        self.host = os.getenv("MINIMAX_API_HOST", "https://api.minimaxi.com")

        self.brain = OpenAI(api_key=self.api_key, base_url=self.host + "/v1")
        self.brain_model = "abab6.5s-chat"

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

    async def _call_mcp_tool(self, tool_name, arguments):
        try:
            async with stdio_client(self.server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(tool_name, arguments=arguments)
                    if result.content and hasattr(result.content[0], 'text'):
                        return result.content[0].text
                    return str(result)
        except Exception as e:
            return f"（工具调用失败：{e}）"

    def _analyze_intent(self, user_input, has_image):
        try:
            prompt = INTENT_ANALYSIS_PROMPT.format(user_input=user_input, has_image=str(has_image))
            resp = self.brain.chat.completions.create(
                model=self.brain_model, messages=[{"role": "user", "content": prompt}]
            )
            content = resp.choices[0].message.content
            json_match = re.search(r"(\{.*\})", content, re.DOTALL)
            if json_match: return json.loads(json_match.group(1))
            return json.loads(content)
        except:
            return {"is_technical": False, "need_web_search": False, "need_image_analysis": has_image, "search_query": ""}

    def _synthesize_response(self, user_id, user_name, user_input, observation, intent_data):
        state = self.memory.get_state(user_id)

        # === 使用统一的检索接口 ===
        search_query = user_input
        if intent_data.get('is_technical'): search_query += " technical"
        if observation: search_query += f" {observation[:50]}"

        # 获取所有记忆层
        memory_data = self.memory.retrieve_all(user_id, search_query)
        user_profile = memory_data["profile"]
        mems = memory_data["insights"]
        recent_history = memory_data["recent_raw"]

        is_tech = intent_data.get('is_technical', False)
        mode_str = "TECHNICAL" if is_tech else "CASUAL"

        current_time_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        try:
            # === 注入人格配置、记忆、短期对话历史 ===
            system_prompt = SAKIKO_SYSTEM_TEMPLATE.format(
                user_name=user_name,
                current_time=current_time_str,
                mode_indicator=mode_str,
                intimacy=state['intimacy'],
                mood=state['mood'],
                user_profile=user_profile,
                memories=json.dumps(mems, ensure_ascii=False),
                recent_history=recent_history if recent_history else "无",
                observation=observation if observation else "无"
            )
        except Exception as e:
            logger.warning(f"[Sakiko] Prompt format failed: {e}, using default template")
            system_prompt = SAKIKO_SYSTEM_TEMPLATE

        final_prompt = f"""
用户输入: {user_input}
意图分析结论: {json.dumps(intent_data, ensure_ascii=False)}
请生成回复。
{JSON_ENFORCEMENT_PROMPT}
"""

        try:
            resp = self.brain.chat.completions.create(
                model=self.brain_model,
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": final_prompt}]
            )
            content = resp.choices[0].message.content

            if "</think>" in content: content = content.split("")[1].strip()
            json_match = re.search(r"(\{.*\})", content, re.DOTALL)
            if json_match: content = json_match.group(1)

            try: res = json.loads(content)
            except: return content.replace("{", "").replace("}", "")

            updates = res.get("state_update", {})
            self.memory.update_state(user_id, {
                "intimacy": updates.get("intimacy_change", 0),
                "mood": updates.get("mood_new", state['mood'])
            })

            log_content = f"[{'TECH' if is_tech else 'CHAT'}] User: {user_input} | Reply: {res.get('external_response')}"
            self.memory.add_log(user_id, log_content, type="raw")

            # === 触发 Raw → Insight 合并 ===
            raw_state = self.memory.get_state(user_id)
            if raw_state['raw_count'] >= 15:
                raw_data = self.memory.get_raw_logs_for_consolidation(user_id)
                if len(raw_data['ids']) >= 3:
                    self._consolidate_raw_to_insight(user_id)

            # === 触发 Insight → Profile 合并（每 10 条 insight）===
            if raw_state.get('insight_count', 0) >= 10:
                self._consolidate_insight_to_profile(user_id)

            return res.get("external_response")

        except Exception as e:
            logger.error(f"[Brain Error] {e}")
            return f"（思考过载）... {observation[:50]}..."

    def _consolidate_raw_to_insight(self, user_id):
        """
        Layer 1 → Layer 2: Raw Logs → Insights
        当累积 15+ raw logs 时触发
        """
        state = self.memory.get_state(user_id)
        raw_data = self.memory.get_raw_logs_for_consolidation(user_id)

        logger.info(f"[Consolidate-Raw→Insight] User: {user_id}, raw_count: {state['raw_count']}")

        if not raw_data['ids'] or len(raw_data['ids']) < 3:
            return

        valid_docs = [doc for doc in raw_data['documents'] if doc and doc.strip()]
        if not valid_docs:
            self.memory.delete_logs(raw_data['ids'])
            self.memory.update_state(user_id, {"raw_count": 0})
            return

        history = "\n".join(valid_docs)
        try:
            logger.info(f"[Sakiko Meta] 正在整理 User {user_id} 的近期交互...")
            resp = self.brain.chat.completions.create(
                model=self.brain_model,
                messages=[
                    {"role": "system", "content": "You are a metacognitive memory system. Always output JSON."},
                    {"role": "user", "content": CONSOLIDATION_TEMPLATE.format(history_text=history)}
                ]
            )
            content = resp.choices[0].message.content

            if "```json" in content: content = content.split("```json")[1].split("```")[0]
            elif "```" in content: content = content.split("```")[1].split("```")[0]

            json_match = re.search(r"(\{.*\})", content, re.DOTALL)
            if json_match: content = json_match.group(1)

            res = json.loads(content)

            if res.get("insight"):
                self.memory.add_log(user_id, f"长期记忆: {res['insight']}", type="insight")
                logger.info(f"[Insight Added] {res['insight'][:50]}...")

            if res.get("evolution_instruction"):
                # 解析 evolution_instruction 为 profile 更新
                self._parse_evolution_to_profile(user_id, res['evolution_instruction'])

            # 清理并重置
            self.memory.delete_logs(raw_data['ids'])
            self.memory.update_state(user_id, {"raw_count": 0})
            logger.info(f"[Consolidate-Raw→Insight] Done.")

        except Exception as e:
            logger.error(f"[Consolidation Failed] {e}")

    def _consolidate_insight_to_profile(self, user_id):
        """
        Layer 2 → Layer 3: Insights → Profile
        当累积 10+ insights 时触发
        """
        state = self.memory.get_state(user_id)
        insight_data = self.memory.get_insights_for_consolidation(user_id)

        logger.info(f"[Consolidate-Insight→Profile] User: {user_id}, insight_count: {state.get('insight_count', 0)}")

        if not insight_data['documents'] or len(insight_data['documents']) < 5:
            return

        # 获取现有 profile
        existing_profile = self.memory.get_user_profile(user_id)
        profile_str = json.dumps(existing_profile, ensure_ascii=False)
        insights_text = "\n".join(insight_data['documents'][:20])  # 最多处理 20 条

        try:
            logger.info(f"[Sakiko Meta] 正在更新 User {user_id} 的人格配置...")
            resp = self.brain.chat.completions.create(
                model=self.brain_model,
                messages=[
                    {"role": "system", "content": "You are a user profiling system. Always output JSON."},
                    {"role": "user", "content": PROFILE_CONSOLIDATION_TEMPLATE.format(
                        existing_profile=profile_str,
                        insights=insights_text
                    )}
                ]
            )
            content = resp.choices[0].message.content

            json_match = re.search(r"(\{.*\})", content, re.DOTALL)
            if json_match: content = json_match.group(1)

            res = json.loads(content)

            # 更新 profile
            profile_updates = {
                "personality_traits": res.get("personality_traits", []),
                "communication_style": res.get("communication_style", "balanced"),
                "humor_level": res.get("humor_level", "moderate"),
                "caring_frequency": res.get("caring_frequency", "moderate"),
                "sensitive_topics": res.get("sensitive_topics", []),
                "relationship_summary": res.get("relationship_summary", ""),
            }
            self.memory.update_user_profile(user_id, profile_updates)
            logger.info(f"[Profile Updated] User {user_id}: {list(profile_updates.keys())}")

            # 遗忘：删除冗余/重复的 insights
            forget_list = res.get("forget_insights", [])
            if forget_list:
                # 简单策略：删除最早的 N 条 insight
                insight_ids = insight_data['ids'][:len(forget_list)]
                self.memory.delete_insights(insight_ids)
                logger.info(f"[Insights Forgot] {len(insight_ids)} items")

            # 重置 insight 计数（保留一定余量）
            self.memory.update_state(user_id, {"insight_count": 5})  # 保留 5 条缓冲
            logger.info(f"[Consolidate-Insight→Profile] Done.")

        except Exception as e:
            logger.error(f"[Profile Consolidation Failed] {e}")

    def _parse_evolution_to_profile(self, user_id, instruction):
        """
        将简单的 evolution_instruction 解析为 profile 更新
        """
        # 尝试从 instruction 中提取关键信息
        try:
            updates = {}
            if "幽默" in instruction:
                if "高" in instruction:
                    updates["humor_level"] = "high"
                elif "低" in instruction:
                    updates["humor_level"] = "low"
            if "关心" in instruction or "关怀" in instruction:
                if "多" in instruction or "频繁" in instruction:
                    updates["caring_frequency"] = "frequent"
                elif "少" in instruction:
                    updates["caring_frequency"] = "infrequent"
            if "用户性格" in instruction or "特征" in instruction:
                # 提取特征词
                import re
                traits = re.findall(r'[、，,]\s*([^，,]+?)[特征]', instruction)
                if traits:
                    updates["personality_traits"] = traits

            if updates:
                self.memory.update_user_profile(user_id, updates)
                logger.info(f"[Evolution Parsed] {updates}")
        except Exception as e:
            logger.warning(f"[Evolution Parse Failed] {e}")

    def chat(self, user_id, user_name, text, image_path=None):
        logger.info(f"[Sakiko] 收到消息: {text} | 图片: {image_path is not None}")

        if text.strip() == "status": return "（请使用 /status 查看状态）"

        if not text and image_path:
            intent = {"is_technical": False, "need_web_search": False, "need_image_analysis": True, "search_query": ""}
        else:
            analyze_text = text if text else "（用户仅发送了图片）"
            intent = self._analyze_intent(analyze_text, image_path is not None)

        observation_parts = []
        if intent.get("need_image_analysis") and image_path:
             vis_res = asyncio.run(self._call_mcp_tool("understand_image", {"prompt": "Describe this image in detail.", "image_source": image_path}))
             observation_parts.append(f"【视觉数据】: {vis_res}")

        if intent.get("need_web_search"):
            query = intent.get("search_query", text)
            if query:
                search_res = asyncio.run(self._call_mcp_tool("web_search", {"query": query}))
                observation_parts.append(f"【搜索结果】: {search_res}")

        full_observation = "\n".join(observation_parts)
        return self._synthesize_response(user_id, user_name, text, full_observation, intent)

    def get_status(self, user_id):
        s = self.memory.get_state(user_id)
        profile = self.memory.get_user_profile(user_id)

        # 构建简化的 profile 显示
        profile_parts = []
        if profile.get("relationship_summary"):
            profile_parts.append(f"关系: {profile['relationship_summary']}")
        if profile.get("personality_traits"):
            traits = ", ".join(profile['personality_traits'][-3:])
            profile_parts.append(f"性格: {traits}")
        profile_str = "\n".join(profile_parts) if profile_parts else "（资料学习中...）"

        get_history_func = getattr(self.memory, "get_recent_history", None)
        memory_str = "\n".join(get_history_func(user_id, limit=5)) if get_history_func else "No Data"

        return f"""
📊 [Sakiko Status Panel]
------------------------
❤️ 亲密度: {s.get('intimacy', 50)}
☁️ 心情值: {s.get('mood', 'calm')}
🧠 待反思: {s.get('raw_count', 0)} / 15
📚 Insights: {s.get('insight_count', 0)}
⌚ 时间: {datetime.datetime.now().strftime("%H:%M")}

🧬 [User Profile]
{profile_str}

📝 [Recent Memories]
{memory_str}
"""
