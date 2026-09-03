from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Incident(Base):
    """Written when action_service exhausts its retry budget (CLAUDE.md
    non-negotiable #4). Deliberate extension beyond CLAUDE.md's original
    five-table schema -- resolved_at/resolver_notes genuinely don't belong
    on the actions row, which describes what happened, not how a human
    handled it afterward. See docs/DECISIONS.md."""

    __tablename__ = "incidents"

    id: Mapped[int] = mapped_column(primary_key=True)
    payment_id: Mapped[str] = mapped_column(String(64), index=True)
    action_type: Mapped[str] = mapped_column(String(32))
    attempts: Mapped[int] = mapped_column(Integer)
    last_status: Mapped[int | None] = mapped_column(Integer)
    error_summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolver_notes: Mapped[str | None] = mapped_column(Text)
