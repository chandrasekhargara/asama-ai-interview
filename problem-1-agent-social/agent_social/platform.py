from __future__ import annotations

from dataclasses import dataclass

from .llm import CommentGenerator, build_comment_generator
from .models import Agent, Comment, Notification, Post, RoutingStatus
from .router import RelevanceRouter
from .store import InMemoryStore
from .webhook import deliver_webhook


@dataclass
class PublishResult:
    post: Post
    notifications: list[Notification]
    comments: list[Comment]
    webhooks: list = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.webhooks is None:
            self.webhooks = []


class AgentSocialPlatform:
    """Orchestrates register → post → multi-stage route → HMAC notify → comment."""

    def __init__(
        self,
        store: InMemoryStore | None = None,
        router: RelevanceRouter | None = None,
        commenter: CommentGenerator | None = None,
        *,
        auto_engage: bool = True,
        deliver_webhooks: bool = True,
    ) -> None:
        self.store = store or InMemoryStore()
        self.router = router or RelevanceRouter(self.store)
        self.commenter = commenter or build_comment_generator()
        self.auto_engage = auto_engage
        self.deliver_webhooks = deliver_webhooks

    def register(
        self,
        *,
        name: str,
        company: str,
        interests: list[str],
        description: str,
        verified: bool = True,
        industry_category: str = "general",
        interest_manifesto: str = "",
        webhook_url: str = "",
        webhook_secret: str = "",
        trust_score: float = 1.0,
        blocked_industries: list[str] | None = None,
    ) -> Agent:
        manifesto = interest_manifesto or (
            f"{company} agent focusing on: {', '.join(interests)}. {description}"
        )
        agent = Agent(
            name=name,
            company=company,
            interests=[i.strip().lower() for i in interests],
            description=description,
            verified=verified,
            industry_category=industry_category,
            interest_manifesto=manifesto,
            webhook_url=webhook_url or f"https://agents.example/{name}/hooks",
            webhook_secret=webhook_secret or f"whsec_{name}",
            trust_score=trust_score,
            blocked_industries=[b.lower() for b in (blocked_industries or [])],
        )
        return self.store.register_agent(agent)

    def publish(
        self,
        agent_id: str,
        content: str,
        tags: list[str] | None = None,
        *,
        title: str = "",
        auto_engage: bool | None = None,
    ) -> PublishResult:
        author = self.store.get_agent(agent_id)
        if not author.verified:
            raise PermissionError(f"unverified agent cannot post: {author.name}")

        post = self.store.create_post(
            Post(
                agent_id=agent_id,
                content=content,
                title=title,
                tags=[t.strip().lower() for t in (tags or [])],
            )
        )
        notifications = self.router.route(post)
        comments: list[Comment] = []
        webhooks = []

        if self.deliver_webhooks:
            for n in notifications:
                target = self.store.get_agent(n.agent_id)
                webhooks.append(
                    deliver_webhook(
                        self.store,
                        agent=target,
                        post=post,
                        author=author,
                        notification=n,
                    )
                )

        should_engage = self.auto_engage if auto_engage is None else auto_engage
        if should_engage:
            for n in notifications:
                agent = self.store.get_agent(n.agent_id)
                body = self.commenter.generate(agent, post, author)
                engaged = body is not None
                self.record_engagement(n.id, engaged=engaged, comment_body=body)
                if body:
                    comments.append(
                        self.store.add_comment(
                            Comment(post_id=post.id, agent_id=agent.id, content=body)
                        )
                    )

        return PublishResult(
            post=post,
            notifications=notifications,
            comments=comments,
            webhooks=webhooks,
        )

    def add_comment(
        self,
        post_id: str,
        *,
        author_agent_id: str,
        content: str,
    ) -> Comment:
        """API-facing comment path; also records ENGAGED feedback."""
        comment = self.store.add_comment(
            Comment(post_id=post_id, agent_id=author_agent_id, content=content)
        )
        # Feedback hook: commenting after notify → ENGAGED
        for n in self.store.notifications_for_post(post_id):
            if n.agent_id == author_agent_id:
                self.record_engagement(n.id, engaged=True)
                break
        return comment

    def record_engagement(
        self,
        notification_id: str,
        *,
        engaged: bool,
        comment_body: str | None = None,
    ) -> None:
        """Closed-loop feedback: update notification + routing_log status."""
        n = self.store.mark_engagement(notification_id, engaged)
        status = RoutingStatus.ENGAGED if engaged else RoutingStatus.IGNORED
        self.store.update_routing_status(n.post_id, n.agent_id, status)

    def feedback_stats(self) -> dict:
        return self.store.engagement_stats()
