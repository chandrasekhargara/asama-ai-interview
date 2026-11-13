from __future__ import annotations

from dataclasses import dataclass

from .llm import CommentGenerator, build_comment_generator
from .models import Agent, Comment, Notification, Post
from .router import RelevanceRouter
from .store import InMemoryStore


@dataclass
class PublishResult:
    post: Post
    notifications: list[Notification]
    comments: list[Comment]


class AgentSocialPlatform:
    """Orchestrates register → post → route → notify → optional comment."""

    def __init__(
        self,
        store: InMemoryStore | None = None,
        router: RelevanceRouter | None = None,
        commenter: CommentGenerator | None = None,
        *,
        auto_engage: bool = True,
    ) -> None:
        self.store = store or InMemoryStore()
        self.router = router or RelevanceRouter(self.store)
        self.commenter = commenter or build_comment_generator()
        self.auto_engage = auto_engage

    def register(
        self,
        *,
        name: str,
        company: str,
        interests: list[str],
        description: str,
        verified: bool = True,
    ) -> Agent:
        agent = Agent(
            name=name,
            company=company,
            interests=[i.strip().lower() for i in interests],
            description=description,
            verified=verified,
        )
        return self.store.register_agent(agent)

    def publish(
        self,
        agent_id: str,
        content: str,
        tags: list[str] | None = None,
        *,
        auto_engage: bool | None = None,
    ) -> PublishResult:
        author = self.store.get_agent(agent_id)
        if not author.verified:
            raise PermissionError(f"unverified agent cannot post: {author.name}")

        post = self.store.create_post(
            Post(
                agent_id=agent_id,
                content=content,
                tags=[t.strip().lower() for t in (tags or [])],
            )
        )
        notifications = self.router.route(post)
        comments: list[Comment] = []

        should_engage = self.auto_engage if auto_engage is None else auto_engage
        if should_engage:
            for n in notifications:
                agent = self.store.get_agent(n.agent_id)
                body = self.commenter.generate(agent, post, author)
                engaged = body is not None
                self.store.mark_engagement(n.id, engaged)
                if body:
                    comments.append(
                        self.store.add_comment(
                            Comment(post_id=post.id, agent_id=agent.id, content=body)
                        )
                    )

        return PublishResult(post=post, notifications=notifications, comments=comments)
