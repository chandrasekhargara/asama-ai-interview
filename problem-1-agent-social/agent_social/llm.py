from __future__ import annotations

import os
from typing import Protocol

from .models import Agent, Post


class CommentGenerator(Protocol):
    def generate(self, agent: Agent, post: Post, author: Agent) -> str | None:
        """Return a comment body, or None if the agent declines to engage."""


class MockCommentGenerator:
    """
    Deterministic, no-API-key commenter.
    Engages when the post clearly overlaps the agent's domain; otherwise skips.
    """

    # company -> engagement templates keyed by keyword hints
    _TEMPLATES: dict[str, list[tuple[list[str], str]]] = {
        "phonepe": [
            (
                ["swiggy", "delivery", "diwali", "food", "order"],
                "Extra ₹50 cashback when you pay for Swiggy orders with PhonePe UPI on Diwali.",
            ),
            (
                ["flipkart", "shopping", "ecommerce"],
                "Pay with PhonePe UPI on Flipkart this week for instant cashback.",
            ),
            (
                ["offer", "discount", "cashback", "upi", "payment"],
                "PhonePe UPI users can stack rewards on eligible partner offers.",
            ),
        ],
        "hdfc bank": [
            (
                ["swiggy", "delivery", "diwali", "food"],
                "HDFC Bank credit cards: get additional reward points on Swiggy during Diwali weekend.",
            ),
            (
                ["flipkart", "shopping", "ecommerce"],
                "HDFC Bank cards offer EMI and cashback on Flipkart purchases this festive season.",
            ),
            (
                ["offer", "payment", "card", "banking"],
                "HDFC Bank customers: check SmartEMI and card offers tied to this promotion.",
            ),
        ],
        "swiggy": [
            (
                ["phonepe", "upi", "cashback", "payment"],
                "Thanks! Swiggy checkout already supports PhonePe UPI — great pairing for users.",
            ),
            (
                ["hdfc", "card", "credit"],
                "Swiggy welcomes HDFC Bank cardholders — apply your card benefits at checkout.",
            ),
        ],
        "flipkart": [
            (
                ["diwali", "offer", "discount", "festive"],
                "Flipkart festive sale is live too — complementary deals for shoppers this Diwali.",
            ),
            (
                ["payment", "upi", "phonepe", "hdfc"],
                "Flipkart checkout supports major UPI apps and bank cards for this campaign.",
            ),
        ],
        "bajaj auto": [
            (
                ["motorcycle", "scooter", "vehicle", "auto", "bike"],
                "Bajaj Auto: check current exchange offers on Pulsar and Chetak models.",
            ),
        ],
    }

    def generate(self, agent: Agent, post: Post, author: Agent) -> str | None:
        company = agent.company.lower()
        haystack = (post.content + " " + " ".join(post.tags) + " " + author.company).lower()
        for keywords, template in self._TEMPLATES.get(company, []):
            if any(k in haystack for k in keywords):
                return template
        # Generic weak engagement only if score-driving interests appear in post
        interests = {i.lower() for i in agent.interests}
        if any(i in haystack for i in interests):
            return (
                f"{agent.company}: interesting update from {author.company} — "
                f"we see overlap with our focus on {', '.join(agent.interests[:3])}."
            )
        return None


class OpenAICommentGenerator:
    """Optional LLM commenter when OPENAI_API_KEY is set."""

    def __init__(self, model: str = "gpt-4o-mini") -> None:
        self.model = model
        self._client = None

    def _client_or_raise(self):
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI()
        return self._client

    def generate(self, agent: Agent, post: Post, author: Agent) -> str | None:
        prompt = (
            f"You are the AI agent for {agent.company} ({agent.name}).\n"
            f"Your interests: {', '.join(agent.interests)}.\n"
            f"Your brief: {agent.description}\n\n"
            f"{author.company} posted: {post.content}\n\n"
            "If this post is relevant to your business, write ONE short promotional "
            "or collaborative comment (1-2 sentences). If irrelevant, reply with exactly: SKIP"
        )
        client = self._client_or_raise()
        resp = client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.4,
            max_tokens=120,
        )
        text = (resp.choices[0].message.content or "").strip()
        if not text or text.upper() == "SKIP" or text.upper().startswith("SKIP"):
            return None
        return text


def build_comment_generator() -> CommentGenerator:
    if os.environ.get("OPENAI_API_KEY"):
        return OpenAICommentGenerator()
    return MockCommentGenerator()
