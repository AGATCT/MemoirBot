# MemoirBot

An AI personal assistant with an automatic memory system. Supports natural language conversation and diary features, extracting user information from interactions and persisting it across sessions.

Architecture inspired by Claude Code's memory system design.

## Memory System

The memory system operates through a three-layer Agent collaboration:

**Write** — ExtractionAgent triggers every few conversation rounds, reusing chat context prefixes to extract structured memories from new messages, writing them to Markdown files and updating the MEMORY.md index. Five memory types cover user information, behavioral guidance, events, state, and external references.

**Recall** — The MEMORY.md index is directly injected into the system prompt. Agents have tools to search and read memory files, autonomously deciding when and what to retrieve during conversations without external pre-filtering.

**Maintain** — DreamAgent runs periodically, reading all memories to merge duplicates and clean up outdated information. Trigger conditions are controlled via time gating, session gating, and file locking. SessionMemoryAgent maintains session notes for context compression during long conversations.

Chat requests and extraction requests share the same tools and message prefix to maintain API cache hits. All data is stored as plain files in the `data/` directory.

## Quick Start

```bash
pip install -r requirements.txt
cp .env.example .env        # fill in DEEPSEEK_API_KEY
uvicorn app.main:app --reload
```

Visit `http://localhost:8000`

## Configuration

| Environment Variable     | Default           | Description              |
| ------------------------ | ----------------- | ------------------------ |
| `DEEPSEEK_API_KEY`     | —                | DeepSeek API Key         |
| `LLM_MODEL`            | `deepseek-chat` | Model name               |
| `EXTRACTION_INTERVAL`  | `3`             | Memory extraction interval (conversation rounds) |
| `DREAM_INTERVAL_HOURS` | `24`            | Memory consolidation interval |
| `DREAM_MIN_SESSIONS`   | `5`             | Min sessions for consolidation |

---

# MemoirBot

具备自动记忆系统的 AI 个人助手。支持自然语言对话和日记功能，能够从交互中提取用户信息并跨会话持久化。

架构参考 Claude Code 的记忆系统设计。

## 记忆系统

记忆系统通过三层 Agent 协作运行：

**写入** — ExtractionAgent 每数轮对话后触发，复用聊天上下文前缀，从新增消息中提取结构化记忆，写入 Markdown 文件并更新 MEMORY.md 索引。五种记忆类型覆盖用户信息、行为指引、事件、状态和外部参考。

**召回** — MEMORY.md 索引直接注入 system prompt，agent 具备搜索和读取记忆文件的工具，在对话中自主决定何时检索、检索什么，无需外部预筛选。

**维护** — DreamAgent 定时运行，通读全部记忆，合并重复条目，清理过时信息。通过时间门控、会话门控和文件锁三道机制控制触发条件。SessionMemoryAgent 维护会话笔记，用于长对话的上下文压缩。

聊天请求与提取请求共享相同的 tools 和消息前缀，以维持 API 缓存命中。所有数据以纯文件形式存储于 `data/` 目录。

## 快速开始

```bash
pip install -r requirements.txt
cp .env.example .env        # 填入 DEEPSEEK_API_KEY
uvicorn app.main:app --reload
```

访问 `http://localhost:8000`

## 配置

| 环境变量                 | 默认值            | 说明                     |
| ------------------------ | ----------------- | ------------------------ |
| `DEEPSEEK_API_KEY`     | —                | DeepSeek API Key         |
| `LLM_MODEL`            | `deepseek-chat` | 模型名称                 |
| `EXTRACTION_INTERVAL`  | `3`             | 记忆提取间隔（对话轮数） |
| `DREAM_INTERVAL_HOURS` | `24`            | 记忆整理间隔             |
| `DREAM_MIN_SESSIONS`   | `5`             | 整理所需最少会话数       |
