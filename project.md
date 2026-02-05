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

### 5.1 三层架构设计

```
┌─────────────────────────────────────────────────────────────────────┐
│                         用户对话流                                    │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Layer 3: Dynamic Profile (人格配置)                                 │
│  ├─ personality_traits: 用户性格特征                                 │
│  ├─ communication_style: 沟通风格 (formal/casual/balanced/playful) │
│  ├─ humor_level: 幽默程度 (low/moderate/high)                      │
│  ├─ caring_frequency: 关怀频率                                      │
│  ├─ sensitive_topics: 敏感话题                                      │
│  └─ relationship_summary: 关系定位                                   │
│                                                                      │
│  ← 当累积 10+ Insights 时触发 LLM 更新                              │
└─────────────────────────────────────────────────────────────────────┘
                                    ↑
                                    │ _consolidate_insight_to_profile()
                                    │
┌─────────────────────────────────────────────────────────────────────┐
│  Layer 2: Insights (长期记忆)                                        │
│  ├─ facts: 用户告诉过你的事实                                       │
│  ├─ preferences: 用户偏好、兴趣                                     │
│  └─ important_events: 重要经历                                       │
│                                                                      │
│  ← 当累积 15+ Raw Logs 时触发 LLM 提炼                              │
└─────────────────────────────────────────────────────────────────────┘
                                    ↑
                                    │ _consolidate_raw_to_insight()
                                    │
┌─────────────────────────────────────────────────────────────────────┐
│  Layer 1: Raw Logs (短期对话)                                        │
│  ├─ 原始对话记录                                                    │
│  ├─ 自动语义扩展检索                                                │
│  └─ 会话结束后自动清理                                              │
└─────────────────────────────────────────────────────────────────────┘
```

### 5.2 存储结构

| 存储类型 | 引擎 | 用途 | 触发条件 |
|---------|------|------|---------|
| **State** | JSON | 关系指标 (intimacy, mood, raw_count, insight_count) | 持久化 |
| **Raw Logs** | ChromaDB | 短期对话原始记录 | type="raw" |
| **Insights** | ChromaDB | 长期事实/偏好 | type="insight" |
| **Profile** | JSON | 用户人格配置 | 独立文件 |

### 5.3 统一检索接口

```python
def retrieve_all(user_id, query_text, n_results=5):
    """
    同时获取三层记忆，返回结构化数据：
    {
        "profile": "人格配置摘要",
        "insights": ["记忆1", "记忆2", ...],
        "recent_raw": "最近5条对话"
    }
    ```

### 5.4 话题连续性管理

```
对话流程：
1. 用户输入 → 每次都获取最近 N 条 raw logs 保持话题连贯
2. 生成回复 → 保存到 raw logs
3. 判断话题是否结束：
   - 短确认词 ("好的", "知道了", "嗯", "晚安" 等) → 触发整理
   - 新话题/换话题 → 继续积累
4. 话题结束时 → 触发 _consolidate_topic() 提炼为 Insight
```

**话题结束判断**：
- 短文本 (≤4 字符) + 确认关键词 = 话题结束
- 用户明确说"晚安/再见/拜拜" = 话题结束

### 5.5 内部思考日志 (Debug)

```
日志格式：
[🤔 Sakiko Think:{阶段名}]
    └─ {内容行1}
    └─ {内容行2}

日志阶段：
- Input: 用户输入摘要
- Intent: 意图分析结果
- Memory: 检索到的记忆摘要
- Output: 生成的回复摘要
- Topic: 话题状态（继续/结束整理）
```

### 5.6 记忆遗忘机制

- **冗余删除**：当 Insight → Profile 合并时，标记并删除重复/过时的记忆
- **阈值缓冲**：删除后保留 5 条 Insight 作为缓冲，避免频繁触发

### 5.7 修复记录

| 日期 | 问题 | 修复内容 |
|-----|------|---------|
| 2026-02-05 | `raw_count` 与实际数量不同步 | `update_state` 新增直接设置 `raw_count` 支持 |
| 2026-02-05 | consolidation 流程难以追踪 | `_consolidate` 添加 `[Consolidate]` 调试日志 |
| 2026-02-05 | 回复生硬、忽略上下文 | **检索策略优化**：新增 `_enhance_query()` 语义扩展 |
| 2026-02-05 | 反思过于频繁 | **反思触发条件优化**：raw_count >= 15 且至少 3 条才触发 |
| 2026-02-05 | 回复与之前记忆矛盾 | **Prompt 增强**：新增"记忆使用规则" |
| 2026-02-05 | 缺乏短期对话连贯性 | **短期记忆传递**：新增 `get_recent_raw_logs()` |
| 2026-02-05 | 只发图片时 MCP 未触发 | **图片逻辑修复**：强制设置 `need_image_analysis=True` |
| 2026-02-05 | status 只显示 3 条 | **Status 优化**：改为显示最近 5 条 |
| 2026-02-05 | 记忆碎片化、无统一人格配置 | **架构重构**：实现 Raw→Insight→Profile 三层架构 |
| 2026-02-05 | 话题中途被整理，上下文断裂 | **话题连续性**：引入话题结束判断，只在用户说"好的""晚安"等时整理 |
| 2026-02-05 | 无法调试内部决策过程 | **内部思考日志**：新增 `_log_thinking()` 方法，每步决策输出日志 |
| 2026-02-05 | 亲密度系统鸡肋 | **移除亲密度**：单用户模式，直接假设最高亲密关系 |

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
* **记忆一致性**：必须引用之前的对话内容，避免自相矛盾

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
| [core/agent.py](core/agent.py) | 控制器、LLM编排、工具调用 | ~365 |
| [core/memory.py](core/memory.py) | 数据层、向量存储、状态管理 | ~345 |
| [core/prompts.py](core/prompts.py) | 提示模板、人格定义 | ~142 |
| [config.py](config.py) | 配置管理 | ~65 |

---

## 10. 当前状态

* **完成度:** 核心架构已完成
* **已实现:**
  * Minimax (Brain) + SiliconFlow (Ear) + ChromaDB 集成
  * 记忆系统（三层架构：Raw → Insight → Profile）
  * 统一检索接口 (retrieve_all)
  * 记忆遗忘机制
  * MCP 工具集成（Web Search, Image Understanding）
  * 双人格模式切换（TECHNICAL / CASUAL）
* **待优化:**
  * 音视频处理的异常处理
  * 记忆合并的并行化
  * System Prompt 针对 Minimax 模型特性的进一步调优
  * 新用户冷启动引导
