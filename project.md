# Project Context: AstrBot Plugin - Project Sakiko (AI Soulmate)

## 1. 项目概述

这是一个基于 **AstrBot (v3/Star)** 框架开发的 Python 插件，旨在创建一个具备**长期记忆**、**人格进化**、**多模态理解（视觉+听觉）**的高级拟人 Agent（角色：丰川祥子 / Sakiko）。

项目核心目标是实现一个“灵魂伴侣”级别的 AI，能够根据与用户的交互历史自动调整相处模式，并具备类似人类海马体的记忆整理机制。

## 2. 技术栈

* **Framework:** AstrBot (Python)
* **LLM (Brain):** Minimax (abab-6.5s-chat) via OpenAI SDK
* **STT (Ear):** SiliconFlow (SenseVoiceSmall) via OpenAI SDK
* **Database:** ChromaDB (Vector Store) + JSON (State Persistence)
* **Network:** `aiohttp` (Audio download), `openai` (API calls)
* **Deployment:** Docker

## 3. 核心架构 (MVC-like)

项目已重构为模块化结构，避免 God Class。

```text
astrbot_plugin_ai_personality/
├── main.py              # [入口/View] 事件监听、多模态提取、消息分发
├── config.py            # [配置] 统一管理配置加载与默认值
├── requirements.txt     # [依赖] chromadb, openai, aiohttp
└── core/                # [核心逻辑]
    ├── __init__.py
    ├── agent.py         # [控制器/Controller] 思考流、LLM/STT调用、调度记忆
    ├── memory.py        # [模型/Model] 数据库CRUD、状态管理、向量检索
    └── prompts.py       # [视图/Templates] System Prompts (人设、整理指令)

```

## 4. 关键逻辑与约束

### A. 记忆系统 (Memory System) - `core/memory.py`

* **存储介质：** 使用 `ChromaDB` 存储向量记忆，`JSON` 存储用户状态（亲密度、心情）和全局人格档案。
* **双层记忆：**
* `Raw`: 短期流水账（带时间戳、原始对话、内心戏）。
* `Insight`: 长期洞察（经 LLM 提炼的事实与偏好）。


* **海马体机制 (Consolidation):**
* 当 `Raw` 记忆积累 >= 10 条时触发。
* 流程：提取最近 Raw -> LLM 总结 Insight -> 写入 Insight -> **物理删除** Raw。


* **重要约束：** 所有 `user_id` 必须强制转换为 `str` 类型以防止 JSON/DB 读写不一致。

### B. 智能体逻辑 (Agent Logic) - `core/agent.py`

* **双客户端架构：**
* `self.brain`: 连接 Minimax，负责对话生成、视觉理解、记忆整理。
* `self.ear`: 连接 SiliconFlow，负责语音转文字 (STT)。


* **人格进化 (Evolution):**
* 在记忆整理阶段，LLM 会分析用户风格，生成 `evolution_instruction`（如“用户喜欢硬核技术”）。
* 该指令会被注入到下一次对话的 System Prompt 中，实现人格的动态调整。


* **多模态处理：**
* **视觉：** 接收 `main.py` 传入的图片 URL，封装为 OpenAI Vision 格式。
* **听觉：** 接收本地音频路径，调用 STT API 转文字后拼接到用户输入中。



### C. 入口处理 (Entry Logic) - `main.py`

* **职责：** 解析 `AstrBotMessage`。
* **组件提取：** 使用 `event.get_messages()` 遍历组件，识别 `Image` (URL) 和 `Record` (Audio)。
* **音频处理：** 使用 `aiohttp` 下载音频流 -> 保存为临时文件 -> 传给 Agent 转录 -> 删除临时文件。
* **异步处理：** 耗时操作（LLM/IO）使用 `asyncio.to_thread` 包装，防止阻塞 AstrBot 主线程。

### D. 配置管理 - `config.json`

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

## 5. 当前任务与待办

* **Status:** 已完成架构重构，支持 Minimax (Brain) + SiliconFlow (Ear) + ChromaDB。
* **Fixes:** 修复了 SQLite 权限问题 (Code 14) 和 `user_id` 类型问题。
* **Next Steps:**
* 微调 System Prompt 以适应 Minimax 模型特性。
* 测试在极端情况下的记忆遗忘/保留效果。
* 优化音频下载的异常处理。


