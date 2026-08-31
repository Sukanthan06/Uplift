import pytest

from simulator import taxonomy


def test_every_code_has_a_valid_cause_family() -> None:
    for code in taxonomy.DECLINE_TAXONOMY:
        assert code.cause_family in taxonomy.CAUSE_FAMILIES


def test_every_method_has_both_transient_and_hard_codes() -> None:
    methods = {c.method for c in taxonomy.DECLINE_TAXONOMY}
    assert methods == {"card", "upi", "netbanking", "wallet"}
    for method in methods:
        codes = taxonomy.codes_for_method(method)
        assert any(c.is_transient for c in codes)
        assert any(not c.is_transient for c in codes)


def test_every_code_has_a_source_citation() -> None:
    for code in taxonomy.DECLINE_TAXONOMY:
        assert code.source.strip()


def test_codes_for_unknown_method_raises() -> None:
    with pytest.raises(KeyError):
        taxonomy.codes_for_method("cheque")
