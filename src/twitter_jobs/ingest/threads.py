"""Thread reconstruction — fetches a self-reply thread so the classifier sees full context.

We only reconstruct if:
  - ``conversation_id`` equals the tweet id (i.e., this is the head of a thread)
  - the author has replied to themselves in the last 7 days (search/recent window)

The result is an ordered list of tweets (head first). Capped at 20 tweets to
control cost.
"""

from __future__ import annotations

import logging

from twitter_jobs.x_api.client import XClient
from twitter_jobs.x_api.endpoints import search_recent
from twitter_jobs.x_api.types import XAuthor, XTweet

logger = logging.getLogger(__name__)

MAX_THREAD_TWEETS = 20


async def reconstruct_thread(
    client: XClient,
    tweet: XTweet,
    author: XAuthor,
) -> list[XTweet]:
    """Return an ordered list of thread tweets (head first) or [tweet] if not a thread."""
    conversation_id = tweet.get("conversation_id")
    tweet_id = tweet.get("id")
    username = (author or {}).get("username")
    if not (conversation_id and tweet_id and username):
        return [tweet]
    if conversation_id != tweet_id:
        return [tweet]

    query = f"conversation_id:{conversation_id} from:{username}"
    try:
        payload = await search_recent(client, query, max_results=MAX_THREAD_TWEETS)
    except Exception as exc:  # pragma: no cover
        logger.warning("thread reconstruction failed for %s: %s", tweet_id, exc)
        return [tweet]

    data = payload.get("data") or []
    by_id: dict[str, XTweet] = {t["id"]: t for t in data}
    by_id.setdefault(tweet_id, tweet)
    ordered = sorted(by_id.values(), key=lambda t: _id_key(t["id"]))
    return ordered[:MAX_THREAD_TWEETS]


def _id_key(tweet_id: str) -> tuple[int, str]:
    # Compare by length then lexicographically — same logic as elsewhere.
    return (len(tweet_id), tweet_id)
