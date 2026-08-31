"""initial schema

Revision ID: f9e6ef386981
Revises:
Create Date: 2026-08-31

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "f9e6ef386981"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "payment_attempts",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("order_id", sa.String(64), nullable=False),
        sa.Column("customer_id", sa.String(64), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("method", sa.String(32), nullable=False),
        sa.Column("psp", sa.String(32), nullable=False),
        sa.Column("issuer", sa.String(64), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_desc", sa.Text(), nullable=True),
        sa.Column("attempt_no", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "parent_attempt_id",
            sa.BigInteger(),
            sa.ForeignKey("payment_attempts.id"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_payment_attempts_order_id", "payment_attempts", ["order_id"])
    op.create_index("ix_payment_attempts_customer_id", "payment_attempts", ["customer_id"])
    op.create_index("ix_payment_attempts_status", "payment_attempts", ["status"])
    op.create_index(
        "ix_payment_attempts_parent_attempt_id",
        "payment_attempts",
        ["parent_attempt_id"],
    )

    op.create_table(
        "reconciliations",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "payment_id",
            sa.BigInteger(),
            sa.ForeignKey("payment_attempts.id"),
            nullable=False,
        ),
        sa.Column("gateway_reported_status", sa.String(16), nullable=False),
        sa.Column(
            "reconciled_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_reconciliations_payment_id", "reconciliations", ["payment_id"])

    op.create_table(
        "diagnoses",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "payment_id",
            sa.BigInteger(),
            sa.ForeignKey("payment_attempts.id"),
            nullable=False,
        ),
        sa.Column("root_cause", sa.String(128), nullable=False),
        sa.Column("cause_family", sa.String(64), nullable=False),
        sa.Column("is_transient", sa.Boolean(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("raw_llm_response", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_diagnoses_payment_id", "diagnoses", ["payment_id"])
    op.create_index("ix_diagnoses_cause_family", "diagnoses", ["cause_family"])

    op.create_table(
        "decisions",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "payment_id",
            sa.BigInteger(),
            sa.ForeignKey("payment_attempts.id"),
            nullable=False,
        ),
        sa.Column("uplift_now", sa.Float(), nullable=False),
        sa.Column("uplift_best", sa.Float(), nullable=False),
        sa.Column("best_retry_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("chosen_action", sa.String(32), nullable=False),
        sa.Column("policy_version", sa.String(16), nullable=False),
        sa.Column(
            "rules_fired",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("assigned_treatment", sa.String(16), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_decisions_payment_id", "decisions", ["payment_id"])

    op.create_table(
        "actions",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "decision_id",
            sa.BigInteger(),
            sa.ForeignKey("decisions.id"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("api_attempt_no", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("response_body", postgresql.JSONB(), nullable=True),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_actions_decision_id", "actions", ["decision_id"])
    op.create_unique_constraint("uq_actions_idempotency_key", "actions", ["idempotency_key"])

    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("payload_json", postgresql.JSONB(), nullable=False),
        sa.Column("prev_hash", sa.String(64), nullable=True),
        sa.Column("hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_unique_constraint("uq_audit_log_hash", "audit_log", ["hash"])


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("actions")
    op.drop_table("decisions")
    op.drop_table("diagnoses")
    op.drop_table("reconciliations")
    op.drop_table("payment_attempts")
