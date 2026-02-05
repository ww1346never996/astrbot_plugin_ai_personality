# plugins/astrbot_plugin_ai_personality/core/agent.py
# -*- coding: utf-8 -*-
import os
import json
import asyncio
import traceback
import re
import datetime # <--- 新增时间库
from openai import OpenAI
from astrbot.api import logger

# MCP Client
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Internal Modules
from .memory import MemoryManager
from .prompts import SAKIKO_SYSTEM_TEMPLATE, JSON_ENFORCEMENT_PROMPT, CONSOLIDATION_TEMPLATE, INTENT_ANALYSIS_PROMPT

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
        # ... (保持不变) ...
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
        # ... (保持不变) ...
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
        
        # 记忆检索
        search_query = user_input
        if intent_data.get('is_technical'): search_query += " technical"
        if observation: search_query += f" {observation[:50]}"
        mems = self.memory.retrieve(user_id, search_query)
        
        is_tech = intent_data.get('is_technical', False)
        mode_str = "TECHNICAL" if is_tech else "CASUAL"
        
        # === 修复点 1: 获取当前时间 ===
        current_time_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        try:
            # === 修复点 2: 注入时间 ===
            system_prompt = SAKIKO_SYSTEM_TEMPLATE.format(
                user_name=user_name,
                current_time=current_time_str, # <--- 注入
                mode_indicator=mode_str,
                intimacy=state['intimacy'],
                mood=state['mood'],
                memories=json.dumps(mems, ensure_ascii=False),
                observation=observation if observation else "无"
            )
        except:
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
            
            if "</think>" in content: content = content.split("</think>")[-1].strip()
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
            
            # 触发反思
            if self.memory.get_state(user_id)['raw_count'] >= 10:
                self._consolidate(user_id)
            
            return res.get("external_response")

        except Exception as e:
            logger.error(f"[Brain Error] {e}")
            return f"（思考过载）... {observation[:50]}..."

    def _consolidate(self, user_id):
        """
        === 修复点 3: 这里的 prompt 结构已修正，不会再报 400 empty content ===
        """
        raw_data = self.memory.get_raw_logs_for_consolidation(user_id)
        if not raw_data['ids']: return

        valid_docs = [doc for doc in raw_data['documents'] if doc and doc.strip()]
        if not valid_docs:
            self.memory.delete_logs(raw_data['ids'])
            return

        history = "\n".join(valid_docs)
        try:
            logger.info(f"[Sakiko Meta] 正在反思 User {user_id} 的近期交互...")
            resp = self.brain.chat.completions.create(
                model=self.brain_model,
                messages=[
                    # 关键修改：必须有 System 和 User 两条
                    {"role": "system", "content": "You are a metacognitive memory system. Always output JSON."},
                    {"role": "user", "content": CONSOLIDATION_TEMPLATE.format(history_text=history)}
                ]
            )
            content = resp.choices[0].message.content
            
            if "```json" in content: content = content.split("```json")[1].split("```")[0]
            elif "```" in content: content = content.split("```")[1].split("```")[0]
            
            import re
            json_match = re.search(r"(\{.*\})", content, re.DOTALL)
            if json_match: content = json_match.group(1)

            res = json.loads(content)
            
            if res.get("insight"):
                self.memory.add_log(user_id, f"长期记忆: {res['insight']}", type="insight")
            if res.get("evolution_instruction"):
                self.memory.update_profile(user_id, res['evolution_instruction'])
            
            # 清理旧日志并重置计数器
            self.memory.delete_logs(raw_data['ids'])
            # 强制计算新的 raw_count
            current_state = self.memory.get_state(user_id)
            new_count = max(0, current_state.get('raw_count', 0) - len(raw_data['ids']))
            self.memory.update_state(user_id, {"raw_count": new_count})
            
        except Exception as e:
            logger.error(f"[Consolidation Failed] {e}")

    def chat(self, user_id, user_name, text, image_path=None):
        # ... (chat 逻辑保持 Router 版逻辑不变) ...
        # (为了节省篇幅，这里假设 chat 方法与上一版一致，包含 _analyze_intent 等调用)
        # 只要确保上面 _synthesize_response 和 _consolidate 改了就行
        logger.info(f"[Sakiko] 收到消息: {text} | 图片: {image_path is not None}")
        
        # 过滤完全匹配 "status" 的文本，防止漏网之鱼
        if text.strip() == "status": return "（请使用 /status 查看状态）"

        analyze_text = text if text else "（用户仅发送了图片）"
        intent = self._analyze_intent(analyze_text, image_path is not None)
        
        observation_parts = []
        if intent.get("need_image_analysis") and image_path:
             vis_res = asyncio.run(self._call_mcp_tool("understand_image", {"prompt": "Analyze detail.", "image_source": image_path}))
             observation_parts.append(f"【视觉数据】: {vis_res}")

        if intent.get("need_web_search"):
            query = intent.get("search_query", text)
            if query:
                search_res = asyncio.run(self._call_mcp_tool("web_search", {"query": query}))
                observation_parts.append(f"【搜索结果】: {search_res}")
        
        full_observation = "\n".join(observation_parts)
        return self._synthesize_response(user_id, user_name, text, full_observation, intent)

    def get_status(self, user_id):
        # ... (保持上一版的轻量级实现) ...
        s = self.memory.get_state(user_id)
        evolution = self.memory.get_profile(user_id) or "默认"
        get_history_func = getattr(self.memory, "get_recent_history", None)
        memory_str = "\n".join(get_history_func(user_id, limit=3)) if get_history_func else "No Data"
        
        return f"""
📊 [Sakiko Status Panel]
------------------------
❤️ 亲密度: {s.get('intimacy', 50)}
☁️ 心情值: {s.get('mood', 'calm')}
🧠 待反思: {s.get('raw_count', 0)} / 10
⌚ 时间: {datetime.datetime.now().strftime("%H:%M")}

🧬 [Evolution]
{evolution}

📝 [Memories]
{memory_str}
"""