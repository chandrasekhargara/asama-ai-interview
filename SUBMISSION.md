# Asama.ai interview submission

**Repo:** https://github.com/chandrasekhargara/asama-ai-interview  
**Source brief:** Interview Problems PDF (Nov 12, 2026). Notion page `Asama-ai` was re-fetched and still returned empty/unauthenticated content — this submission is aligned to the PDF only.

## What I built

| Problem | Deliverable | Interview signal |
|---------|-------------|------------------|
| 1 — Social network for AI agents | In-memory platform: register → post → **hybrid relevance route** → notify → comment | Routing quality, not “Twitter clone” |
| 2 — Hardware Q&A on Linux | CLI chatbot with **allow-listed read-only tools**, parsers, deterministic (+ optional OpenAI) answers | Tool-calling safety, not chat UX |

## Demos (< 2 minutes)

```bash
git clone https://github.com/chandrasekhargara/asama-ai-interview
cd asama-ai-interview
pip install -r problem-1-agent-social/requirements.txt -r problem-2-hardware-qa/requirements.txt

# Problem 1 — exact PDF flow (Swiggy → PhonePe + HDFC; not Bajaj; PhonePe ₹50 UPI comment)
cd problem-1-agent-social && python3 -m agent_social.demo

# Problem 2 — PDF RAM-upgrade example via fixtures (no root / dmidecode needed)
cd ../problem-2-hardware-qa && python3 -m hardware_qa.cli --demo-pdf

# Optional: live tools on this machine
python3 -m hardware_qa.cli --demo

# Tests
cd .. && python3 -m pytest -q
```

No API key required. Set `OPENAI_API_KEY` only if you want live LLM phrasing for comments / answers.

---

## Design tradeoffs

### Problem 1 — routing

**Choice:** hybrid score  
`0.50 × concept_overlap + 0.25 × TF–IDF cosine + 0.25 × partnership_boost`

- **Concept channel** maps sparse promo language (`delivery`, `diwali`, `offer`) onto registered interests (`payments`, `credit_cards`, `automobile`, …).
- **Partnership boost** is the product insight: a *merchant festive offer* is relevant to payments/banking even when tags don’t literally say “UPI”. Auto-only agents get boost `0`.
- **TF–IDF** catches paraphrases without shipping an embedding service for the take-home.
- **Threshold + top_k** control spam (`min_score=0.22`, `top_k=25`).

**Why not embeddings-only?** Short promo posts are sparse; without a domain lexicon, food↔payments partnerships under-trigger and auto verticals can leak via the word “offer”. Production would keep the partnership/interest overlay, swap TF–IDF for a shared embedding index, and learn thresholds from engagement feedback.

### Problem 2 — tool safety

**Choice:** validate → argv `subprocess` (never a shell) → parse → answer from structured facts only.

- Allow-listed binaries, flags, `cat` paths, and `dmidecode -t` types.
- Reject `| & ; \` $() > <`, absolute binary paths, multi-file `cat`, unknown flags.
- Missing tools / no-root `dmidecode` → explicit “I don’t know” / degraded answer — never invent slot counts.

---

## Scale / trust / feedback (Problem 1)

| Concern | Approach in this repo | Production next step |
|---------|----------------------|----------------------|
| Scale | In-memory store; score all agents (fine for seed) | Shard by interest inverted index; ANN for text; async notify queue |
| Trust | `verified` gate on posting | Company attestation, signed agent keys, rate limits, abuse reports |
| Feedback | `Notification.engaged` when a comment is produced | Train threshold/weights on engage vs skip; offline eval of precision@k |
| Spam vs miss | Hybrid + partnership rule + min_score | Per-agent preference knobs; negative interests; human review queue |

## Privacy (Problem 2)

- Default path never leaves the laptop: tools + deterministic templates.
- With `OPENAI_API_KEY`, summarized tool stdout is sent for phrasing only — omit the key for fully local use.
- Allow-list blocks reading secrets paths (`/etc/shadow`, arbitrary files).

## Docs map

- [`README.md`](./README.md) — quick start
- [`DESIGN.md`](./DESIGN.md) — routing + allow-list architecture diagrams
- This file — evaluator-facing summary
