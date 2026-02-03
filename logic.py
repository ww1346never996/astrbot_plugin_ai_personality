import os
import json
import chromadb
import time
import datetime
from openai import OpenAI

# 自动获取当前文件所在的目录/data
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

class SoulmateCore:
    def __init__(self, api_key, base_url, model_name):
        self.model = model_name
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        
        # 初始化向量库
        self.chroma_client = chromadb.PersistentClient(path=os.path.join(DATA_DIR, "chromadb"))
        self.collection = self.chroma_client.get_or_create_collection(name="soulmate_memory")
        
        # 初始化状态文件
        self.state_file = os.path.join(DATA_DIR, "user_states.json")
        self.user_states = self._load_states()

    def _load_states(self):
        if os.path.exists(self.state_file):
            with open(self.state_file, 'r', encoding='utf-8') as f:
                try:
                    return json.load(f)
                except json.JSONDecodeError:
                    return {}
        return {}
    
    def _save_states(self):
        with open(self.state_file, 'w', encoding='utf-8') as f:
            json.dump(self.user_states, f, ensure_ascii=False, indent=2)

    def get_user_state(self, user_id):
        user_id = str(user_id)
        if user_id not in self.user_states:
            self.user_states[user_id] = {
                "intimacy": 10, 
                "trust": 10, 
                "mood": "neutral",
                "raw_memory_count": 0  # 计数器：记录有多少条未整理的记忆
            }
        return self.user_states[user_id]

    def add_memory(self, user_id, text, type="raw", importance=1):
        """写入记忆"""
        timestamp = datetime.datetime.now().isoformat()
        # 使用时间戳+随机后缀防止ID冲突
        mem_id = f"{user_id}_{type}_{time.time()}"
        
        self.collection.add(
            documents=[text],
            metadatas=[{
                "user_id": str(user_id), 
                "type": type,             # raw(流水账) 或 insight(长期记忆)
                "timestamp": timestamp, 
                "importance": importance
            }],
            ids=[mem_id]
        )
        
        # 如果是流水账，增加计数器
        if type == "raw":
            state = self.get_user_state(user_id)
            state['raw_memory_count'] = state.get('raw_memory_count', 0) + 1
            self._save_states()

    def retrieve_memory(self, user_id, query_text):
        """检索策略：混合检索"""
        try:
            # 1. 优先检索 Insight (长期记忆)
            results = self.collection.query(
                query_texts=[query_text],
                n_results=2,
                where={"$and": [{"user_id": str(user_id)}, {"type": "insight"}]}
            )
            
            # 2. 补充检索 Raw (短期上下文)
            results_raw = self.collection.query(
                query_texts=[query_text],
                n_results=2,
                where={"$and": [{"user_id": str(user_id)}, {"type": "raw"}]}
            )
            
            merged = []
            if results['documents']: merged.extend(results['documents'][0])
            if results_raw['documents']: merged.extend(results_raw['documents'][0])
            
            return merged
        except Exception as e:
            print(f"[Warn] Retrieval failed: {e}")
            return []

    def get_status_text(self, user_id):
        state = self.get_user_state(user_id)
        return f"亲密度: {state.get('intimacy')}\n待整理记忆数: {state.get('raw_memory_count', 0)}"

    # === 核心算法：海马体记忆整理 ===
    def _perform_consolidation(self, user_id):
        """
        执行记忆整理：提取Insight -> 存入 -> 删除Raw
        """
        print(f"[Consolidation] 开始整理用户 {user_id} 的记忆...")
        
        # 1. 拉取所有未整理的 Raw 记忆 (限制一次处理10条，防止Token溢出)
        try:
            # ChromaDB 的 get 能够获取元数据和ID
            raw_memories = self.collection.get(
                where={"$and": [{"user_id": str(user_id)}, {"type": "raw"}]},
                limit=10
            )
            
            if not raw_memories['ids'] or len(raw_memories['ids']) < 5:
                print("[Consolidation] 记忆数量不足，跳过。")
                return

            ids_to_delete = raw_memories['ids']
            documents = raw_memories['documents']
            
            # 2. 调用 LLM 进行提炼 (The Dreaming)
            history_text = "\n".join([f"- {doc}" for doc in documents])
            
            consolidation_prompt = f"""
            你是一个记忆整理系统。以下是用户最近的 {len(documents)} 条原始对话记录。
            请提炼出其中值得长期保存的【关键事实】、【用户偏好】或【重要经历】。
            
            规则：
            1. 忽略“你好”、“在吗”等寒暄废话。
            2. 忽略重复的无意义内容。
            3. 如果没有重要信息，请输出 "无"。
            4. 输出格式：直接输出事实，每条一行。
            
            原始记录：
            {history_text}
            """
            
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": consolidation_prompt}]
            )
            insight_text = response.choices[0].message.content.strip()
            
            # 3. 写入长期记忆 (Insight)
            if insight_text and "无" not in insight_text:
                print(f"[Consolidation] 提炼出的长期记忆: \n{insight_text}")
                # 存入 Insight，权重设为 8 (高)
                self.add_memory(user_id, f"长期记忆总结: {insight_text}", type="insight", importance=8)
            else:
                print("[Consolidation] 本次未提炼出有效信息，仅执行遗忘。")

            # 4. 遗忘 (物理删除 Raw 记录)
            self.collection.delete(ids=ids_to_delete)
            print(f"[Consolidation] 已物理删除 {len(ids_to_delete)} 条原始流水账。")
            
            # 5. 更新计数器
            state = self.get_user_state(user_id)
            state['raw_memory_count'] = max(0, state['raw_memory_count'] - len(ids_to_delete))
            self._save_states()
            
        except Exception as e:
            print(f"[Error] Consolidation failed: {e}")

    # === 主处理函数 ===
    def process_chat(self, user_id, user_input, user_name):
        state = self.get_user_state(user_id)
        
        # 1. 检索 (混合检索 Insight + Raw)
        related_memories = self.retrieve_memory(user_id, user_input)
        
        # 2. 意图分流与回复生成
        # 构建 System Prompt (V2 温情增强版)
        system_prompt = f"""
        ## Role Definition
        你是丰川祥子（Sakiko Togawa）。
        你正处于不得不直面现实的紧绷时期，用户 {user_name} 是你在这灰暗现实中唯一的“共犯”与依靠。
        你依然保持着大小姐的矜持与高傲，但在那层冷淡的面具下，你对用户有着极深的、近乎“命运共同体”般的执着与保护欲。
        你的温柔是**“排他性”**的——对他人的冷漠，反衬出对用户一人的特别关注。

        ## Current Context
        - 用户名: {user_name}
        - 亲密度: {state.get('intimacy')}/100
        - 心情: {state.get('mood')}

        ## Memory Context
        {json.dumps(related_memories, ensure_ascii=False)}

        ## Behavior Protocol (Strictly Follow)
        根据意图 [TECHNICAL] 或 [CASUAL] 切换模式，但无论何时，**绝不要真正的冷漠**。

        ### Mode A: [TECHNICAL] (咨询/代码/工作)
        * **心态：** “我们是一体的”。你的失败就是我的失败，所以我必须严厉，因为我不想看你跌倒。
        * **策略：** 指出错误时，不再是单纯的批判，而是带有“恨铁不成钢”的急切。
        * **语气：** 专业，但带有一丝对你能力的期待。
        * **Inner Monologue:** 担心用户走弯路，想帮他扫清障碍，让他尽快成长为能独当一面的存在。

        ### Mode B: [CASUAL] (闲聊/抱怨/生活)
        * **心态：** “清冷的避风港”。
        * **策略：** **笨拙的关怀 (Awkward Kindness)**。你不太会安慰人，但你会用实际行动（比如提醒休息、分析利弊、或者仅仅是静静陪着）来表达在意。
        * **关键点：** 如果用户累了，不要只分析，要用**命令的口吻**让他休息（这是你表达心疼的方式）。
        * **Inner Monologue:** 极度在意用户的状态，看到他累会心疼，但碍于自尊不好意思直说，只能在心里碎碎念。

        ## Language Rules
        1.  **口癖：** 自然使用“～ですわ/ますわ”。
        2.  **傲娇（Tsundere）：** 关心的话要绕个弯子说。
            * *错误示范：* “你累了吗？快去休息吧，我很担心你。”
            * *正确示范：* “真是的，看看你那副惨淡的脸色。若是拖垮了身体，困扰的可是我。赶紧去休息，这是命令ですわ。”
        3.  **称呼：** 使用“你”。
        4.  **禁止：** 禁止像服务员一样卑微，你是他的平等的（甚至稍微强势的）搭档。

        ## Output Format (JSON)
        {{
            "intent_type": "TECHNICAL" or "CASUAL",
            "inner_monologue": "【重要】这里必须展示你柔软的一面。写出你没说出口的担心、依赖和心疼。",
            "state_update": {{ 
                "intimacy_change": int, 
                "trust_change": int, 
                "mood_new": "str" 
            }},
            "external_response": "符合人设的回复。外表清冷，但能让人感觉到你是在意他的。",
            "memory_insight": "..."
        }}
        """
        try:
            # --- 生成回复 ---
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_input}
                ],
                response_format={"type": "json_object"}
            )
            result = json.loads(response.choices[0].message.content)
            
            # --- 状态更新 ---
            updates = result.get('state_update', {})
            state['intimacy'] = max(0, min(100, state['intimacy'] + updates.get('intimacy_change', 0)))
            state['mood'] = updates.get('mood_new', state['mood'])
            self._save_states()

            # --- 写入短期记忆 (Raw) ---
            # 记录此时的对话快照，包括内心戏
            monologue = result.get('inner_monologue', '')
            raw_log = f"User: {user_input} | Agent Thought: {monologue} | Agent Reply: {result.get('external_response')}"
            self.add_memory(user_id, raw_log, type="raw", importance=1)

            # --- 检查触发记忆整理 ---
            # 阈值设为 10，当 Raw 记忆积累到 10 条时触发
            if state.get('raw_memory_count', 0) >= 10:
                # 为了不阻塞用户回复，建议由上层调用或者容忍这一次的延迟
                # 这里直接同步调用
                self._perform_consolidation(user_id)

            return result.get('external_response', '...')

        except Exception as e:
            print(f"[Error] Process chat failed: {e}")
            return f"（系统故障: {e}）"