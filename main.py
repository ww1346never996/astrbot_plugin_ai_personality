# plugins/astrbot_plugin_ai_personality/main.py
# -*- coding: utf-8 -*-
import os
import time
import aiohttp
import asyncio
import traceback
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api.message_components import Image
from .config import PluginConfig
from .core.agent import SakikoAgent

@register("soulmate_agent", "YourName", "Sakiko Persona MCP", "1.4.1-final")
class SoulmatePlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.cfg = PluginConfig(self.base_dir)
        self.agent = SakikoAgent(self.cfg, self.base_dir)

    async def _download_image_to_file(self, url):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        filename = f"mcp_img_{int(time.time())}.jpg"
                        save_dir = "/AstrBot/data/mcp_temp"
                        if not os.path.exists(save_dir): os.makedirs(save_dir, exist_ok=True)
                        file_path = os.path.join(save_dir, filename)
                        with open(file_path, "wb") as f: f.write(data)
                        return file_path
        except Exception as e:
            logger.error(f"[Sakiko] Download Failed: {e}")
            return None

    # === 修改 check_status 方法 ===
    @filter.command("status")
    async def check_status(self, event: AstrMessageEvent):
        if not self.agent: return
        user_id = str(event.get_sender_id())
        msg = await asyncio.to_thread(self.agent.get_status, user_id)
        
        # 1. 发送结果
        yield event.plain_result(msg)
        
        # 2. 关键：停止事件传播，防止 handle_msg 再次处理
        event.stop_event()

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def handle_msg(self, event: AstrMessageEvent):
        if not self.agent: return
        text = event.message_str or ""
        image_path = None
        
        try:
            message_chain = event.get_messages()
            for component in message_chain:
                if isinstance(component, Image):
                    url = component.url or (component.file if str(component.file).startswith("http") else None)
                    if url: image_path = await self._download_image_to_file(url)
        except: return

        # === 增加：额外的指令过滤 ===
        # 如果用户直接发了 "/status" 但没被 command 拦截（不太可能，但以防万一）
        # 或者发了 "status"（无斜杠）
        if text.strip() in ["status", "/status"]:
            return

        if not text and not image_path: return
        if text.startswith("/"): return

        # 权限检查
        try:
            is_at = getattr(event, "is_at", False)
            is_private = False
            astr_type_str = str(event.message_obj.type).lower()
            if "private" in astr_type_str or "friend" in astr_type_str: is_private = True
            if not is_private:
                raw = getattr(event.message_obj, "raw_data", {}) or {}
                if raw.get("message_type") == "private": is_private = True
            if not (is_private or is_at): return
        except: 
            if not getattr(event, "is_at", False): return

        event.stop_event()

        user_id = str(event.get_sender_id())
        user_name = event.get_sender_name()

        reply = await asyncio.to_thread(self.agent.chat, user_id, user_name, text, image_path)
        yield event.plain_result(reply)