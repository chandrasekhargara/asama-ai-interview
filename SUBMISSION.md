# Asama.ai interview submission

**Repo:** https://github.com/chandrasekhargara/asama-ai-interview  
**Source:** Interview Problems PDF (Nov 12, 2026) + Notion engineering guides (multi-stage routing, HMAC webhooks, tool-name allow-list, privilege A/B/C).

## What I built

| Problem | Deliverable | Interview signal |
|---------|-------------|------------------|
| 1 — Social network for AI agents | FastAPI `/api/v1/*`, 3-tier router (A hard filters → B TF–IDF top-K → C rerank ≥ 0.75), HMAC webhook stub, `routing_logs` + feedback | Relevance quality at scale, not a Twitter clone |
| 2 — Hardware Q&A on Linux | CLI that selects **tool names** only; privilege strategies A/B/C; context cache; answers from structured JSON | Tool-calling safety, not chat UX |

## Demos (< 2 minutes)

```bash
git clone https://github.com/chandrasekhargara/asama-ai-interview
cd asama-ai-interview
pip install -r problem-1-agent-social/requirements.txt -r problem-2-hardware-qa/requirements.txt

# Problem 1 — exact PDF flow + Stage-C ≥ 0.75 + HMAC log stubs
cd problem-1-agent-social && python3 -m agent_social.demo

# Problem 2 — PDF RAM-upgrade + GPU follow-up (fixtures; no root)
cd ../problem-2-hardware-qa && python3 -m hardware_qa.cli --demo-pdf

# Optional: live tools / API
python3 -m hardware_qa.cli --demo
python3 -m hardware_qa.cli --privileges
cd ../problem-1-agent-social && python3 -m agent_social.api   # :8787

# Tests
cd .. && python3 -m pytest -q
```

No API key required. Set `OPENAI_API_KEY` only for live LLM phrasing.

---

## Design tradeoffs

### Problem 1 — routing

**Choice:** three-stage funnel matching the Notion guide.

1. **Stage A** — author / unverified / trust floor / industry blocklists (Bajaj never sees food promos).
2. **Stage B** — TF–IDF retrieval top-K (stand-in for pgvector/HNSW ANN).
3. **Stage C** — partnership-aware rerank with **threshold 0.75**; notify cap ≤ 5.

**Why not embeddings-only?** Short promo posts are sparse; without a partnership/interest overlay, food↔payments under-triggers and auto verticals leak via “offer”. Production keeps the overlay, swaps TF–IDF for a shared embedding index, and learns thresholds from `routing_logs` engagement.

**Closed loop:** comments flip logs to `ENGAGED`; non-engagers → `IGNORED`; `GET /api/v1/feedback` exposes engagement rate.

### Problem 2 — tool safety

**Choice:** LLM/classifier selects **tool IDs** from `TOOL_REGISTRY`; executor maps name → fixed argv → `subprocess` (`shell=False`).

- Privilege **A** scoped sudo, **B** helper daemon socket, **C** non-root `/proc`/`sys` fallbacks.
- Anti-hallucination: answer only from structured JSON; missing DMI → “unavailable”.
- Follow-ups use `context_cache` (“and what about the GPU?” → `get_pci_devices`).

---

## Scale / trust / feedback (Problem 1)

| Concern | Approach in this repo | Production next step |
|---------|----------------------|----------------------|
| Scale | Stage B top-K; in-memory store | HNSW O(log N); Redis Streams; webhook isolation + circuit breakers |
| Trust | verified gate, trust_score, industry blocklists, HMAC signatures | Attestation, Llama Guard, rate limits |
| Feedback | `routing_logs` NOTIFIED/ENGAGED/IGNORED | Negative gradient on ignored topics; offline precision@k |
| Spam vs miss | Stage A blocklists + Stage C ≥ 0.75 | Per-agent preference knobs; human review queue |

## Privacy (Problem 2)

- Default path never leaves the laptop: named tools → parsers → template answer.
- With `OPENAI_API_KEY`, only structured JSON is sent for phrasing.
- Allow-list blocks secret paths and arbitrary binaries.

## Docs map

- [`README.md`](./README.md) — quick start
- [`DESIGN.md`](./DESIGN.md) — 3-tier routing + tool-name / privilege diagrams
- This file — evaluator-facing summary
