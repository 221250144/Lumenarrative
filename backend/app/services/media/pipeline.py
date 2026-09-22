import bisect
import hashlib
import json
import math
import re
import shutil
import statistics
import subprocess
import tempfile
import uuid
from pathlib import Path
from app.config import settings
from app.providers.storage import storage
from app.services.concurrency import resource_slot
from app.services.media.shot_boundaries import MIN_SHOT_DURATION_S, select_shot_boundaries


# Changing shot detection or timestamp selection requires a new version so older
# assets are reprocessed before their shots are used for Vlog diagnosis.
SEGMENTATION_VERSION = "vlog-shots-v3-min500ms"
SCENE_SCORE_THRESHOLD = 0.22


def _bounded_ffmpeg_args(args: list[str]):
    """Apply one thread budget to every input, output and filter graph.

    Media commands in this service have one final output, including image
    sequences and null sinks. FFmpeg's codec options are scoped per file, so a
    single global -threads would leave later decoders/encoders unrestricted.
    """
    threads = str(settings.ffmpeg_threads)
    cleaned = [args[0]]
    index = 1
    while index < len(args):
        argument = args[index]
        name = argument.split("=", 1)[0].split(":", 1)[0]
        if name in ("-threads", "-filter_threads", "-filter_complex_threads"):
            # Existing per-stream overrides must not bypass the server budget.
            index += 1 if "=" in argument else 2
            continue
        cleaned.append(argument)
        index += 1
    bounded = [cleaned[0], "-filter_threads", threads, "-filter_complex_threads", threads]
    for argument in cleaned[1:]:
        if argument == "-i":
            bounded.extend(["-threads", threads])
        bounded.append(argument)
    if "-i" in cleaned:
        bounded[-1:-1] = ["-threads", threads]
    return bounded


def run(args: list[str], timeout=300):
    executable = str(args[0]) if args else ""
    is_ffmpeg = executable == settings.ffmpeg_bin or Path(executable).name in (
        "ffmpeg", "ffmpeg.exe",
    )
    if is_ffmpeg:
        args = _bounded_ffmpeg_args(args)
        # The slot is shared by API threads and every Celery process using the
        # same data directory. Waiting for a slot does not consume run timeout.
        with resource_slot("ffmpeg", settings.media_concurrency):
            process = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    else:
        # FFprobe is lightweight metadata inspection, not a transcode job.
        process = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if process.returncode:
        raise ValueError("媒体处理失败：" + process.stderr[-700:])
    return process.stdout, process.stderr


def probe(path: Path):
    out, _ = run(
        [
            settings.ffprobe_bin,
            "-v",
            "error",
            "-protocol_whitelist",
            "file,pipe",
            "-show_format",
            "-show_streams",
            "-of",
            "json",
            str(path),
        ],
        30,
    )
    info = json.loads(out)
    allowed = {"mov", "mp4", "m4a", "3gp", "3g2", "mj2", "matroska", "webm", "avi"}
    if not set(info.get("format", {}).get("format_name", "").split(",")) & allowed:
        raise ValueError("仅支持可解码的 MP4 / MOV / WebM / MKV / AVI 视频")
    video = next(
        (
            s
            for s in info["streams"]
            if s["codec_type"] == "video"
            and not s.get("disposition", {}).get("attached_pic")
        ),
        None,
    )
    if not video:
        raise ValueError("文件没有视频轨道")
    duration = float(video.get("duration") or info["format"].get("duration") or 0)
    if (
        not math.isfinite(duration)
        or not 0 < duration <= settings.max_project_duration_s
    ):
        raise ValueError("视频时长无效或超过项目时长上限")
    if video["width"] * video["height"] > 7680 * 4320:
        raise ValueError("首版最高支持 8K 视频，请先导出较低分辨率素材")
    return {
        "duration_s": duration,
        "width": video["width"],
        "height": video["height"],
        "has_audio": any(s["codec_type"] == "audio" for s in info["streams"]),
        "source_start_time": float(video.get("start_time", 0)),
    }


def windows(duration: float, boundaries=()):
    size, overlap = settings.window_s, settings.overlap_s
    if size <= 0 or overlap < 0 or overlap >= size:
        raise ValueError("分段配置必须满足 0 <= overlap < window")
    points = sorted(
        {0.0, duration, *(float(x) for x in boundaries if 0 < x < duration)}
    )
    result = []
    for a, b in zip(points, points[1:]):
        start = a
        while start < b - 0.05:
            end = min(start + size, b)
            result.append((round(start, 3), round(end, 3)))
            if end >= b:
                break
            start = end - overlap
    return result


def _scan_frames(proxy: Path):
    """Decode every frame once; use actual PTS, never a nominal sampling clock.

    RGB scene scores detect hard cuts even when two scenes have similar luma.
    Black intervals provide explicitly labelled fade-through-black candidates.
    This is visual candidate detection, not semantic shot-boundary ground truth:
    complex dissolves, whip pans and flashing lights can be missed/misclassified.
    """
    out, log = run(
        [
            settings.ffmpeg_bin, "-hide_banner", "-nostats", "-i", str(proxy),
            "-vf",
            "scale=320:-2,blackdetect=d=0.04:pix_th=0.10:pic_th=0.98,"
            "format=rgb24,select='gte(scene,0)',"
            "metadata=mode=print:key=lavfi.scene_score:file=-",
            "-an", "-fps_mode", "passthrough", "-f", "null", "-",
        ]
    )
    entries = re.findall(
        r"frame:(\d+)\s+pts:[^\s]+\s+pts_time:([-+\d.eE]+)\s+"
        r"lavfi.scene_score=([-+\d.eE]+)", out,
    )
    frames = [
        {"frame_index": int(index), "time_s": round(float(time), 6), "score": float(score)}
        for index, time, score in entries
    ]
    if not frames:
        raise ValueError("无法解码视频关键帧，请检查视频格式")
    black_intervals = [
        (float(start), float(end))
        for start, end in re.findall(
            r"black_start:([-+\d.eE]+)\s+black_end:([-+\d.eE]+)", log
        )
    ]
    return frames, black_intervals


def _scene_boundaries(frames, black_intervals, duration):
    timestamps = [frame["time_s"] for frame in frames]
    steps = [b - a for a, b in zip(timestamps, timestamps[1:]) if b > a]
    frame_step = statistics.median(steps) if steps else duration
    # First suppress adjacent-frame flicker. The minimum-length pass below then
    # merges cuts closer than 0.5s while retaining the stronger available cut.
    debounce = max(0.015, min(0.075, frame_step * 1.1))
    candidates = [
        {"time_s": frame["time_s"], "score": frame["score"], "type": "hard_cut"}
        for frame in frames
        if frame["score"] >= SCENE_SCORE_THRESHOLD
        and 0 < frame["time_s"] < duration
    ]
    fades = []
    for start, end in black_intervals:
        # A leading fade-in or final fade-out is not a new shot. Use one
        # boundary through an internal black interval, aligned to a real frame.
        if start <= frame_step or end >= duration - frame_step or end <= start:
            continue
        middle = (start + end) / 2
        index = min(bisect.bisect_left(timestamps, middle), len(timestamps) - 1)
        point = timestamps[index]
        if 0 < point < duration:
            fades.append({"time_s": point, "score": 1, "type": "fade_candidate"})
            candidates = [
                candidate for candidate in candidates
                if not start - debounce <= candidate["time_s"] <= end + debounce
            ]
    candidates = sorted(candidates + fades, key=lambda item: item["time_s"])
    kept = []
    for candidate in candidates:
        if kept and candidate["time_s"] - kept[-1]["time_s"] <= debounce:
            if candidate["score"] > kept[-1]["score"]:
                kept[-1] = candidate
        else:
            kept.append(candidate)
    return select_shot_boundaries(kept, 0.0, duration)


def _analysis_windows(start: float, end: float):
    """Overlap is only context within one shot, never a new transition."""
    size, overlap = settings.window_s, settings.overlap_s
    if size <= 0 or overlap < 0 or overlap >= size:
        raise ValueError("分段配置必须满足 0 <= overlap < window")
    result = []
    cursor = start
    while cursor < end:
        stop = min(cursor + size, end)
        result.append((round(cursor, 6), round(stop, 6)))
        if stop >= end:
            break
        cursor = stop - overlap
    return result


def _sample_indices(frames, start, end, limit=4):
    available = [
        frame["frame_index"] for frame in frames
        if start <= frame["time_s"] < end
    ]
    if not available:
        raise ValueError("镜头范围内没有可解码画面，请重新处理素材")
    count = min(limit, len(available))
    if count == 1:
        return [available[0]]
    # Include the first/last available source frame and evenly spaced context.
    return [available[round(i * (len(available) - 1) / (count - 1))] for i in range(count)]


def _frame_selection(indices):
    """Bound expression depth for FFmpeg's evaluator on long montages."""
    if not indices:
        return "0"
    if len(indices) == 1:
        return f"eq(n,{indices[0]})"
    middle = len(indices) // 2
    return f"({_frame_selection(indices[:middle])}+{_frame_selection(indices[middle:])})"


def _extract_selected_frames(proxy, folder, frames, selected):
    """One pass, exact frame indices, isolated outputs on every retry."""
    generation = hashlib.sha256(":".join(map(str, selected)).encode()).hexdigest()[:16]
    destination = folder / SEGMENTATION_VERSION / generation
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="keyframes-", dir=folder) as scratch:
        scratch = Path(scratch)
        output = scratch / "images"
        output.mkdir()
        filter_file = scratch / "select.txt"
        # A filter script avoids command-line length limits on long montages.
        selection = _frame_selection(selected)
        filter_file.write_text(f"select='{selection}',scale=640:-2")
        args = [
            settings.ffmpeg_bin, "-y", "-v", "error", "-i", str(proxy),
            "-/filter:v", str(filter_file), "-an", "-fps_mode", "passthrough",
            "-q:v", "3", str(output / "frame-%06d.jpg"),
        ]
        try:
            run(args)
        except ValueError as error:
            if "Unrecognized option '/filter:v'" not in str(error):
                raise
            # Older distro FFmpeg uses filter_script; FFmpeg 9 removed it in
            # favour of loading option values from files with the slash form.
            args[args.index("-/filter:v")] = "-filter_script:v"
            run(args)
        images = sorted(output.glob("frame-*.jpg"))
        if len(images) != len(selected):
            raise ValueError("关键帧数量与时间映射不符，请重新处理素材")
        # Never enumerate previous frame files: a retry may select fewer frames.
        if destination.exists():
            shutil.rmtree(destination)
        output.rename(destination)
    times = {frame["frame_index"]: frame["time_s"] for frame in frames}
    return {
        index: {
            "time_s": round(times[index], 6),
            "key": str((destination / f"frame-{number:06d}.jpg").relative_to(settings.data_dir.resolve())),
        }
        for number, index in enumerate(selected, 1)
    }


def preprocess(asset, progress):
    # Two analyses may both upgrade the same old asset. Keep all writes to its
    # preview and frame directories exclusive while unrelated assets proceed.
    with resource_slot("asset-" + asset.id, 1):
        return _preprocess(asset, progress)


def _preprocess(asset, progress):
    original = storage.path(asset.storage_key)
    folder = original.parent
    proxy = folder / "preview.mp4"
    progress("生成预览视频", 0, 1)
    run(
        [
            settings.ffmpeg_bin, "-y", "-v", "error",
            "-protocol_whitelist", "file,pipe", "-i", str(original),
            "-map", "0:v:0", "-map", "0:a:0?",
            "-vf", "setpts=PTS-STARTPTS,scale=w='min(960,iw)':h=-2,setsar=1",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "25",
            "-pix_fmt", "yuv420p", "-fps_mode", "vfr",
            "-c:a", "aac", "-ac", "2", "-ar", "48000",
            "-movflags", "+faststart", str(proxy),
        ]
    )
    preview_meta = probe(proxy)
    if abs(preview_meta["duration_s"] - asset.duration_s) > 0.3:
        raise ValueError("代理视频与源视频时长偏差超过 0.3 秒，需检查时间映射")
    progress("识别 Vlog 镜头与转场", 0, 1)
    frames, black_intervals = _scan_frames(proxy)
    frames = [frame for frame in frames if 0 <= frame["time_s"] < asset.duration_s]
    boundaries = _scene_boundaries(frames, black_intervals, asset.duration_s)
    starts = [{"time_s": 0.0, "type": "start"}, *boundaries]
    scene_shots, analysis = [], []
    selections = set()
    for index, (begin, end) in enumerate(
        zip(starts, [*[item["time_s"] for item in boundaries], asset.duration_s]), 1
    ):
        start, end = round(begin["time_s"], 6), round(end, 6)
        shot_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"xuguangji:{asset.id}:{start:.6f}:{end:.6f}"))
        indices = _sample_indices(frames, start, end)
        selections.update(indices)
        scene_shots.append({
            "id": shot_id, "index": index, "start_s": start, "end_s": end,
            "boundary_type": begin["type"], "boundary_score": begin.get("score", 0.0),
            "frame_indices": indices,
        })
        for window_start, window_end in _analysis_windows(start, end):
            indices = _sample_indices(frames, window_start, window_end)
            selections.update(indices)
            analysis.append({
                "shot_id": shot_id, "shot_index": index,
                "start_s": window_start, "end_s": window_end, "frame_indices": indices,
            })
    progress("抽取镜头关键帧", 0, len(selections))
    extracted = _extract_selected_frames(proxy, folder, frames, sorted(selections))
    for item in [*scene_shots, *analysis]:
        item["keyframes"] = [extracted[i] for i in item.pop("frame_indices")]
        if "id" in item:
            item["thumbnail_key"] = item["keyframes"][len(item["keyframes"]) // 2]["key"]
    progress("抽取镜头关键帧", len(selections), len(selections))
    audio_key = None
    if asset.has_audio:
        audio = folder / "audio.wav"
        run(
            [
                settings.ffmpeg_bin, "-y", "-v", "error", "-i", str(proxy),
                "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(audio),
            ]
        )
        audio_key = str(audio.relative_to(settings.data_dir.resolve()))
    return {
        **(asset.meta or {}),
        "proxy_key": str(proxy.relative_to(settings.data_dir.resolve())),
        "thumbnail_key": scene_shots[0]["thumbnail_key"],
        "audio_key": audio_key,
        "scene_shots": scene_shots,
        "shots": analysis,
        "scene_boundaries": [item["time_s"] for item in boundaries],
        "segmentation_version": SEGMENTATION_VERSION,
        "segmentation": {
            "method": "ffmpeg_rgb_scene_score_and_blackdetect",
            "scene_threshold": SCENE_SCORE_THRESHOLD,
            "minimum_shot_duration_s": MIN_SHOT_DURATION_S,
            "short_shot_policy": "merge_adjacent_keep_stronger_boundary",
            "limitations": "硬切自动检测；不足0.5秒的镜头并入相邻镜头，整片不足0.5秒时保留整片。经过黑场的淡入淡出仅为候选。复杂叠化、快速摇镜和闪光可能漏检或误分。分析窗口不代表转场。",
        },
        "time_mapping": "source_relative_seconds",
        "preview_duration_s": preview_meta["duration_s"],
        "preprocessing_version": SEGMENTATION_VERSION,
    }


def dense_frames(asset, start, end):
    """Bounded local review using real frame PTS, including subsecond shots."""
    if not 0 <= start < end <= asset.duration_s:
        raise ValueError("复核范围超出素材时间")
    folder = storage.path(asset.storage_key).parent / (
        "review-" + hashlib.sha256(f"{start}:{end}".encode()).hexdigest()[:12]
    )
    folder.mkdir(exist_ok=True)
    proxy = storage.path(asset.meta["proxy_key"])
    frames, _ = _scan_frames(proxy)
    selected = _sample_indices(frames, start, end)
    extracted = _extract_selected_frames(proxy, folder, frames, selected)
    return [extracted[index] for index in selected]
