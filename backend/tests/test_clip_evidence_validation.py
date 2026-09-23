from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.providers.validation import clip_evidence_schema
from app.schemas import EvidenceOutput


@pytest.fixture
def evidence():
    return {
        "source_start_s": 39.512345678,
        "source_end_s": 44.066666667,
        "subjects": ["行人"],
        "action": "行人沿河岸向前行走",
        "start_state": "步行中",
        "end_state": "继续前行",
        "story_roles": ["过程"],
        "quality_issues": [],
        "uncertainty": "",
        "evidence_type": "visual",
    }


def test_valid_absolute_timestamps_and_observations_are_unchanged(evidence):
    schema = clip_evidence_schema(39.5, 44.066666667)
    payload = {"evidence": [deepcopy(evidence)]}
    result = schema.model_validate(payload)
    assert isinstance(result, EvidenceOutput)
    assert result.model_dump() == payload
    assert result.evidence[0].source_start_s == 39.512345678
    assert result.evidence[0].source_end_s == 44.066666667


def test_schema_exposes_exact_window_bounds_and_absolute_time_semantics():
    schema = clip_evidence_schema(39.5, 44.066666667).model_json_schema()
    items = schema["properties"]["evidence"]["items"]
    fields = schema["$defs"][items["$ref"].rsplit("/", 1)[-1]]["properties"]
    assert fields["source_start_s"]["minimum"] == 39.5
    assert fields["source_start_s"]["exclusiveMaximum"] == 44.066666667
    assert fields["source_end_s"]["exclusiveMinimum"] == 39.5
    assert fields["source_end_s"]["maximum"] == 44.066666667
    assert "原片绝对时间" in fields["source_start_s"]["description"]
    assert "严格大于source_start_s" in fields["source_end_s"]["description"]


@pytest.mark.parametrize("start,end", [
    (39.49999999, 42), (40, 44.066666668),  # Outside either window boundary.
    (0, 2), (39.5, 39.5), (41, 41), (42, 41),  # Relative, empty, reversed.
    (44.066666667, 44.066666667),
    (float("nan"), 42), (40, float("nan")),
    (float("inf"), 42), (40, float("inf")),
    (float("-inf"), 42), (40, float("-inf")),
])
def test_invalid_intervals_are_rejected_without_coercing_bounds(evidence, start, end):
    schema = clip_evidence_schema(39.5, 44.066666667)
    with pytest.raises(ValidationError):
        schema.model_validate({"evidence": [{
            **evidence, "source_start_s": start, "source_end_s": end,
        }]})


def test_zero_length_error_identifies_end_field(evidence):
    schema = clip_evidence_schema(39.5, 44.066666667)
    with pytest.raises(ValidationError) as raised:
        schema.model_validate({"evidence": [{
            **evidence, "source_start_s": 41, "source_end_s": 41,
        }]})
    error = raised.value.errors()[0]
    assert error["loc"] == ("evidence", 0, "source_end_s")
    assert "严格大于source_start_s" in error["msg"]


def test_output_constraints_defaults_and_evidence_enums_are_inherited(evidence):
    schema = clip_evidence_schema(39.5, 44.066666667)
    assert schema.model_validate({"evidence": []}).model_dump() == {"evidence": []}
    assert len(schema.model_validate({"evidence": [evidence, evidence]}).evidence) == 2
    invalid_outputs = [
        {}, {"evidence": [evidence] * 3}, {"evidence": [], "extra": "value"},
        {"evidence": [{**evidence, "extra": "value"}]},
        {"evidence": [{**evidence, "evidence_type": "guessed"}]},
        {"evidence": [{key: value for key, value in evidence.items() if key != "action"}]},
    ]
    for payload in invalid_outputs:
        with pytest.raises(ValidationError):
            schema.model_validate(payload)
    minimal = {key: evidence[key] for key in ("source_start_s", "source_end_s", "action")}
    assert schema.model_validate({"evidence": [minimal]}).model_dump() == (
        EvidenceOutput.model_validate({"evidence": [minimal]}).model_dump()
    )


def test_window_schemas_do_not_share_or_mutate_bounds(evidence):
    early = clip_evidence_schema(0, 5)
    later = clip_evidence_schema(39.5, 44.066666667)
    assert later.model_validate({"evidence": [evidence]}).evidence[0].source_start_s == evidence["source_start_s"]
    with pytest.raises(ValidationError):
        early.model_validate({"evidence": [evidence]})
    assert "maximum" not in EvidenceOutput.model_json_schema()["$defs"]["EvidenceDraft"]["properties"]["source_end_s"]


@pytest.mark.parametrize("start,end", [
    (-1, 1), (1, 1), (2, 1), (0, float("nan")), (0, float("inf")),
    (float("-inf"), 5), (True, 5), (0, False), ("0", 5),
])
def test_invalid_sampling_windows_cannot_create_a_schema(start, end):
    with pytest.raises(ValueError):
        clip_evidence_schema(start, end)
