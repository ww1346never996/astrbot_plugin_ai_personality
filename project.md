# Project Context: AstrBot Plugin - Sakiko (AI Soulmate)

## 1. 项目概述

这是一个基于 **AstrBot (v3/Star)** 的插件，旨在创建一个具备**记忆能力**、**情感交互**、**多模态感知（视觉+语音）**的高级智能 Agent。角色名：丰川祥子 / Sakiko。

项目核心目标：实现一个能够记住用户交互历史、自动切换交流模式、具备长期记忆的智能陪伴角色。

## 2. 技术栈

* **Framework:** AstrBot (Python)
* **LLM (Brain):** Minimax (abab-6.5s-chat) via OpenAI SDK
* **STT (Ear):** SiliconFlow (SenseVoiceSmall) via OpenAI SDK
* **Database:** ChromaDB (Vector Store) + JSON (State Persistence)
* **Network:** `aiohttp` (Audio download), `httpx` (API calls)
* **Tools:** MCP (Model Context Protocol) - Web Search, Image Understanding

## 3. 项目架构 (MVC-like)

项目遵循模块化设计，避免 God Class。

```
astrbot_plugin_ai_personality/
├── main.py              # [入口/View] 事件处理、消息提取、插件注册
├── config.py            # [配置] 统一配置管理与默认值
├── requirements.txt     # [依赖] chromadb, openai, httpx, aiohttp
├── metadata.yaml        # [插件清单] 插件元信息
├── README.md            # [文档] 快速入门
├── core/                # [核心逻辑]
│   ├── __init__.py
│   ├── agent.py         # [控制器/Controller] 思维核心、LLM/STT调用、工具编排
│   ├── memory.py        # [模型/Model] 数据库CRUD、状态管理、记忆系统
│   └── prompts.py       # [视图/Templates] System Prompts (人格定义、指令模板)
```

---

## 4. 插件消息传播流程（核心）

### 4.1 消息流概览

```
┌─────────────────────────────────────────────────────────────────────┐
│                         用户消息 (通过 AstrBot)                         │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│  main.py: SoulmatePlugin.handle_msg()                               │
│  - @filter.event_message_type(EventMessageType.ALL)                │
│  - 接收 AstrMessageEvent 事件                                       │
│  - 权限检查：私聊 或 @提及                                           │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│  消息解析与预处理                                                    │
│  - event.message_str 获取文本                                        │
│  - event.get_messages() 获取组件链                                   │
│  - 下载图片/音频到临时文件                                           │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│  core/agent.py: SakikoAgent.chat()                                 │
│  - 意图分析 (TECHNICAL vs CASUAL)                                   │
│  - 工具调用 (MCP Web Search / Image Understanding)                   │
│  - 记忆检索 (MemoryManager.retrieve)                                │
│  - LLM 响应生成                                                      │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│  core/memory.py: MemoryManager                                      │
│  - 状态更新 (intimacy, mood)                                        │
│  - 记忆存储 (add_log)                                               │
│  - 记忆合并 (consolidate, 当 raw_count >= 10)                       │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│  main.py: 返回响应                                                   │
│  - event.plain_result(reply)                                       │
│  - event.stop_event()  ← 关键：阻止事件继续传播                      │
└─────────────────────────────────────────────────────────────────────┘
```

### 4.2 关键代码路径

#### 事件注册与处理 (`main.py`)

```python
@register("soulmate_agent", "YourName", "Sakiko Persona MCP", "1.4.1-final")
class SoulmatePlugin(Star):
    def __init__(self, context: Context, config: dict):
        self.context = context
        self.agent = SakikoAgent(config)

    @filter.command("status")
    async def check_status(self, event: AstrMessageEvent):
        """处理 /status 命令"""
        status = self.agent.get_status(event.get_self_id())
        yield event.plain_result(status)
        event.stop_event()  # 阻止传播

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def handle_msg(self, event: AstrMessageEvent):
        """处理所有消息类型"""
        # 权限检查：私聊 或 @提及
        is_private = event.message_type == MessageType.Private
        is_at = event.is_at(event.get_self_id())

        if not (is_private or is_at):
            return  # 忽略群聊中未@的消息

        # 提取消息内容
        text = event.message_str

        # 处理多媒体组件
        message_chain = event.get_messages()
        for component in message_chain:
            if isinstance(component, Image):
                path = await self._download_image_to_file(component.url)
            elif isinstance(component, Record):
                path = await self._download_audio_to_file(component.url)

        # 调用 Agent 处理
        response = await self.agent.chat(
            user_id=event.get_self_id(),
            user_name=event.get_sender_name(),
            message=text,
            image_path=image_path
        )

        # 返回结果
        yield event.plain_result(response)
        event.stop_event()  # 关键：阻止事件继续传播
```

#### Agent 核心逻辑 (`core/agent.py`)

```python
class SakikoAgent:
    def __init__(self, config):
        self.brain = OpenAI(...)  # Minimax LLM
        self.ear = OpenAI(...)    # SiliconFlow STT
        self.memory = MemoryManager()
        self.mcp_tools = {}       # MCP 工具映射

    async def chat(self, user_id, user_name, message, image_path=None):
        # 1. 意图分析
        intent = await self._analyze_intent(message, has_image)

        # 2. 工具调用 (MCP)
        observation = ""
        if intent.get("need_web_search"):
            observation = await self._call_mcp_tool("web_search", intent["query"])
        if intent.get("need_image_analysis"):
            observation = await self._call_mcp_tool("understand_image", image_path)

        # 3. 记忆检索
        memories = self.memory.retrieve(user_id, message)

        # 4. 构建系统提示
        system_prompt = build_system_prompt(
            user_name=user_name,
            intimacy=self.memory.get_state(user_id)["intimacy"],
            mood=self.memory.get_state(user_id)["mood"],
            memories=memories,
            mode="TECHNICAL" if intent["is_technical"] else "CASUAL"
        )

        # 5. LLM 生成响应
        response = await self._generate_response(system_prompt, message)

        # 6. 更新状态与记忆
        self.memory.update_state(user_id, intimacy_delta, mood_new)
        self.memory.add_log(user_id, message, response, type="raw")

        # 7. 记忆合并检查
        if self.memory.get_state(user_id)["raw_count"] >= 10:
            await self._consolidate(user_id)

        return response
```

---

## 5. 记忆系统架构 (`core/memory.py`)

### 5.1 存储结构

| 存储类型 | 引擎 | 用途 | 生命周期 |
|---------|------|------|---------|
| **State** | JSON | 用户关系指标 (intimacy, mood, raw_count) | 持久化 |
| **Raw Logs** | ChromaDB | 短期对话原始记录 | 合并后删除 |
| **Insights** | ChromaDB | 长期记忆 (LLM 摘要的事实、偏好、重要经历) | 持久化 |

### 5.2 记忆合并流程

```
Raw Logs (数量 >= 10)
        │
        ▼
MemoryManager.get_raw_logs_for_consolidation()
        │
        ▼
LLM 摘要 (Consolidation Template)
        │
        ▼
提取:
├─ "insight" → 存储为 type="insight"
├─ "evolution_instruction" → 更新动态人格配置
        │
        ▼
删除 Raw Logs + 重置 raw_count
```

---

## 6. 人格系统

### 6.1 角色模式

| 模式 | 触发条件 | 行为特征 |
|------|---------|---------|
| **TECHNICAL** | `is_technical=True` | 专业、严格、专注于准确性 |
| **CASUAL** | `is_technical=False` | 傲娇、温柔、间接表达关怀 |

### 6.2 人格特征

* 使用日语风格语言（~ですわ/ますわ）
* 关心用户但间接表达
* 保护性强但维护尊严
* 根据用户交互模式动态演化

---

## 7. MCP 工具集成

### 7.1 工具列表

| 工具名 | 功能 | 触发条件 |
|-------|------|---------|
| `web_search` | 网络搜索 | `need_web_search=True` |
| `understand_image` | 图片理解 | 用户发送图片 |

### 7.2 工具调用流程

```
用户输入 → 意图分析 → 需要工具? → [MCP调用] → observation → LLM合成响应
```

---

## 8. 配置文件 (`config.json`)

```json
{
    "openai_api_key": "Minimax_Key",
    "openai_base_url": "https://api.minimax.chat/v1",
    "model_name": "abab-6.5s-chat",
    "stt_api_key": "SiliconFlow_Key",
    "stt_base_url": "https://api.siliconflow.cn/v1",
    "stt_model": "FunAudioLLM/SenseVoiceSmall"
}
```

**环境变量覆盖：**
- `SAKIKO_OPENAI_KEY` / `SAKIKO_OPENAI_URL` / `SAKIKO_MODEL_NAME`
- `SAKIKO_STT_KEY` / `SAKIKO_STT_URL` / `SAKIKO_STT_MODEL`

---

## 9. 文件清单

| 文件 | 职责 | 代码行数 |
|------|------|---------|
| [main.py](main.py) | 入口、事件处理、消息提取 | ~100 |
| [core/agent.py](core/agent.py) | 控制器、LLM编排、工具调用 | ~230 |
| [core/memory.py](core/memory.py) | 数据层、向量存储、状态管理 | ~160 |
| [core/prompts.py](core/prompts.py) | 提示模板、人格定义 | ~100 |
| [config.py](config.py) | 配置管理 | ~65 |

---

## 10. 当前状态

* **完成度:** 核心架构已完成
* **已实现:**
  * Minimax (Brain) + SiliconFlow (Ear) + ChromaDB 集成
  * 记忆系统（Raw + Insight 双层）
  * MCP 工具集成（Web Search, Image Understanding）
  * 双人格模式切换（TECHNICAL / CASUAL）
* **待优化:**
  * 音视频处理的异常处理
  * 记忆合并的并行化
  * System Prompt 针对 Minimax 模型特性的进一步调优
