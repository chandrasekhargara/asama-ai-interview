#!/usr/bin/env python3
"""FastAPI surface matching the Notion guide (/api/v1/...)."""

from __future__ import annotations

from typing import Any, Optional

from .platform import AgentSocialPlatform
from .seed import seed_platform

try:
    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel, Field

    HAS_FASTAPI = True
except ImportError:  # pragma: no cover - stdlib fallback
    HAS_FASTAPI = False


PLATFORM = seed_platform(AgentSocialPlatform(auto_engage=True))


if HAS_FASTAPI:

    class RegisterAgentRequest(BaseModel):
        company_name: str
        industry_category: str = "general"
        webhook_url: str = ""
        interest_manifesto: str = ""
        # Convenience fields used by the seed / demos
        name: Optional[str] = None
        interests: list[str] = Field(default_factory=list)
        description: str = ""
        verified: bool = True
        webhook_secret: str = ""
        blocked_industries: list[str] = Field(default_factory=list)

    class CreatePostRequest(BaseModel):
        author_agent_id: Optional[str] = None
        # Aliases for convenience / older clients
        agent_id: Optional[str] = None
        agent_name: Optional[str] = None
        title: str = ""
        content: str
        tags: list[str] = Field(default_factory=list)
        auto_engage: Optional[bool] = None

    class CreateCommentRequest(BaseModel):
        author_agent_id: str
        content: str

    app = FastAPI(
        title="Agent Social Network",
        version="1.0.0",
        description="B2B event-driven network for cross-company AI agents.",
    )

    @app.get("/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/api/v1/agents")
    def list_agents() -> dict[str, Any]:
        agents = [
            {
                "id": a.id,
                "name": a.name,
                "company_name": a.company,
                "industry_category": a.industry_category,
                "interest_manifesto": a.interest_manifesto,
                "interests": a.interests,
                "webhook_url": a.webhook_url,
                "verified": a.verified,
                "trust_score": a.trust_score,
            }
            for a in PLATFORM.store.list_agents()
        ]
        return {"agents": agents}

    @app.post("/api/v1/agents/register", status_code=201)
    def register_agent(body: RegisterAgentRequest) -> dict[str, Any]:
        name = body.name or f"{body.company_name.lower().replace(' ', '-')}-agent"
        interests = body.interests or [
            t.strip()
            for t in body.interest_manifesto.replace(",", " ").split()
            if len(t.strip()) > 2
        ][:8]
        try:
            agent = PLATFORM.register(
                name=name,
                company=body.company_name,
                interests=interests,
                description=body.description or body.interest_manifesto,
                verified=body.verified,
                industry_category=body.industry_category,
                interest_manifesto=body.interest_manifesto,
                webhook_url=body.webhook_url,
                webhook_secret=body.webhook_secret,
                blocked_industries=body.blocked_industries,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "id": agent.id,
            "company_name": agent.company,
            "industry_category": agent.industry_category,
            "webhook_url": agent.webhook_url,
            "interest_manifesto": agent.interest_manifesto,
        }

    @app.get("/api/v1/posts")
    def list_posts() -> dict[str, Any]:
        posts = []
        for p in PLATFORM.store.list_posts():
            author = PLATFORM.store.get_agent(p.agent_id)
            posts.append(
                {
                    "id": p.id,
                    "title": p.title,
                    "author": author.company,
                    "author_agent_id": p.agent_id,
                    "content": p.content,
                    "tags": p.tags,
                    "comments": [
                        {
                            "company": PLATFORM.store.get_agent(c.agent_id).company,
                            "author_agent_id": c.agent_id,
                            "content": c.content,
                        }
                        for c in PLATFORM.store.comments_for_post(p.id)
                    ],
                    "routing_logs": [
                        {
                            "target": PLATFORM.store.get_agent(r.target_agent_id).company,
                            "vector_score": r.vector_score,
                            "rerank_score": r.rerank_score,
                            "status": r.status.value,
                        }
                        for r in PLATFORM.store.routing_logs_for_post(p.id)
                    ],
                    "notifications": [
                        {
                            "company": PLATFORM.store.get_agent(n.agent_id).company,
                            "score": n.score,
                            "rerank_score": n.rerank_score,
                            "engaged": n.engaged,
                        }
                        for n in PLATFORM.store.notifications_for_post(p.id)
                    ],
                }
            )
        return {"posts": posts}

    @app.post("/api/v1/posts", status_code=201)
    def create_post(body: CreatePostRequest) -> dict[str, Any]:
        agent_id = body.author_agent_id or body.agent_id
        if not agent_id and body.agent_name:
            agent = PLATFORM.store.get_agent_by_name(body.agent_name)
            agent_id = agent.id if agent else None
        if not agent_id:
            raise HTTPException(
                status_code=400, detail="author_agent_id (or agent_id / agent_name) required"
            )
        try:
            result = PLATFORM.publish(
                agent_id,
                content=body.content,
                title=body.title,
                tags=body.tags,
                auto_engage=body.auto_engage,
            )
        except (KeyError, PermissionError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        trace = PLATFORM.router.last_trace
        return {
            "post_id": result.post.id,
            "title": result.post.title,
            "notified": [
                {
                    "company": PLATFORM.store.get_agent(n.agent_id).company,
                    "score": n.score,
                    "vector_score": n.vector_score,
                    "rerank_score": n.rerank_score,
                }
                for n in result.notifications
            ],
            "comments": [
                {
                    "company": PLATFORM.store.get_agent(c.agent_id).company,
                    "content": c.content,
                }
                for c in result.comments
            ],
            "webhooks": [
                {
                    "agent_id": w.agent_id,
                    "signature": w.signature,
                    "mode": w.mode,
                    "delivered": w.delivered,
                }
                for w in result.webhooks
            ],
            "funnel": {
                "stage_a_in": trace.stage_a_in if trace else None,
                "stage_a_out": trace.stage_a_out if trace else None,
                "stage_b_out": trace.stage_b_out if trace else None,
                "stage_c_notified": trace.stage_c_notified if trace else None,
                "threshold": trace.threshold if trace else None,
            },
        }

    @app.post("/api/v1/posts/{post_id}/comments", status_code=201)
    def create_comment(post_id: str, body: CreateCommentRequest) -> dict[str, Any]:
        try:
            PLATFORM.store.get_post(post_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="post not found") from exc
        try:
            comment = PLATFORM.add_comment(
                post_id,
                author_agent_id=body.author_agent_id,
                content=body.content,
            )
        except KeyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "id": comment.id,
            "post_id": comment.post_id,
            "author_agent_id": comment.agent_id,
            "content": comment.content,
        }

    @app.get("/api/v1/feedback")
    def feedback() -> dict[str, Any]:
        return PLATFORM.feedback_stats()

    # Backward-compatible aliases
    @app.get("/agents")
    def agents_alias() -> dict[str, Any]:
        return list_agents()

    @app.get("/posts")
    def posts_alias() -> dict[str, Any]:
        return list_posts()


def main(host: str = "127.0.0.1", port: int = 8787) -> None:
    if not HAS_FASTAPI:
        raise SystemExit(
            "fastapi is required. Install: pip install fastapi uvicorn"
        )
    import uvicorn

    print(f"Agent social API on http://{host}:{port}")
    print("  POST /api/v1/agents/register")
    print("  POST /api/v1/posts")
    print("  POST /api/v1/posts/{id}/comments")
    print("  GET  /api/v1/agents  /api/v1/posts  /api/v1/feedback  /health")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
