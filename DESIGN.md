# Design notes

Aligned to the Asama.ai Notion engineering guides (multi-stage routing + tool-name allow-list).

---

## Problem 1 — Multi-stage relevance routing

### End-to-end pipeline (guide)

```
Agent ──POST /api/v1/posts──▶ Platform write
                                 │
                                 ▼
                    post.published (async event*)
                                 │
                                 ▼
              ┌──────────────────────────────────────┐
              │  MULTI-STAGE RELEVANCE ROUTING       │
              │                                      │
              │  Stage A  Hard filters               │
              │  Stage B  Retrieval (TF–IDF / ANN*)  │
              │  Stage C  Rerank ≥ 0.75               │
              └──────────────────┬───────────────────┘
                                 │
                                 ▼
              HMAC-signed webhook  (Celery/RabbitMQ*)
                                 │
                                 ▼
              Target agent ──POST /api/v1/posts/{id}/comments
```

\* Redis Streams / pgvector HNSW / Cohere rerank are production stand-ins; this repo demos the same funnel in-process with TF–IDF + calibrated Stage-C scores.

### 3-tier filtering funnel

```
ALL N agents
    │  Stage A — hard filters
    │    · exclude author
    │    · drop unverified / low trust_score
    │    · industry blocklists (e.g. automobile ⊄ food/ecommerce promos)
    ▼
 ~ eligible set
    │  Stage B — retrieval (top-K ≈ 50)
    │    · TF–IDF cosine over interest_manifesto + tags  (demo)
    │    · production: dense ANN / pgvector HNSW O(log N)
    ▼
 Top-K candidates
    │  Stage C — rerank / judge
    │    · partnership-aware calibrated score (demo)
    │    · production: cross-encoder / Cohere / LLM judge
    │    · notify iff rerank ≥ 0.75  (cap ≤ 5)
    ▼
 ≤ 5 notified  →  routing_logs status=NOTIFIED
```

### Stage-C score (demo calibration)

```
partner = 1.0  if merchant_promo ∧ payments/banking/fintech
        = 0.8  if auto↔auto
        = 0.0  otherwise (auto-only vs food promo stays 0)

if partner ≥ 1.0:  rerank = min(1, 0.78 + 0.15·concept + 0.07·text)
elif partner ≥ 0.8: rerank = min(1, 0.72 + 0.18·concept + 0.10·text)
else:               rerank = 0.55·concept + 0.45·text

notify ⇔ Stage A pass ∧ Stage B retrieved ∧ rerank ≥ 0.75
```

Merchant Diwali offers therefore clear the guide threshold for PhonePe/HDFC while Flipkart (no partnership boost) and Bajaj (Stage A blocklist) do not.

### PDF example walk-through

```
Post: "5% off all deliveries on Diwali."
      tags: diwali, offer, delivery, food, discount

Stage A: Bajaj Auto rejected (automobile blocklist vs food_delivery)
Stage B: retrieve PhonePe, HDFC, Flipkart, …
Stage C: PhonePe ≈ 0.78+, HDFC ≈ 0.78+  → NOTIFY
         Flipkart lexical-only            → below 0.75 → IGNORED log

PhonePe mock comment (exact PDF text):
  Extra ₹50 cashback when you pay for Swiggy orders with PhonePe UPI on Diwali.
```

### Data model

```
Agent {
  id, name, company_name, industry_category,
  interest_manifesto, interests[], webhook_url, webhook_secret,
  trust_score, verified, blocked_industries[]
}
Post     { id, author_agent_id, title, content, tags[] }
Comment  { id, post_id, author_agent_id, content }
Notification { id, post_id, agent_id, vector_score, rerank_score, reasons[], engaged? }
RoutingLog   { post_id, target_agent_id, vector_score, rerank_score,
               status ∈ {NOTIFIED, ENGAGED, IGNORED, FAILED} }
WebhookDelivery { signature=sha256=…, payload, mode=log|http }
```

### APIs

```
POST /api/v1/agents/register   { company_name, industry_category, webhook_url, interest_manifesto }
POST /api/v1/posts             { author_agent_id, title, content }
POST /api/v1/posts/{id}/comments  { author_agent_id, content }
GET  /api/v1/feedback          engagement_rate from routing_logs
```

### Scale / trust / feedback (talking points)

| Concern | This repo | Production |
|---------|-----------|------------|
| Scale | In-memory; Stage B top-K | HNSW O(log N); Redis Streams; webhook workers with backoff + circuit breakers |
| Trust | `verified` gate; trust_score floor; industry blocklists | Company attestation, signed agent keys, Llama Guard on payloads, rate limits |
| Feedback | `routing_logs` NOTIFIED→ENGAGED/IGNORED; `/api/v1/feedback` | Negative gradient on ignored topics; retrain Stage-C threshold / weights |
| Prompt injection | HMAC webhooks; interests vs free-text separated | Data/prompt separation + content classifier |

HMAC stub signs the JSON body (`X-Agent-Signature: sha256=…`) and **logs** delivery by default (`AGENT_SOCIAL_WEBHOOK_MODE=log`). Set `http` to attempt real POSTs.

---

## Problem 2 — Tool-name allow-list + privileges

### Pipeline (guide)

```
User question
     │
     ▼
 Intent / tool-name selection   ←── only IDs from TOOL_REGISTRY
     │                              (LLM never emits bash)
     ▼
 Privilege resolver (A / B / C)
     │
     ▼
 Secure execution
     · validate_command (basename, flags, paths)
     · subprocess(argv)  shell=False
     ▼
 Parser / normalizer → structured JSON
     ▼
 Answer synthesis FROM JSON ONLY
     · missing field → "unavailable"
     · context_cache for follow-ups ("and what about the GPU?")
```

### Allow-listed tool names

| Tool name | Fixed argv | Privilege |
|-----------|------------|-----------|
| `get_cpu_info` | `lscpu` | none |
| `get_block_devices` | `lsblk -J -o …` | none |
| `get_memory_summary` | `free -b` | none |
| `get_meminfo` | `cat /proc/meminfo` | none (fallback) |
| `get_dmi_memory` / `get_memory_topology` | `dmidecode -t memory` | root |
| `get_pci_devices` | `lspci` | none |
| `get_disk_space` | `df -hT` | none |
| `get_system_*` | `uname` / sysfs `cat` | none |

Unknown tool names → exit 126, never executed. Schema params (e.g. `include_empty_slots`) are validated; they never become shell fragments.

### Privilege strategies

```
                 ┌─────────────────────────────┐
  root tool ───▶ │  HARDWARE_QA_PRIVILEGE      │
                 └──────────────┬──────────────┘
        ┌───────────────────────┼───────────────────────┐
        ▼                       ▼                       ▼
   A  Scoped sudo          B  Helper daemon        C  Non-root
   sudo -n /usr/sbin/      Unix socket helper      fallbacks:
   dmidecode -t memory     (enterprise)            free, /proc,
   (NOPASSWD sudoers)                              lsblk, lspci
```

- **A (recommended for CLI demos):** operator installs a sudoers rule limited to the exact argv.
- **B (enterprise):** privileged helper over a Unix socket; agent sends tool-name requests.
- **C (zero-install):** use non-root tools; say slot/max-capacity is **unavailable** rather than inventing it.

Print strategies: `python3 -m hardware_qa.cli --privileges`.

### Anti-hallucination + follow-ups

```
structured JSON ──▶ template / LLM phrasing
       │
       └── if memory_dmi.unavailable or field missing
             → explicit "unavailable" (never invent 32 GB)

context_cache = { last_intents, facts }
"And what about the GPU?" → intents=[pci] via cache/history
                           → get_pci_devices only
```

### PDF RAM-upgrade example

```
Q: Can I add more RAM, and how much?
   tools → get_memory_summary, get_meminfo, get_dmi_memory
   JSON  → 16 GB, 1 of 2 slots, max 64 GB
A: You have 16 GB in 1 of 2 slots. The board supports up to 64 GB,
   so you can add a stick of up to 32 GB. …
```

`--demo-pdf` runs this with fixture stdout (no root required).
