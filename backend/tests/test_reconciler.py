from app.services.reconciler import reconcile


def test_non_ambiguous_code_is_always_known_failed() -> None:
    result = reconcile({"order_id": "order_x", "error_code": "card_declined"})
    assert result.is_known_failed is True
    assert result.gateway_reported_status == "failed"


def test_ambiguous_code_with_no_ground_truth_defaults_to_known_failed() -> None:
    result = reconcile({"order_id": "order_not_in_ground_truth", "error_code": "upi_timeout"})
    assert result.is_known_failed is True


def test_ambiguous_code_with_silent_success_blocks_retry(monkeypatch) -> None:
    import app.services.reconciler as reconciler_module

    monkeypatch.setattr(
        reconciler_module,
        "_ground_truth_by_order",
        lambda: {"order_silent": {"actually_succeeded_silently": True}},
    )
    result = reconciler_module.reconcile({"order_id": "order_silent", "error_code": "upi_timeout"})
    assert result.is_known_failed is False
    assert result.gateway_reported_status == "success"


def test_ambiguous_code_without_silent_success_is_known_failed(monkeypatch) -> None:
    import app.services.reconciler as reconciler_module

    monkeypatch.setattr(
        reconciler_module,
        "_ground_truth_by_order",
        lambda: {"order_normal": {"actually_succeeded_silently": False}},
    )
    result = reconciler_module.reconcile({"order_id": "order_normal", "error_code": "upi_timeout"})
    assert result.is_known_failed is True
