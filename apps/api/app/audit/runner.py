"""Runs one website audit as a background job: crawl, check, score, store (FR-AUD-01, 06),
reporting progress to its job row so the UI can follow it over SSE (SRS §3.5)."""
import logging
from collections import Counter
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.checks import Finding, run_checks
from app.audit.crawler import CrawlResult, crawl
from app.audit.fetcher import SafeFetcher
from app.audit.scoring import score_audit
from app.db.rls import set_rls_context
from app.jobs.progress import is_cancelled, job_status, update_job
from app.models.audit import Audit, AuditFinding

logger = logging.getLogger(__name__)
CRAWL_SHARE = (5, 85)  # progress range used up by the crawl itself


def _summary(
    crawl_result: CrawlResult, findings: list[Finding], categories: dict[str, int]
) -> dict[str, object]:
    return {
        "categories": categories,
        "severity_counts": dict(Counter(f.severity for f in findings)),
        "pages_crawled": len(crawl_result.pages),
        "external_links_checked": len(crawl_result.external),
        "truncated": crawl_result.truncated,
        "skipped_by_robots": crawl_result.skipped_by_robots,
        "robots_present": crawl_result.robots.present,
        "sitemap_present": crawl_result.sitemap_present,
        "sitemap_urls": crawl_result.sitemap_urls,
    }


def _raw(crawl_result: CrawlResult) -> dict[str, object]:
    """Per-page crawl facts, kept so later features (reports, comparisons) need no re-crawl."""
    return {
        "pages": [
            {
                "url": url,
                "depth": rec.depth,
                "status": rec.fetch.status,
                "final_url": rec.fetch.final_url,
                "redirects": len(rec.fetch.chain),
                "ms": rec.fetch.elapsed_ms,
                "error": rec.fetch.error,
                "title": rec.data.title if rec.data else None,
                "h1": rec.data.h1_count if rec.data else None,
                "headings": rec.data.headings[:20] if rec.data else None,
            }
            for url, rec in crawl_result.pages.items()
        ],
    }


async def _set_audit(db: AsyncSession, tenant_id: UUID, audit_id: UUID, **values: object) -> bool:
    """Returns False when the audit no longer exists (its client was deleted meanwhile)."""
    await set_rls_context(db, tenant_id=tenant_id)
    audit = await db.scalar(select(Audit).where(Audit.id == audit_id))
    if audit is None:
        return False
    for key, value in values.items():
        setattr(audit, key, value)
    await db.commit()
    return True


async def run_audit(
    db: AsyncSession,
    tenant_id: UUID,
    audit_id: UUID,
    job_id: UUID,
    *,
    fetcher: SafeFetcher | None = None,
) -> None:
    await set_rls_context(db, tenant_id=tenant_id)
    audit = await db.scalar(
        select(Audit).where(Audit.id == audit_id, Audit.tenant_id == tenant_id)
    )
    if audit is None:
        await update_job(
            db, tenant_id, job_id, status="cancelled",
            message="The audit was deleted before it ran.",
        )
        return
    url = audit.url
    await db.rollback()  # no transaction is held open while the site is being crawled

    state = await job_status(db, tenant_id, job_id)
    if state in ("succeeded", "failed"):  # a duplicate delivery of finished work
        return
    if state == "cancelled":
        await _set_audit(
            db, tenant_id, audit_id, status="cancelled", finished_at=_now(),
            error="Cancelled before it started.",
        )
        return
    await update_job(db, tenant_id, job_id, status="running", progress=5, message="Starting")
    await _set_audit(db, tenant_id, audit_id, status="running", started_at=_now())

    async def progress(done: int, total: int, message: str) -> None:
        low, high = CRAWL_SHARE
        await update_job(
            db, tenant_id, job_id, progress=low + int((high - low) * done / max(total, 1)),
            message=message,
        )

    async def should_stop() -> bool:
        return await is_cancelled(db, tenant_id, job_id)

    own = fetcher is None
    fetcher = fetcher or SafeFetcher()
    try:
        result = await crawl(url, fetcher, on_progress=progress, should_stop=should_stop)
        if result.cancelled:
            await _set_audit(
                db, tenant_id, audit_id, status="cancelled", finished_at=_now(),
                error="Cancelled.",
            )
            return
        await update_job(db, tenant_id, job_id, progress=90, message="Scoring")
        findings = run_checks(result)
        score, categories = score_audit(findings, len(result.pages))
        await set_rls_context(db, tenant_id=tenant_id)
        db.add_all(
            AuditFinding(
                tenant_id=tenant_id, audit_id=audit_id, code=f.code, category=f.category,
                severity=f.severity, title=f.title, detail=f.detail, url=f.url,
                recommendation=f.recommendation, metric=f.metric,
            )
            for f in findings
        )
        if not await _set_audit(
            db, tenant_id, audit_id, status="succeeded", score=score, finished_at=_now(),
            summary=_summary(result, findings, categories), raw=_raw(result),
        ):
            return
        await update_job(
            db, tenant_id, job_id, status="succeeded", message="Audit complete",
            result_ref={"audit_id": str(audit_id), "score": score, "findings": len(findings)},
        )
    except Exception:
        logger.exception("Audit failed", extra={"audit_id": str(audit_id)})
        await db.rollback()
        await _set_audit(
            db, tenant_id, audit_id, status="failed", finished_at=_now(),
            error="The audit failed unexpectedly. Try running it again.",
        )
        await update_job(
            db, tenant_id, job_id, status="failed", error="The audit failed.",
            message="Audit failed",
        )
    finally:
        if own:
            await fetcher.aclose()


def _now() -> datetime:
    return datetime.now(timezone.utc)
