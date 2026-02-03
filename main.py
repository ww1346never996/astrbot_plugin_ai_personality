import asyncio
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger

# --- 关键修改：从 pydantic 直接导入 BaseModel 和 Field ---
from pydantic import BaseModel, Field 

from .logic import SoulmateCore

# --- 1. 定义配置模型 ---
class SoulmateConfig(BaseModel):
    openai_api_key: str = Field(default="", description="OpenAI API Key (sk-...)")
    openai_base_url: str = Field(default="https://api.openai.com/v1", description="OpenAI Base URL (如使用中转请修改)")
    model_name: str = Field(default="gpt-4o-mini", description="使用的模型名称")

# --- 2. 在注册时绑定配置模型 ---
@register("soulmate_agent", "YourName", "具备内心戏和长期记忆的拟人插件", "1.0.0", options_type=SoulmateConfig)
class SoulmatePlugin(Star):
    # AstrBot 会自动将 config 实例注入到 __init__ 中
    def __init__(self, context: Context, config: SoulmateConfig):
        super().__init__(context)
        self.config = config  # 保存配置以便后续使用
        self.core = None

    async def initialize(self):
        """初始化时将配置传给 Core"""
        if not self.config.openai_api_key:
            logger.error("[Soulmate] 未配置 API Key！插件无法工作，请在 AstrBot 配置中填写。")
            return

        logger.info(f"[Soulmate] 正在初始化... 模型: {self.config.model_name}")
        
        # 将配置传给逻辑核心
        self.core = SoulmateCore(
            api_key=self.config.openai_api_key,
            base_url=self.config.openai_base_url,
            model_name=self.config.model_name
        )
        logger.info("[Soulmate] 初始化完成")

    # --- 以下逻辑保持不变 ---

    @filter.command("status")
    async def check_status(self, event: AstrMessageEvent):
        if not self.core:
            yield event.plain_result("插件未正确初始化（请检查配置）。")
            return
        user_id = event.get_sender_id()
        status_text = self.core.get_status_text(user_id)
        yield event.plain_result(status_text)

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def handle_conversation(self, event: AstrMessageEvent):
        if not self.core:
            return
            
        message_str = event.message_str
        if message_str.startswith("/"):
            return
        if not event.is_at_or_private:
            return

        event.stop_event()
        user_id = event.get_sender_id()
        user_name = event.get_sender_name()

        # 异步调用
        reply_text = await asyncio.to_thread(
            self.core.process_chat, 
            user_id, 
            message_str, 
            user_name
        )
        yield event.plain_result(reply_text)