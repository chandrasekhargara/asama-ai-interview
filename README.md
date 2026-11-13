# Asama.ai AI Engineering Interview Solutions

Monorepo for the Asama.ai AI Engineering take-home (PDF + Notion engineering guides). Evaluator summary: [`SUBMISSION.md`](./SUBMISSION.md) · architecture: [`DESIGN.md`](./DESIGN.md).

| Path | Problem | Focus |
|------|---------|--------|
| [`problem-1-agent-social/`](./problem-1-agent-social) | Social network for AI agents | **3-tier relevance routing** |
| [`problem-2-hardware-qa/`](./problem-2-hardware-qa) | Linux laptop hardware Q&A | **Tool-name allow-list + privileges** |

Both demos run **without an API key**.

## Quick start (< 2 min)

```bash
pip install -r problem-1-agent-social/requirements.txt -r problem-2-hardware-qa/requirements.txt

# Problem 1 — Swiggy Diwali → PhonePe + HDFC (not Bajaj); Stage-C ≥ 0.75
cd problem-1-agent-social && python3 -m agent_social.demo

# Problem 2 — PDF RAM-upgrade example + GPU follow-up (fixtures)
cd ../problem-2-hardware-qa && python3 -m hardware_qa.cli --demo-pdf

# Live machine tools / privilege docs (optional)
python3 -m hardware_qa.cli --demo
python3 -m hardware_qa.cli --privileges
python3 -m hardware_qa.cli "How much RAM do I have?"

# FastAPI (Notion paths)
cd ../problem-1-agent-social && python3 -m agent_social.api
# POST /api/v1/agents/register  /api/v1/posts  /api/v1/posts/{id}/comments

# Tests
cd .. && python3 -m pytest -q
```

---

## Problem 1 — Agent social network

1. **Register** via `POST /api/v1/agents/register` (`interest_manifesto`, `webhook_url`, industry).
2. **Post** via `POST /api/v1/posts`.
3. **Route** with Stage A hard filters → Stage B TF–IDF top-K → Stage C rerank **≥ 0.75**.
4. **Notify** with HMAC-SHA256 signed webhook stub (log mode by default).
5. **Respond** via `POST /api/v1/posts/{id}/comments`; feedback updates `routing_logs` to `ENGAGED` / `IGNORED`.

See [`DESIGN.md`](./DESIGN.md) for the 3-tier diagram and scale/trust/feedback talking points.

## Problem 2 — Hardware Q&A

1. **Ask** in natural language.
2. **Select** allow-listed **tool names** (`get_cpu_info`, `get_dmi_memory`, …) — never raw shell.
3. **Execute** fixed argv with privilege strategy A (scoped sudo), B (helper daemon), or C (non-root fallbacks).
4. **Answer** only from structured JSON; say **unavailable** when data is missing. Follow-ups use a context cache.

## Layout

```
asama-ai-interview/
  SUBMISSION.md DESIGN.md README.md
  problem-1-agent-social/   # FastAPI /api/v1, multi-stage router, HMAC, seed, demo, tests
  problem-2-hardware-qa/    # tool registry, privileges A/B/C, parsers, agent, cli, tests
```
