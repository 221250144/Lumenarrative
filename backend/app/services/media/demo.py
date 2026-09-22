import hashlib
import shutil
from app.models import Asset, uid
from app.providers.storage import storage
from app.config import settings
from app.services.media.pipeline import run, probe

SCENARIOS = {
    "missing": ["establish", "result"],
    "complete": ["establish", "process", "result"],
    "obscured": ["establish", "obscured", "result"],
    "unordered": ["result", "process", "establish"],
    "montage": ["establish", "result"],
    "dialogue": ["process", "result"],
    "conflict": ["establish", "process", "conflict"],
    "partial": ["establish", "result", "process"],
}
NAMES = {
    "establish": "01_午后场景.mp4",
    "process": "02_制作过程.mp4",
    "result": "03_完成时刻.mp4",
    "obscured": "02_动作遮挡.mp4",
    "conflict": "03_属性冲突.mp4",
}


def create_demo_asset(db, project, role):
    if role not in NAMES:
        raise ValueError("未知演示分镜")
    cache = storage.path("demo-source/" + role + ".mp4")
    cache.parent.mkdir(parents=True, exist_ok=True)
    colors = {
        "establish": "0xb98357",
        "process": "0x668a77",
        "result": "0x9c685b",
        "obscured": "0x636977",
        "conflict": "0x5775a0",
    }
    if not cache.exists():
        # Generated geometric storyboard cards. Narrative labels are fixtures, not VLM observations.
        background = colors[role]
        filters = "drawbox=x=80:y=65:w=800:h=410:color=white@0.10:t=2,drawbox=x=0:y=400:w=960:h=140:color=0x20252a:t=fill,drawbox=x=380:y=250:w=160:h=150:color=0xf0dfca:t=fill,drawbox=x=395:y=255:w=130:h=12:color=0x523924:t=fill,drawbox=x=540:y=282:w=50:h=65:color=0xf0dfca:t=8"
        if role == "process":
            filters += ",drawbox=x=450:y=110:w=10:h=145:color=0xeee2d0:t=fill"
        if role == "obscured":
            filters += ",drawbox=x=290:y=205:w=360:h=170:color=0x30323a:t=fill"
        run(
            [
                settings.ffmpeg_bin,
                "-y",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                f"color=c={background}:s=960x540:r=24:d=5",
                "-vf",
                filters,
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(cache),
            ]
        )
    aid = uid()
    target = storage.path(f"assets/{project.id}/{aid}/original.mp4")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(cache, target)
    meta = probe(target)
    asset = Asset(
        id=aid,
        project_id=project.id,
        source_type="unknown",
        original_name=NAMES[role],
        storage_key=str(target.relative_to(settings.data_dir.resolve())),
        sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
        duration_s=meta["duration_s"],
        width=meta["width"],
        height=meta["height"],
        has_audio=meta["has_audio"],
        meta={
            "demo_role": role,
            "demo_fail": project.demo_scenario == "partial" and role == "process",
            "demo_audio_context": project.demo_scenario == "dialogue"
            and role == "process",
            "synthetic_media": True,
        },
    )
    db.add(asset)
    project.revision += 1
    project.latest_analysis_id = None
    db.flush()
    return asset
