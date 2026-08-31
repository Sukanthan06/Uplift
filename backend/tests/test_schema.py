from app.models import Base


def test_all_five_tables_registered_on_metadata() -> None:
    expected = {
        "payment_attempts",
        "reconciliations",
        "diagnoses",
        "decisions",
        "actions",
        "audit_log",
    }
    assert expected == set(Base.metadata.tables)


def test_actions_idempotency_key_is_unique() -> None:
    table = Base.metadata.tables["actions"]
    unique_cols = {
        col.name
        for constraint in table.constraints
        for col in constraint.columns
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert "idempotency_key" in unique_cols


def test_audit_log_hash_is_unique() -> None:
    table = Base.metadata.tables["audit_log"]
    unique_cols = {
        col.name
        for constraint in table.constraints
        for col in constraint.columns
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert "hash" in unique_cols


def test_payment_attempts_self_referential_fk() -> None:
    table = Base.metadata.tables["payment_attempts"]
    fk_targets = {fk.target_fullname for fk in table.foreign_keys}
    assert "payment_attempts.id" in fk_targets
