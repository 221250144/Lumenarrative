"""Real FFmpeg regressions: source shots must not be sampling windows."""
from pathlib import Path
from types import SimpleNamespace
import shutil
import subprocess
import uuid

import pytest

from app.config import settings
from app.providers.storage import storage
from app.services.media.pipeline import SEGMENTATION_VERSION, dense_frames, preprocess, probe, run


pytestmark = pytest.mark.skipif(
    not shutil.which(settings.ffmpeg_bin) or not shutil.which(settings.ffprobe_bin),
    reason="FFmpeg and FFprobe are required for real video segmentation tests",
)


@pytest.fixture
def media_root(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "window_s", 8)
    monkeypatch.setattr(settings, "overlap_s", 2)
    return tmp_path


def make_asset(root: Path, clips, fps=25):
    folder = root / str(uuid.uuid4())
    folder.mkdir()
    source = folder / "source.mp4"
    nodes = []
    for index, (color, duration, filters) in enumerate(clips):
        nodes.append(
            f"color=c={color}:s=160x90:r={fps}:d={duration}"
            f"{',' + filters if filters else ''}[c{index}]"
        )
    nodes.append(
        "".join(f"[c{index}]" for index in range(len(clips)))
        + f"concat=n={len(clips)}:v=1:a=0[out]"
    )
    run([
        settings.ffmpeg_bin, "-y", "-v", "error", "-f", "lavfi",
        "-i", ";".join(nodes), "-c:v", "libx264", "-pix_fmt", "yuv420p", str(source),
    ])
    metadata = probe(source)
    return SimpleNamespace(
        id=str(uuid.uuid4()), storage_key=str(source.relative_to(root)),
        duration_s=metadata["duration_s"], has_audio=False, meta={},
    )


def process(asset):
    return preprocess(asset, lambda *args: None)


def assert_timeline(meta, duration):
    shots = meta["scene_shots"]
    assert meta["segmentation_version"] == SEGMENTATION_VERSION
    assert shots[0]["start_s"] == 0
    assert shots[-1]["end_s"] == pytest.approx(duration, abs=0.000001)
    assert [shot["index"] for shot in shots] == list(range(1, len(shots) + 1))
    for first, second in zip(shots, shots[1:]):
        assert first["end_s"] == second["start_s"]
    by_id = {shot["id"]: shot for shot in shots}
    for item in [*shots, *meta["shots"]]:
        assert item["start_s"] < item["end_s"]
        assert 1 <= len(item["keyframes"]) <= 4
        assert item["keyframes"] == sorted(item["keyframes"], key=lambda frame: frame["time_s"])
        for frame in item["keyframes"]:
            assert item["start_s"] <= frame["time_s"] < item["end_s"]
            assert storage.path(frame["key"]).is_file()
    for window in meta["shots"]:
        parent = by_id[window["shot_id"]]
        assert parent["start_s"] <= window["start_s"] < window["end_s"] <= parent["end_s"]
        assert parent["index"] == window["shot_index"]
    for shot in shots:
        windows = [window for window in meta["shots"] if window["shot_id"] == shot["id"]]
        assert windows[0]["start_s"] == shot["start_s"]
        assert windows[-1]["end_s"] == shot["end_s"]
        assert all(right["start_s"] <= left["end_s"] for left, right in zip(windows, windows[1:]))
        assert shot["thumbnail_key"] in {frame["key"] for frame in shot["keyframes"]}


def average_rgb(key):
    return tuple(subprocess.check_output([
        settings.ffmpeg_bin, "-v", "error", "-i", str(storage.path(key)),
        "-vf", "scale=1:1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-frames:v", "1", "-",
    ]))


def test_hard_cuts_are_contiguous_source_shots_with_correct_frames(media_root):
    asset = make_asset(media_root, [("red", 2, ""), ("blue", 3, ""), ("green", 2, "")])
    meta = process(asset)
    assert_timeline(meta, 7)
    assert meta["scene_boundaries"] == pytest.approx([2, 5], abs=0.04)
    assert len(meta["scene_shots"]) == 3
    assert [shot["boundary_type"] for shot in meta["scene_shots"]] == ["start", "hard_cut", "hard_cut"]
    for shot, channel in zip(meta["scene_shots"], [0, 2, 1]):
        for frame in shot["keyframes"]:
            rgb = average_rgb(frame["key"])
            assert rgb[channel] > max(rgb[index] for index in range(3) if index != channel) + 70


def test_subsecond_montage_never_loses_short_shot_images(media_root):
    asset = make_asset(media_root, [
        ("red", 0.16, ""), ("blue", 0.12, ""), ("white", 0.2, ""),
        ("green", 0.08, ""), ("red", 0.16, ""),
    ])
    meta = process(asset)
    assert_timeline(meta, 0.72)
    assert meta["scene_boundaries"] == pytest.approx([0.16, 0.28, 0.48, 0.56], abs=0.001)
    assert len(meta["scene_shots"]) == 5
    assert len(meta["shots"]) == 5
    assert all(shot["keyframes"] for shot in meta["scene_shots"])
    # Every short shot has its own decoded image, including those between 1fps ticks.
    assert len({shot["thumbnail_key"] for shot in meta["scene_shots"]}) == 5
    assert len(meta["scene_shots"][3]["keyframes"]) == 2


def test_long_continuous_take_is_one_shot_with_contained_analysis_windows(media_root):
    asset = make_asset(media_root, [("red", 19, "")])
    meta = process(asset)
    assert_timeline(meta, 19)
    assert len(meta["scene_shots"]) == 1
    assert meta["scene_boundaries"] == []
    assert [(window["start_s"], window["end_s"]) for window in meta["shots"]] == [(0, 8), (6, 14), (12, 19)]
    assert len(meta["scene_shots"][0]["keyframes"]) == 4
    assert meta["scene_shots"][0]["keyframes"][0]["time_s"] == 0
    assert meta["scene_shots"][0]["keyframes"][-1]["time_s"] == pytest.approx(18.96, abs=0.001)
    for window in meta["shots"]:
        assert len(window["keyframes"]) == 4
        assert window["keyframes"][0]["time_s"] == window["start_s"]
        assert window["keyframes"][-1]["time_s"] == pytest.approx(window["end_s"] - 0.04, abs=0.001)


def test_retry_replaces_frame_set_and_keeps_stable_shot_ids(media_root):
    asset = make_asset(media_root, [("red", 0.2, ""), ("blue", 0.2, "")], fps=30)
    first = process(asset)
    folder = storage.path(asset.storage_key).parent
    generation = storage.path(first["scene_shots"][0]["thumbnail_key"]).parent
    (generation / "frame-999999.jpg").write_bytes(b"stale retry frame")
    (folder / "frame-99999.jpg").write_bytes(b"legacy 1fps frame")
    second = process(asset)
    assert_timeline(second, asset.duration_s)
    assert len(second["scene_shots"]) == 2
    assert [shot["id"] for shot in first["scene_shots"]] == [shot["id"] for shot in second["scene_shots"]]
    assert not (generation / "frame-999999.jpg").exists()
    assert all("99999" not in frame["key"] for shot in second["scene_shots"] for frame in shot["keyframes"])
    assert second["scene_shots"][1]["keyframes"][0]["time_s"] == second["scene_shots"][1]["start_s"]


def test_internal_fade_through_black_is_labelled_candidate(media_root):
    asset = make_asset(media_root, [
        ("red", 2, "fade=t=out:st=1.5:d=0.5"),
        ("black", 0.16, ""),
        ("blue", 2, "fade=t=in:st=0:d=0.5"),
    ])
    meta = process(asset)
    assert_timeline(meta, asset.duration_s)
    fade_shots = [shot for shot in meta["scene_shots"] if shot["boundary_type"] == "fade_candidate"]
    assert len(fade_shots) == 1
    assert 1.5 < fade_shots[0]["start_s"] < 2.7
    assert "复杂叠化" in meta["segmentation"]["limitations"]


def test_local_review_has_real_frames_and_preserves_older_frame_sets(media_root, monkeypatch):
    asset = make_asset(media_root, [("red", 12, ""), ("blue", 0.08, "")])
    first = process(asset)
    old_keys = {frame["key"] for window in first["shots"] for frame in window["keyframes"]}
    monkeypatch.setattr(settings, "window_s", 6)
    second = process(asset)
    # Changing context windows must not make an old snapshot's frame URL point
    # at a different timestamp or remove its image.
    assert all(storage.path(key).is_file() for key in old_keys)
    assert [shot["id"] for shot in first["scene_shots"]] == [shot["id"] for shot in second["scene_shots"]]
    asset.meta = second
    long_review = dense_frames(asset, 0, 12)
    short_review = dense_frames(asset, 12, 12.08)
    assert len(long_review) == 4
    assert [frame["time_s"] for frame in short_review] == [12, 12.04]
    for frame in short_review:
        red, green, blue = average_rgb(frame["key"])
        assert blue > max(red, green) + 70
