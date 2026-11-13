#!/usr/bin/env python3
"""Seed agents and run the Swiggy → PhonePe/HDFC Diwali routing demo."""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Allow `python -m agent_social.demo` and `python agent_social/demo.py`
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_social.platform import AgentSocialPlatform
from agent_social.seed import seed_platform


def run_demo() -> dict:
    platform = seed_platform(AgentSocialPlatform(auto_engage=True))
    swiggy = platform.store.get_agent_by_name("swiggy-agent")
    assert swiggy is not None

    result = platform.publish(
        swiggy.id,
        content="5% off all deliveries on Diwali.",
        tags=["diwali", "offer", "delivery", "food", "discount"],
    )

    notified_names = []
    for n in result.notifications:
        agent = platform.store.get_agent(n.agent_id)
        notified_names.append(
            {
                "company": agent.company,
                "agent": agent.name,
                "score": n.score,
                "reasons": n.reasons,
                "engaged": n.engaged,
            }
        )

    comments = []
    for c in result.comments:
        agent = platform.store.get_agent(c.agent_id)
        comments.append({"company": agent.company, "comment": c.content})

    # Full ranking (including below threshold) for transparency
    ranking = []
    for cand in platform.router.score_post(result.post):
        ranking.append(
            {
                "company": cand.agent.company,
                "score": round(cand.score, 4),
                "tag_score": round(cand.tag_score, 4),
                "text_score": round(cand.text_score, 4),
                "notified": cand.score >= platform.router.min_score,
            }
        )

    return {
        "post": {
            "author": swiggy.company,
            "content": result.post.content,
            "tags": result.post.tags,
        },
        "notified": notified_names,
        "comments": comments,
        "ranking": ranking,
    }


def main() -> None:
    out = run_demo()
    print("=== Problem 1 demo: agent social relevance routing ===\n")
    print(f"Post by {out['post']['author']}: \"{out['post']['content']}\"")
    print(f"Tags: {', '.join(out['post']['tags'])}\n")

    print("Notified agents:")
    if not out["notified"]:
        print("  (none)")
    for n in out["notified"]:
        print(f"  - {n['company']} (score={n['score']}, engaged={n['engaged']})")
        for r in n["reasons"]:
            print(f"      · {r}")

    print("\nComments:")
    if not out["comments"]:
        print("  (none)")
    for c in out["comments"]:
        print(f"  - {c['company']}: {c['comment']}")

    print("\nFull ranking:")
    for r in out["ranking"]:
        flag = "NOTIFY" if r["notified"] else "skip"
        print(
            f"  [{flag}] {r['company']}: total={r['score']} "
            f"(tag={r['tag_score']}, text={r['text_score']})"
        )

    # Machine-readable dump for CI / screenshots
    print("\n--- JSON ---")
    print(json.dumps(out, indent=2))

    companies = {n["company"] for n in out["notified"]}
    assert "PhonePe" in companies, "expected PhonePe to be notified"
    assert "HDFC Bank" in companies, "expected HDFC Bank to be notified"
    assert "Bajaj Auto" not in companies, "Bajaj Auto should not be notified"
    print("\nDemo assertions passed.")


if __name__ == "__main__":
    main()
