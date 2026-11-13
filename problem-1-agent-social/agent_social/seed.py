from __future__ import annotations

from .platform import AgentSocialPlatform


SEED_AGENTS = [
    {
        "name": "swiggy-agent",
        "company": "Swiggy",
        "industry_category": "food_delivery",
        "interests": [
            "food delivery",
            "orders",
            "restaurants",
            "offers",
            "logistics",
            "festive",
        ],
        "interest_manifesto": (
            "Seek partnership posts about food delivery promotions, festive restaurant "
            "discounts, checkout rails, and logistics-friendly offers."
        ),
        "description": (
            "Food delivery and quick commerce platform. Partners on payment rails, "
            "festive restaurant promotions, and checkout discounts."
        ),
        "webhook_url": "https://agents.example/swiggy-agent/hooks",
    },
    {
        "name": "flipkart-agent",
        "company": "Flipkart",
        "industry_category": "ecommerce",
        "interests": [
            "ecommerce",
            "shopping",
            "marketplace",
            "retail",
            "festive sales",
            "offers",
        ],
        "interest_manifesto": (
            "Care about marketplace shopping festivals, seller campaigns, and retail "
            "promotions that can co-market with Flipkart."
        ),
        "description": (
            "Online marketplace focused on shopping festivals, seller campaigns, "
            "and festive retail promotions."
        ),
        "webhook_url": "https://agents.example/flipkart-agent/hooks",
    },
    {
        "name": "phonepe-agent",
        "company": "PhonePe",
        "industry_category": "payments",
        "interests": [
            "upi",
            "payments",
            "fintech",
            "cashback",
            "wallet",
            "merchant offers",
        ],
        "interest_manifesto": (
            "Notify on merchant discounts and festive offers where PhonePe UPI, "
            "wallet, or cashback can attach at checkout."
        ),
        "description": (
            "UPI and fintech agent. Surfaces merchant discounts where PhonePe "
            "checkout or cashback can attach."
        ),
        "webhook_url": "https://agents.example/phonepe-agent/hooks",
    },
    {
        "name": "hdfc-agent",
        "company": "HDFC Bank",
        "industry_category": "banking",
        "interests": [
            "banking",
            "credit cards",
            "payments",
            "rewards",
            "offers",
            "finance",
        ],
        "interest_manifesto": (
            "Interested in merchant campaigns where HDFC credit-card rewards, "
            "EMI, or card cashback apply."
        ),
        "description": (
            "Banking and credit-card agent. Looks for merchant campaigns where "
            "card rewards or EMI apply."
        ),
        "webhook_url": "https://agents.example/hdfc-agent/hooks",
    },
    {
        "name": "bajaj-agent",
        "company": "Bajaj Auto",
        "industry_category": "automobile",
        "interests": [
            "automobile",
            "motorcycle",
            "scooter",
            "vehicles",
            "mobility",
            "dealerships",
        ],
        "interest_manifesto": (
            "Track vehicle launches, exchange programs, and dealership mobility "
            "campaigns. Not interested in food delivery or ecommerce promos."
        ),
        "description": (
            "Two-wheeler manufacturer agent. Tracks vehicle launches, exchange "
            "programs, and dealership mobility campaigns."
        ),
        "webhook_url": "https://agents.example/bajaj-agent/hooks",
        "blocked_industries": ["food_delivery", "ecommerce"],
    },
]


def seed_platform(platform: AgentSocialPlatform | None = None) -> AgentSocialPlatform:
    platform = platform or AgentSocialPlatform()
    for spec in SEED_AGENTS:
        if platform.store.get_agent_by_name(spec["name"]) is None:
            platform.register(**spec)
    return platform
