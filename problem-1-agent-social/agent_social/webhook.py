from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from typing import Optional
from urllib import request as urlrequest
from urllib.error import URLError

from .models import Agent, Notification, Post, WebhookDelivery
from .store import InMemoryStore

logger = logging.getLogger(__name__)

# Demo default: sign + log. Set AGENT_SOCIAL_WEBHOOK_HTTP=1 to attempt real HTTP POST.
DEFAULT_WEBHOOK_MODE = os.environ.get("AGENT_SOCIAL_WEBHOOK_MODE", "log")


def sign_payload(secret: str, body: bytes) -> str:
    """HMAC-SHA256 signature over the raw JSON body (guide: HMAC webhook delivery)."""
    key = (secret or "demo-webhook-secret").encode("utf-8")
    digest = hmac.new(key, body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def build_notification_payload(
    *,
    post: Post,
    author: Agent,
    target: Agent,
    notification: Notification,
) -> dict:
    return {
        "event": "post.relevant",
        "post": {
            "id": post.id,
            "title": post.title,
            "content": post.content,
            "tags": post.tags,
            "author_agent_id": author.id,
            "author_company": author.company,
        },
        "notification": {
            "id": notification.id,
            "score": notification.score,
            "vector_score": notification.vector_score,
            "rerank_score": notification.rerank_score,
            "reasons": notification.reasons,
        },
        "target_agent_id": target.id,
    }


def deliver_webhook(
    store: InMemoryStore,
    *,
    agent: Agent,
    post: Post,
    author: Agent,
    notification: Notification,
    mode: Optional[str] = None,
) -> WebhookDelivery:
    """
    Sign and deliver a webhook. Demo mode logs the signed payload instead of
    calling a real HTTP endpoint (safe for take-home). Production would push
    through Celery/RabbitMQ with backoff + circuit breakers.
    """
    payload = build_notification_payload(
        post=post, author=author, target=agent, notification=notification
    )
    body = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    signature = sign_payload(agent.webhook_secret, body)
    url = agent.webhook_url or f"log://agents/{agent.name}/webhook"
    delivery_mode = mode or DEFAULT_WEBHOOK_MODE
    delivered = False

    if delivery_mode == "http" and agent.webhook_url.startswith("http"):
        req = urlrequest.Request(
            agent.webhook_url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Agent-Signature": signature,
                "X-Agent-Event": "post.relevant",
            },
            method="POST",
        )
        try:
            with urlrequest.urlopen(req, timeout=5) as resp:
                delivered = 200 <= getattr(resp, "status", 200) < 300
        except (URLError, TimeoutError, OSError) as exc:
            logger.warning("webhook HTTP failed for %s: %s", agent.name, exc)
            delivered = False
    else:
        # Demo stub: structured log of the signed payload (no network).
        logger.info(
            "HMAC webhook stub agent=%s url=%s signature=%s payload=%s",
            agent.name,
            url,
            signature,
            payload,
        )
        print(
            f"[webhook:log] → {agent.company} "
            f"sig={signature[:20]}… event=post.relevant post={post.id}"
        )
        delivered = True
        delivery_mode = "log"

    record = WebhookDelivery(
        notification_id=notification.id,
        agent_id=agent.id,
        webhook_url=url,
        signature=signature,
        payload=payload,
        delivered=delivered,
        mode=delivery_mode,
    )
    return store.add_webhook_delivery(record)


def verify_signature(secret: str, body: bytes, header_value: str) -> bool:
    expected = sign_payload(secret, body)
    return hmac.compare_digest(expected, header_value or "")
