import hashlib
import json
import math
import re
import subprocess
from pathlib import Path
from app.config import settings
from app.providers.storage import storage


def run(args: list[str], timeout=300):
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


def preprocess(asset, progress):
    original = storage.path(asset.storage_key)
    folder = original.parent
    proxy = folder / "preview.mp4"
    progress("生成预览视频", 0, 1)
    run(
        [
            settings.ffmpeg_bin,
            "-y",
            "-v",
            "error",
            "-protocol_whitelist",
            "file,pipe",
            "-i",
            str(original),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
            "-vf",
            "scale=w='min(960,iw)':h=-2,setsar=1",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "25",
            "-pix_fmt",
            "yuv420p",
            "-fps_mode",
            "vfr",
            "-c:a",
            "aac",
            "-ac",
            "2",
            "-ar",
            "48000",
            "-movflags",
            "+faststart",
            str(proxy),
        ]
    )
    preview_meta = probe(proxy)
    if abs(preview_meta["duration_s"] - asset.duration_s) > 0.3:
        raise ValueError("代理视频与源视频时长偏差超过 0.3 秒，需检查时间映射")
    _, scene_log = run(
        [
            settings.ffmpeg_bin,
            "-hide_banner",
            "-i",
            str(proxy),
            "-vf",
            "select='gt(scene,0.32)',showinfo",
            "-an",
            "-f",
            "null",
            "-",
        ]
    )
    boundaries = [float(x) for x in re.findall(r"pts_time:([\d.]+)", scene_log)]
    segments = windows(asset.duration_s, boundaries)
    # Single-pass sparse sampling: retain source-relative timestamp for each frame.
    fps = max(0.25, min(settings.sample_fps, 4))
    run(
        [
            settings.ffmpeg_bin,
            "-y",
            "-v",
            "error",
            "-i",
            str(proxy),
            "-vf",
            f"fps={fps}:start_time=0,scale=640:-2",
            "-q:v",
            "3",
            str(folder / "frame-%05d.jpg"),
        ]
    )
    frames = [
        {
            "time_s": round(i / fps, 4),
            "key": str(f.relative_to(settings.data_dir.resolve())),
        }
        for i, f in enumerate(sorted(folder.glob("frame-*.jpg")))
        if i / fps < asset.duration_s
    ]
    shots = []
    for i, (start, end) in enumerate(segments):
        shots.append(
            {
                "start_s": start,
                "end_s": end,
                "keyframes": [f for f in frames if start <= f["time_s"] < end],
            }
        )
        progress("抽帧与时间映射", i + 1, len(segments))
    audio_key = None
    if asset.has_audio:
        audio = folder / "audio.wav"
        run(
            [
                settings.ffmpeg_bin,
                "-y",
                "-v",
                "error",
                "-i",
                str(proxy),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                str(audio),
            ]
        )
        audio_key = str(audio.relative_to(settings.data_dir.resolve()))
    return {
        **asset.meta,
        "proxy_key": str(proxy.relative_to(settings.data_dir.resolve())),
        "thumbnail_key": frames[0]["key"] if frames else None,
        "audio_key": audio_key,
        "shots": shots,
        "scene_boundaries": boundaries,
        "time_mapping": "source_relative_seconds",
        "preview_duration_s": preview_meta["duration_s"],
        "preprocessing_version": "frames-v1",
    }


def dense_frames(asset, start, end):
    folder = storage.path(asset.storage_key).parent / (
        "review-" + hashlib.sha256(f"{start}:{end}".encode()).hexdigest()[:12]
    )
    folder.mkdir(exist_ok=True)
    run(
        [
            settings.ffmpeg_bin,
            "-y",
            "-v",
            "error",
            "-ss",
            str(start),
            "-i",
            str(storage.path(asset.meta["proxy_key"])),
            "-t",
            str(end - start),
            "-vf",
            "fps=4,scale=640:-2",
            "-q:v",
            "3",
            str(folder / "%04d.jpg"),
        ]
    )
    return [
        {
            "time_s": round(start + i / 4, 3),
            "key": str(f.relative_to(settings.data_dir.resolve())),
        }
        for i, f in enumerate(sorted(folder.glob("*.jpg")))
        if start + i / 4 < end
    ]
