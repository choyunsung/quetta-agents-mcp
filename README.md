# quetta-agents-mcp

Claude MCP server for [Quetta Agents](https://github.com/choyunsung/quetta-agents) — smart LLM gateway with auto-routing.

Automatically routes queries to the best model:
- **Code tasks** → Gemma4 + agent-skills (plan/build/test/review/security)
- **Medical queries** → DeepSeek-R1 (clinical/diagnostic) or Claude Opus (imaging)
- **Complex multi-step** → SCION parallel multi-agent (3× Gemma4 + Claude synthesis)
- **Simple queries** → Gemma4 (local, free, fast)

## Installation

### 서버 (SSH 키 등록된 경우)

`~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "quetta-agents": {
      "command": "uvx",
      "args": ["--from", "git+ssh://git@github.com/choyunsung/quetta-agents-mcp", "quetta-agents-mcp"],
      "env": {
        "QUETTA_GATEWAY_URL": "http://localhost:8701",
        "QUETTA_ORCHESTRATOR_URL": "http://localhost:8700",
        "QUETTA_TIMEOUT": "300",
        "QUETTA_API_KEY": ""
      }
    }
  }
}
```

### 개인 PC (외부 접근)

```json
{
  "mcpServers": {
    "quetta-agents": {
      "command": "uvx",
      "args": ["--from", "git+ssh://git@github.com/choyunsung/quetta-agents-mcp", "quetta-agents-mcp"],
      "env": {
        "QUETTA_GATEWAY_URL": "https://rag.quetta-soft.com",
        "QUETTA_ORCHESTRATOR_URL": "https://rag.quetta-soft.com/orchestrator",
        "QUETTA_API_KEY": "YOUR_API_KEY",
        "QUETTA_TIMEOUT": "300"
      }
    }
  }
}
```

> SSH 키가 없는 경우 GitHub Personal Access Token 사용:  
> `git+https://TOKEN@github.com/choyunsung/quetta-agents-mcp`

## Tools

| Tool | Description |
|------|-------------|
| `quetta_ask` | Auto-route query to best model |
| `quetta_code` | Code task with 5 agent-skills injected |
| `quetta_medical` | Medical query (DeepSeek-R1 / Claude Opus) |
| `quetta_multi_agent` | Complex task via parallel SCION agents |
| `quetta_routing_info` | Preview routing decision for a query |
| `quetta_list_agents` | List registered specialist agents |
| `quetta_run_agent` | Delegate task to a specific agent |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `QUETTA_GATEWAY_URL` | `http://localhost:8701` | Gateway API URL |
| `QUETTA_ORCHESTRATOR_URL` | `http://localhost:8700` | Orchestrator URL |
| `QUETTA_API_KEY` | _(empty)_ | API key (외부 접근 시 필수) |
| `QUETTA_TIMEOUT` | `300` | Request timeout (seconds) |
