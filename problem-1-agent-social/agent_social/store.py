from __future__ import annotations

from typing import Optional

from .models import (
    Agent,
    Comment,
    Notification,
    Post,
    RoutingLog,
    RoutingStatus,
    WebhookDelivery,
)


class InMemoryStore:
    """Simple in-memory persistence suitable for demos and tests."""

    def __init__(self) -> None:
        self.agents: dict[str, Agent] = {}
        self.posts: dict[str, Post] = {}
        self.comments: dict[str, Comment] = {}
        self.notifications: dict[str, Notification] = {}
        self.routing_logs: dict[str, RoutingLog] = {}
        self.webhook_deliveries: dict[str, WebhookDelivery] = {}
        self._name_index: dict[str, str] = {}

    def register_agent(self, agent: Agent) -> Agent:
        key = agent.name.lower()
        if key in self._name_index:
            raise ValueError(f"agent already registered: {agent.name}")
        self.agents[agent.id] = agent
        self._name_index[key] = agent.id
        return agent

    def get_agent(self, agent_id: str) -> Agent:
        return self.agents[agent_id]

    def get_agent_by_name(self, name: str) -> Optional[Agent]:
        aid = self._name_index.get(name.lower())
        return self.agents.get(aid) if aid else None

    def list_agents(self) -> list[Agent]:
        return list(self.agents.values())

    def create_post(self, post: Post) -> Post:
        if post.agent_id not in self.agents:
            raise KeyError(f"unknown agent: {post.agent_id}")
        self.posts[post.id] = post
        return post

    def get_post(self, post_id: str) -> Post:
        return self.posts[post_id]

    def list_posts(self) -> list[Post]:
        return sorted(self.posts.values(), key=lambda p: p.created_at)

    def add_comment(self, comment: Comment) -> Comment:
        if comment.post_id not in self.posts:
            raise KeyError(f"unknown post: {comment.post_id}")
        if comment.agent_id not in self.agents:
            raise KeyError(f"unknown agent: {comment.agent_id}")
        self.comments[comment.id] = comment
        return comment

    def comments_for_post(self, post_id: str) -> list[Comment]:
        return [c for c in self.comments.values() if c.post_id == post_id]

    def add_notification(self, notification: Notification) -> Notification:
        self.notifications[notification.id] = notification
        return notification

    def notifications_for_agent(self, agent_id: str) -> list[Notification]:
        return [n for n in self.notifications.values() if n.agent_id == agent_id]

    def notifications_for_post(self, post_id: str) -> list[Notification]:
        return [n for n in self.notifications.values() if n.post_id == post_id]

    def mark_engagement(self, notification_id: str, engaged: bool) -> Notification:
        n = self.notifications[notification_id]
        n.engaged = engaged
        return n

    def add_routing_log(self, log: RoutingLog) -> RoutingLog:
        self.routing_logs[log.id] = log
        return log

    def routing_logs_for_post(self, post_id: str) -> list[RoutingLog]:
        return [r for r in self.routing_logs.values() if r.post_id == post_id]

    def update_routing_status(
        self, post_id: str, target_agent_id: str, status: RoutingStatus
    ) -> Optional[RoutingLog]:
        for log in self.routing_logs.values():
            if log.post_id == post_id and log.target_agent_id == target_agent_id:
                log.status = status
                return log
        return None

    def add_webhook_delivery(self, delivery: WebhookDelivery) -> WebhookDelivery:
        self.webhook_deliveries[delivery.id] = delivery
        return delivery

    def engagement_stats(self) -> dict:
        """Feedback hook: engagement rate for closed-loop routing."""
        logs = list(self.routing_logs.values())
        notified = [r for r in logs if r.status in {
            RoutingStatus.NOTIFIED, RoutingStatus.ENGAGED, RoutingStatus.IGNORED
        }]
        engaged = [r for r in logs if r.status == RoutingStatus.ENGAGED]
        ignored = [r for r in logs if r.status == RoutingStatus.IGNORED]
        return {
            "routing_log_count": len(logs),
            "notified_or_outcome": len(notified),
            "engaged": len(engaged),
            "ignored": len(ignored),
            "engagement_rate": (len(engaged) / len(notified)) if notified else 0.0,
        }
