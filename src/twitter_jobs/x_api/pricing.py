"""Per-endpoint pricing table for the X API v2.

Values are USD per *resource* (i.e., per tweet returned, or per user fetched for
/users/me). These are the public tier rates as of April 2026.

Source: https://developer.x.com/en/portal/products  (verify periodically — X has
changed this page before).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EndpointPrice:
    """Pricing info for a single endpoint."""

    endpoint: str
    cost_per_resource_usd: float
    resource_name: str  # what the resource is ("tweet", "user")


# Keyed by a stable short name used internally. Callers look up the entry and
# compute cost by multiplying cost_per_resource_usd by the number of items the
# call actually returned.
PRICING: dict[str, EndpointPrice] = {
    # Recent search — $0.005 / tweet.
    "tweets_search_recent": EndpointPrice(
        endpoint="/2/tweets/search/recent",
        cost_per_resource_usd=0.005,
        resource_name="tweet",
    ),
    # Tweets lookup — $0.005 / tweet.
    "tweets_lookup": EndpointPrice(
        endpoint="/2/tweets",
        cost_per_resource_usd=0.005,
        resource_name="tweet",
    ),
    # users/me — billed per user returned, same $0.005.
    "users_me": EndpointPrice(
        endpoint="/2/users/me",
        cost_per_resource_usd=0.005,
        resource_name="user",
    ),
}


def estimate_cost(endpoint_key: str, resource_count: int) -> float:
    """Return the USD estimate for ``resource_count`` resources from ``endpoint_key``.

    Unknown endpoints cost zero (logged but not billed) so we never crash on a
    new endpoint; the api_calls row will still be written with a note.
    """
    entry = PRICING.get(endpoint_key)
    if entry is None:
        return 0.0
    return round(entry.cost_per_resource_usd * max(resource_count, 0), 6)
