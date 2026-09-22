import math
from pathlib import Path
from app.config import settings
from app.providers.storage import storage
from app.services.media.pipeline import run, probe


def validate_timeline(timeline, assets, max_duration=600):
    if not timeline or len(timeline) > 100:
        raise ValueError("时间线需包含 1—100 个片段")
    total = 0.0
    for clip in timeline:
        asset = assets.get(clip["asset_id"])
        a, b = clip["source_in_s"], clip["source_out_s"]
        if asset is None or asset.status != "ready":
            raise ValueError("时间线引用了未就绪或不属于本项目的素材")
        if (
            not all(math.isfinite(x) for x in (a, b))
            or not 0 <= a < b <= asset.duration_s + 0.001
        ):
            raise ValueError("时间线入出点超出原片范围")
        if not storage.path(asset.storage_key).is_file():
            raise ValueError("原始素材文件不存在")
        total += b - a
    if total > max_duration + 0.01:
        raise ValueError("时间线超过时长上限")
    return total


def make_timeline(assets, evidence, matches, target_duration, primary_id=None):
    if primary_id:
        ordered = [a for a in assets if a.id == primary_id]
    else:
        evs = {e["id"]: e for e in evidence}
        ids = []
        for m in matches:
            for eid in m["evidence_ids"]:
                if eid in evs and evs[eid]["asset_id"] not in ids:
                    ids.append(evs[eid]["asset_id"])
        ids += [a.id for a in assets if a.id not in ids]
        ordered = sorted(assets, key=lambda a: ids.index(a.id))
    result, remaining = [], target_duration
    for asset in ordered:
        if remaining <= 0.05:
            break
        duration = min(asset.duration_s, remaining)
        result.append(
            {"asset_id": asset.id, "source_in_s": 0.0, "source_out_s": duration}
        )
        remaining -= duration
    return result


def render(edit_id, timeline, assets, progress):
    expected = validate_timeline(timeline, assets)
    folder = storage.path("renders/" + edit_id)
    folder.mkdir(parents=True, exist_ok=True)
    clips = []
    for i, item in enumerate(timeline):
        asset = assets[item["asset_id"]]
        out = folder / f"{i:04d}.mp4"
        duration = item["source_out_s"] - item["source_in_s"]
        args = [
            settings.ffmpeg_bin,
            "-y",
            "-v",
            "error",
            "-ss",
            str(item["source_in_s"]),
            "-i",
            str(storage.path(asset.storage_key)),
        ]
        if not asset.has_audio:
            args += [
                "-f",
                "lavfi",
                "-i",
                "anullsrc=channel_layout=stereo:sample_rate=48000",
            ]
        args += [
            "-t",
            str(duration),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0" if asset.has_audio else "1:a:0",
            "-vf",
            "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30",
            "-af",
            "aresample=48000,apad",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-movflags",
            "+faststart",
            str(out),
        ]
        run(args)
        clips.append(out.name)
        progress("渲染片段", i + 1, len(timeline) + 1)
    manifest = folder / "concat.txt"
    manifest.write_text("".join(f"file '{name}'\n" for name in clips))
    output = folder / "output.mp4"
    run(
        [
            settings.ffmpeg_bin,
            "-y",
            "-v",
            "error",
            "-f",
            "concat",
            "-safe",
            "1",
            "-i",
            str(manifest),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(output),
        ]
    )
    meta = probe(output)
    if abs(meta["duration_s"] - expected) > max(0.3, len(timeline) * 0.05):
        raise ValueError("渲染时长校验失败")
    progress("视频导出完成", len(timeline) + 1, len(timeline) + 1)
    return str(output.relative_to(settings.data_dir.resolve())), meta
