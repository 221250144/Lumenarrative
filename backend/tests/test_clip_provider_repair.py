"""The real provider request path repairs sampled-window errors once, without clamping."""

import json
from types import SimpleNamespace

import pytest

from app.providers.models import CompatibleProvider
from app.providers.storage import storage
from test_provider import configure, response


@pytest.mark.parametrize("bad_start,bad_end,field", [
    (39.51234, 44.5, "source_end_s"),
    (39.5, 39.5, "source_end_s"),
    (0.0, 4.0, "source_start_s"),
    (42.0, 41.0, "source_end_s"),
])
def test_clip_provider_repairs_window_error_using_same_frames_and_preserves_precision(
    monkeypatch, tmp_path, bad_start, bad_end, field,
):
    image = tmp_path / "sample.jpg"
    image.write_bytes(b"mock-image-bytes")
    monkeypatch.setattr(storage, "path", lambda _key: image)
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        start, end = (bad_start, bad_end) if len(calls) == 1 else (39.51234, 44.01234)
        return response(json.dumps({"evidence": [{
            "source_start_s": start, "source_end_s": end, "action": "沿着河岸行走", "evidence_type": "visual",
        }]}))

    configure(monkeypatch, handler)
    result = CompatibleProvider().analyze_clip(
        SimpleNamespace(duration_s=96.0),
        {"start_s": 39.5, "end_s": 44.0667, "keyframes": [{"key": "sample.jpg", "time_s": 40.0}]},
    )
    assert len(calls) == 2
    assert result[0]["source_start_s"] == 39.51234 and result[0]["source_end_s"] == 44.01234
    assert calls[1]["messages"][:2] == calls[0]["messages"]
    assert calls[0]["messages"][1]["content"][-1]["type"] == "image_url"
    repair = calls[1]["messages"][-1]["content"]
    assert f"evidence.0.{field}" in repair
    assert "39.5" in repair and "44.0667" in repair
