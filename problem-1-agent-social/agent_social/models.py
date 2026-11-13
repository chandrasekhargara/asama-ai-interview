from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
import uuid


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


@dataclass
class Agent:
    name: str
    company: str
    interests: list[str]
    description: str
    id: str = field(default_factory=lambda: _id("agt"))
    verified: bool = True
    created_at: datetime = field(default_factory=_now)

    def interest_text(self) -> str:
        return " ".join(self.interests) + " " + self.description


@dataclass
class Post:
    agent_id: str
    content: str
    tags: list[str] = field(default_factory=list)
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
    id: str = field(default_factory=lambda: _id("ntf"))
    created_at: datetime = field(default_factory=_now)
