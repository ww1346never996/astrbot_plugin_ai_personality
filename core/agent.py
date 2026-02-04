# core/agent.py
# -*- coding: utf-8 -*-
import json
from openai import OpenAI
from .memory import MemoryManager
from .prompts import SAKIKO_SYSTEM_TEMPLATE, CONSOLIDATION_TEMPLATE

class SakikoAgent:
    def __init__(self, config, plugin_dir):
        self.client = OpenAI(api_key=config.api_key, base_url=config.base_url)
        self.model = config.model
        self.memory = MemoryManager(plugin_dir)

    def chat(self, user_id, user_name, text, image_urls=[]):
        # 1. 准备上下文
        state = self.memory.get_state(user_id)
        mems = self.memory.retrieve(user_id, text)
        profile = self.memory.get_profile(user_id)
        
        # 2. 构造 Prompt
        system_prompt = SAKIKO_SYSTEM_TEMPLATE.format(
            user_name=user_name,
            dynamic_profile=profile,
            intimacy=state['intimacy'],
            mood=state['mood'],
            memories=json.dumps(mems, ensure_ascii=False)
        )
        
        # 3. 构造消息体 (多模态)
        user_msg = [{"type": "text", "text": text if text else "(图片)"}]
        for url in image_urls:
            user_msg.append({"type": "image_url", "image_url": {"url": url}})

        try:
            # 4. LLM 调用
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_msg}
                ],
                response_format={"type": "json_object"}
            )
            res = json.loads(resp.choices[0].message.content)
            
            # 5. 执行副作用 (Side Effects)
            # 更新状态
            updates = res.get("state_update", {})
            self.memory.update_state(user_id, {
                "intimacy": updates.get("intimacy_change", 0),
                "mood": updates.get("mood_new", state['mood'])
            })
            
            # 存入流水账
            log = f"User: {text} | Thought: {res.get('inner_monologue')} | Reply: {res.get('external_response')}"
            self.memory.add_log(user_id, log, type="raw")
            
            # 检查整理触发
            if self.memory.get_state(user_id)['raw_count'] >= 10:
                self._consolidate(user_id)
                
            return res.get("external_response", "...")
            
        except Exception as e:
            return f"(Sakiko System Error: {str(e)})"

    def _consolidate(self, user_id):
        # 记忆整理逻辑
        raws = self.memory.get_raw_logs_for_consolidation(user_id)
        if not raws or not raws['ids']: return
        
        docs = raws['documents']
        ids = raws['ids']
        history = "\n".join([f"- {d}" for d in docs])
        
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": CONSOLIDATION_TEMPLATE.format(history_text=history)}],
                response_format={"type": "json_object"}
            )
            res = json.loads(resp.choices[0].message.content)
            
            # 存 Insight
            if res.get("insight"):
                self.memory.add_log(user_id, f"长期记忆: {res['insight']}", type="insight", importance=8)
            
            # 更新人格
            if res.get("evolution_instruction"):
                self.memory.update_profile(user_id, res['evolution_instruction'])
                
            # 删除旧记忆 & 重置计数器
            self.memory.delete_logs(ids)
            self.memory.update_state(user_id, {"raw_count_delta": -len(ids)})
            
        except Exception as e:
            print(f"Consolidation failed: {e}")

    def get_status(self, user_id):
        s = self.memory.get_state(user_id)
        return f"亲密度: {s['intimacy']}, 积压记忆: {s.get('raw_count',0)}"