"""Regex-based prefilter — cheap first pass to find tweets potentially worth classifying.

Two groups of patterns:

- HIRING_PATTERNS: phrases humans use when they're the hiring party.
- ROLE_PATTERNS: keywords that plausibly map to one of our five target roles.

A tweet is a hit if either (a) it matches at least one HIRING_PATTERN plus at
least one ROLE_PATTERN, OR (b) the author bio has recruiting/talent signals and
the tweet shows *any* hiring signal. The second case catches talent partners
whose whole feed is openings, so they post things like "we need one more Corp
Dev Associate" without the "we are hiring" boilerplate.

If the tweet is a retweet, we run the filter against the referenced tweet's
text (populated via includes.tweets), not the RT wrapper.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# --- hiring-language patterns ---
HIRING_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\bwe(?:'re| are) hiring\b",
        r"\bcurrently hiring\b",
        r"\bnow hiring\b",
        r"\bjoin (?:our|the) team\b",
        r"\bopen (?:role|roles|position|positions|seat|seats)\b",
        r"\bhiring for\b",
        r"\bapply (?:here|via|at|now|today)\b",
        r"\bDM (?:me|us)\b",
        r"\blooking for (?:a|an|our next|my next)\b",
        r"\brecruiting (?:a|an|for)\b",
        r"\b(?:new|fresh) (?:role|roles|opening|openings)\b",
        r"\bwe(?:'re| are) looking\b",
        r"\b(?:join|come) work(?: with us)?\b",
        r"\bi'm hiring\b",
        r"\bhiring alert\b",
        r"\bseeking (?:a|an|our next|candidates)\b",
    ]
]

# --- role keywords ---
ROLE_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\bcorp(?:orate)?[ \-]?dev(?:elopment)?\b",
        r"\bcorp(?:orate)? strategy\b",
        r"\bstrategic finance\b",
        r"\bstrat[ \-]?fin\b",
        r"\bbusiness development\b",
        r"\bBD\b",
        r"\bchief of staff\b",
        r"\bCoS\b",
        r"\b(?:biz|business) ops\b",
        r"\bbusiness operations\b",
        r"\boperations (?:manager|lead|director|analyst|associate)\b",
        r"\bstrategy (?:&|and) ops\b",
        r"\bstrategy (?:manager|lead|director|analyst|associate)\b",
        r"\bhead of (?:strategy|ops|operations|bd|business development|corp dev|corporate development)\b",
        r"\bvp (?:of )?(?:strategy|ops|operations|bd|business development|corp dev|corporate development)\b",
    ]
]

# --- author bio recruiter signals ---
BIO_RECRUITER_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\btalent\b",
        r"\brecruit(?:er|ing)\b",
        r"\bhead of people\b",
        r"\bpeople ops\b",
        r"\bhr\b",
        r"\bexecutive search\b",
        r"\bhiring manager\b",
    ]
]

# Weak hiring signal — any of these count when the author bio marks them as a
# recruiter/talent person.
WEAK_HIRING_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\bhiring\b",
        r"\bopening\b",
        r"\brole\b",
        r"\bwe need\b",
        r"\bapply\b",
        r"\bjoin\b",
    ]
]


@dataclass
class PrefilterResult:
    hit: bool
    hiring_matches: list[str] = field(default_factory=list)
    role_matches: list[str] = field(default_factory=list)
    bio_recruiter_hit: bool = False
    text_used: str = ""  # the text we actually evaluated (post-RT unwrap)


def _first_matches(text: str, patterns: list[re.Pattern[str]]) -> list[str]:
    hits: list[str] = []
    for pat in patterns:
        m = pat.search(text)
        if m:
            hits.append(m.group(0))
    return hits


def _resolve_text(tweet: dict[str, Any], includes_tweets_by_id: dict[str, dict[str, Any]]) -> str:
    """If this tweet is a retweet, return the referenced tweet's text."""
    ref = tweet.get("referenced_tweets") or []
    for r in ref:
        if r.get("type") == "retweeted":
            src = includes_tweets_by_id.get(r.get("id", ""))
            if src and src.get("text"):
                return src["text"]
    return tweet.get("text", "")


def is_potential_job(
    tweet: dict[str, Any],
    author: dict[str, Any] | None,
    *,
    includes_tweets_by_id: dict[str, dict[str, Any]] | None = None,
) -> PrefilterResult:
    """Pure function. Returns a PrefilterResult indicating whether to classify."""
    includes_tweets_by_id = includes_tweets_by_id or {}
    text = _resolve_text(tweet, includes_tweets_by_id)
    bio = (author or {}).get("description") or ""

    hiring = _first_matches(text, HIRING_PATTERNS)
    roles = _first_matches(text, ROLE_PATTERNS)
    bio_recruiter = bool(_first_matches(bio, BIO_RECRUITER_PATTERNS))

    # Primary rule: strong hiring phrase AND role keyword.
    if hiring and roles:
        return PrefilterResult(
            hit=True,
            hiring_matches=hiring,
            role_matches=roles,
            bio_recruiter_hit=bio_recruiter,
            text_used=text,
        )

    # Secondary rule: recruiter bio + any weak hiring word + any role keyword.
    if bio_recruiter and roles:
        weak = _first_matches(text, WEAK_HIRING_PATTERNS)
        if weak:
            return PrefilterResult(
                hit=True,
                hiring_matches=weak,
                role_matches=roles,
                bio_recruiter_hit=True,
                text_used=text,
            )

    return PrefilterResult(
        hit=False,
        hiring_matches=hiring,
        role_matches=roles,
        bio_recruiter_hit=bio_recruiter,
        text_used=text,
    )
