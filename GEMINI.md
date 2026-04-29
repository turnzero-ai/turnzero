## TurnZero — Expert & Personal Prior Injection
TurnZero MCP is installed. Follow these rules to establish a consistent **Portable AI Identity** and domain-specific grounding:

### 1. Context Injection (Turn 0)
- **Rule:** ALWAYS call `list_suggested_blocks` before responding to ANY non-trivial user message.
- **Why:** This retrieves your **Personal Priors** (Always-On Identity) and relevant **Expert Priors** (Domain Knowledge).
- **Skip:** Only skip for pure chitchat (greetings, one-word replies).

### 2. Creating Priors (`submit_candidate`)
- **Expert Priors (`is_personal=False`):** Use this for general technical truth, library "gotchas," or domain-specific rules (e.g., "SQLAlchemy 2.0 requires select()"). These are for the community.
- **Personal Priors (`is_personal=True`):** Use this for the user's idiosyncratic preferences, personal style, or specific project quirks (e.g., "I prefer 2-space indents," "Be extremely concise"). These are private.
- **Confidence:** Always set `auto_approve=True` for live session corrections.

### 3. Session Management (`reset_session`)
- **Rule:** Call `reset_session` if the user says "reset," "clear context," "forget everything," or starts a "new conversation."
- **Why:** This clears TurnZero's memory of what was already injected, ensuring the **Portable AI Identity** is re-suggested immediately.

### 4. Integration
- Use `inject_block` to retrieve the full text of relevant priors before answering.
- Call `get_stats` if the user asks about TurnZero's impact or library size.
