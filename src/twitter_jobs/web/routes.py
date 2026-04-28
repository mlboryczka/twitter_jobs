"""FastAPI routes — dashboard, review queue, all-jobs list, status-change endpoints, /health."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import joinedload

from twitter_jobs.classify.industries import (
    INDUSTRY_LABELS,
    PRIORITY_1,
    PRIORITY_2,
    ROLE_LABELS,
    get_priority,
)
from twitter_jobs.classify.training import (
    ocr_screenshot,
    save_image,
    training_dir,
)
from twitter_jobs.db.models import ApiCall, JobPosting, TrainingExample, Tweet, WorkerState
from twitter_jobs.db.session import session_scope
from twitter_jobs.ingest.common import spam_dismiss_reason
from twitter_jobs.ingest.search_worker import LAST_PULL_SUMMARY_KEY
from twitter_jobs.web.auth import require_basic_auth

_TWITTER_HOSTS = ("twitter.com", "x.com", "t.co")


def _is_twitter_url(url: str | None) -> bool:
    if not url:
        return True
    lower = url.lower()
    return any(host in lower for host in _TWITTER_HOSTS)


def apply_url_for(job: JobPosting, tweet: Tweet) -> str | None:
    """Return the best 'Apply' destination for a job row.

    The classifier sometimes stores a t.co shortened URL (or nothing) as
    apply_link. Prefer the expanded_url from the tweet's entities so the
    button goes to the real careers page (Ashby, Greenhouse, the company
    site, etc.) instead of the X tweet itself. Skip URLs that point back
    to Twitter/X.
    """
    entities = tweet.entities or {}
    for entry in entities.get("urls") or []:
        expanded = entry.get("expanded_url")
        if expanded and not _is_twitter_url(expanded):
            return expanded
    if job.apply_link and not _is_twitter_url(job.apply_link):
        return job.apply_link
    return None


def build_router(templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()

    def _render_job_row(request: Request, job: JobPosting, tweet: Tweet) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "partials/job_row.html",
            {
                "job": job,
                "tweet": tweet,
                "role_labels": ROLE_LABELS,
                "industry_labels": INDUSTRY_LABELS,
                "priority_for": get_priority,
                "apply_url_for": apply_url_for,
            },
        )

    @router.get("/", response_class=HTMLResponse)
    async def dashboard(
        request: Request,
        role: str | None = None,
        q: str | None = None,
        priority: str | None = None,
        _: str = Depends(require_basic_auth),
    ) -> HTMLResponse:
        def _author_dict(tweet: Tweet) -> dict[str, Any]:
            a = tweet.author
            if a is None:
                return {}
            return {
                "verified": a.verified,
                "description": a.description,
                "public_metrics": a.public_metrics,
            }

        # Section 1: status='new' inbox (only items still needing triage).
        inbox = await _list_jobs(statuses=["new"], role=role, text_query=q)
        # Defensive: never surface AVOID industries, non-US-eligible postings,
        # or anything spam_dismiss_reason flags — even if upstream missed it.
        inbox = [
            jt for jt in inbox
            if get_priority(jt[0].industry) != 0
            and jt[0].is_us_eligible is not False
            and spam_dismiss_reason(_author_dict(jt[1])) is None
        ]
        inbox.sort(key=lambda jt: get_priority(jt[0].industry))
        if priority == "1":
            inbox = [jt for jt in inbox if get_priority(jt[0].industry) == 1]
        elif priority and priority in INDUSTRY_LABELS:
            inbox = [jt for jt in inbox if jt[0].industry == priority]

        # Section 2: status='accepted' — accepted-but-not-yet-applied.
        to_apply = await _list_jobs(statuses=["accepted"], role=role, text_query=q)
        to_apply.sort(key=lambda jt: get_priority(jt[0].industry))

        p1_industries = sorted(
            (i for i in INDUSTRY_LABELS if i in PRIORITY_1),
            key=lambda i: INDUSTRY_LABELS[i],
        )
        p2_industries = sorted(
            (i for i in INDUSTRY_LABELS if i in PRIORITY_2),
            key=lambda i: INDUSTRY_LABELS[i],
        )

        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {
                "inbox": inbox,
                "to_apply": to_apply,
                "role_labels": ROLE_LABELS,
                "industry_labels": INDUSTRY_LABELS,
                "priority_for": get_priority,
                "apply_url_for": apply_url_for,
                "p1_industries": p1_industries,
                "p2_industries": p2_industries,
                "active_role": role,
                "active_priority": priority,
                "text_query": q or "",
                "page": "dashboard",
            },
        )

    @router.get("/all", response_class=HTMLResponse)
    async def all_jobs(
        request: Request,
        role: str | None = None,
        statuses: str | None = None,
        days: int = 30,
        q: str | None = None,
        _: str = Depends(require_basic_auth),
    ) -> HTMLResponse:
        status_list = [s for s in (statuses or "").split(",") if s] or None
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        jobs = await _list_jobs(
            statuses=status_list, role=role, since=cutoff, text_query=q
        )
        jobs.sort(key=lambda jt: get_priority(jt[0].industry))
        return templates.TemplateResponse(
            request,
            "all.html",
            {
                "jobs": jobs,
                "role_labels": ROLE_LABELS,
                "industry_labels": INDUSTRY_LABELS,
                "priority_for": get_priority,
                "apply_url_for": apply_url_for,
                "active_role": role,
                "active_statuses": statuses,
                "active_days": days,
                "text_query": q or "",
                "page": "all",
            },
        )

    async def _record_decision(
        tweet_id: str, request: Request, status_value: str, feedback: str
    ) -> HTMLResponse:
        async with session_scope() as session:
            job = await session.get(JobPosting, tweet_id)
            if job is None:
                raise HTTPException(status_code=404)
            job.status = status_value
            job.user_feedback = feedback.strip() or None
            if status_value == "dismissed":
                # Mirror feedback into dismissal_reason for backward-compat readers.
                job.dismissal_reason = feedback.strip() or None
            job.status_changed_at = datetime.now(timezone.utc)
            tweet = await session.get(
                Tweet, tweet_id, options=[joinedload(Tweet.author)]
            )
        return _render_job_row(request, job, tweet)

    @router.post("/jobs/{tweet_id}/accept", response_class=HTMLResponse)
    async def accept(
        tweet_id: str,
        request: Request,
        feedback: str = Form(""),
        _: str = Depends(require_basic_auth),
    ) -> HTMLResponse:
        return await _record_decision(tweet_id, request, "accepted", feedback)

    @router.post("/jobs/{tweet_id}/dismiss", response_class=HTMLResponse)
    async def dismiss(
        tweet_id: str,
        request: Request,
        feedback: str = Form(""),
        _: str = Depends(require_basic_auth),
    ) -> HTMLResponse:
        return await _record_decision(tweet_id, request, "dismissed", feedback)

    @router.post("/jobs/{tweet_id}/applied", response_class=HTMLResponse)
    async def applied(
        tweet_id: str,
        request: Request,
        feedback: str = Form(""),
        _: str = Depends(require_basic_auth),
    ) -> HTMLResponse:
        return await _record_decision(tweet_id, request, "applied", feedback)

    @router.get("/training", response_class=HTMLResponse)
    async def training_page(
        request: Request,
        _: str = Depends(require_basic_auth),
    ) -> HTMLResponse:
        async with session_scope() as session:
            res = await session.execute(
                select(TrainingExample).order_by(TrainingExample.created_at.desc())
            )
            examples = res.scalars().all()
        return templates.TemplateResponse(
            request,
            "training.html",
            {
                "examples": examples,
                "industry_labels": INDUSTRY_LABELS,
                "role_labels": ROLE_LABELS,
                "page": "training",
            },
        )

    @router.post("/training", response_class=HTMLResponse)
    async def training_create(
        request: Request,
        decision: str = Form(...),
        reasoning: str = Form(""),
        role_category: str = Form(""),
        industry: str = Form(""),
        tweet_text_override: str = Form(""),
        author_handle_override: str = Form(""),
        screenshot: UploadFile | None = File(None),
        _: str = Depends(require_basic_auth),
    ) -> HTMLResponse:
        if decision not in {"accept", "dismiss"}:
            raise HTTPException(status_code=400, detail="invalid decision")

        image_path: str | None = None
        media_type: str | None = None
        ocr_text = ""
        ocr_handle: str | None = None

        if screenshot is not None and screenshot.filename:
            content = await screenshot.read()
            if content:
                path, media_type = save_image(content, screenshot.filename)
                image_path = str(path.relative_to(training_dir().parent.parent))
                ocr_text, ocr_handle = await ocr_screenshot(content, media_type)

        tweet_text = tweet_text_override.strip() or ocr_text
        author_handle = author_handle_override.strip() or ocr_handle

        async with session_scope() as session:
            session.add(
                TrainingExample(
                    image_path=image_path,
                    image_media_type=media_type,
                    tweet_text=tweet_text,
                    author_handle=author_handle,
                    decision=decision,
                    role_category=role_category or None,
                    industry=industry or None,
                    reasoning=reasoning.strip(),
                )
            )

        return RedirectResponse(url="/training", status_code=303)

    @router.post("/training/{example_id}/delete", response_class=HTMLResponse)
    async def training_delete(
        example_id: int,
        _: str = Depends(require_basic_auth),
    ) -> HTMLResponse:
        async with session_scope() as session:
            await session.execute(
                sa_delete(TrainingExample).where(TrainingExample.id == example_id)
            )
        return RedirectResponse(url="/training", status_code=303)

    @router.get("/training/image/{filename}")
    async def training_image(
        filename: str,
        _: str = Depends(require_basic_auth),
    ) -> FileResponse:
        # Restrict to data/training/ — no traversal.
        safe_name = filename.replace("/", "").replace("\\", "")
        path = training_dir() / safe_name
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=404)
        return FileResponse(path)

    @router.get("/health")
    async def health() -> dict[str, Any]:
        async with session_scope() as session:
            try:
                await session.execute(select(func.count()).select_from(JobPosting))
                db_ok = True
            except SQLAlchemyError:
                db_ok = False

            last_pull_row = await session.get(WorkerState, LAST_PULL_SUMMARY_KEY)

            cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
            cost_q = await session.execute(
                select(func.coalesce(func.sum(ApiCall.cost_usd), 0)).where(
                    ApiCall.called_at >= cutoff
                )
            )
            cost_24h = float(cost_q.scalar_one())

            jobs_q = await session.execute(
                select(func.count()).select_from(JobPosting).where(
                    JobPosting.classified_at >= cutoff
                )
            )
            jobs_24h = int(jobs_q.scalar_one())

        return {
            "db_ok": db_ok,
            "last_feed_pull": last_pull_row.value if last_pull_row else None,
            "cost_usd_last_24h": round(cost_24h, 6),
            "jobs_classified_last_24h": jobs_24h,
        }

    return router


async def _list_jobs(
    statuses: list[str] | None = None,
    role: str | None = None,
    text_query: str | None = None,
    needs_manual_review: bool | None = None,
    since: datetime | None = None,
) -> list[tuple[JobPosting, Tweet]]:
    """Return a list of (JobPosting, Tweet) tuples, newest first."""
    async with session_scope() as session:
        stmt = (
            select(JobPosting, Tweet)
            .join(Tweet, JobPosting.tweet_id == Tweet.tweet_id)
            .options(joinedload(Tweet.author))
            .order_by(JobPosting.classified_at.desc())
        )
        if statuses:
            stmt = stmt.where(JobPosting.status.in_(statuses))
        if role:
            stmt = stmt.where(JobPosting.role_category == role)
        if needs_manual_review is not None:
            stmt = stmt.where(JobPosting.needs_manual_review.is_(needs_manual_review))
        if since is not None:
            stmt = stmt.where(JobPosting.classified_at >= since)
        if text_query:
            like = f"%{text_query.lower()}%"
            stmt = stmt.where(
                func.lower(Tweet.text).like(like)
                | func.lower(func.coalesce(JobPosting.company, "")).like(like)
                | func.lower(func.coalesce(JobPosting.location, "")).like(like)
            )
        result = await session.execute(stmt)
        return [(job, tweet) for job, tweet in result.unique().all()]
