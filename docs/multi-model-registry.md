# Multi-Model Registry

Reference for available models, invocation patterns, and integration notes.
Used by the multi-model receptionist architecture (planned) and independent review workflows.

## Available Models

### Claude (Max subscription)

Separate rate limit pools per model tier.

| Model | ID | Invocation | Notes |
|---|---|---|---|
| Opus 4.6 | `claude-opus-4-6` | `claude --model claude-opus-4-6` | Default for Claude Code. Architecture, complex implementation, executive function. |
| Sonnet 4.6 | `claude-sonnet-4-6` | `claude --model claude-sonnet-4-6` | Mid-tier. Code work, reviews. Separate quota from Opus. |
| Haiku 4.5 | `claude-haiku-4-5-20251001` | `claude --model claude-haiku-4-5-20251001` | Fast, cheap. Triage, classification, simple lookups. |

**Integration pattern:** `claude -p PROMPT --model MODEL --output-format stream-json` for one-shot. Persistent bidirectional sessions via stdin/stdout pipes (what ChatProcessManager uses).

**API key note:** API key access provides 1M token context versions of Opus and Sonnet, but switching between API key and subscription auth requires re-login. Not dynamically switchable. Treat as a separate deployment mode, not a runtime option.

### Codex / GPT (ChatGPT Pro subscription)

| Model | ID | Invocation | Notes |
|---|---|---|---|
| GPT-5.3-Codex | `gpt-5.3-codex` | `codex exec` (default) | Latest frontier. Tunable reasoning effort. |
| GPT-5.3-Codex-Spark | `gpt-5.3-codex-spark` | `codex exec -m gpt-5.3-codex-spark` | Ultra-fast. Reports suggest poor $/useful-work ratio — test before relying on. |
| GPT-5.2-Codex | `gpt-5.2-codex` | `codex exec -m gpt-5.2-codex` | Previous frontier. |
| GPT-5.1-Codex-Max | `gpt-5.1-codex-max` | `codex exec -m gpt-5.1-codex-max` | Flagship deep reasoning. |
| GPT-5.1-Codex-Mini | `gpt-5.1-codex-mini` | `codex exec -m gpt-5.1-codex-mini` | Cheap, fast, less capable. |

**Reasoning effort:** Independent axis from model selection. Set via `-c 'reasoning_effort="LEVEL"'`.
Levels: `low`, `medium` (default), `high`, `extra_high`.

**Integration patterns:**
- One-shot: `codex exec --json "PROMPT"` — streams JSONL events, `item.completed` with `type: "agent_message"` has the response.
- Persistent: `codex mcp-server` — MCP over stdio. `codex` tool starts session (returns threadId), `codex-reply` continues it.
- Built-in review: `codex exec review` — dedicated review subcommand.

### Gemini (Google subscription)

| Model | ID | Invocation | Notes |
|---|---|---|---|
| 3.1 Pro Preview | `gemini-3.1-pro-preview` | `gemini --model gemini-3.1-pro-preview` | Latest frontier. Requires `-preview` suffix. |
| 2.5 Pro | `gemini-2.5-pro` | `gemini --model gemini-2.5-pro` | Strong reasoning, large context. |
| 3 Flash Preview | `gemini-3-flash-preview` | `gemini --model gemini-3-flash-preview` | Mid-tier fast. |
| 2.5 Flash | `gemini-2.5-flash` | `gemini --model gemini-2.5-flash` | Fast, cheap. Good for locate-mode reviews. |

**Note:** Default "auto" mode uses `gemini-2.5-flash-lite` as a utility router, then routes to a main model. Explicit `--model` bypasses the router.

**Integration patterns:**
- One-shot: `gemini -p "PROMPT" --output-format json` — single JSON blob at completion with `response` and `stats`.
- Persistent: `gemini --experimental-acp` — JSON-RPC bidirectional. Experimental but used by IDEs (Zed, JetBrains).
- No MCP server mode — Gemini consumes MCP servers but doesn't expose itself as one. Would need a wrapper.

## Capability Mapping (Observed)

From live testing and the Bedrock review portfolio findings:

| Capability | Best fit |
|---|---|
| Architecture, vision, executive function | Claude Opus |
| Spec-driven feature implementation | Codex (high effort) |
| Deep debugging | Codex (high/extra_high effort) |
| Large-scale refactoring, data organization | Gemini Pro (large context) |
| Code review (independent) | Any non-implementing model (diversity > capability) |
| Triage, classification, routing | Haiku, Flash, or Codex (low effort) |
| Locate-mode review scans | Flash models, Mini (pattern matching without reasoning) |

**Key insight from Bedrock multi-model review work:** The portfolio effect matters more than individual model capability. Different models catch different things. Multi-model agreement = high confidence. Running 3-4 complementary models covers more surface area than running the best model 4 times. The separation of implementing model and reviewing model brings a diversity benefit independent of varying capabilities.

## Rate Limit Strategy

Each provider has separate pools per model tier. Spreading work across tiers extends effective throughput:

- **Claude:** Opus, Sonnet, and Haiku have separate quotas
- **Codex:** Unclear if model variants share a pool. Test empirically.
- **Gemini:** OAuth login gives 1000 req/day. Model-level pool separation unknown.

A receptionist that routes across providers and tiers gets substantially more total throughput than using a single model.

## Subscription Limits (Feb 26, 2026)

Published limits are fuzzy — all vendors frame them as task-dependent (context size + model + reasoning depth).
Treat "messages per window" as capacity bands, not fixed quotas.

### Claude Max 20x (~$200/mo)

- **Shared bucket** across Claude apps + Claude Code
- **5-hour session reset** + **weekly limits**
- **Separate weekly pools for Opus vs all other models** — visible in Usage UI
- "20x Pro capacity per session"
- Extended thinking, big context, and tools burn quota faster
- **Extra Usage** available: pay-as-you-go API rates after hitting cap

### ChatGPT Pro ($200/mo)

Per 5-hour window (local + cloud share the same bucket):
- **Local messages:** 300–1,500 / 5h
- **Cloud tasks:** 50–400 / 5h
- **Code reviews:** 100–250 / week

Credit burn per message:
- GPT-5.3/5.2-Codex: ~5 credits/msg
- GPT-5.1-Codex-Mini: ~1 credit/msg (**4x more mileage**)
- Cloud task: ~25 credits/msg
- Code review: ~25 credits/PR

Higher reasoning effort → more output tokens (reasoning tokens billed as output) → faster cap consumption.
Spark has a separate, possibly more restrictive limit.

### Google AI Pro (~$20/mo)

- **120 requests/min**, **1,500 requests/day**
- Shared across Gemini CLI + Code Assist agent mode
- Request-based, not token-based — higher thinking increases cost/latency but not request count
- One agentic prompt can trigger multiple model requests (tool use loops)
- Preview models may have more restrictive rate limits
- 1M token context window (capability limit, separate from request quota)

### Strategic Implications

| Strategy | Benefit |
|---|---|
| Use Haiku/Sonnet for triage | Preserves Opus weekly pool for interactive work |
| Use Codex Mini for bulk | 4x mileage vs frontier Codex models |
| Use Gemini Flash for locate scans | Request-based billing, cheap per scan |
| Spread across all 3 providers | Completely independent rate limit pools |
| Separate Linux user with API key | Parallel billing context, 1M context Claude models |

### Cost Comparison: API vs Subscription for Receptionist

Rough estimate for a receptionist doing 100 triage decisions/day:

| Option | Cost | Rate limit impact |
|---|---|---|
| Haiku via Max subscription | $0 marginal | ~100 of weekly non-Opus budget |
| Gemini 2.5 Flash via Google AI Pro | $0 marginal | 100 of 1500 daily (6.7%) |
| Haiku via API key (~$0.25/MTok in, $1.25/MTok out) | ~$0.15/day | Zero impact on subscription |
| Codex Mini via Pro subscription | $0 marginal | ~100 credits of 5h budget |

At low volume, subscription models are effectively free. API billing becomes interesting at higher volumes where subscription limits are a concern, or for 1M context use cases.

## API Pricing for Non-Subscription Models (Feb 26, 2026)

For models not covered by subscriptions, or for parallel billing contexts.
All prices are $/1M tokens. Blended cost assumes 3:1 input:output ratio (0.75×In + 0.25×Out).

Reasoning-token risk: **High** = explicit thinking/reasoning modes (lots of billed reasoning tokens),
**Medium** = big/verbose models, **Low** = flash/small/controllable output.

### Cheap Candidates for Receptionist / Triage / Locate Scans

| Provider | Model | In | Out | Blended | Risk | Notes |
|---|---|---:|---:|---:|---|---|
| AWS Bedrock | Voxtral Mini 1.0 | 0.04 | 0.04 | 0.04 | Low | Cheapest option |
| Together | LFM2 24B A2B | 0.03 | 0.12 | 0.05 | Low | |
| Groq | Llama 3.1 8B Instant | 0.05 | 0.08 | 0.06 | Low | Fast inference |
| Together | Llama 3.2 3B Instruct Turbo | 0.06 | 0.06 | 0.06 | Low | |
| Together | gpt-oss-20B | 0.05 | 0.20 | 0.09 | Low | |
| AWS Bedrock | Ministral 3B 3.0 | 0.10 | 0.10 | 0.10 | Low | |
| Z.ai | GLM-4.7-FlashX (cache hit) | 0.01 | 0.40 | 0.11 | Low | Bedrock review: GLM traces logic well |
| AWS Bedrock | Ministral 8B 3.0 | 0.15 | 0.15 | 0.15 | Low | |
| Groq | Llama 4 Scout | 0.11 | 0.34 | 0.17 | Medium | |
| Together | Llama 3.1 8B | 0.18 | 0.18 | 0.18 | Low | |
| AI21 | Jamba Mini | 0.20 | 0.40 | 0.25 | Low | |

### Mid-Tier for Reviews / Implementation

| Provider | Model | In | Out | Blended | Risk | Notes |
|---|---|---:|---:|---:|---|---|
| DeepSeek | deepseek-chat (cache hit) | 0.07 | 1.10 | 0.33 | Low | Strong coder |
| Groq | Qwen3 32B | 0.29 | 0.59 | 0.37 | Low | Bedrock review: Qwen precise, zero false positives |
| Together | GLM-4.5-Air | 0.20 | 1.10 | 0.43 | Low | |
| Together | Llama 4 Maverick | 0.27 | 0.85 | 0.42 | Medium | |
| DeepSeek | deepseek-chat (cache miss) | 0.27 | 1.10 | 0.48 | Low | |
| Together | Qwen3 Next 80B A3B Instruct | 0.15 | 1.50 | 0.49 | Medium | |
| MiniMax | M2.5 | 0.30 | 1.20 | 0.53 | Low | |
| Groq | Llama 3.3 70B Versatile | 0.59 | 0.79 | 0.64 | Medium | |
| AWS Bedrock | Mistral Large 3 | 0.50 | 1.50 | 0.75 | Medium | Bedrock review: catches naming/doc symmetry |
| Together | GLM-4.7 | 0.45 | 2.00 | 0.84 | Medium | |
| Together | DeepSeek-V3.1 | 0.60 | 1.70 | 0.88 | Medium | |

### Frontier / Deep Reasoning (API alternatives to subscriptions)

| Provider | Model | In | Out | Blended | Risk | Notes |
|---|---|---:|---:|---:|---|---|
| DeepSeek | deepseek-reasoner (cache hit) | 0.14 | 2.19 | 0.65 | High | Explicit reasoning mode |
| DeepSeek | deepseek-reasoner (cache miss) | 0.55 | 2.19 | 0.96 | High | |
| AWS Bedrock | Kimi K2 Thinking | 0.60 | 2.50 | 1.08 | High | |
| AWS Bedrock | Kimi K2.5 | 0.60 | 3.00 | 1.20 | Medium | |
| Together | Kimi K2 Instruct | 1.00 | 3.00 | 1.50 | Medium | |
| Groq | Kimi K2-0905 1T | 1.00 | 3.00 | 1.50 | Medium | |
| Z.ai | GLM-5 (cache miss) | 1.00 | 3.20 | 1.55 | Medium | |
| Together | Qwen3.5-397B-A17B | 0.60 | 3.60 | 1.35 | Medium | |
| Together | DeepSeek-R1-0528 | 3.00 | 7.00 | 4.00 | High | |
| Together | Llama 3.1 405B | 3.50 | 3.50 | 3.50 | Medium | |

### Provider Notes

- **AWS Bedrock**: Also offers Priority (+75%) and Flex/Batch (−50%) multipliers vs Standard prices above.
- **DeepSeek**: Cache hit pricing is significant — 4x cheaper on input. Worth designing for cacheable prompts.
- **Z.ai (GLM)**: Cache hit pricing also dramatic. GLM-4.7-FlashX at $0.01/MTok input with cache is remarkably cheap.
- **Groq**: Fast inference, good for latency-sensitive triage. Pricing competitive on small models.
- **Together**: Broadest model selection. Good for testing many models cheaply.
- **OpenRouter**: Aggregator with routing across providers. Useful as a single integration point but adds margin.

### Auth Switching: Subscription vs API Key

| CLI | Switch to API | Switch back to subscription | Interactive step? |
|---|---|---|---|
| Claude | Set `ANTHROPIC_API_KEY` env var | Unset env var | No (if OAuth was done previously) |
| Gemini | Set `GEMINI_API_KEY` env var | Unset env var | No |
| Codex | `codex login --with-api-key` (pipe key) | Requires browser OAuth | Codex→subscription needs browser |

Separate Linux users avoid the switching problem entirely — each user has its own credential file.

## Smoke Test Results (Feb 26, 2026)

All models confirmed working with subscription auth from nexus server:

```
Claude:  Haiku, Sonnet, Opus — via ChatProcessManager (env -u CLAUDECODE)
Codex:   gpt-5.3-codex, gpt-5.1-codex-mini — via `codex exec --json`
Gemini:  gemini-3.1-pro-preview, gemini-2.5-pro, gemini-3-flash-preview, gemini-2.5-flash — via `gemini -p --output-format json`
```

Reasoning effort confirmed for Codex: `-c 'reasoning_effort="low"'` through `"extra_high"`.
