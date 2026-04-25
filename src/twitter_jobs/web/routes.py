"""FastAPI routes — dashboard, review queue, all-jobs list, status-change endpoints, /health."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from twitter_jobs.db.models import ApiCall, JobPosting, Tweet, WorkerState
from twitter_jobs.db.session import session_scope
from twitter_jobs.ingest.feed_worker import LAST_PULL_SUMMARY_KEY
from twitter_jobs.web.auth import require_basic_auth

ROLE_LABELS = {
    "corp_dev": "Corp Dev",
    "strategy": "Strategy",
    "bd": "BD",
    "ops": "Ops",
    "cos": "Chief of Staff",
    "unknown": "Unknown",
}


def build_router(templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()

    def _render_job_row(request: Request, job: JobPosting, tweet: Tweet) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "partials/job_row.html",
            {"job": job, "tweet": tweet, "role_labels": ROLE_LABELS},
        )

    @router.get("/", response_class=HTMLResponse)
    async def dashboard(
        request: Request,
        role: str | None = None,
        q: str | None = None,
        _: str = Depends(require_basic_auth),
    ) -> HTMLResponse:
        jobs = await _list_jobs(statuses=["new"], role=role, text_query=q)
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {
                "jobs": jobs,
                "role_labels": ROLE_LABELS,
                "active_role": role,
                "text_query": q or "",
                "page": "dashboard",
            },
        )

    @router.get("/review", response_class=HTMLResponse)
    async def review(
        request: Request,
        _: str = Depends(require_basic_auth),
    ) -> HTMLResponse:
        jobs = await _list_jobs(needs_manual_review=True)
        return templates.TemplateResponse(
            request,
            "review.html",
            {
                "jobs": jobs,
                "role_labels": ROLE_LABELS,
                "page": "review",
            },
        )

    @router.get("/all", response_class=HTMLResponse)
    async def all_jobs(
        request: Request,
        role: str | None = None,
        statuses: str | None = None,
        days: int = 30,
        _: str = Depends(require_basic_auth),
    ) -> HTMLResponse:
        status_list = [s for s in (statuses or "").split(",") if s] or None
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        jobs = await _list_jobs(statuses=status_list, role=role, since=cutoff)
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {
                "jobs": jobs,
                "role_labels": ROLE_LABELS,
                "active_role": role,
                "text_query": "",
                "page": "all",
            },
        )

    @router.post("/jobs/{tweet_id}/status", response_class=HTMLResponse)
    async def change_status(
        tweet_id: str,
        request: Request,
        new_status: str = Form(...),
        _: str = Depends(require_basic_auth),
    ) -> HTMLResponse:
        if new_status not in {"new", "seen", "applied", "dismissed"}:
            raise HTTPException(status_code=400, detail="invalid status")
        async with session_scope() as session:
            job = await session.get(JobPosting, tweet_id)
            if job is None:
                raise HTTPException(status_code=404)
            job.status = new_status
            job.status_changed_at = datetime.now(timezone.utc)
            tweet = await session.get(
                Tweet, tweet_id, options=[joinedload(Tweet.author)]
            )
        return _render_job_row(request, job, tweet)

    @router.post("/jobs/{tweet_id}/dismiss", response_class=HTMLResponse)
    async def dismiss(
        tweet_id: str,
        request: Request,
        reason: str = Form(""),
        _: str = Depends(require_basic_auth),
    ) -> HTMLResponse:
        async with session_scope() as session:
            job = await session.get(JobPosting, tweet_id)
            if job is None:
                raise HTTPException(status_code=404)
            job.status = "dismissed"
            job.dismissal_reason = reason or None
            job.status_changed_at = datetime.now(timezone.utc)
            tweet = await session.get(
                Tweet, tweet_id, options=[joinedload(Tweet.author)]
            )
        return _render_job_row(request, job, tweet)

    @router.get("/health")
    async def health() -> dict[str, Any]:
        async with session_scope() as session:
            try:
                await session.execute(select(func.count()).select_from(JobPosting))
                db_ok = True
            except Exception:
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
