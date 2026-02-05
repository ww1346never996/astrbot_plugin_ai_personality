# plugins/astrbot_plugin_ai_personality/core/agent.py
# -*- coding: utf-8 -*-
"""
Memory System with Topic Continuity & Debug Logging

核心设计：
- 话题状态管理：跟踪当前话题，对话连贯
- 内部思考日志：每步决策输出日志，方便调试
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

# 话题结束关键词
TOPIC_END_KEYWORDS = [
    "好的", "知道了", "明白了", "嗯", "行", "好", "晚安", "再见",
    "拜拜", "那就这样", "就这样吧", "先去忙了"
]


class SakikoAgent:
    def __init__(self, config):
        # AstrBot 只传 Context (包含config)，从中获取 plugin_dir
        # config 保留用于兼容，但不使用（单用户模式）
        plugin_dir = getattr(config, "BASE_DIR", None) or os.getenv("PLUGIN_DIR", "/AstrBot/data")
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

    # ============================================================
    # 工具调用
    # ============================================================

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
            logger.warning(f"[MCP Tool Error] {tool_name}: {e}")
            return f"（工具调用失败：{e}）"

    # ============================================================
    # 话题状态管理
    # ============================================================

    def _is_topic_ended(self, user_input) -> bool:
        """判断话题是否结束"""
        text = user_input.strip()
        # 短确认回复 = 话题结束
        if len(text) <= 4:
            for keyword in TOPIC_END_KEYWORDS:
                if keyword in text:
                    return True
        return False

    def _should_consolidate_topic(self, user_input) -> bool:
        """判断是否应该整理当前话题（话题结束时）"""
        return self._is_topic_ended(user_input)

    # ============================================================
    # 内部思考日志
    # ============================================================

    def _log_thinking(self, stage: str, content: str):
        """输出内部思考日志"""
        logger.info(f"[🤔 Sakiko Think:{stage}]")
        for line in content.strip().split("\n"):
            logger.info(f"    └─ {line}")

    # ============================================================
    # 意图分析
    # ============================================================

    def _analyze_intent(self, user_input: str, has_image: bool) -> dict:
        try:
            prompt = INTENT_ANALYSIS_PROMPT.format(
                user_input=user_input,
                has_image=str(has_image)
            )
            resp = self.brain.chat.completions.create(
                model=self.brain_model,
                messages=[{"role": "user", "content": prompt}]
            )
            content = resp.choices[0].message.content
            json_match = re.search(r"(\{.*\})", content, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group(1))
            else:
                result = json.loads(content)

            self._log_thinking("Intent", f"Input: {user_input[:50]}... → {result}")
            return result
        except Exception as e:
            logger.warning(f"[Intent Analysis Failed] {e}")
            return {
                "is_technical": False,
                "need_web_search": False,
                "need_image_analysis": has_image,
                "search_query": ""
            }

    # ============================================================
    # 核心对话逻辑
    # ============================================================

    def _build_system_prompt(self, user_id: str, user_name: str, user_input: str,
                            intent_data: dict, memories: dict) -> str:
        """构建系统提示词（无亲密度简化版）"""
        profile = memories.get("profile", {})
        insights = memories.get("insights", [])
        recent_raw = memories.get("recent_raw", "")

        is_tech = intent_data.get('is_technical', False)
        mode_str = "TECHNICAL" if is_tech else "CASUAL"
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        try:
            prompt = SAKIKO_SYSTEM_TEMPLATE.format(
                user_name=user_name,
                current_time=current_time,
                mode_indicator=mode_str,
                user_profile=profile,
                memories=json.dumps(insights, ensure_ascii=False),
                recent_history=recent_raw if recent_raw else "无",
                observation=memories.get("observation", "无")
            )
            return prompt
        except Exception as e:
            logger.warning(f"[Prompt Build Failed] {e}")
            return SAKIKO_SYSTEM_TEMPLATE

    def _synthesize_response(self, user_id: str, user_name: str,
                             user_input: str, observation: str,
                             intent_data: dict, memories: dict) -> str:
        """生成回复（简化版：无亲密度）"""
        # 构建提示词
        system_prompt = self._build_system_prompt(user_id, user_name, user_input,
                                                   intent_data, memories)

        # 输出检索到的记忆日志
        profile = memories.get("profile", "（空）")
        insights_count = len(memories.get("insights", []))
        self._log_thinking("Memory",
                          f"Profile: {profile[:100]}...\n"
                          f"Insights: {insights_count} 条\n"
                          f"Recent Raw: {memories.get('recent_raw', '（空）')[:100]}...")

        final_prompt = f"""
用户输入: {user_input}
意图分析: {json.dumps(intent_data, ensure_ascii=False)}
请生成回复。

{JSON_ENFORCEMENT_PROMPT}
"""

        try:
            resp = self.brain.chat.completions.create(
                model=self.brain_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": final_prompt}
                ]
            )
            content = resp.choices[0].message.content

            # 提取 JSON
            if "</think>" in content:
                content = content.split("")[1].strip()
            json_match = re.search(r"(\{.*\})", content, re.DOTALL)
            if json_match:
                content = json_match.group(1)

            try:
                res = json.loads(content)
            except:
                self._log_thinking("Output", f"Non-JSON: {content[:100]}...")
                return content.replace("{", "").replace("}", "")

            # 记录思考日志
            self._log_thinking("Output",
                             f"Response: {res.get('external_response', '')[:100]}...")

            # 保存原始对话（不立即触发整理）
            log_content = f"[{'TECH' if intent_data.get('is_technical') else 'CHAT'}] User: {user_input}"
            if res.get("external_response"):
                log_content += f" | Reply: {res.get('external_response')}"
            self.memory.add_log(user_id, log_content, type="raw")

            return res.get("external_response", "")

        except Exception as e:
            logger.error(f"[Brain Error] {e}")
            return f"（思考过载）... {observation[:50]}..."

    def chat(self, user_id: str, user_name: str, text: str, image_path=None) -> str:
        """主对话入口"""
        self._log_thinking("Input", f"User: {user_name} | Text: {text[:100]}... | Image: {image_path is not None}")

        # 1. 过滤命令
        if text.strip() == "status":
            return "（请使用 /status 查看状态）"

        # 2. 意图分析
        if not text and image_path:
            intent = {
                "is_technical": False,
                "need_web_search": False,
                "need_image_analysis": True,
                "search_query": ""
            }
        else:
            analyze_text = text if text else "（用户仅发送了图片）"
            intent = self._analyze_intent(analyze_text, image_path is not None)

        # 3. 工具调用
        observation_parts = []
        if intent.get("need_image_analysis") and image_path:
            vis_res = asyncio.run(self._call_mcp_tool(
                "understand_image",
                {"prompt": "Describe this image in detail.", "image_source": image_path}
            ))
            observation_parts.append(f"【视觉数据】: {vis_res}")

        if intent.get("need_web_search"):
            query = intent.get("search_query", text)
            if query:
                search_res = asyncio.run(self._call_mcp_tool("web_search", {"query": query}))
                observation_parts.append(f"【搜索结果】: {search_res}")

        full_observation = "\n".join(observation_parts)

        # 4. 统一检索（每次都获取最近的 raw logs，保持话题连贯）
        search_query = text if text else "image"
        if intent.get('is_technical'):
            search_query += " technical"

        memories = self.memory.retrieve_all(user_id, search_query)
        memories["observation"] = full_observation

        # 5. 生成回复
        response = self._synthesize_response(user_id, user_name, text, full_observation, intent, memories)

        # 6. 检查是否应该整理话题（话题结束时）
        if self._should_consolidate_topic(text):
            self._log_thinking("Topic", "话题结束，触发整理...")
            self._consolidate_topic(user_id)
        else:
            self._log_thinking("Topic", f"话题继续 (raw_count: {self.memory.get_state(user_id).get('raw_count', 0)})")

        return response

    # ============================================================
    # 话题整理（Raw → Insight）
    # ============================================================

    def _consolidate_topic(self, user_id: str):
        """整理当前话题：将 raw logs 提炼为 insights"""
        state = self.memory.get_state(user_id)
        raw_data = self.memory.get_raw_logs_for_consolidation(user_id)

        if not raw_data['ids'] or len(raw_data['ids']) < 2:
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

            # 解析 JSON
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]

            json_match = re.search(r"(\{.*\})", content, re.DOTALL)
            if json_match:
                content = json_match.group(1)

            res = json.loads(content)

            # 保存 insight
            if res.get("insight"):
                self.memory.add_log(user_id, f"长期记忆: {res['insight']}", type="insight")
                logger.info(f"[Insight Added] {res['insight'][:100]}...")

            # 更新 profile
            if res.get("evolution_instruction"):
                self._parse_evolution_to_profile(user_id, res['evolution_instruction'])

            # 清理并重置
            self.memory.delete_logs(raw_data['ids'])
            self.memory.update_state(user_id, {"raw_count": 0})
            logger.info(f"[Topic Consolidated] {len(raw_data['ids'])} raw logs → insights")

        except Exception as e:
            logger.error(f"[Consolidation Failed] {e}")

    def _parse_evolution_to_profile(self, user_id: str, instruction: str):
        """解析 evolution instruction 为 profile 更新"""
        try:
            updates = {}
            if "幽默" in instruction:
                updates["humor_level"] = "high" if "高" in instruction else "low"
            if "关心" in instruction or "关怀" in instruction:
                updates["caring_frequency"] = "frequent" if "多" in instruction else "infrequent"

            if updates:
                self.memory.update_user_profile(user_id, updates)
                logger.info(f"[Profile Updated] {updates}")
        except Exception as e:
            logger.warning(f"[Evolution Parse Failed] {e}")

    # ============================================================
    # Insight → Profile 合并（较少触发）
    # ============================================================

    def _consolidate_insight_to_profile(self, user_id: str):
        """高级整理：将 insights 提炼为 profile"""
        state = self.memory.get_state(user_id)
        insight_data = self.memory.get_insights_for_consolidation(user_id)

        if not insight_data['documents'] or len(insight_data['documents']) < 5:
            return

        existing_profile = self.memory.get_user_profile(user_id)
        profile_str = json.dumps(existing_profile, ensure_ascii=False)
        insights_text = "\n".join(insight_data['documents'][:20])

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

            json_match = re.search(r"(\{.*\})", resp.choices[0].message.content, re.DOTALL)
            if not json_match:
                return

            res = json.loads(json_match.group(1))

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
            logger.info(f"[Profile Consolidated] {list(profile_updates.keys())}")

            # 遗忘冗余 insights
            forget_count = len(res.get("forget_insights", []))
            if forget_count > 0:
                insight_ids = insight_data['ids'][:forget_count]
                self.memory.delete_insights(insight_ids)
                logger.info(f"[Insights Forgot] {forget_count} items")

            self.memory.update_state(user_id, {"insight_count": 5})

        except Exception as e:
            logger.error(f"[Profile Consolidation Failed] {e}")

    # ============================================================
    # Status 查询
    # ============================================================

    def get_status(self, user_id: str) -> str:
        """获取状态面板（简化版：无亲密度）"""
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
