import json
import httpx
import pytest
from app.config import settings
from app.providers.models import CompatibleProvider
from app.schemas import RequirementsOutput


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
