def selected_reference_frame(asset, at):
    """One shared selection rule for displayed and submitted reference images."""
    if not 0 <= at < asset.duration_s:
        raise ValueError("参考帧时间超出素材范围")
    scene = next((s for s in asset.meta.get("scene_shots", []) if s["start_s"] <= at < s["end_s"]), None)
    frames = [f for shot in asset.meta.get("shots", [])
              if scene is None or shot.get("shot_id") == scene["id"]
              for f in shot["keyframes"]]
    if scene:
        frames += scene["keyframes"]
    if not frames:
        raise ValueError("参考帧尚未准备好")
    return min(frames, key=lambda frame: abs(frame["time_s"] - at))


def asset_shots(asset):
    """Public shot metadata, without storage paths or model-only sampling windows."""
    return [
        {
            "id": shot["id"], "asset_id": asset.id, "index": shot["index"],
            "start_s": shot["start_s"], "end_s": shot["end_s"],
            "boundary_type": shot["boundary_type"],
            "thumbnail_url": f"/api/v1/assets/{asset.id}/frame?at={shot['keyframes'][len(shot['keyframes']) // 2]['time_s']}",
        }
        for shot in asset.meta.get("scene_shots", [])
    ]
