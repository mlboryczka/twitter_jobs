"""Typed async wrappers over individual X API endpoints.

These return raw dicts from the API — the ingestion layer is responsible for
parsing them into DB rows. Adding a thin dataclass layer here added no value,
so we return the JSON as-is.
"""

from __future__ import annotations

from typing import Any

from twitter_jobs.x_api.client import XClient

TWEET_FIELDS = ",".join(
    [
        "id",
        "text",
        "author_id",
        "created_at",
        "lang",
        "public_metrics",
        "entities",
        "conversation_id",
        "in_reply_to_user_id",
        "referenced_tweets",
        "attachments",
    ]
)
USER_FIELDS = ",".join(
    [
        "id",
        "username",
        "name",
        "description",
        "verified",
        "public_metrics",
    ]
)
EXPANSIONS = "author_id,referenced_tweets.id,referenced_tweets.id.author_id"


async def get_me(client: XClient) -> dict[str, Any]:
    return await client.get(
        "/2/users/me",
        params={"user.fields": USER_FIELDS},
        endpoint_key="users_me",
        resource_count_key=None,
    )


async def get_home_timeline(
    client: XClient,
    user_id: str,
    *,
    since_id: str | None = None,
    next_token: str | None = None,
    max_results: int = 100,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "max_results": max_results,
        "tweet.fields": TWEET_FIELDS,
        "user.fields": USER_FIELDS,
        "expansions": EXPANSIONS,
    }
    if since_id:
        params["since_id"] = since_id
    if next_token:
        params["pagination_token"] = next_token
    return await client.get(
        f"/2/users/{user_id}/timelines/reverse_chronological",
        params=params,
        endpoint_key="users_timelines_reverse_chronological",
    )


async def get_tweets(client: XClient, ids: list[str]) -> dict[str, Any]:
    if not ids:
        return {"data": []}
    params = {
        "ids": ",".join(ids),
        "tweet.fields": TWEET_FIELDS,
        "user.fields": USER_FIELDS,
        "expansions": EXPANSIONS,
    }
    return await client.get(
        "/2/tweets",
        params=params,
        endpoint_key="tweets_lookup",
    )


async def search_recent(
    client: XClient,
    query: str,
    *,
    since_id: str | None = None,
    next_token: str | None = None,
    max_results: int = 100,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "query": query,
        "max_results": max_results,
        "tweet.fields": TWEET_FIELDS,
        "user.fields": USER_FIELDS,
        "expansions": EXPANSIONS,
    }
    if since_id:
        params["since_id"] = since_id
    if next_token:
        params["next_token"] = next_token
    return await client.get(
        "/2/tweets/search/recent",
        params=params,
        endpoint_key="tweets_search_recent",
    )
