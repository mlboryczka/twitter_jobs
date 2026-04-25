"""Claude Haiku classifier — structured tool-use output.

We send the tweet (or reconstructed thread) plus author metadata and a detailed
system prompt. The model calls a single tool, ``record_classification``, whose
schema defines every field on job_postings. We accept only the first tool call;
if the model refuses or returns no tool call, we treat it as not-a-target.

The model is ``claude-haiku-4-5`` (Claude 4 Haiku). Cheap enough to run on every
prefilter hit.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from anthropic import AsyncAnthropic

from twitter_jobs.config import get_settings

logger = logging.getLogger(__name__)

MODEL = "claude-haiku-4-5"
MAX_TOKENS = 1024

ROLE_CATEGORIES = ["corp_dev", "strategy", "bd", "ops", "cos", "unknown"]
SENIORITIES = ["ic", "senior", "lead", "director", "vp", "exec", "unknown"]

TOOL_SCHEMA = {
    "name": "record_classification",
    "description": "Record the classification of a tweet that may or may not be a job posting in one of our five target role areas.",
    "input_schema": {
        "type": "object",
        "required": [
            "is_target",
            "role_category",
            "classifier_reasoning",
        ],
        "properties": {
            "is_target": {
                "type": "boolean",
                "description": "True only if the tweet is a real job posting written by or on behalf of the hiring party AND the role maps to one of the five target categories.",
            },
            "role_category": {
                "type": "string",
                "enum": ROLE_CATEGORIES,
                "description": "One of the five target role buckets, or 'unknown' when unsure (rare; prefer is_target=false for ambiguous cases).",
            },
            "company": {
                "type": ["string", "null"],
                "description": "Hiring company name if stated, otherwise null.",
            },
            "location": {
                "type": ["string", "null"],
                "description": "Work location as stated (city/country/'remote'). Null if not mentioned.",
            },
            "is_remote": {
                "type": ["boolean", "null"],
                "description": "True if explicitly remote, false if explicitly in-person, null if unclear.",
            },
            "seniority": {
                "type": ["string", "null"],
                "enum": [*SENIORITIES, None],
                "description": "Seniority bucket. 'ic' = individual contributor (associate/analyst), 'senior', 'lead', 'director', 'vp', 'exec' = C-suite. Null when unclear.",
            },
            "apply_link": {
                "type": ["string", "null"],
                "description": "Apply URL if present. If the only apply mechanism is 'DM me', this MUST be null.",
            },
            "classifier_reasoning": {
                "type": "string",
                "description": "One-to-three sentences explaining the decision. Quote specific phrases from the tweet when possible.",
            },
        },
    },
}


SYSTEM_PROMPT = """You classify X (Twitter) posts to decide whether they are real job postings in one of five specific categories I care about:

1. corp_dev — Corporate Development (M&A, deals, acquisitions, partnerships at a corporate scale).
2. strategy — Corporate Strategy, Strategic Finance, StratFin, FP&A+strategy hybrid roles.
3. bd — Business Development (partnerships, sales-adjacent, but NOT AE/sales reps).
4. ops — Operations / Business Operations / Chief Operating (excluding engineering/devops, marketing ops, sales ops unless billed as biz ops).
5. cos — Chief of Staff, to a founder/CEO/exec.

Hard rules:
- The tweet must be written by, or on behalf of, the hiring party. If it's a job seeker saying "I'm available / looking for my next role", set is_target=false.
- Commentary about hiring trends, macro takes, or tweets ABOUT a role (e.g. "being a Chief of Staff is hard") are not job postings — is_target=false.
- Engineering, design, product, marketing, sales-rep, data science, research roles → is_target=false. Return role_category='unknown' in that case.
- If the apply mechanism is only "DM me" or "DM us", leave apply_link=null. Do NOT invent a URL.
- If the tweet clearly is a posting but the role doesn't match any of the five, still set is_target=false.
- If the role is vaguely described but plausibly fits one of the five, pick your best bucket and note the uncertainty in reasoning.
- For threads (multiple numbered replies), read the entire thread — the apply link and details are usually further down.
- Prefer precision over recall. If you're not sure this is a hiring tweet in one of the five categories, is_target=false.

Always call the record_classification tool exactly once with your answer.
"""

FEW_SHOT_EXAMPLES = [
    {
        "text": "We're hiring our first Corporate Development Associate at Acme (NYC). 3-5yrs IB/PE, M&A deal experience. Apply: acme.com/jobs/corpdev",
        "expected": {"is_target": True, "role_category": "corp_dev", "seniority": "ic"},
    },
    {
        "text": "My portco is hiring a Chief of Staff to the CEO (SF, in-person). Series B, 2-4yrs BCG/Bain/McKinsey preferred. DM me.",
        "expected": {"is_target": True, "role_category": "cos", "apply_link": None},
    },
    {
        "text": "Looking for my next Strategic Finance / Corp Dev role (5yrs IB + ops). Remote preferred. DMs open.",
        "expected": {"is_target": False, "reason": "job seeker, not hiring"},
    },
    {
        "text": "Chief of Staff is the most underrated role in startups. Thread below on why.",
        "expected": {"is_target": False, "reason": "commentary, not a posting"},
    },
    {
        "text": "Hiring a Senior Backend Engineer (Go, NYC). Apply: https://example.com",
        "expected": {"is_target": False, "role_category": "unknown", "reason": "engineering role"},
    },
    {
        "text": "Now hiring: Head of Business Development at Orbit. Remote. 7+ yrs. orbit.so/careers",
        "expected": {"is_target": True, "role_category": "bd", "seniority": "director"},
    },
    {
        "text": "Looking for a Director of Operations to own our supply chain. Based in Austin. hello@warehouse.co",
        "expected": {"is_target": True, "role_category": "ops", "seniority": "director"},
    },
    {
        "text": "We just closed our Series A — now hiring a Corp Strategy lead (reporting to COO). San Francisco or remote-US. Apply here: strat.co/jobs",
        "expected": {"is_target": True, "role_category": "strategy", "seniority": "lead"},
    },
    {
        "text": "Talent Partner here. My portfolio is hiring across: Chief of Staff (seed fintech), Strategic Finance (Series B commerce), Corp Dev (growth SaaS). DM for details.",
        "expected": {"is_target": True, "role_category": "cos", "reason": "multi-role; pick the first target category, note others in reasoning", "apply_link": None},
    },
    {
        "text": "GTN hires Mark Evans as Head of Corporate Development to lead M&A and growth strategy. #Fintech #Hiring",
        "expected": {"is_target": False, "reason": "hire announcement (someone got the job), not a job posting"},
    },
    {
        "text": "Stripe is hiring a Senior Corporate Development Manager to drive M&A pipeline. 6+ yrs IB/CD. Apply: stripe.com/jobs/corp-dev-mgr",
        "expected": {"is_target": True, "role_category": "corp_dev", "seniority": "senior"},
    },
    {
        "text": "We're hiring a Strategic Finance Lead at Ramp. Series D fintech, 4-6yrs IB+ops. DM me to chat.",
        "expected": {"is_target": True, "role_category": "strategy", "seniority": "lead", "company": "Ramp", "apply_link": None},
    },
    {
        "text": "This week's open Chief of Staff roles I'm tracking: Pilot (NYC), Brex (SF), Vercel (remote). DM if you want intros.",
        "expected": {"is_target": False, "reason": "aggregator listing multiple companies, not a single posting we can act on"},
    },
    {
        "text": "We just hit $50M ARR. Insane team execution. Btw we're hiring across functions if you want to come build with us.",
        "expected": {"is_target": False, "reason": "self-promotion that mentions hiring in passing; no specific role to apply for"},
    },
    {
        "text": "Anyone strong on deal-running and growth-stage strategy looking for their next thing? Building something in fintech, will share details by DM.",
        "expected": {"is_target": True, "role_category": "corp_dev", "seniority": None, "apply_link": None, "reason": "borderline; plausibly corp_dev or strategy; pick corp_dev as best fit and flag uncertainty in reasoning"},
    },
    {
        "text": "We're hiring a VP of Operations at our portco (Series C SaaS, $40M ARR, 200ppl). Apply: portco.com/careers/vp-ops",
        "expected": {"is_target": True, "role_category": "ops", "seniority": "vp"},
    },
]


@dataclass
class JobClassification:
    is_target: bool
    role_category: str
    company: str | None
    location: str | None
    is_remote: bool | None
    seniority: str | None
    apply_link: str | None
    classifier_reasoning: str


def _format_tweet_block(
    tweet: dict[str, Any],
    author: dict[str, Any],
    thread_tweets: list[dict[str, Any]],
) -> str:
    """Turn tweet + thread + author into a single string the model sees."""
    lines = []
    lines.append(f"AUTHOR: @{author.get('username', '?')} — {author.get('name', '')}")
    if author.get("verified"):
        lines.append("AUTHOR VERIFIED: yes")
    desc = author.get("description") or ""
    if desc:
        lines.append(f"AUTHOR BIO: {desc}")
    followers = (author.get("public_metrics") or {}).get("followers_count")
    if followers is not None:
        lines.append(f"AUTHOR FOLLOWERS: {followers}")
    lines.append("")
    if len(thread_tweets) > 1:
        lines.append(f"THREAD ({len(thread_tweets)} tweets, in order):")
        for i, t in enumerate(thread_tweets, 1):
            lines.append(f"  [{i}] {t.get('text', '')}")
    else:
        lines.append("TWEET:")
        lines.append(f"  {tweet.get('text', '')}")
    return "\n".join(lines)


FEEDBACK_EXAMPLE_LIMIT = 20


def _few_shot_block() -> str:
    rows = []
    for ex in FEW_SHOT_EXAMPLES:
        rows.append(f"- Text: {ex['text']}\n  Expected: {json.dumps(ex['expected'])}")
    return "Examples of how to classify:\n\n" + "\n\n".join(rows)


async def _user_feedback_block() -> str:
    """Pull the user's most-recent accept/dismiss decisions and format as examples.

    Empty string if there's no feedback yet — just relies on the static examples.
    Imported lazily to avoid a circular import (classifier <- feedback <- db <- ...).
    """
    from sqlalchemy import select
    from sqlalchemy.orm import joinedload

    from twitter_jobs.db.models import JobPosting, Tweet
    from twitter_jobs.db.session import session_scope

    async with session_scope() as session:
        stmt = (
            select(JobPosting, Tweet)
            .join(Tweet, JobPosting.tweet_id == Tweet.tweet_id)
            .options(joinedload(Tweet.author))
            .where(JobPosting.status.in_(["accepted", "dismissed"]))
            .order_by(JobPosting.status_changed_at.desc())
            .limit(FEEDBACK_EXAMPLE_LIMIT)
        )
        result = await session.execute(stmt)
        rows = result.unique().all()

    if not rows:
        return ""

    header = (
        "User feedback on prior classifications. THIS user has personally "
        "accepted or dismissed each tweet below. These are the STRONGEST signal "
        "of the user's actual preferences and override the generic examples "
        "above when they conflict.\n\n"
        "How to use these:\n"
        "- If a new tweet closely resembles a DISMISSED example for the same "
        "kind of reason, strongly prefer is_target=false.\n"
        "- If a new tweet closely resembles an ACCEPTED example, treat that as "
        "positive evidence for is_target=true.\n"
        "- The user's note (after \"note:\") explains WHY they made each call. "
        "Generalize from those reasons; don't just match exact text.\n"
        "- The classifier's original output (after \"originally classified as:\") "
        "shows what we predicted last time. If the user dismissed it, our "
        "prediction was likely wrong for that pattern."
    )

    lines = [header]
    for job, tweet in rows:
        decision = "ACCEPTED" if job.status == "accepted" else "DISMISSED"
        note = f" — note: {job.user_feedback}" if job.user_feedback else ""
        text = (tweet.text or "").replace("\n", " ").strip()[:280]
        original_parts: list[str] = [f"role_category={job.role_category}"]
        if job.seniority:
            original_parts.append(f"seniority={job.seniority}")
        if job.company:
            original_parts.append(f"company={job.company}")
        original = ", ".join(original_parts)
        lines.append(
            f"- {decision}{note}\n"
            f"  Originally classified as: {original}\n"
            f"  Tweet text: {text}"
        )
    return "\n\n".join(lines)


async def classify(
    tweet: dict[str, Any],
    author: dict[str, Any],
    thread_tweets: list[dict[str, Any]] | None = None,
    *,
    client: AsyncAnthropic | None = None,
) -> JobClassification | None:
    """Classify a single tweet (or thread). Returns None on API failure."""
    settings = get_settings()
    if not settings.anthropic_api_key:
        logger.error("ANTHROPIC_API_KEY not set — skipping classification")
        return None

    anthro = client or AsyncAnthropic(api_key=settings.anthropic_api_key)
    thread_tweets = thread_tweets or [tweet]

    user_message = _format_tweet_block(tweet, author, thread_tweets)
    system_parts = [SYSTEM_PROMPT, _few_shot_block()]
    try:
        feedback = await _user_feedback_block()
    except Exception:
        # A DB hiccup mustn't kill classification — fall back to static examples.
        logger.exception("failed to load user feedback; classifying without it")
        feedback = ""
    if feedback:
        system_parts.append(feedback)
    system = "\n\n".join(system_parts)

    try:
        resp = await anthro.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system,
            tools=[TOOL_SCHEMA],
            tool_choice={"type": "tool", "name": "record_classification"},
            messages=[{"role": "user", "content": user_message}],
        )
    except Exception:
        logger.exception("classifier API call failed")
        return None

    for block in resp.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "record_classification":
            return _parse_tool_input(block.input)
    logger.warning("classifier returned no tool_use block")
    return None


def _parse_tool_input(data: dict[str, Any]) -> JobClassification:
    role = data.get("role_category") or "unknown"
    if role not in ROLE_CATEGORIES:
        role = "unknown"
    seniority = data.get("seniority")
    if seniority not in SENIORITIES and seniority is not None:
        seniority = "unknown"
    return JobClassification(
        is_target=bool(data.get("is_target", False)),
        role_category=role,
        company=data.get("company"),
        location=data.get("location"),
        is_remote=data.get("is_remote"),
        seniority=seniority,
        apply_link=data.get("apply_link"),
        classifier_reasoning=data.get("classifier_reasoning") or "",
    )
