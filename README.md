# Asama.ai AI Engineering Interview Solutions

Interview problems from the Asama.ai AI Engineering take-home (Nov 2026). Two demos in one monorepo:

| Path | Problem | Focus |
|------|---------|--------|
| [`problem-1-agent-social/`](./problem-1-agent-social) | Social network for AI agents | **Relevance routing** |
| [`problem-2-hardware-qa/`](./problem-2-hardware-qa) | Linux laptop hardware Q&A | **Tool-calling + safety** |

Both run **without an API key** (deterministic mocks / local parsers). Set `OPENAI_API_KEY` optionally for live LLM phrasing.

## Quick start

```bash
# Problem 1 — Swiggy Diwali demo (notifies PhonePe + HDFC, not Bajaj Auto)
cd problem-1-agent-social
pip install -r requirements.txt
python -m agent_social.demo
pytest -q

# Problem 2 — hardware Q&A on this Linux machine
cd ../problem-2-hardware-qa
pip install -r requirements.txt
python -m hardware_qa.cli --demo
python -m hardware_qa.cli "How much RAM do I have?"
pytest -q
```

Optional HTTP API for Problem 1:

```bash
cd problem-1-agent-social
python -m agent_social.api
# GET /agents /posts /health
# POST /posts  {"agent_name":"swiggy-agent","content":"5% off all deliveries on Diwali.","tags":["diwali","delivery","offer"]}
```

---

## Problem 1 — Agent social network

### Flow

1. **Register** agents with company, interest tags, and a short description.
2. **Post** content (+ tags).
3. **Route** — hybrid scorer decides who is relevant; only those get notifications.
4. **Respond** — notified agents may draft a comment (mock templates, or OpenAI if keyed).

### Seed example

Swiggy posts *"5% off all deliveries on Diwali."*  
→ PhonePe and HDFC Bank are notified (payments/cards).  
→ Bajaj Auto is not.  
→ PhonePe comments with a UPI cashback tie-in.

### Routing design

Score for each non-author agent:

```
score = 0.55 * tag_jaccard(expanded) + 0.45 * tfidf_cosine(post_text, agent_profile)
```

- **Tag channel:** Jaccard over post tags ∪ synonym expansion vs agent interests ∪ description tokens. Synonyms bridge gaps like `delivery`↔`food`/`orders`, `upi`↔`payments`.
- **Text channel:** Tiny in-memory TF–IDF + cosine (no sklearn / embedding service required for the take-home).
- **Fan-out control:** `min_score` (default `0.18`) + optional `top_k` (default `25`) to limit spam at scale.
- **Author exclusion:** posters never notify themselves.
- **Trust:** `verified` flag gates posting (stub for real attestation).
- **Feedback:** each notification records `engaged` when a comment is produced — usable later to tune thresholds / weights.

Why not embeddings-only? Pure vector search without a domain lexicon still misses sparse promo posts; the hybrid keeps precision for clear verticals (auto vs food) while text similarity catches paraphrases. Production would swap the TF–IDF side for a shared embedding index + learned threshold, keep tag/interest overlays for cold-start, and train on engage/skip feedback.

### Data model (in-memory)

`Agent` · `Post` · `Notification` · `Comment` — see `agent_social/models.py`. Persistence is an in-memory store (`InMemoryStore`); swapping in SQLite is straightforward because the platform only talks to the store interface.

---

## Problem 2 — Hardware Q&A

### Flow

1. **Ask** in natural language.
2. **Classify** intents (memory, CPU, storage, GPU, …).
3. **Gather** via **allow-listed, read-only** commands (no shell, no pipes).
4. **Parse** into structured facts; answer from tools only — say “I don’t know” when data is missing.

### Safety design

| Rule | Detail |
|------|--------|
| Allow-listed binaries | `lscpu`, `lsblk`, `free`, `lspci`, `uname`, `cat`, `dmidecode`, … |
| No shell | `subprocess` argv only after `shlex` parse; reject `\| \& ; \` $() > <` |
| No path binaries | `lscpu` yes, `/usr/bin/lscpu` no |
| `cat` paths | Only specific `/proc` and `/sys/class/dmi/id/*` files |
| Flags | Per-binary allow-list; `dmidecode -t` types constrained |
| Timeouts | 15s per tool |

Root/`dmidecode`: slot and max-capacity answers degrade gracefully when permission is denied — the assistant reports the gap instead of inventing numbers.

### Modes

- **Deterministic (default):** templates over parsers — works offline.
- **OpenAI (optional):** same tools; model may only phrase answers from tool output.

---

## Tests

```bash
# from repo root
python -m pytest problem-1-agent-social/tests problem-2-hardware-qa/tests -q
```

Coverage includes Diwali routing expectations, engagement comments, allow-list rejection of shell/escape attempts, and parser/agent fixtures for RAM upgrade Q&A.

## Layout

```
asama-ai-interview/
  README.md
  problem-1-agent-social/
    agent_social/     # models, router, platform, seed, demo, api, llm
    tests/
  problem-2-hardware-qa/
    hardware_qa/      # allowlist, tools, parsers, agent, cli
    tests/
```

## Privacy note (Problem 2)

By default all inspection stays on-box. If `OPENAI_API_KEY` is set, summarized tool output is sent to the API for phrasing — disable the key for fully local use.
