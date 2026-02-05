# Refactor Plan: Sakiko Native Injection Architecture

## 1. Context & Goal
Currently, the `SakikoAgent` initializes its own LLM client (OpenAI/MiniMax) and MCP tools to generate responses, completely bypassing AstrBot's native agent. This causes double configuration and resource waste.
**Goal:** Refactor the plugin to act as a **Context Middleware**. It should retrieve memories and persona settings, inject them into the user's message, and let AstrBot's native agent (configured in `config.yml`) generate the final response.

## 2. Architecture Change
* **Before:** `User -> Plugin (Router -> MCP -> LLM) -> Reply`
* **After:** `User -> Plugin (Retrieve Memory -> Construct Context -> Modify Event) -> AstrBot Native Agent -> Reply`

## 3. Implementation Tasks

### Task 1: Define Injection Templates
**File:** `plugins/astrbot_plugin_ai_personality/core/prompts.py`
**Action:**
1.  Create a new `INJECTION_TEMPLATE` designed to guide the native LLM.
2.  The template must explicitly tell the LLM to ignore previous instructions and adopt the Sakiko persona using the provided memory/profile.
3.  Keep the existing `SAKIKO_SYSTEM_TEMPLATE` as reference but adapt it for injection (e.g., wrap in `[System Instruction]`).

### Task 2: Refactor `SakikoAgent` (The Brain Surgery)
**File:** `plugins/astrbot_plugin_ai_personality/core/agent.py`
**Action:**
1.  **Remove:** `self.brain` (OpenAI client), `self.server_params` (MCP tools), and `_call_mcp_tool`. The plugin no longer performs generation or tool calls directly.
2.  **Keep:** `self.memory` (MemoryManager).
3.  **Modify:** Change `chat()` method to `generate_context_string(user_id, user_name, text)`.
    * This method should retrieve state/memories from `self.memory`.
    * It should format the data using `INJECTION_TEMPLATE`.
    * Return the formatted string instead of a reply.
4.  **Preserve:** Keep `_consolidate` logic if possible, or mark it for future refactoring (since we lose the raw IO logs from the plugin's perspective, consolidation might need a new trigger mechanism, but for this step, ensure the code doesn't crash).

### Task 3: Refactor `SoulmatePlugin` (The Logic Flow)
**File:** `plugins/astrbot_plugin_ai_personality/main.py`
**Action:**
1.  Modify `handle_msg`.
2.  **Remove:** The logic that calls `self.agent.chat` and `yield event.plain_result`.
3.  **Add:** Logic to call `self.agent.generate_context_string`.
4.  **Implement Injection:**
    * Construct the `full_prompt` = `injection_text` + `\n\n` + `original_text`.
    * Modify `event.message_str` (for simple text).
    * Modify `event.message_obj.message` chain: Insert a `Plain` component at index 0 with the injection text.
5.  **Critical Change:** Do **NOT** call `event.stop_event()`. Let the event propagate so AstrBot's native handler picks up the modified message.
6.  Add logging to indicate "Context Injected".

### Task 4: Cleanup & Verification
**Action:**
1.  Remove unused imports in `agent.py` (e.g., `stdio_client`, `ClientSession`).
2.  Verify `core/memory.py` is intact (it should remain mostly unchanged as it's just a data store).
3.  Ensure `core/prompts.py` has the new template.

## 4. Verification Criteria
1.  When a user sends a message, the logs should show `[Sakiko] Context Injected`.
2.  AstrBot should reply using its globally configured LLM provider.
3.  The reply should reflect Sakiko's persona (arrogant/tsundere) and reference stored memories.
4.  No "Double Reply" (Plugin reply + Native reply).