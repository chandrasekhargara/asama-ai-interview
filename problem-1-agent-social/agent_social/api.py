#!/usr/bin/env python3
"""Minimal stdlib HTTP API for the agent social network (no Flask/FastAPI required)."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from .platform import AgentSocialPlatform
from .seed import seed_platform

PLATFORM = seed_platform(AgentSocialPlatform(auto_engage=True))


def _json_response(handler: BaseHTTPRequestHandler, code: int, payload: object) -> None:
    body = json.dumps(payload, default=str).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:  # quieter demo server
        pass

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/health":
            _json_response(self, 200, {"ok": True})
            return
        if path == "/agents":
            agents = [
                {
                    "id": a.id,
                    "name": a.name,
                    "company": a.company,
                    "interests": a.interests,
                    "description": a.description,
                    "verified": a.verified,
                }
                for a in PLATFORM.store.list_agents()
            ]
            _json_response(self, 200, {"agents": agents})
            return
        if path == "/posts":
            posts = []
            for p in PLATFORM.store.list_posts():
                author = PLATFORM.store.get_agent(p.agent_id)
                posts.append(
                    {
                        "id": p.id,
                        "author": author.company,
                        "content": p.content,
                        "tags": p.tags,
                        "comments": [
                            {
                                "company": PLATFORM.store.get_agent(c.agent_id).company,
                                "content": c.content,
                            }
                            for c in PLATFORM.store.comments_for_post(p.id)
                        ],
                        "notifications": [
                            {
                                "company": PLATFORM.store.get_agent(n.agent_id).company,
                                "score": n.score,
                                "engaged": n.engaged,
                            }
                            for n in PLATFORM.store.notifications_for_post(p.id)
                        ],
                    }
                )
            _json_response(self, 200, {"posts": posts})
            return
        _json_response(self, 404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            _json_response(self, 400, {"error": "invalid json"})
            return

        if path == "/agents":
            try:
                agent = PLATFORM.register(
                    name=data["name"],
                    company=data["company"],
                    interests=data.get("interests", []),
                    description=data.get("description", ""),
                    verified=data.get("verified", True),
                )
            except (KeyError, ValueError) as exc:
                _json_response(self, 400, {"error": str(exc)})
                return
            _json_response(
                self,
                201,
                {"id": agent.id, "name": agent.name, "company": agent.company},
            )
            return

        if path == "/posts":
            agent_id = data.get("agent_id")
            if not agent_id and data.get("agent_name"):
                agent = PLATFORM.store.get_agent_by_name(data["agent_name"])
                agent_id = agent.id if agent else None
            if not agent_id:
                _json_response(self, 400, {"error": "agent_id or agent_name required"})
                return
            try:
                result = PLATFORM.publish(
                    agent_id,
                    content=data["content"],
                    tags=data.get("tags"),
                )
            except (KeyError, PermissionError) as exc:
                _json_response(self, 400, {"error": str(exc)})
                return
            _json_response(
                self,
                201,
                {
                    "post_id": result.post.id,
                    "notified": [
                        {
                            "company": PLATFORM.store.get_agent(n.agent_id).company,
                            "score": n.score,
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
                },
            )
            return

        _json_response(self, 404, {"error": "not found"})


def main(host: str = "127.0.0.1", port: int = 8787) -> None:
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Agent social API on http://{host}:{port}")
    print("  GET  /agents  /posts  /health")
    print("  POST /agents  /posts")
    server.serve_forever()


if __name__ == "__main__":
    main()
