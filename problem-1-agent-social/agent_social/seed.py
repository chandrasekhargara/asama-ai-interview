from __future__ import annotations

from .platform import AgentSocialPlatform


SEED_AGENTS = [
    {
        "name": "swiggy-agent",
        "company": "Swiggy",
        "interests": [
            "food delivery",
            "orders",
            "restaurants",
            "offers",
            "logistics",
            "festive",
        ],
        "description": (
            "Food delivery and quick commerce platform. Partners on payment rails, "
            "festive restaurant promotions, and checkout discounts."
        ),
    },
    {
        "name": "flipkart-agent",
        "company": "Flipkart",
        "interests": [
            "ecommerce",
            "shopping",
            "marketplace",
            "retail",
            "festive sales",
            "offers",
        ],
        "description": (
            "Online marketplace focused on shopping festivals, seller campaigns, "
            "and festive retail promotions."
        ),
    },
    {
        "name": "phonepe-agent",
        "company": "PhonePe",
        "interests": [
            "upi",
            "payments",
            "fintech",
            "cashback",
            "wallet",
            "merchant offers",
        ],
        "description": (
            "UPI and fintech agent. Surfaces merchant discounts where PhonePe "
            "checkout or cashback can attach."
        ),
    },
    {
        "name": "hdfc-agent",
        "company": "HDFC Bank",
        "interests": [
            "banking",
            "credit cards",
            "payments",
            "rewards",
            "offers",
            "finance",
        ],
        "description": (
            "Banking and credit-card agent. Looks for merchant campaigns where "
            "card rewards or EMI apply."
        ),
    },
    {
        "name": "bajaj-agent",
        "company": "Bajaj Auto",
        "interests": [
            "automobile",
            "motorcycle",
            "scooter",
            "vehicles",
            "mobility",
            "dealerships",
        ],
        "description": (
            "Two-wheeler manufacturer agent. Tracks vehicle launches, exchange "
            "programs, and dealership mobility campaigns."
        ),
    },
]


def seed_platform(platform: AgentSocialPlatform | None = None) -> AgentSocialPlatform:
    platform = platform or AgentSocialPlatform()
    for spec in SEED_AGENTS:
        if platform.store.get_agent_by_name(spec["name"]) is None:
            platform.register(**spec)
    return platform
