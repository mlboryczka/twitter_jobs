"""TypedDicts for the X API v2 payloads we deserialize.

These describe the fields we explicitly request via TWEET_FIELDS, USER_FIELDS,
and EXPANSIONS in endpoints.py. ``total=False`` everywhere because the API
omits empty fields and our request fields list can change.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict


class PublicMetrics(TypedDict, total=False):
    followers_count: int
    following_count: int
    tweet_count: int
    listed_count: int
    like_count: int
    retweet_count: int
    reply_count: int
    quote_count: int
    impression_count: int


class XUrlEntity(TypedDict, total=False):
    start: int
    end: int
    url: str
    expanded_url: str
    display_url: str


class XEntities(TypedDict, total=False):
    urls: list[XUrlEntity]
    hashtags: list[dict[str, Any]]
    mentions: list[dict[str, Any]]
    annotations: list[dict[str, Any]]
    cashtags: list[dict[str, Any]]


class XReferencedTweet(TypedDict):
    id: str
    type: Literal["replied_to", "retweeted", "quoted"]


class XAttachments(TypedDict, total=False):
    media_keys: list[str]
    poll_ids: list[str]


class XAuthor(TypedDict, total=False):
    id: str
    username: str
    name: str
    description: str
    verified: bool
    public_metrics: PublicMetrics


class XTweet(TypedDict, total=False):
    id: str
    text: str
    author_id: str
    created_at: str
    lang: str
    public_metrics: PublicMetrics
    entities: XEntities
    conversation_id: str
    in_reply_to_user_id: str
    referenced_tweets: list[XReferencedTweet]
    attachments: XAttachments


class XIncludes(TypedDict, total=False):
    users: list[XAuthor]
    tweets: list[XTweet]


class XMeta(TypedDict, total=False):
    newest_id: str
    oldest_id: str
    result_count: int
    next_token: str


class XResponse(TypedDict, total=False):
    data: list[XTweet]
    includes: XIncludes
    meta: XMeta
