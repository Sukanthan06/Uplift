from app.models import AuditLog
from app.services.audit import (
    GENESIS_PREV_HASH,
    AuditRecord,
    _compute_hash,
    append,
    verify,
    verify_chain,
)


def _build_chain(payloads: list[dict]) -> list[AuditRecord]:
    """Mimics what audit.append() would produce for a sequence of payloads,
    without touching the DB -- lets the chain-walking logic be tested in
    isolation."""
    records = []
    prev_hash = GENESIS_PREV_HASH
    for i, payload in enumerate(payloads, start=1):
        h = _compute_hash(prev_hash, payload)
        records.append(AuditRecord(id=i, payload_json=payload, prev_hash=prev_hash, hash=h))
        prev_hash = h
    return records


def test_untampered_chain_is_entirely_valid() -> None:
    records = _build_chain([{"event": "a"}, {"event": "b"}, {"event": "c"}])
    results = verify_chain(records)
    assert all(r.valid for r in results)
    assert all(r.reason is None for r in results)


def test_empty_chain_is_valid() -> None:
    assert verify_chain([]) == []


def test_single_genesis_record_is_valid() -> None:
    records = _build_chain([{"event": "only"}])
    results = verify_chain(records)
    assert results[0].valid is True


def test_naive_tamper_breaks_that_record_and_every_one_after() -> None:
    """CLAUDE.md Phase 6: manually mutating a row causes chain verification
    to fail on that record and every one after."""
    records = _build_chain([{"event": "a"}, {"event": "b"}, {"event": "c"}, {"event": "d"}])
    tampered = list(records)
    tampered[1] = AuditRecord(
        id=records[1].id,
        payload_json={"event": "TAMPERED"},
        prev_hash=records[1].prev_hash,
        hash=records[1].hash,  # attacker left the hash column alone
    )

    results = verify_chain(tampered)
    assert results[0].valid is True
    assert results[1].valid is False
    assert results[1].reason == "payload does not match this record's stored hash"
    assert results[2].valid is False
    assert results[2].reason == "chain already broken at an earlier record"
    assert results[3].valid is False


def test_sophisticated_tamper_that_recomputes_its_own_hash_breaks_the_next_record() -> None:
    """A tamperer who edits the payload AND recomputes that record's own
    hash to hide the edit is still caught -- at the next record, whose
    prev_hash now points to a hash value that no longer exists in the
    (unmodified) chain after it."""
    records = _build_chain([{"event": "a"}, {"event": "b"}, {"event": "c"}])
    tampered_payload = {"event": "TAMPERED"}
    fake_hash = _compute_hash(records[1].prev_hash, tampered_payload)
    tampered = list(records)
    tampered[1] = AuditRecord(
        id=records[1].id,
        payload_json=tampered_payload,
        prev_hash=records[1].prev_hash,
        hash=fake_hash,
    )
    # record 3 (index 2) still has the ORIGINAL prev_hash, which no longer
    # matches record 2's new (recomputed) hash.

    results = verify_chain(tampered)
    assert results[0].valid is True
    assert results[1].valid is True  # its own hash math now checks out
    assert results[2].valid is False
    assert results[2].reason == "prev_hash does not match the previous record's stored hash"


def test_canonical_json_key_order_does_not_affect_hash() -> None:
    payload_a = {"b": 2, "a": 1}
    payload_b = {"a": 1, "b": 2}
    hash_a = _compute_hash(GENESIS_PREV_HASH, payload_a)
    hash_b = _compute_hash(GENESIS_PREV_HASH, payload_b)
    assert hash_a == hash_b


def test_different_payload_produces_different_hash() -> None:
    h1 = _compute_hash(GENESIS_PREV_HASH, {"event": "a"})
    h2 = _compute_hash(GENESIS_PREV_HASH, {"event": "b"})
    assert h1 != h2


def test_append_first_record_chains_off_genesis(fake_session) -> None:
    row = append({"event": "a"}, session=fake_session)
    assert row.prev_hash == GENESIS_PREV_HASH
    assert row.hash == _compute_hash(GENESIS_PREV_HASH, {"event": "a"})


def test_append_second_record_chains_off_the_first(fake_session) -> None:
    first = append({"event": "a"}, session=fake_session)
    second = append({"event": "b"}, session=fake_session)
    assert second.prev_hash == first.hash
    assert second.hash == _compute_hash(first.hash, {"event": "b"})


def test_verify_reports_all_valid_for_untampered_appends(fake_session) -> None:
    append({"event": "a"}, session=fake_session)
    append({"event": "b"}, session=fake_session)
    append({"event": "c"}, session=fake_session)
    results = verify(session=fake_session)
    assert len(results) == 3
    assert all(r.valid for r in results)


def test_verify_detects_a_direct_row_tamper(fake_session) -> None:
    append({"event": "a"}, session=fake_session)
    second = append({"event": "b"}, session=fake_session)
    append({"event": "c"}, session=fake_session)

    row = next(r for r in fake_session.rows_of(AuditLog) if r.id == second.id)
    row.payload_json = {"event": "TAMPERED"}

    results = verify(session=fake_session)
    assert results[0].valid is True
    assert results[1].valid is False
    assert results[2].valid is False
