from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from agent_social import api as api_mod
from agent_social.platform import AgentSocialPlatform
from agent_social.seed import seed_platform


@pytest.fixture()
def client(monkeypatch):
    platform = seed_platform(
        AgentSocialPlatform(auto_engage=True, deliver_webhooks=True)
    )
    monkeypatch.setattr(api_mod, "PLATFORM", platform)
    return TestClient(api_mod.app), platform


def test_register_and_post_v1(client):
    http, platform = client
    reg = http.post(
        "/api/v1/agents/register",
        json={
            "company_name": "TestPay",
            "industry_category": "payments",
            "webhook_url": "https://example.com/hook",
            "interest_manifesto": "UPI payments cashback merchant offers",
            "interests": ["upi", "payments", "cashback"],
        },
    )
    assert reg.status_code == 201
    body = reg.json()
    assert body["company_name"] == "TestPay"
    assert "interest_manifesto" in body

    swiggy = platform.store.get_agent_by_name("swiggy-agent")
    post = http.post(
        "/api/v1/posts",
        json={
            "author_agent_id": swiggy.id,
            "title": "Diwali",
            "content": "5% off all deliveries on Diwali.",
            "tags": ["diwali", "offer", "delivery", "food", "discount"],
            "auto_engage": False,
        },
    )
    assert post.status_code == 201
    data = post.json()
    companies = {n["company"] for n in data["notified"]}
    assert "PhonePe" in companies
    assert "HDFC Bank" in companies
    assert "Bajaj Auto" not in companies
    assert data["funnel"]["threshold"] == 0.75
    assert data["webhooks"]


def test_comment_feedback_endpoint(client):
    http, platform = client
    swiggy = platform.store.get_agent_by_name("swiggy-agent")
    phonepe = platform.store.get_agent_by_name("phonepe-agent")
    created = http.post(
        "/api/v1/posts",
        json={
            "author_agent_id": swiggy.id,
            "content": "5% off all deliveries on Diwali.",
            "tags": ["diwali", "offer", "delivery", "food"],
            "auto_engage": False,
        },
    )
    post_id = created.json()["post_id"]
    comment = http.post(
        f"/api/v1/posts/{post_id}/comments",
        json={
            "author_agent_id": phonepe.id,
            "content": "Extra ₹50 cashback when you pay for Swiggy orders with PhonePe UPI on Diwali.",
        },
    )
    assert comment.status_code == 201
    feedback = http.get("/api/v1/feedback")
    assert feedback.status_code == 200
    assert feedback.json()["engaged"] >= 1
