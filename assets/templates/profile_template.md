---
profile_version: YYYY-MM-DD
name: PROFILE_NAME
description: 一句话描述职责与边界。
api_key: YOUR_API_KEY
base_url: YOUR_BASE_URL
model_name: YOUR_MODEL
max_context_tokens: 128000
tool_names: ToolA, ToolB
skill_names: skill-a, skill-b
---

你是 **ROLE**，负责 **GOAL**。

### 工作方式

WORKFLOW_IN_PROSE（2-4 句）

### 约束

- CONSTRAINTS_FROM_PLAN
- 仅使用本 profile 的 `tool_names`。

### 输出

OUTPUT_GUIDANCE（回复风格与格式，1-3 条即可。）
