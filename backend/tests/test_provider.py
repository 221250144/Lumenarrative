import json
import httpx
import pytest
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_core import PydanticCustomError
from app.config import settings
from app.providers.models import CompatibleProvider
from app.schemas import RequirementsOutput, VlogRecommendation


def configure(monkeypatch, handler):
    original = httpx.Client
    monkeypatch.setattr(settings, "model_api_key", "test-key-not-real")
    monkeypatch.setattr(
        "app.providers.models.httpx.Client",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )


def response(content):
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": content}}],
            "usage": {"total_tokens": 3},
        },
    )


def test_structured_output_repairs_once_and_never_fabricates(monkeypatch):
    calls = []
    good = json.dumps(
        {
            "requirements": [
                {
                    "description": "看清手部动作",
                    "priority": "must",
                    "origin": "user_explicit",
                    "accepted_evidence_types": ["visual"],
                    "dependencies": [],
                    "user_confirmed": False,
                }
            ]
        },
        ensure_ascii=False,
    )

    def handler(request):
        calls.append(json.loads(request.content))
        return response("not json" if len(calls) == 1 else good)

    configure(monkeypatch, handler)
    result = CompatibleProvider().generate_structured(
        "test", {"intent": "手部动作"}, RequirementsOutput
    )
    assert result["requirements"][0]["description"] == "看清手部动作"
    assert len(calls) == 2 and len(calls[1]["messages"]) == 4


def test_repeated_schema_errors_fail_after_one_repair(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        return response('{"unexpected": true}')

    configure(monkeypatch, handler)
    with pytest.raises(ValueError, match="连续两次"):
        CompatibleProvider().generate_structured("test", {}, RequirementsOutput)
    assert len(calls) == 2


def test_duration_repair_receives_specific_field_and_numeric_constraints(monkeypatch, caplog):
    class Recommendation(BaseModel):
        duration_s: float = Field(gt=0, le=30)

    class Finding(BaseModel):
        recommendation: Recommendation

    class Review(BaseModel):
        findings: list[Finding]

    calls = []
    review = {"findings": [{"recommendation": {"duration_s": 4.0}} for _ in range(5)]}

    def handler(request):
        calls.append(json.loads(request.content))
        review["findings"][4]["recommendation"]["duration_s"] = 0.0 if len(calls) == 1 else 4.0
        return response(json.dumps(review))

    configure(monkeypatch, handler)
    result = CompatibleProvider().generate_structured("review", {}, Review)
    assert len(calls) == 2
    assert result["findings"][4]["recommendation"]["duration_s"] == 4.0
    feedback = calls[1]["messages"][-1]["content"]
    for expected in ("findings.4.recommendation.duration_s", "greater_than", '"exclusiveMinimum":0', '"maximum":30'):
        assert expected in feedback
        assert expected in caplog.text


def test_reshoot_zero_repair_includes_conditional_duration_rule(monkeypatch):
    calls = []
    recommendation = {
        "kind": "reshoot", "instruction": "补拍4秒餐厅入口，交代位置。",
        "shot_scale": "中景", "subject_action": "拍清入口与招牌", "duration_s": 0,
        "insert_position": "before", "acceptance_checks": ["入口与招牌清晰可见"],
    }

    def handler(request):
        calls.append(json.loads(request.content))
        if len(calls) > 1:
            recommendation["duration_s"] = 4
        return response(json.dumps(recommendation, ensure_ascii=False))

    configure(monkeypatch, handler)
    result = CompatibleProvider().generate_structured("review", {}, VlogRecommendation)
    assert len(calls) == 2 and result["duration_s"] == 4
    feedback = calls[1]["messages"][-1]["content"]
    assert "duration_s" in feedback and "reshoot补拍必须大于0" in feedback
    assert "reedit" in feedback and "不虚构时长" in feedback
    assert calls[1]["messages"][-2]["content"] == json.dumps(
        {**recommendation, "duration_s": 0}, ensure_ascii=False,
    )


def test_validation_details_do_not_expose_values_custom_errors_or_unknown_keys(monkeypatch, caplog):
    class SensitiveOutput(BaseModel):
        model_config = ConfigDict(extra="forbid")
        text: str

        @field_validator("text")
        @classmethod
        def reject(cls, value):
            raise PydanticCustomError(
                "SENSITIVE_ERROR_CODE", "SENSITIVE_MESSAGE: {value}",
                {"value": value, "private": "SENSITIVE_CONTEXT"},
            )

    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        return response(json.dumps({"text": "SENSITIVE_INPUT", "SENSITIVE_UNKNOWN_KEY": "SENSITIVE_VALUE"}))

    configure(monkeypatch, handler)
    with pytest.raises(ValueError, match="自动修复未成功") as error:
        CompatibleProvider().generate_structured("test", {}, SensitiveOutput)
    assert len(calls) == 2
    feedback = calls[1]["messages"][-1]["content"]
    assert "validation_error" in feedback and "[unknown field]" in feedback
    assert "SENSITIVE" not in feedback + caplog.text + str(error.value)
    # Suppress the underlying Pydantic exception, whose default traceback includes inputs.
    assert error.value.__suppress_context__ is True


def test_validation_details_are_bounded_without_dropping_schema_validation(monkeypatch, caplog):
    class NumberList(BaseModel):
        numbers: list[int]

    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        return response(json.dumps({"numbers": ["PRIVATE_CONTENT" + "x" * 1000] * 100}))

    configure(monkeypatch, handler)
    with pytest.raises(ValueError, match="连续两次"):
        CompatibleProvider().generate_structured("test", {}, NumberList)
    feedback = calls[1]["messages"][-1]["content"]
    assert '"error_count":100' in feedback and '"omitted":92' in feedback
    assert feedback.count('"path":') == 8
    assert len(feedback) < 5000
    assert "PRIVATE_CONTENT" not in feedback + caplog.text
    assert len(calls) == 2


def test_auth_failure_does_not_leak_key_or_fallback(monkeypatch):
    configure(
        monkeypatch,
        lambda request: httpx.Response(
            401, json={"error": "private payload must not surface"}
        ),
    )
    with pytest.raises(ValueError, match="HTTP 401") as error:
        CompatibleProvider().generate_structured("test", {}, RequirementsOutput)
    assert "test-key" not in str(error.value) and "private payload" not in str(
        error.value
    )


@pytest.mark.parametrize("seconds,read_limit", [(900, 900), (0, None)])
def test_long_inference_timeout_keeps_connection_and_upload_bounded(monkeypatch, seconds, read_limit):
    seen = []

    def handler(request):
        seen.append(request.extensions["timeout"])
        return response('{"requirements": []}')

    monkeypatch.setattr(settings, "model_timeout_s", seconds)
    configure(monkeypatch, handler)
    CompatibleProvider().generate_structured("test", {}, RequirementsOutput)
    assert seen == [{"connect": 30.0, "read": read_limit, "write": 60.0, "pool": 30.0}]


def test_model_read_timeout_is_clear_and_does_not_retry_paid_request(monkeypatch):
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("timed out", request=request)

    monkeypatch.setattr(settings, "model_timeout_s", 900)
    configure(monkeypatch, handler)
    with pytest.raises(ValueError, match="单次模型响应等待超时.*900"):
        CompatibleProvider().generate_structured("test", {}, RequirementsOutput)
    assert len(calls) == 1
