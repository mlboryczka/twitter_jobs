"""Regex-based prefilter — cheap first pass to find tweets potentially worth classifying.

Strategy: be **loose**. The prefilter only filters out tweets that are clearly
not hiring-adjacent. The Claude classifier is the strict filter; it's cheap
enough (~$0.001/tweet) that we'd rather pay it to reject false positives than
miss a real job posting via a too-narrow regex.

A tweet is a hit if any of these are true:

- It contains a hiring phrase ("we're hiring", "open role", "looking for", ...).
- The author bio looks like a recruiter/talent person AND the tweet has any
  weak hiring word (so a talent partner posting "another opening" still hits).
- It contains a target-role keyword (e.g. "corp dev", "chief of staff"), even
  with no canonical hiring phrase — covers tweets like "open seat for someone
  who's done M&A".

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
        r"\blooking for\b",
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
        r"\bM&A\b",
        r"\bmergers (?:&|and) acquisitions\b",
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

    # Any hiring phrase → hit. Classifier decides if it's a target role.
    if hiring:
        return PrefilterResult(
            hit=True,
            hiring_matches=hiring,
            role_matches=roles,
            bio_recruiter_hit=bio_recruiter,
            text_used=text,
        )

    # Any target-role keyword → hit, even without a canonical hiring phrase.
    if roles:
        return PrefilterResult(
            hit=True,
            hiring_matches=hiring,
            role_matches=roles,
            bio_recruiter_hit=bio_recruiter,
            text_used=text,
        )

    # Recruiter-bio author + any weak hiring word → hit.
    if bio_recruiter:
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
