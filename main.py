import os
import json
import asyncio
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger
from .logic import SoulmateCore

# 获取插件所在目录，用于存放配置文件
PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(PLUGIN_DIR, "config.json")

# 默认配置
DEFAULT_CONFIG = {
    "openai_api_key": "sk-xxxx",
    "openai_base_url": "https://api.openai.com/v1",
    "model_name": "gpt-4o-mini"
}

@register("soulmate_agent", "YourName", "具备内心戏和长期记忆的拟人插件", "1.0.0")
class SoulmatePlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        
        # --- 手动加载配置 ---
        self.config = self._load_config()
        
        # 检查 Key 是否填写
        if self.config["openai_api_key"] == "sk-xxxx":
            logger.error("[Soulmate] ⚠️ 请打开插件目录下的 config.json 填写 OpenAI Key！")
            self.core = None
        else:
            logger.info(f"[Soulmate] 正在初始化... 模型: {self.config['model_name']}")
            try:
                self.core = SoulmateCore(
                    api_key=self.config["openai_api_key"],
                    base_url=self.config["openai_base_url"],
                    model_name=self.config["model_name"]
                )
                logger.info("[Soulmate] 初始化完成")
            except Exception as e:
                logger.error(f"[Soulmate] 初始化失败: {e}")
                self.core = None

    def _load_config(self):
        """加载或生成配置文件"""
        if not os.path.exists(CONFIG_PATH):
            # 如果不存在，生成默认配置
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_CONFIG, f, indent=4, ensure_ascii=False)
            logger.warning(f"[Soulmate] 未找到配置文件，已生成默认文件: {CONFIG_PATH}")
            return DEFAULT_CONFIG
        
        # 如果存在，读取
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"[Soulmate] 配置文件读取失败: {e}")
            return DEFAULT_CONFIG

    # --- 功能 1: 查看好感度指令 (/status) ---
    @filter.command("status")
    async def check_status(self, event: AstrMessageEvent):
        if not self.core:
            yield event.plain_result("插件未初始化，请检查 config.json 中的 API Key。")
            return
        
        user_id = event.get_sender_id()
        # 异步调用获取状态
        status_text = await asyncio.to_thread(self.core.get_status_text, user_id)
        yield event.plain_result(status_text)

    # --- 功能 2: 接管日常对话 (核心) ---
    @filter.event_message_type(filter.EventMessageType.ALL)
    async def handle_conversation(self, event: AstrMessageEvent):
        if not self.core:
            return
            
        message_str = event.message_str
        # 过滤指令
        if message_str.startswith("/") or message_str.startswith("！"):
            return
        # 仅处理私聊或@
        if not event.is_at_or_private:
            return

        # 阻断 AstrBot 默认回复
        event.stop_event()
        
        user_id = event.get_sender_id()
        user_name = event.get_sender_name()
        
        # 异步调用核心逻辑
        reply_text = await asyncio.to_thread(
            self.core.process_chat, 
            user_id, 
            message_str, 
            user_name
        )
        yield event.plain_result(reply_text)