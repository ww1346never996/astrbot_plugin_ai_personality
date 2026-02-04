# main.py
# -*- coding: utf-8 -*-
import os
import asyncio
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from .config import PluginConfig
from .core.agent import SakikoAgent

@register("soulmate_agent", "YourName", "Sakiko Persona", "1.2.0")
class SoulmatePlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        # 1. 加载配置
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.cfg = PluginConfig(self.base_dir)
        
        # 2. 初始化大脑
        if self.cfg.api_key == "sk-xxxx":
            logger.error("请配置 OpenAI Key")
            self.agent = None
        else:
            self.agent = SakikoAgent(self.cfg, self.base_dir)

    @filter.command("status")
    async def check_status(self, event: AstrMessageEvent):
        if not self.agent: return
        user_id = str(event.get_sender_id())
        msg = await asyncio.to_thread(self.agent.get_status, user_id)
        yield event.plain_result(msg)

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def handle_msg(self, event: AstrMessageEvent):
        if not self.agent: return
        
        # ... (此处保留之前的图片提取逻辑，为了简洁略去，代码逻辑与之前一致) ...
        # 解析文本和图片
        text = event.message_str
        imgs = [] 
        # ... 遍历 event.message_obj.content 提取 image_url ...
        for component in event.message_obj.content:
             if component.type == "image" and hasattr(component, "url") and component.url:
                 imgs.append(component.url)

        # 过滤
        if not text and not imgs: return
        if text.startswith("/"): return
        is_private = event.message_obj.type == "private"
        is_at = getattr(event, "is_at", False)
        if not (is_private or is_at): return
        
        event.stop_event()
        
        # 调用核心
        reply = await asyncio.to_thread(
            self.agent.chat, 
            str(event.get_sender_id()), 
            event.get_sender_name(), 
            text, 
            imgs
        )
        yield event.plain_result(reply)