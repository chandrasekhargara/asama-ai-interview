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
    platform = seed_platform(AgentSocialPlatform(auto_engage=True, deliver_webhooks=True))
    swiggy = platform.store.get_agent_by_name("swiggy-agent")
    assert swiggy is not None

    result = platform.publish(
        swiggy.id,
        title="Diwali delivery offer",
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
                "vector_score": n.vector_score,
                "rerank_score": n.rerank_score,
                "reasons": n.reasons,
                "engaged": n.engaged,
            }
        )

    comments = []
    for c in result.comments:
        agent = platform.store.get_agent(c.agent_id)
        comments.append({"company": agent.company, "comment": c.content})

    ranking = []
    for cand in platform.router.score_post(result.post):
        ranking.append(
            {
                "company": cand.agent.company,
                "score": round(cand.score, 4),
                "vector_score": round(cand.vector_score, 4),
                "rerank_score": round(cand.rerank_score, 4),
                "tag_score": round(cand.tag_score, 4),
                "text_score": round(cand.text_score, 4),
                "stage_a_passed": cand.stage_a_passed,
                "notified": cand.stage_a_passed
                and cand.rerank_score >= platform.router.min_score,
            }
        )

    routing_logs = [
        {
            "target": platform.store.get_agent(r.target_agent_id).company,
            "vector_score": r.vector_score,
            "rerank_score": r.rerank_score,
            "status": r.status.value,
        }
        for r in platform.store.routing_logs_for_post(result.post.id)
    ]

    webhooks = [
        {
            "company": platform.store.get_agent(w.agent_id).company,
            "signature": w.signature,
            "mode": w.mode,
            "delivered": w.delivered,
        }
        for w in result.webhooks
    ]

    trace = platform.router.last_trace
    return {
        "post": {
            "author": swiggy.company,
            "title": result.post.title,
            "content": result.post.content,
            "tags": result.post.tags,
        },
        "funnel": {
            "stage_a_in": trace.stage_a_in if trace else None,
            "stage_a_out": trace.stage_a_out if trace else None,
            "stage_b_out": trace.stage_b_out if trace else None,
            "stage_c_notified": trace.stage_c_notified if trace else None,
            "threshold": trace.threshold if trace else None,
        },
        "notified": notified_names,
        "comments": comments,
        "routing_logs": routing_logs,
        "webhooks": webhooks,
        "feedback": platform.feedback_stats(),
        "ranking": ranking,
    }


def main() -> None:
    out = run_demo()
    print("=== Problem 1 demo: PDF Swiggy Diwali routing ===\n")
    print("Expect: notify PhonePe + HDFC Bank; skip Bajaj Auto.")
    print("Expect PhonePe comment: Extra ₹50 cashback … PhonePe UPI on Diwali.\n")
    print(f"Post by {out['post']['author']}: \"{out['post']['content']}\"")
    print(f"Tags: {', '.join(out['post']['tags'])}\n")

    f = out["funnel"]
    print(
        "3-tier funnel: "
        f"N={f['stage_a_in']} → Stage A → {f['stage_a_out']} → "
        f"Stage B → {f['stage_b_out']} → Stage C (≥{f['threshold']}) → "
        f"{f['stage_c_notified']} notified"
    )

    print("\nNotified agents:")
    if not out["notified"]:
        print("  (none)")
    for n in out["notified"]:
        print(
            f"  - {n['company']} (rerank={n['rerank_score']}, "
            f"vector={n['vector_score']}, engaged={n['engaged']})"
        )
        for r in n["reasons"]:
            print(f"      · {r}")

    print("\nRouting logs:")
    for r in out["routing_logs"]:
        print(
            f"  - {r['target']}: status={r['status']} "
            f"vector={r['vector_score']} rerank={r['rerank_score']}"
        )

    print("\nHMAC webhooks (demo log mode):")
    for w in out["webhooks"]:
        print(f"  - {w['company']}: {w['signature'][:28]}… mode={w['mode']}")

    print("\nComments:")
    if not out["comments"]:
        print("  (none)")
    for c in out["comments"]:
        print(f"  - {c['company']}: {c['comment']}")

    print("\nFull ranking:")
    for r in out["ranking"]:
        flag = "NOTIFY" if r["notified"] else ("SKIP-A" if not r["stage_a_passed"] else "skip")
        print(
            f"  [{flag}] {r['company']}: rerank={r['rerank_score']} "
            f"(vector={r['vector_score']}, concept={r['tag_score']}, text={r['text_score']})"
        )

    print("\nFeedback:", json.dumps(out["feedback"]))
    print("\n--- JSON ---")
    print(json.dumps(out, indent=2))

    companies = {n["company"] for n in out["notified"]}
    assert companies == {"PhonePe", "HDFC Bank"}, f"unexpected notify set: {companies}"
    assert "Bajaj Auto" not in companies, "Bajaj Auto should not be notified"
    phonepe = next(c["comment"] for c in out["comments"] if c["company"] == "PhonePe")
    assert phonepe == (
        "Extra ₹50 cashback when you pay for Swiggy orders with PhonePe UPI on Diwali."
    )
    assert all(n["rerank_score"] >= 0.75 for n in out["notified"])
    print("\nDemo assertions passed (PDF example + Stage-C ≥ 0.75).")


if __name__ == "__main__":
    main()
