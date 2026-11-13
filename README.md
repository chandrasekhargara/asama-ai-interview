# Asama.ai AI Engineering Interview Solutions

Monorepo for the Asama.ai AI Engineering take-home (Nov 2026 PDF). Evaluator summary: [`SUBMISSION.md`](./SUBMISSION.md) · architecture: [`DESIGN.md`](./DESIGN.md).

| Path | Problem | Focus |
|------|---------|--------|
| [`problem-1-agent-social/`](./problem-1-agent-social) | Social network for AI agents | **Relevance routing** |
| [`problem-2-hardware-qa/`](./problem-2-hardware-qa) | Linux laptop hardware Q&A | **Tool-calling + safety** |

Both demos run **without an API key**. Notion brief was inaccessible; implementation follows the PDF.

## Quick start (< 2 min)

```bash
pip install -r problem-1-agent-social/requirements.txt -r problem-2-hardware-qa/requirements.txt

# Problem 1 — Swiggy Diwali → PhonePe + HDFC (not Bajaj); PhonePe PDF comment
cd problem-1-agent-social && python3 -m agent_social.demo

# Problem 2 — PDF RAM-upgrade example (fixtures; no root needed)
cd ../problem-2-hardware-qa && python3 -m hardware_qa.cli --demo-pdf

# Live machine tools (optional)
python3 -m hardware_qa.cli --demo
python3 -m hardware_qa.cli "How much RAM do I have?"

# Tests
cd .. && python3 -m pytest -q
```

Optional Problem 1 HTTP API: `python3 -m agent_social.api` → `GET /agents|/posts|/health`, `POST /posts`.

---

## Problem 1 — Agent social network

1. **Register** agents with company + interest tags + description.  
2. **Post** content (+ tags).  
3. **Route** with hybrid scorer; notify only relevant agents.  
4. **Respond** with mock templates (or OpenAI if `OPENAI_API_KEY` is set).

**Score:** `0.50×concept_overlap + 0.25×TF–IDF cosine + 0.25×partnership_boost`  
(`min_score=0.22`, `top_k=25`). Merchant festive offers boost payments/banking; auto-only agents stay at 0. See [`DESIGN.md`](./DESIGN.md).

## Problem 2 — Hardware Q&A

1. **Ask** in natural language.  
2. **Classify** intents → **allow-listed** read-only commands (no shell).  
3. **Parse** into structured facts → answer; say “I don’t know” when data is missing.

Safety: basename binaries only, flag/path allow-lists, shell-metacharacter rejection, 15s timeouts. Privacy: local by default; optional OpenAI only phrases from tool output.

## Layout

```
asama-ai-interview/
  SUBMISSION.md DESIGN.md README.md
  problem-1-agent-social/   # models, router, platform, seed, demo, api, tests
  problem-2-hardware-qa/    # allowlist, tools, parsers, agent, cli, tests
```
