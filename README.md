# quetta-agents-mcp

Claude MCP server for [Quetta Agents](https://github.com/choyunsung/quetta-agents) — smart LLM gateway with auto-routing.

Automatically routes queries to the best model:
- **Code tasks** → Gemma4 + agent-skills (plan/build/test/review/security)
- **Medical queries** → DeepSeek-R1 (clinical/diagnostic) or Claude Opus (imaging)
- **Complex multi-step** → SCION parallel multi-agent (3× Gemma4 + Claude synthesis)
- **Simple queries** → Gemma4 (local, free, fast)

---

## Installation

### One-line (recommended)

```bash
curl -fsSL https://raw.githubusercontent.com/choyunsung/quetta-agents-mcp/master/install.sh | bash
```

With custom gateway and API key:

```bash
QUETTA_GATEWAY_URL=https://rag.quetta-soft.com \
QUETTA_API_KEY=your_api_key \
bash <(curl -fsSL https://raw.githubusercontent.com/choyunsung/quetta-agents-mcp/master/install.sh)
```

The script will:
1. Install `uv` if not present
2. Add `quetta-agents` to `~/.claude/settings.json`
3. Prompt for Gateway URL and API key (if not set via env vars)

### Manual

Add to `~/.claude/settings.json`:

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

> **Local (same machine):** set `QUETTA_GATEWAY_URL=http://localhost:8701` and leave `QUETTA_API_KEY` empty.

---

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

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `QUETTA_GATEWAY_URL` | `http://localhost:8701` | Gateway API URL |
| `QUETTA_ORCHESTRATOR_URL` | `http://localhost:8700` | Orchestrator URL |
| `QUETTA_API_KEY` | _(empty)_ | API key (외부 접근 시 필수) |
| `QUETTA_TIMEOUT` | `300` | Request timeout in seconds |
