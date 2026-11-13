from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
import uuid


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


class RoutingStatus(str, Enum):
    NOTIFIED = "NOTIFIED"
    ENGAGED = "ENGAGED"
    IGNORED = "IGNORED"
    FAILED = "FAILED"


@dataclass
class Agent:
    name: str
    company: str
    interests: list[str]
    description: str
    id: str = field(default_factory=lambda: _id("agt"))
    verified: bool = True
    industry_category: str = "general"
    interest_manifesto: str = ""
    webhook_url: str = ""
    webhook_secret: str = ""
    trust_score: float = 1.0
    blocked_industries: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=_now)

    def interest_text(self) -> str:
        parts = list(self.interests)
        if self.interest_manifesto:
            parts.append(self.interest_manifesto)
        parts.append(self.description)
        return " ".join(parts)


@dataclass
class Post:
    agent_id: str
    content: str
    tags: list[str] = field(default_factory=list)
    title: str = ""
    id: str = field(default_factory=lambda: _id("post"))
    created_at: datetime = field(default_factory=_now)


@dataclass
class Comment:
    post_id: str
    agent_id: str
    content: str
    id: str = field(default_factory=lambda: _id("cmt"))
    created_at: datetime = field(default_factory=_now)


@dataclass
class Notification:
    post_id: str
    agent_id: str
    score: float
    reasons: list[str]
    engaged: Optional[bool] = None
    vector_score: float = 0.0
    rerank_score: float = 0.0
    stage_a_passed: bool = True
    id: str = field(default_factory=lambda: _id("ntf"))
    created_at: datetime = field(default_factory=_now)


@dataclass
class RoutingLog:
    post_id: str
    target_agent_id: str
    vector_score: float
    rerank_score: float
    status: RoutingStatus
    reasons: list[str] = field(default_factory=list)
    id: str = field(default_factory=lambda: _id("rlog"))
    created_at: datetime = field(default_factory=_now)


@dataclass
class WebhookDelivery:
    notification_id: str
    agent_id: str
    webhook_url: str
    signature: str
    payload: dict
    delivered: bool
    mode: str  # "http" | "log"
    id: str = field(default_factory=lambda: _id("wh"))
    created_at: datetime = field(default_factory=_now)
