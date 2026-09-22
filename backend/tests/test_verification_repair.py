from copy import deepcopy
import pytest
from app.providers.models import CompatibleProvider
from app.services.diagnosis.verification import validate_verification_result


TASK = {"acceptance_checks": ["从院内走向出口"]}
NEW = [{"id": "new-1", "action": "从院内走向出口"}]
OLD = [{"id": "old-1", "action": "原片已经出现出口"}]
GOOD = {"checks": [{"check": TASK["acceptance_checks"][0], "status": "passed", "evidence_ids": ["new-1"], "reason": "镜头展示了离开动作"}],
        "requirement_status": "passed", "reason": "新画面可表达离开动作", "continuity_issues": []}


def outputs(monkeypatch, values):
    calls = []
    def generate(self, instruction, payload, schema, images=()):
        calls.append(deepcopy(payload))
        assert len(calls) <= len(values), "semantic repair must be bounded"
        return deepcopy(values[len(calls) - 1])
    monkeypatch.setattr(CompatibleProvider, "generate_structured", generate)
    return calls


def test_valid_verification_does_not_request_repair(monkeypatch):
    calls = outputs(monkeypatch, [GOOD])
    assert CompatibleProvider().verify(TASK, NEW, OLD) == GOOD
    assert len(calls) == 1


@pytest.mark.parametrize("invalid", ["old_reference", "invented_reference", "missing_reference", "changed_check"])
def test_verification_repairs_invalid_semantics_with_original_evidence(monkeypatch, invalid):
    bad = deepcopy(GOOD)
    if invalid == "changed_check":
        bad["checks"][0]["check"] = "另一个更容易通过的条件"
    else:
        bad["checks"][0]["evidence_ids"] = {"old_reference": ["old-1"], "invented_reference": ["fake"], "missing_reference": []}[invalid]
    calls = outputs(monkeypatch, [bad, GOOD])
    assert CompatibleProvider().verify(TASK, NEW, OLD) == GOOD
    assert len(calls) == 2
    assert calls[1]["previous_verification"] == bad
    assert calls[1]["validation_error"]
    for key in ["task", "new_evidence", "reference_evidence", "allowed_new_evidence_ids"]:
        assert calls[0][key] == calls[1][key]
    assert calls[1]["allowed_new_evidence_ids"] == ["new-1"]


def test_two_invalid_responses_fail_without_dropping_invalid_citations(monkeypatch):
    bad = deepcopy(GOOD)
    bad["checks"][0]["evidence_ids"] = ["new-1", "old-1"]
    calls = outputs(monkeypatch, [bad, bad])
    with pytest.raises(ValueError, match="连续两次"):
        CompatibleProvider().verify(TASK, NEW, OLD)
    assert len(calls) == 2
    with pytest.raises(ValueError, match="新素材证据"):
        validate_verification_result(bad, TASK, NEW)
