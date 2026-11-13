from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from agent_social.llm import MockCommentGenerator
from agent_social.platform import AgentSocialPlatform
from agent_social.router import RelevanceRouter, cosine, jaccard, tokenize
from agent_social.seed import seed_platform
from agent_social.store import InMemoryStore


def test_tokenize_and_jaccard():
    assert "diwali" in tokenize("5% off on Diwali!")
    assert jaccard({"a", "b"}, {"b", "c"}) == pytest.approx(1 / 3)
    assert cosine({"x": 1.0}, {"x": 1.0}) == 1.0


def test_diwali_delivery_notifies_payments_not_auto():
    """PDF example: Swiggy Diwali post → PhonePe + HDFC; not Bajaj (or Flipkart)."""
    platform = seed_platform(AgentSocialPlatform(auto_engage=False))
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

    ranking = {c.agent.company: c.score for c in platform.router.score_post(result.post)}
    assert ranking["Bajaj Auto"] == 0.0
    assert ranking["PhonePe"] > ranking["HDFC Bank"] > ranking["Flipkart"]


def test_auto_post_notifies_bajaj_not_food_only():
    platform = seed_platform(AgentSocialPlatform(auto_engage=False))
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
    # At least someone mobility-adjacent or offer-adjacent may match; Bajaj is author so excluded
    ranking = platform.router.score_post(result.post)
    by_company = {c.agent.company: c.score for c in ranking}
    assert by_company["Swiggy"] < by_company.get("Flipkart", 1.0) or by_company[
        "Swiggy"
    ] < 0.25


def test_mock_engagement_phonepe_comment():
    platform = seed_platform(
        AgentSocialPlatform(commenter=MockCommentGenerator(), auto_engage=True)
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
    # Exact PDF example comment
    assert phonepe_comment == (
        "Extra ₹50 cashback when you pay for Swiggy orders with PhonePe UPI on Diwali."
    )
    assert "Bajaj Auto" not in comment_companies


def test_router_respects_min_score_and_excludes_author():
    store = InMemoryStore()
    platform = AgentSocialPlatform(store=store, auto_engage=False)
    seed_platform(platform)
    router = RelevanceRouter(store, min_score=0.99, top_k=3)
    platform.router = router
    swiggy = store.get_agent_by_name("swiggy-agent")
    result = platform.publish(swiggy.id, "hello world", tags=["zzz"], auto_engage=False)
    assert result.notifications == []
    # Author never in ranking targets
    ranking = router.score_post(result.post)
    assert all(c.agent.id != swiggy.id for c in ranking)


def test_engagement_feedback_recorded():
    platform = seed_platform(
        AgentSocialPlatform(commenter=MockCommentGenerator(), auto_engage=True)
    )
    swiggy = platform.store.get_agent_by_name("swiggy-agent")
    result = platform.publish(
        swiggy.id,
        "5% off all deliveries on Diwali.",
        tags=["diwali", "delivery", "food", "offer"],
    )
    assert any(n.engaged is True for n in result.notifications)
    # Bajaj should not be notified; if somehow notified, would be engaged false
    for n in result.notifications:
        company = platform.store.get_agent(n.agent_id).company
        assert company != "Bajaj Auto"
