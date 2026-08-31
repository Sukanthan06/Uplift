from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    payment_id: Mapped[int] = mapped_column(ForeignKey("payment_attempts.id"), index=True)
    uplift_now: Mapped[float] = mapped_column(Float)
    uplift_best: Mapped[float] = mapped_column(Float)
    best_retry_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    chosen_action: Mapped[str] = mapped_column(String(32))
    policy_version: Mapped[str] = mapped_column(String(16))
    rules_fired: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    assigned_treatment: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
