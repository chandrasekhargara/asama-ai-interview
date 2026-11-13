from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from agent_social.llm import MockCommentGenerator
from agent_social.models import RoutingStatus
from agent_social.platform import AgentSocialPlatform
from agent_social.router import RERANK_THRESHOLD, RelevanceRouter, cosine, jaccard, tokenize
from agent_social.seed import seed_platform
from agent_social.store import InMemoryStore
from agent_social.webhook import sign_payload, verify_signature


def test_tokenize_and_jaccard():
    assert "diwali" in tokenize("5% off on Diwali!")
    assert jaccard({"a", "b"}, {"b", "c"}) == pytest.approx(1 / 3)
    assert cosine({"x": 1.0}, {"x": 1.0}) == 1.0


def test_diwali_delivery_notifies_payments_not_auto():
    """PDF example: Swiggy Diwali post → PhonePe + HDFC; not Bajaj (or Flipkart)."""
    platform = seed_platform(
        AgentSocialPlatform(auto_engage=False, deliver_webhooks=False)
    )
    swiggy = platform.store.get_agent_by_name("swiggy-agent")
    assert swiggy is not None

    result = platform.publish(
        swiggy.id,
        "5% off all deliveries on Diwali.",
        tags=["diwali", "offer", "delivery", "food", "discount"],
        auto_engage=False,
    )

    companies = {
        platform.store.get_agent(n.agent_id).company for n in result.notifications
    }
    assert companies == {"PhonePe", "HDFC Bank"}
    assert "Bajaj Auto" not in companies
    assert "Flipkart" not in companies

    for n in result.notifications:
        assert n.rerank_score >= RERANK_THRESHOLD

    ranking = {c.agent.company: c.score for c in platform.router.score_post(result.post)}
    assert ranking["Bajaj Auto"] == 0.0
    assert ranking["PhonePe"] > ranking["HDFC Bank"] > ranking["Flipkart"]

    # Stage A should reject Bajaj (automobile blocklist)
    bajaj_cand = next(
        c for c in platform.router.score_post(result.post) if c.agent.company == "Bajaj Auto"
    )
    assert bajaj_cand.stage_a_passed is False


def test_auto_post_notifies_bajaj_not_food_only():
    platform = seed_platform(
        AgentSocialPlatform(auto_engage=False, deliver_webhooks=False)
    )
    bajaj = platform.store.get_agent_by_name("bajaj-agent")
    assert bajaj is not None

    result = platform.publish(
        bajaj.id,
        "New Pulsar motorcycle exchange offer at dealerships this month.",
        tags=["motorcycle", "automobile", "vehicles", "offer"],
        auto_engage=False,
    )
    companies = {
        platform.store.get_agent(n.agent_id).company for n in result.notifications
    }
    # Food-only agents should score low vs auto content
    assert "Swiggy" not in companies or all(
        n.score < 0.35
        for n in result.notifications
        if platform.store.get_agent(n.agent_id).company == "Swiggy"
    )
    ranking = platform.router.score_post(result.post)
    by_company = {c.agent.company: c.score for c in ranking}
    assert by_company["Swiggy"] < by_company.get("Flipkart", 1.0) or by_company[
        "Swiggy"
    ] < 0.25


def test_mock_engagement_phonepe_comment():
    platform = seed_platform(
        AgentSocialPlatform(
            commenter=MockCommentGenerator(),
            auto_engage=True,
            deliver_webhooks=False,
        )
    )
    swiggy = platform.store.get_agent_by_name("swiggy-agent")
    result = platform.publish(
        swiggy.id,
        "5% off all deliveries on Diwali.",
        tags=["diwali", "delivery", "offer", "food"],
    )
    comment_companies = {
        platform.store.get_agent(c.agent_id).company for c in result.comments
    }
    assert "PhonePe" in comment_companies
    phonepe_comment = next(
        c.content
        for c in result.comments
        if platform.store.get_agent(c.agent_id).company == "PhonePe"
    )
    assert phonepe_comment == (
        "Extra ₹50 cashback when you pay for Swiggy orders with PhonePe UPI on Diwali."
    )
    assert "Bajaj Auto" not in comment_companies


def test_router_respects_min_score_and_excludes_author():
    store = InMemoryStore()
    platform = AgentSocialPlatform(store=store, auto_engage=False, deliver_webhooks=False)
    seed_platform(platform)
    router = RelevanceRouter(store, min_score=0.99, top_k=3)
    platform.router = router
    swiggy = store.get_agent_by_name("swiggy-agent")
    result = platform.publish(swiggy.id, "hello world", tags=["zzz"], auto_engage=False)
    assert result.notifications == []
    ranking = router.score_post(result.post)
    assert all(c.agent.id != swiggy.id for c in ranking)


def test_engagement_feedback_recorded():
    platform = seed_platform(
        AgentSocialPlatform(
            commenter=MockCommentGenerator(),
            auto_engage=True,
            deliver_webhooks=False,
        )
    )
    swiggy = platform.store.get_agent_by_name("swiggy-agent")
    result = platform.publish(
        swiggy.id,
        "5% off all deliveries on Diwali.",
        tags=["diwali", "delivery", "food", "offer"],
    )
    assert any(n.engaged is True for n in result.notifications)
    for n in result.notifications:
        company = platform.store.get_agent(n.agent_id).company
        assert company != "Bajaj Auto"

    logs = platform.store.routing_logs_for_post(result.post.id)
    statuses = {r.status for r in logs}
    assert RoutingStatus.ENGAGED in statuses
    stats = platform.feedback_stats()
    assert stats["engaged"] >= 1
    assert stats["engagement_rate"] > 0


def test_hmac_webhook_stub_signs_payload():
    platform = seed_platform(
        AgentSocialPlatform(auto_engage=False, deliver_webhooks=True)
    )
    swiggy = platform.store.get_agent_by_name("swiggy-agent")
    result = platform.publish(
        swiggy.id,
        "5% off all deliveries on Diwali.",
        tags=["diwali", "offer", "delivery", "food", "discount"],
        auto_engage=False,
    )
    assert len(result.webhooks) == 2
    for w in result.webhooks:
        assert w.signature.startswith("sha256=")
        assert w.mode == "log"
        assert w.delivered is True
        import json

        body = json.dumps(w.payload, sort_keys=True, default=str).encode("utf-8")
        agent = platform.store.get_agent(w.agent_id)
        assert verify_signature(agent.webhook_secret, body, w.signature)


def test_stage_a_rejects_unverified():
    platform = seed_platform(
        AgentSocialPlatform(auto_engage=False, deliver_webhooks=False)
    )
    platform.register(
        name="spoof-agent",
        company="SpoofCo",
        interests=["payments", "upi"],
        description="Unverified payments spoof",
        industry_category="payments",
        verified=False,
    )
    swiggy = platform.store.get_agent_by_name("swiggy-agent")
    result = platform.publish(
        swiggy.id,
        "5% off all deliveries on Diwali.",
        tags=["diwali", "offer", "delivery", "food"],
        auto_engage=False,
    )
    companies = {
        platform.store.get_agent(n.agent_id).company for n in result.notifications
    }
    assert "SpoofCo" not in companies


def test_sign_payload_stable():
    sig = sign_payload("secret", b'{"a":1}')
    assert sig.startswith("sha256=")
    assert verify_signature("secret", b'{"a":1}', sig)
    assert not verify_signature("secret", b'{"a":2}', sig)
