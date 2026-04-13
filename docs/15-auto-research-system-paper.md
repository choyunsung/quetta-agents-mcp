# An Autonomous Multi-Agent Research System with Workspace-Isolated Persistent Memory and Cross-Account Continuity

**Author:** Yunsung Cho (Quetta Soft)
**Version:** 1.0 — 2026-04-13
**Repository:** https://github.com/choyunsung/quetta-agents-mcp

## Abstract

We present the **Autonomous Research System (ARS)**, an end-to-end autonomous research environment that integrates large language model (LLM) routing, remote GPU computation, retrieval-augmented generation (RAG), and persistent multi-account memory into a single Model Context Protocol (MCP) server. **ARS itself is a research artifact** — its design, iterative debugging trace, and operational data have been version-controlled and ingested into the very knowledge base it manages, providing a meta-recursive validation of the architecture (the system documents its own development). ARS allows multiple Claude Code instances—operating across heterogeneous user accounts, operating systems, and geographic locations—to share a unified knowledge base while preserving per-account access control via workspace-level ACLs. The system has been deployed in two parallel research programs: **(1) a magnetocardiography (MCG) clinical study** comprising 5,620 recordings, 2,649 subjects, and three hospital sites, where it executed four research initiatives (RID-001~004) in parallel; and **(2) the ARS infrastructure project itself**, where the system mediated its own 14 release cycles (v0.1.0 → v0.14.1) over a single 24-hour development sprint. Empirically, we show that ARS reduces the cold-start cost of resuming long-horizon research from O(hours of human briefing) to O(seconds via `quetta_session_init`), achieves 100 % stability of WebSocket-based remote agent connections under single-worker uvicorn deployment, and supports a Nougat-OCR + Gemini-Vision + Claude-synthesis pipeline that turns arbitrary academic PDFs into RAG-ingested, queryable knowledge in a single tool call.

**Keywords:** Autonomous research, multi-agent systems, retrieval-augmented generation, MCP, persistent memory, workspace isolation, magnetocardiography.

---

## 1. Introduction

### 1.1 Two Concurrent Research Programs

ARS exists at the intersection of two research efforts that exemplify its design philosophy:

**Program A — Domain Research (MCG Clinical Study).** A 96-channel SQUID magnetocardiography study spanning three hospital sites, where the system orchestrates signal-quality analysis, preprocessing pipelines, CAD classifier training, and beat-by-beat variability extraction across thousands of recordings.

**Program B — Infrastructure Research (ARS itself).** The development of ARS is treated as a first-class research project: every architectural decision, debugging session, and trade-off is logged into the same RAG store that domain researchers use. The result is a self-documenting infrastructure where one can query "*why was uvicorn restricted to a single worker?*" and receive a citation back to the actual incident report.

This duality validates the central claim that **the cost of capturing engineering knowledge approaches zero when the engineering process itself runs through the knowledge-capturing system**. The two programs share the same Gateway, the same RAG store, the same workspace separation primitives — only the workspace tags differ (`mcg-research` vs `quetta-mcp-engineering`).

### 1.2 Friction Points in Modern AI-Assisted Research

Modern AI-assisted research workflows suffer from three persistent friction points:
1. **Session amnesia.** Each new chat loses the context, decisions, and partial results of prior sessions.
2. **Account fragmentation.** Switching between Claude Code accounts (e.g., personal vs. team, free vs. enterprise tier) breaks continuity.
3. **Tool plurality.** Routing a question between local LLMs (Gemma4, DeepSeek-R1), commercial APIs (Claude Sonnet/Opus, Gemini), and remote GPU jobs requires manual orchestration.

**ARS addresses these by:**
- **Centralizing memory** in a shared RAG store keyed by user-hashed access tokens, so any account using the same gateway sees the same accumulated knowledge.
- **Workspace ACLs** that segregate development, business, and project-specific knowledge—non-developers see only their workspace, while administrators retain unified visibility.
- **A smart dispatcher** (`quetta_auto`) that routes natural-language requests to the appropriate sub-tool (LLM model, paper analyzer, blueprint analyzer, GPU executor, etc.) using priority-ranked intent classification.
- **A reverse-WebSocket remote-agent layer** that allows GPU-bearing PCs to register with the gateway without requiring inbound port forwarding.

---

## 2. System Architecture

### 2.1 Three-Layer Topology

```
Layer 1 ── Claude Code (any account, any OS)
            │  stdio MCP
            ▼
Layer 2 ── quetta-agents-mcp (Python, uvx)
            │  HTTP/HTTPS + WebSocket
            ▼
Layer 3 ── Quetta Gateway (FastAPI)
            ├── LLM router (Ollama / Anthropic / Gemini CLI)
            ├── RAG harness (auto-inject relevant context)
            ├── Reverse-WS relay (remote GPU agents)
            ├── Workspace ACL + invite tokens
            ├── Conversation history (MongoDB)
            └── File upload (TUS protocol)
```

### 2.2 Persistence Stack

| Layer | Store | Purpose |
|------|------|------|
| Vector knowledge | Qdrant (RAG) | Semantic recall of past Q&A, papers, blueprints, notes |
| Relational | PostgreSQL | Orchestrator state, agent registry, task queue |
| Document | MongoDB | Per-conversation history with user-hash anonymization |
| Key-value | JSON files (`/data/quetta-agents/storage/`) | Workspace ACL, invite tokens, relay tokens (idempotent) |
| File blob | tusd (resumable upload) | Large papers, design files, datasets |

### 2.3 Multi-Agent Orchestration

Following the principle of cooperative specialization, ARS deploys five logical agents:

| Agent | Role | Persistence Touchpoint |
|------|------|---------------------|
| A1 | Research Initiative #1 (e.g., signal quality) | RID document + RAG ingest |
| A2 | Research Initiative #2 (e.g., preprocessing) | RID document + Knowledge Graph update |
| A3 | Research Initiative #3 (e.g., classifier) | Model checkpoint + benchmark RAG |
| A4 | Research Initiative #4 (e.g., variability) | Pipeline design + result ingest |
| A5 | State Master | Atomic state update, git commit/push, RAG sync |

Each agent operates against the same Gateway, distinguishing itself only by `X-Session-Id` and `X-Workspace` headers.

---

## 3. Methods

### 3.1 Self-Bootstrapping Protocol

At session start, each Claude Code instance is instructed (via `~/.claude/CLAUDE.md` auto-injection during install) to call:

```
quetta_session_init()
```

which atomically returns:
- The user's persisted memory entries (`source=user-memory`).
- Recent conversation context (last N Q&A from MongoDB).
- The list of currently active documents (papers, blueprints) ingested into accessible workspaces.

This single call replaces what previously required tens of manual prompt rebriefings.

### 3.2 Workspace-Isolated RAG

We define a **workspace** as a named partition of the knowledge graph. The `_pick_agent`-style routing logic inside the Gateway harness filters search results using `metadata.workspace ∈ allowedSet(user)`. The default workspaces are:

- `development` — code, architecture, troubleshooting (default for engineers)
- `business` — meeting notes, decisions, schedules (default for non-engineers)

Administrators can create arbitrary workspaces. Users issue `quetta_workspace_request(workspace, reason)` to ask for access; an admin resolves via `quetta_admin_resolve`. This ensures that a non-engineer querying "what does the system do?" never sees code-level details intended only for developers, eliminating cognitive overload.

### 3.3 Smart Dispatch via Intent Classification

`quetta_auto(request)` runs a priority-ranked keyword classifier over 13 intents:

```
memory_save → memory_recall → memory_list →
blueprint_query → blueprint_analysis →
paper_query → paper_analysis →
gpu_compute → screenshot → remote_shell →
file_analysis → medical → code → multi_agent → question
```

Each intent maps to one specialized tool call (`quetta_memory_save`, `quetta_analyze_blueprint`, `quetta_gpu_exec`, etc.). Unmatched requests fall through to `quetta_ask`, which routes via the LLM gateway to the optimal backend (Gemma4 for cheap local inference, Claude Sonnet for complex reasoning, DeepSeek-R1 for clinical questions, Gemini CLI for vision).

### 3.4 Reverse-WebSocket Remote Agents

To use GPU resources on a researcher's home or lab PC without exposing inbound ports, the agent on the GPU host opens an outbound WebSocket to `wss://gateway/agent/ws`. Critical implementation details that we discovered to be necessary for production reliability:

1. **Single uvicorn worker** — multi-worker mode caused `_agents` dict fragmentation and intermittent 50 % failure rates on GPU lookup.
2. **`stdout = open(devnull)`** — `pythonw.exe` has no console, so any `print()` raised `AttributeError` and killed the process.
3. **`stdout.reconfigure(encoding="utf-8")`** — Windows cp949 codec rejected emoji characters (`✓`, `✗`, `⚠`), causing immediate crash inside NSSM service mode.
4. **JSON-file token persistence** — install tokens stored in `/data/quetta-agents/storage/relay_tokens.json` survive container restarts.

After applying these fixes, we observed 100 % connection stability (50/50 polling success) and zero authentication failures.

### 3.5 Document Ingestion Pipeline

For academic papers, the pipeline is:

```
PDF → TUS upload → GPU agent runs nougat-OCR (LaTeX-quality math)
                 → Gemini CLI vision analysis (figures, tables)
                 → Claude Sonnet synthesizes both into Korean report
                 → All three artifacts ingested into RAG
                   (source = paper:<filename>, paper:<filename>#synthesis, paper:<filename>#gemini)
```

For engineering blueprints (mechanical, electrical, CPLD/FPGA), the pipeline substitutes Nougat with PyMuPDF vector-text extraction and uses type-specific Gemini prompts (GD&T for mechanical, single-line diagrams for electrical, RTL/FSM for digital logic).

---

## 4. Implementation

### 4.1 Quetta Agents MCP (v0.14.1)

The MCP server exposes 30+ tools across nine categories:

| Category | Tool Count | Examples |
|---------|-----------|---------|
| LLM Gateway | 7 | `quetta_ask`, `quetta_code`, `quetta_medical`, `quetta_multi_agent` |
| Smart Dispatcher | 1 | `quetta_auto` |
| Remote Control | 6 | `quetta_remote_screenshot`, `quetta_remote_shell` |
| GPU Routing | 3 | `quetta_gpu_exec`, `quetta_gpu_python`, `quetta_gpu_status` |
| Paper Analysis | 2 | `quetta_analyze_paper`, `quetta_paper_query` |
| Blueprint Analysis | 2 | `quetta_analyze_blueprint`, `quetta_blueprint_query` |
| File & RAG | 5 | `quetta_upload_file`, `quetta_analyze_file` |
| Shared Memory | 4 | `quetta_memory_save/recall/list/session_init` |
| History | 3 | `quetta_history_list/get/stats` |
| Workspaces | 6 | `quetta_workspace_list/request`, `quetta_admin_*` |
| Versioning | 2 | `quetta_version`, `quetta_update` |

### 4.2 Gateway Endpoints

REST and WebSocket surfaces are split by concern:

| Path | Purpose |
|------|---------|
| `POST /v1/chat/completions` | OpenAI-compatible LLM (with auto-routing + RAG harness) |
| `WS /agent/ws?token=…` | Reverse WebSocket from remote agents |
| `GET /agent/agents` | List connected agents |
| `POST /agent/{id}/cmd` | Send command to agent (shell, screenshot, etc.) |
| `GET /agent/install-link` | Issue 7-day installer token |
| `GET /install/config?token=…` | Resolve invite token to install config |
| `GET/POST /workspace/*` | Workspace ACL CRUD |
| `GET /history/sessions` | Conversation history (MongoDB) |
| `POST /rag/search`, `POST /rag/ingest` | Direct RAG access |

### 4.3 Distribution Mechanisms

To facilitate adoption across distributed teams, we provide three orthogonal install paths:

1. **GitHub Secret Gist** — administrator publishes config JSON as a secret Gist; installer fetches via `gh` CLI.
2. **Gateway invite token** — administrator runs `invite.sh create "username"` and shares the resulting one-line installer.
3. **Direct API key** — for headless / CI environments.

Cross-platform installers (`install.sh` for Mac/Linux, `install.ps1` for Windows; with `install-service.ps1` for NSSM-based Windows Services) ensure that the same workflow applies everywhere.

---

## 5. Case Studies

We present two case studies executed concurrently on the same ARS instance, demonstrating both **domain-research** and **infrastructure-research** modes.

### 5A. Case Study 1 — Self-Hosted Engineering of ARS Itself (Program B)

A 24-hour development sprint produced 14 release versions (v0.1.0 → v0.14.1) of the ARS infrastructure. Each release was committed across two GitHub repositories (`quetta-agents-mcp`, `quetta-agents`), and every significant decision was simultaneously ingested into the system's own RAG store with `source = user-memory`, `tags = [release-notes, build-log]`.

| Release | Capability | Trigger Event |
|---------|-----------|---------------|
| v0.7.0 | GPU auto-routing | Researcher requests `nvidia-smi` analysis |
| v0.8.0 | Smart dispatcher (`quetta_auto`) | Need for natural-language tool routing |
| v0.9.0 | Paper analyzer (Nougat) | PMB reviewer rebuttal preparation |
| v0.10.0 | RAG auto-ingestion of analyses | Knowledge persistence requirement |
| v0.12.0 | Shared memory + workspace primitives | Multi-account team scenario |
| v0.13.0 | NoSQL conversation history + invite tokens | Audit trail + access control |
| v0.13.1 | GitHub Gist installer | Frictionless team onboarding |
| v0.13.2 | Windows PowerShell installer | Cross-platform parity |
| v0.14.0 | Workspace ACL + admin tools | Engineering vs business knowledge separation |
| v0.14.1 | Windows Service mode (NSSM) | Reboot-survival requirement |

Of the 14 incidents debugged in this period, **all 14 were captured into RAG verbatim**, including their root causes and fixes:
- `OLLAMA_HOST=127.0.0.1` → `0.0.0.0:11434` (container reachability)
- `RAG harness "results" → "sources"` field-name mismatch
- `--bare` Claude CLI flag bypassing OAuth
- `pythonw stdout = None` → `AttributeError` cascade
- Windows `cp949` codec rejecting emoji
- uvicorn `--workers 2` causing `_agents` dictionary fragmentation
- nginx `/agent/` `proxy_read_timeout` insufficient for Nougat installation

These are now retrievable across all team accounts via `quetta_memory_recall`.

### 5B. Case Study 2 — MCG-DATA Clinical Research Program (Program A)

#### 5B.1 Dataset

- **5,620 recordings**, **2,649 subjects** across three hospital sites (GIL, CMCEP, Severance)
- 96-channel SQUID magnetometer (KRISS DROS), 1024 Hz, 120 s per acquisition
- Data scale: **101.8 GB NPZ cache**

#### 5B.2 Research Initiatives Executed Autonomously

| RID | Title | Status | Outcome |
|-----|-------|--------|---------|
| RID-001 | Signal Quality Census | Complete | 1,314 of 5,620 analyzed; 82.8 % usable after noise reduction |
| RID-002 | Preprocessing Pipeline Design | Complete | 6-stage pipeline validated on all 3 sites |
| RID-003 | CAD Binary Classifier Baseline | Design Complete | 2,611 subjects with LOSO validation planned |
| RID-004 | Beat-by-Beat Variability Analysis | Design Complete | Slavic R-peak + multi-channel consensus |

#### 5B.3 Knowledge Graph Insights

| ID | Insight | Impact |
|----|---------|--------|
| KI-001 | 60 Hz noise is ubiquitous across all sites | All pipelines require notch filter |
| KI-002 | Severance has heterogeneous sample rates (500/1000/1500 Hz) | Resampling required for cross-site analysis |
| KI-003 | ~1,082 CAD subjects available for ML training | Sufficient for binary classifier |
| KI-004 | GIL/CMCEP have REST+STRESS pairs | Paired ischemia analysis possible |
| KI-005 | NPZ cache covers 100 % of clinical recordings | Fast batch loading available |

#### 5B.4 Notable Empirical Result (RID-005)

A spatial-pattern analysis of T-wave morphology yielded:
- **T-wave spatial skew**: AUC 0.672 (p = 0.0002), the strongest MCG-only marker
- **T-wave spatial range/dipole**: AUC 0.630 (p = 0.005)
- **Inter-channel correlation std**: AUC 0.610 (p = 0.015)

These results were ingested verbatim into RAG and remain queryable across all team accounts.

---

## 6. Results

### 6.1 Reliability Metrics

| Metric | Pre-fix | Post-fix |
|------|---------|---------|
| Remote agent connection stability | ~50 % (worker race) | **100 % (50/50)** |
| Service-mode crash rate (Windows pythonw) | 100 % within 0.2 s | 0 % |
| RAG harness context injection | 0 chunks (field-name bug) | 4 chunks per query |
| Install-token retention across container restarts | 0 % (in-memory) | 100 % (file-persisted) |

### 6.2 Capability Comparison

| Feature | Vanilla Claude Code | ARS-augmented Claude Code |
|---------|--------------------|----------------------------|
| Cross-session memory | Limited (CLAUDE.md) | Full (RAG + MongoDB + workspaces) |
| Cross-account memory | None | Full (shared gateway) |
| Remote GPU execution | None | Reverse-WebSocket relay |
| Paper analysis | Manual context-pasting | One-tool pipeline (Nougat + Gemini + Claude) |
| Blueprint analysis | Limited vision | Type-specialized (mechanical / electrical / CPLD) |
| Workspace isolation | None | ACL-controlled |
| Conversation history | Per-session | Persistent, queryable, anonymized |

### 6.3 Adoption Friction

- **Install time** (single command, fresh machine): 2-3 minutes
- **Cross-account onboarding**: zero additional steps after install
- **Memory recall latency**: < 100 ms per `quetta_memory_recall` call
- **Paper analysis end-to-end**: 3-10 minutes (first run includes Nougat install)

---

## 7. Discussion

### 7.1 Design Trade-offs

**Single uvicorn worker vs. horizontal scaling.** We deliberately constrained the gateway to a single worker because the WebSocket relay's `_agents` dictionary is process-local. Horizontal scaling would require Redis-backed pub/sub for agent registration, which we defer to future work.

**File-based ACL vs. database ACL.** Workspace and invite tokens live in JSON files inside a mounted volume, not in PostgreSQL. This simplifies disaster recovery (one `cat workspaces.json` reveals the full ACL) at the cost of write throughput, which is negligible for a system with O(10) admin operations per day.

**Anonymization via SHA-256[:16].** Conversation histories store `user_hash` rather than raw API keys. This permits per-user analytics ("who has been most active?") while making it computationally infeasible to reverse the hash to a credential.

### 7.2 Limitations

1. The reverse-WebSocket model assumes the GPU agent has reliable outbound connectivity; agents behind strict NAT timeouts may need keep-alive tuning.
2. Workspace filtering operates client-side after RAG returns top-K results. For workspaces with sparse data, increasing `top_k` is required to compensate.
3. Gemini CLI quota (1,000 free requests/day per Google account) constrains paper-analysis throughput; commercial API key overrides are documented but not baked into the install flow.

### 7.3 Future Work

- **Horizontal scaling** of the WebSocket relay via Redis pub/sub
- **Workspace-level RAG indexing** (separate Qdrant collections) for sub-millisecond filter performance
- **Audit trail** for admin ACL changes
- **Automatic Notion synchronization** of approved research artifacts (currently manual via Outline)

---

## 8. Conclusion

ARS demonstrates that autonomous research can be made practical by colocating LLM routing, GPU access, RAG memory, and access control behind a single MCP server. The system has supported four parallel research initiatives across thousands of MCG recordings while preserving session continuity across multiple Claude Code accounts and operating systems. We release the entire stack — MCP server, gateway, install scripts (Mac, Linux, Windows), and operational documentation — under an open-source license at the URLs below, with the explicit goal of letting other research groups bootstrap an equivalent environment in a single afternoon.

---

## References & Repository Map

| Component | URL | Lines of Code (approx) |
|-----------|-----|-----|
| MCP Server | https://github.com/choyunsung/quetta-agents-mcp | ~3,500 |
| Gateway | https://github.com/choyunsung/quetta-agents | ~4,200 |
| Documentation | `docs/` (14 chapters) + `dist/quetta-agents-mcp-docs.pdf` | ~30,000 words |
| Nougat fork (academic OCR) | https://github.com/choyunsung/nougat | (upstream) |
| Install scripts | `install.sh`, `install.ps1`, `install-service.ps1`, `install-task.ps1` | — |

## Acknowledgements

Built on the shoulders of: FastAPI, uvicorn, Anthropic Claude, Google Gemini CLI, Ollama, Qdrant, MongoDB, NSSM, PyMuPDF, Meta Nougat, websockets, httpx.

---

**Document persistence record (as of build time):**
- RAG ID: `9960f007-e91a-46a3-8fbb-4b87e3148f22` (source = `user-memory`)
- Outline diary: `/doc/claude-2026-04-13-x0hOeggeNl`
- GitHub commits: spans `4e39c9d` (v0.10.0) → `f208f9b` (v0.14.1+) across two repositories.
