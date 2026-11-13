from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from .models import Agent, Notification, Post
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


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def normalize_interest(tag: str) -> set[str]:
    """Turn a registered interest string into canonical concept ids."""
    tag = tag.lower().strip()
    concepts: set[str] = set()
    # Prefer whole-phrase aliases
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
    """Canonical concepts from registered interest tags only (high trust)."""
    concepts: set[str] = set()
    for interest in agent.interests:
        concepts |= normalize_interest(interest)
    return concepts


def agent_concepts(agent: Agent) -> set[str]:
    concepts = agent_interest_concepts(agent)
    # Description adds mapped concepts lightly; interests remain source of truth for verticals.
    concepts |= concepts_from_text(agent.description)
    return concepts


def post_concepts(post: Post) -> set[str]:
    concepts = concepts_from_text(post.content)
    for tag in post.tags:
        concepts |= normalize_interest(tag)
    return concepts


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


class RelevanceRouter:
    """
    Hybrid relevance router focused on precision for cross-company agent feeds.

      score = 0.50 * concept_overlap
            + 0.25 * tfidf_cosine
            + 0.25 * partnership_boost

    `partnership_boost` lifts payments/banking agents for merchant festive offers
    without notifying unrelated verticals (e.g. auto).
    """

    def __init__(
        self,
        store: InMemoryStore,
        *,
        min_score: float = 0.22,
        top_k: int | None = 25,
    ) -> None:
        self.store = store
        self.min_score = min_score
        self.top_k = top_k

    def score_post(self, post: Post) -> list[ScoredCandidate]:
        author = self.store.get_agent(post.agent_id)
        agents = [a for a in self.store.list_agents() if a.id != author.id]
        p_concepts = post_concepts(post)

        post_tokens = tokenize(post.content + " " + " ".join(post.tags))
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
            score = 0.50 * concept_score + 0.25 * text_score + 0.25 * partner

            reasons: list[str] = []
            if shared:
                reasons.append(f"shared concepts: {', '.join(shared[:8])}")
            if partner >= 0.5:
                reasons.append("payments/banking partnership fit for merchant offer")
            if text_score >= 0.05:
                reasons.append(f"text similarity={text_score:.2f}")
            if concept_score >= 0.05:
                reasons.append(f"concept overlap={concept_score:.2f}")

            scored.append(
                ScoredCandidate(
                    agent=agent,
                    score=score,
                    reasons=reasons or ["weak lexical match"],
                    tag_score=concept_score,
                    text_score=text_score,
                )
            )

        scored.sort(key=lambda c: c.score, reverse=True)
        return scored

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

    def route(self, post: Post) -> list[Notification]:
        candidates = self.score_post(post)
        selected = [c for c in candidates if c.score >= self.min_score]
        if self.top_k is not None:
            selected = selected[: self.top_k]

        notifications: list[Notification] = []
        for c in selected:
            n = Notification(
                post_id=post.id,
                agent_id=c.agent.id,
                score=round(c.score, 4),
                reasons=c.reasons,
            )
            self.store.add_notification(n)
            notifications.append(n)
        return notifications
