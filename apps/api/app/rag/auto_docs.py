"""Auto-managed knowledge documents (FR-RAG-02): documents the app writes itself from a
client's saved facts (today the brand profile; later audit summaries and approved
strategies/content) and keeps indexed. Callers commit, then enqueue the returned id."""
import hashlib
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.brand_profile import BrandProfile
from app.models.document import Document

BRAND_PROFILE_TYPE = "brand_profile"
BRAND_PROFILE_TITLE = "Brand profile"
# Types the user cannot delete (they are managed from elsewhere in the app).
AUTO_SOURCE_TYPES = frozenset({BRAND_PROFILE_TYPE})


def field_line(label: str, value: Any) -> str:
    """One "Label: value" line; empty values and empty lists produce nothing."""
    if not value:
        return ""
    if isinstance(value, list):
        value = "; ".join(str(v) for v in value)
    return f"{label}: {value}\n"


def render_brand_profile(profile: BrandProfile, *, include_sample: bool = False) -> str:
    """The profile as text. The strategy prompt uses it without the sample text (as it
    always has); the indexed document includes the sample, which carries the voice."""
    body = (
        field_line("Voice", profile.voice)
        + field_line("Tone", profile.tone)
        + field_line("Audience", profile.audience)
        + field_line("Keywords", profile.keywords)
        + field_line("Do", profile.do_rules)
        + field_line("Don't", profile.dont_rules)
    )
    if include_sample:
        body += field_line("Sample text", profile.sample_text)
    return body


def brand_profile_document_text(profile: BrandProfile) -> str:
    """"" when the profile has nothing in it (the document is then removed)."""
    body = render_brand_profile(profile, include_sample=True)
    return f"{BRAND_PROFILE_TITLE}\n{body}".rstrip() if body.strip() else ""


async def sync_auto_document(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    client_id: UUID,
    source_type: str,
    title: str,
    text: str,
) -> UUID | None:
    """Create, update or remove the client's single auto document of `source_type`.

    Returns the document id when it needs (re-)indexing, else None: empty text removes
    the document (chunks cascade); unchanged content is left alone unless it never
    finished indexing. The hash includes the source type so it can never collide with
    a user-uploaded document that happens to contain the same text."""
    doc = await db.scalar(
        select(Document).where(
            Document.tenant_id == tenant_id,
            Document.client_id == client_id,
            Document.source_type == source_type,
        )
    )
    if not text.strip():
        if doc is not None:
            await db.delete(doc)
        return None

    digest = hashlib.sha256(f"{source_type}\n{text}".encode()).hexdigest()
    if doc is None:
        doc = Document(
            tenant_id=tenant_id,
            client_id=client_id,
            source_type=source_type,
            title=title,
            content=text,
            content_hash=digest,
            status="pending",
        )
        db.add(doc)
        await db.flush()
        return doc.id
    if doc.content_hash == digest:
        # Same content: nothing to re-embed, but retry one that never finished indexing.
        return doc.id if doc.status in ("pending", "failed") else None
    doc.content, doc.content_hash = text, digest
    doc.status, doc.error = "pending", None
    return doc.id
