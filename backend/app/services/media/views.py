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
