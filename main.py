# plugins/astrbot_plugin_ai_personality/main.py
# -*- coding: utf-8 -*-
"""
Sakiko Native Injection Plugin

This plugin acts as a context middleware:
1. Retrieves memories and persona settings from MemoryManager
2. Handles images via MCP understand_image
3. Injects context into the user's message
4. Let AstrBot's native agent generate the final response
"""
import os
import time
import asyncio
import aiohttp
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from astrbot.api.message_components import Plain, Image
from .config import PluginConfig
from .core.agent import SakikoAgent


@register("soulmate_agent", "YourName", "Sakiko Persona Injection", "1.5.0-native")
class SoulmatePlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.cfg = PluginConfig(self.base_dir)
        self.agent = SakikoAgent(self.cfg)

    async def _download_image_to_file(self, url):
        """下载图片到本地"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        filename = f"mcp_img_{int(time.time())}.jpg"
                        save_dir = "/AstrBot/data/mcp_temp"
                        if not os.path.exists(save_dir):
                            os.makedirs(save_dir, exist_ok=True)
                        file_path = os.path.join(save_dir, filename)
                        with open(file_path, "wb") as f:
                            f.write(data)
                        return file_path
        except Exception as e:
            logger.error(f"[Sakiko] Download Failed: {e}")
            return None

    # === Status Command ===
    @filter.command("status")
    async def check_status(self, event: AstrMessageEvent):
        if not self.agent: return
        user_id = str(event.get_sender_id())
        msg = await asyncio.to_thread(self.agent.get_status, user_id)

        # 1. 发送结果
        yield event.plain_result(msg)

        # 2. 停止事件传播，防止 handle_msg 再次处理
        event.stop_event()

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def handle_msg(self, event: AstrMessageEvent):
        if not self.agent: return
        text = event.message_str or ""
        image_path = None

        # === 提取图片 ===
        try:
            message_chain = event.get_messages()
            for component in message_chain:
                if isinstance(component, Image):
                    url = component.url or (component.file if str(component.file).startswith("http") else None)
                    if url:
                        image_path = await self._download_image_to_file(url)
        except Exception as e:
            logger.warning(f"[Sakiko] Image extraction failed: {e}")

        # === 指令过滤 ===
        if text.strip() in ["status", "/status"]:
            return

        if not text and not image_path:
            return
        if text.startswith("/"):
            return

        # === 权限检查 ===
        try:
            is_at = getattr(event, "is_at", False)
            is_private = False
            astr_type_str = str(event.message_obj.type).lower()
            if "private" in astr_type_str or "friend" in astr_type_str:
                is_private = True
            if not is_private:
                raw = getattr(event.message_obj, "raw_data", {}) or {}
                if raw.get("message_type") == "private":
                    is_private = True
            if not (is_private or is_at):
                return
        except:
            if not getattr(event, "is_at", False):
                return

        user_id = str(event.get_sender_id())
        user_name = event.get_sender_name()

        # === 生成注入上下文（包含图像说明） ===
        try:
            injection_text = await asyncio.to_thread(
                self.agent.generate_context_string,
                user_id,
                user_name,
                text,
                image_path
            )
        except Exception as e:
            logger.error(f"[Sakiko] Context generation failed: {e}")
            return

        # === 注入上下文到事件 ===
        logger.info(f"[Sakiko] Context Injected for user {user_id}")

        # 1. 修改 event.message_str (简单文本注入)
        original_text = event.message_str if event.message_str else "（用户发送了图片）"
        event.message_str = f"{injection_text}\n\n--- 用户消息 ---\n{original_text}"

        # 2. 修改消息链：在开头插入 Plain 组件
        try:
            message_chain = event.get_messages()
            if message_chain:
                # 在索引 0 插入注入文本
                injection_message = Plain(text=injection_text)
                message_chain.insert(0, injection_message)
                event.message_obj.message = message_chain
        except Exception as e:
            logger.warning(f"[Sakiko] Failed to inject into message chain: {e}")

        # 关键：不要调用 event.stop_event()
        # 让事件继续传播， AstrBot 的原生处理器会处理修改后的消息
