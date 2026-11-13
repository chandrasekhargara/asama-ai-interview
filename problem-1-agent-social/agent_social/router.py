from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field

from .models import Agent, Notification, Post, RoutingLog, RoutingStatus
from .store import InMemoryStore

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Map surface terms → canonical interest concepts agents register.
_CONCEPTS: dict[str, set[str]] = {
    "delivery": {"food_delivery", "logistics", "orders"},
    "deliveries": {"food_delivery", "logistics", "orders"},
    "food": {"food_delivery", "restaurants"},
    "restaurant": {"food_delivery", "restaurants"},
    "restaurants": {"food_delivery", "restaurants"},
    "swiggy": {"food_delivery"},
    "zomato": {"food_delivery"},
    "order": {"orders", "food_delivery"},
    "orders": {"orders", "food_delivery"},
    "upi": {"payments", "fintech", "upi"},
    "payment": {"payments", "fintech"},
    "payments": {"payments", "fintech"},
    "cashback": {"payments", "fintech", "cashback", "offers"},
    "wallet": {"payments", "fintech", "wallet"},
    "fintech": {"fintech", "payments"},
    "phonepe": {"payments", "fintech", "upi"},
    "card": {"banking", "credit_cards", "payments"},
    "cards": {"banking", "credit_cards", "payments"},
    "credit": {"banking", "credit_cards"},
    "debit": {"banking", "payments"},
    "banking": {"banking", "finance"},
    "bank": {"banking", "finance"},
    "hdfc": {"banking", "credit_cards"},
    "reward": {"rewards", "offers", "credit_cards"},
    "rewards": {"rewards", "offers", "credit_cards"},
    "finance": {"finance", "banking"},
    "diwali": {"festive", "offers"},
    "festive": {"festive", "offers"},
    "festival": {"festive", "offers"},
    "offer": {"offers"},
    "offers": {"offers"},
    "promo": {"offers"},
    "promotion": {"offers"},
    "promotions": {"offers"},
    "discount": {"offers", "discount"},
    "discounts": {"offers", "discount"},
    "deal": {"offers"},
    "deals": {"offers"},
    "ecommerce": {"ecommerce", "shopping"},
    "shopping": {"ecommerce", "shopping"},
    "marketplace": {"ecommerce", "shopping"},
    "retail": {"ecommerce", "shopping"},
    "flipkart": {"ecommerce", "shopping"},
    "automobile": {"automobile", "mobility"},
    "auto": {"automobile", "mobility"},
    "motorcycle": {"automobile", "motorcycle", "mobility"},
    "scooter": {"automobile", "scooter", "mobility"},
    "vehicle": {"automobile", "mobility"},
    "vehicles": {"automobile", "mobility"},
    "bike": {"automobile", "motorcycle", "mobility"},
    "mobility": {"mobility", "automobile"},
    "dealership": {"automobile", "dealerships"},
    "dealerships": {"automobile", "dealerships"},
    "bajaj": {"automobile", "mobility"},
    "pulsar": {"automobile", "motorcycle"},
    "merchant": {"payments", "offers"},
}

# Verticals that care about *other companies'* consumer offers (partnership angle).
_PARTNER_VERTICALS = frozenset({"payments", "fintech", "banking", "credit_cards", "upi"})
_OFFER_CONCEPTS = frozenset({"offers", "discount", "festive", "cashback"})
_MERCHANT_VERTICALS = frozenset(
    {"food_delivery", "ecommerce", "shopping", "restaurants", "orders", "logistics"}
)

# Industry categories inferred from agent profile when not set explicitly.
_INDUSTRY_FROM_CONCEPTS: list[tuple[frozenset[str], str]] = [
    (frozenset({"food_delivery", "restaurants", "orders"}), "food_delivery"),
    (frozenset({"ecommerce", "shopping"}), "ecommerce"),
    (frozenset({"payments", "fintech", "upi"}), "payments"),
    (frozenset({"banking", "credit_cards", "finance"}), "banking"),
    (frozenset({"automobile", "motorcycle", "scooter", "mobility"}), "automobile"),
]

# Stage C notify threshold (guide: cross-encoder / LLM judge ≥ 0.75).
RERANK_THRESHOLD = 0.75
# Stage B retrieval width (guide: ANN top K ≈ 50).
DEFAULT_RETRIEVAL_K = 50


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def normalize_interest(tag: str) -> set[str]:
    """Turn a registered interest string into canonical concept ids."""
    tag = tag.lower().strip()
    concepts: set[str] = set()
    phrase = tag.replace(" ", "_")
    if phrase in {
        "food_delivery",
        "credit_cards",
        "festive_sales",
        "merchant_offers",
    }:
        if phrase == "merchant_offers":
            return {"offers", "payments", "fintech"}
        if phrase == "festive_sales":
            return {"festive", "offers", "ecommerce"}
        if phrase == "credit_cards":
            return {"credit_cards", "banking", "payments"}
        return {phrase, "food_delivery", "orders"} if phrase == "food_delivery" else {phrase}

    for tok in tokenize(tag):
        concepts |= _CONCEPTS.get(tok, {tok})
    if not concepts:
        concepts.add(phrase)
    return concepts


def concepts_from_text(text: str) -> set[str]:
    out: set[str] = set()
    for tok in tokenize(text):
        out |= _CONCEPTS.get(tok, set())
    return out


def agent_interest_concepts(agent: Agent) -> set[str]:
    """Canonical concepts from registered interest tags + manifesto."""
    concepts: set[str] = set()
    for interest in agent.interests:
        concepts |= normalize_interest(interest)
    if agent.interest_manifesto:
        concepts |= concepts_from_text(agent.interest_manifesto)
    return concepts


def agent_concepts(agent: Agent) -> set[str]:
    concepts = agent_interest_concepts(agent)
    concepts |= concepts_from_text(agent.description)
    return concepts


def post_concepts(post: Post) -> set[str]:
    text = f"{post.title} {post.content}".strip()
    concepts = concepts_from_text(text)
    for tag in post.tags:
        concepts |= normalize_interest(tag)
    return concepts


def infer_industry(agent: Agent) -> str:
    if agent.industry_category and agent.industry_category != "general":
        return agent.industry_category.lower()
    concepts = agent_interest_concepts(agent)
    for keys, industry in _INDUSTRY_FROM_CONCEPTS:
        if concepts & keys:
            return industry
    return "general"


def post_industry_hints(post: Post) -> set[str]:
    """Map post concepts to industry categories for Stage A blocklists."""
    concepts = post_concepts(post)
    industries: set[str] = set()
    for keys, industry in _INDUSTRY_FROM_CONCEPTS:
        if concepts & keys:
            industries.add(industry)
    return industries


def tfidf_vectors(docs: list[list[str]]) -> list[dict[str, float]]:
    n = len(docs)
    df: Counter[str] = Counter()
    for doc in docs:
        df.update(set(doc))
    vectors: list[dict[str, float]] = []
    for doc in docs:
        tf = Counter(doc)
        length = max(len(doc), 1)
        vec: dict[str, float] = {}
        for term, count in tf.items():
            idf = math.log((n + 1) / (df[term] + 1)) + 1.0
            vec[term] = (count / length) * idf
        vectors.append(vec)
    return vectors


def cosine(a: dict[str, float], b: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    keys = set(a) | set(b)
    dot = sum(a.get(k, 0.0) * b.get(k, 0.0) for k in keys)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    union = len(a | b)
    return len(a & b) / union if union else 0.0


def overlap_coefficient(a: set[str], b: set[str]) -> float:
    """|∩| / min(|a|,|b|) — robust when one side is a broad profile."""
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


@dataclass
class ScoredCandidate:
    agent: Agent
    score: float
    reasons: list[str]
    tag_score: float
    text_score: float
    vector_score: float = 0.0
    rerank_score: float = 0.0
    partner: float = 0.0
    stage_a_passed: bool = True
    stage_a_reason: str = ""


@dataclass
class StageTrace:
    """Debug / demo visibility into the 3-tier funnel."""

    stage_a_in: int = 0
    stage_a_out: int = 0
    stage_a_rejected: list[dict] = field(default_factory=list)
    stage_b_out: int = 0
    stage_c_notified: int = 0
    threshold: float = RERANK_THRESHOLD


class RelevanceRouter:
    """
    Multi-stage relevance router (Notion engineering guide):

      Stage A — hard filters (author, unverified, industry blocklists)
      Stage B — retrieval (TF–IDF / embedding-style cosine, top-K)
      Stage C — rerank + threshold (≥ 0.75)

    Production swaps Stage B for pgvector/HNSW ANN and Stage C for a
    cross-encoder / Cohere rerank / LLM judge. Demo keeps the same funnel
    with local TF–IDF + calibrated partnership-aware rerank.
    """

    def __init__(
        self,
        store: InMemoryStore,
        *,
        min_score: float = RERANK_THRESHOLD,
        top_k: int | None = DEFAULT_RETRIEVAL_K,
        retrieval_k: int | None = None,
    ) -> None:
        self.store = store
        self.min_score = min_score
        self.top_k = top_k
        self.retrieval_k = retrieval_k if retrieval_k is not None else (top_k or DEFAULT_RETRIEVAL_K)
        self.last_trace: StageTrace | None = None

    def score_post(self, post: Post) -> list[ScoredCandidate]:
        """Full funnel scoring for transparency (includes Stage-C losers)."""
        author = self.store.get_agent(post.agent_id)
        all_agents = self.store.list_agents()
        stage_a = self._stage_a_filter(post, author, all_agents)
        stage_b = self._stage_b_retrieve(post, stage_a.passed)
        stage_c = self._stage_c_rerank(post, stage_b)

        self.last_trace = StageTrace(
            stage_a_in=len(all_agents),
            stage_a_out=len(stage_a.passed),
            stage_a_rejected=stage_a.rejected,
            stage_b_out=len(stage_b),
            stage_c_notified=sum(1 for c in stage_c if c.rerank_score >= self.min_score),
            threshold=self.min_score,
        )
        # Include Stage-A rejects at score 0 for ranking transparency
        rejected_as_candidates = [
            ScoredCandidate(
                agent=item["agent"],
                score=0.0,
                reasons=[item["reason"]],
                tag_score=0.0,
                text_score=0.0,
                stage_a_passed=False,
                stage_a_reason=item["reason"],
            )
            for item in stage_a.rejected
        ]
        combined = stage_c + rejected_as_candidates
        combined.sort(key=lambda c: c.score, reverse=True)
        return combined

    def route(self, post: Post) -> list[Notification]:
        candidates = self.score_post(post)
        selected = [
            c
            for c in candidates
            if c.stage_a_passed and c.rerank_score >= self.min_score
        ]
        # Cap final notifies (guide: ≤5 after Stage C); keep top by rerank
        notify_cap = 5 if self.top_k is None else min(5, self.top_k)
        selected = selected[:notify_cap]

        notifications: list[Notification] = []
        for c in selected:
            n = Notification(
                post_id=post.id,
                agent_id=c.agent.id,
                score=round(c.rerank_score, 4),
                reasons=c.reasons,
                vector_score=round(c.vector_score, 4),
                rerank_score=round(c.rerank_score, 4),
                stage_a_passed=True,
            )
            self.store.add_notification(n)
            self.store.add_routing_log(
                RoutingLog(
                    post_id=post.id,
                    target_agent_id=c.agent.id,
                    vector_score=round(c.vector_score, 4),
                    rerank_score=round(c.rerank_score, 4),
                    status=RoutingStatus.NOTIFIED,
                    reasons=c.reasons,
                )
            )
            notifications.append(n)

        # Log Stage-C near-misses as IGNORED for feedback loop (passed A+B, failed C)
        for c in candidates:
            if not c.stage_a_passed:
                continue
            if c.rerank_score >= self.min_score:
                continue
            if any(n.agent_id == c.agent.id for n in notifications):
                continue
            # Only log those that made Stage B (had a retrieval score computed)
            if c.vector_score <= 0 and c.tag_score <= 0 and c.partner <= 0:
                continue
            self.store.add_routing_log(
                RoutingLog(
                    post_id=post.id,
                    target_agent_id=c.agent.id,
                    vector_score=round(c.vector_score, 4),
                    rerank_score=round(c.rerank_score, 4),
                    status=RoutingStatus.IGNORED,
                    reasons=c.reasons + [f"below Stage-C threshold {self.min_score}"],
                )
            )
        return notifications

    # ------------------------------------------------------------------
    # Stage A — hard filters
    # ------------------------------------------------------------------

    @dataclass
    class _StageAResult:
        passed: list[Agent]
        rejected: list[dict]

    def _stage_a_filter(
        self, post: Post, author: Agent, agents: list[Agent]
    ) -> _StageAResult:
        passed: list[Agent] = []
        rejected: list[dict] = []
        author_industry = infer_industry(author)
        post_industries = post_industry_hints(post)

        for agent in agents:
            if agent.id == author.id:
                # Author is excluded from the candidate universe entirely
                # (not logged as a rejected notify target).
                continue
            if not agent.verified:
                rejected.append({"agent": agent, "reason": "Stage A: unverified agent"})
                continue
            if agent.trust_score < 0.3:
                rejected.append(
                    {"agent": agent, "reason": "Stage A: trust_score below floor"}
                )
                continue
            agent_industry = infer_industry(agent)
            # Recipient blocklist: agent refuses author's industry
            blocked = {b.lower() for b in agent.blocked_industries}
            if author_industry in blocked or (post_industries & blocked):
                rejected.append(
                    {
                        "agent": agent,
                        "reason": f"Stage A: industry blocklist ({author_industry})",
                    }
                )
                continue
            # Automobile agents do not receive food/ecommerce promo spam
            if agent_industry == "automobile" and post_industries & {
                "food_delivery",
                "ecommerce",
            }:
                if not (post_industries & {"automobile"}):
                    rejected.append(
                        {
                            "agent": agent,
                            "reason": "Stage A: automobile blocklist vs merchant promo",
                        }
                    )
                    continue
            passed.append(agent)
        return self._StageAResult(passed=passed, rejected=rejected)

    # ------------------------------------------------------------------
    # Stage B — retrieval (TF–IDF ANN-style top-K)
    # ------------------------------------------------------------------

    def _stage_b_retrieve(
        self, post: Post, agents: list[Agent]
    ) -> list[ScoredCandidate]:
        if not agents:
            return []

        p_concepts = post_concepts(post)
        post_tokens = tokenize(
            f"{post.title} {post.content} " + " ".join(post.tags)
        )
        agent_docs = [tokenize(a.interest_text()) for a in agents]
        vectors = tfidf_vectors([post_tokens] + agent_docs)
        post_vec = vectors[0]

        scored: list[ScoredCandidate] = []
        for i, agent in enumerate(agents):
            a_concepts = agent_concepts(agent)
            verticals = agent_interest_concepts(agent)
            shared = sorted(p_concepts & a_concepts)
            concept_score = 0.65 * overlap_coefficient(p_concepts, a_concepts) + 0.35 * jaccard(
                p_concepts, a_concepts
            )
            text_score = cosine(post_vec, vectors[i + 1])
            partner = self._partnership_boost(p_concepts, verticals)
            # Retrieval score ≈ dense ANN similarity (local TF–IDF stand-in)
            vector_score = 0.55 * concept_score + 0.45 * text_score + 0.25 * partner
            # Softmax-free ranking key
            scored.append(
                ScoredCandidate(
                    agent=agent,
                    score=vector_score,
                    reasons=[],
                    tag_score=concept_score,
                    text_score=text_score,
                    vector_score=vector_score,
                    partner=partner,
                    stage_a_passed=True,
                )
            )
            if shared:
                scored[-1].reasons.append(f"shared concepts: {', '.join(shared[:8])}")

        scored.sort(key=lambda c: c.vector_score, reverse=True)
        k = self.retrieval_k or DEFAULT_RETRIEVAL_K
        return scored[:k]

    # ------------------------------------------------------------------
    # Stage C — rerank + threshold
    # ------------------------------------------------------------------

    def _stage_c_rerank(
        self, post: Post, candidates: list[ScoredCandidate]
    ) -> list[ScoredCandidate]:
        """
        Production: Cohere / cross-encoder / LLM judge.
        Demo: partnership-aware calibrated score with notify threshold 0.75.
        """
        p_concepts = post_concepts(post)
        for c in candidates:
            concept = c.tag_score
            text = c.text_score
            partner = c.partner
            # Calibrated so merchant-promo × payments/banking clears 0.75;
            # pure lexical matches without partnership stay below.
            if partner >= 1.0:
                rerank = min(1.0, 0.78 + 0.15 * concept + 0.07 * text)
            elif partner >= 0.8:
                rerank = min(1.0, 0.72 + 0.18 * concept + 0.10 * text)
            else:
                rerank = 0.55 * concept + 0.45 * text

            reasons = list(c.reasons)
            if partner >= 0.5:
                reasons.append("payments/banking partnership fit for merchant offer")
            if text >= 0.05:
                reasons.append(f"text similarity={text:.2f}")
            if concept >= 0.05:
                reasons.append(f"concept overlap={concept:.2f}")
            reasons.append(f"Stage C rerank={rerank:.3f} (threshold={self.min_score})")

            c.rerank_score = rerank
            c.score = rerank  # public score == Stage C for notify decisions
            c.reasons = reasons or ["weak lexical match"]

        candidates.sort(key=lambda c: c.rerank_score, reverse=True)
        return candidates

    @staticmethod
    def _partnership_boost(post_c: set[str], agent_c: set[str]) -> float:
        """
        Merchant promo (food/ecommerce + offer/festive) → notify payment/bank agents.
        Auto-only agents get 0 even if the word 'offer' appears.
        """
        is_merchant_promo = bool(post_c & _OFFER_CONCEPTS) and bool(post_c & _MERCHANT_VERTICALS)
        is_partner = bool(agent_c & _PARTNER_VERTICALS)
        is_auto = bool(agent_c & {"automobile", "motorcycle", "scooter", "mobility"}) and not is_partner
        if is_auto and not (post_c & {"automobile", "motorcycle", "scooter", "mobility"}):
            return 0.0
        if is_merchant_promo and is_partner:
            return 1.0
        if post_c & {"automobile", "motorcycle", "scooter"} and is_auto:
            return 0.8
        return 0.0
