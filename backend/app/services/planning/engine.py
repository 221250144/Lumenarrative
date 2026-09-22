from app.models import uid
from app.services.diagnosis.vlog import select_key_evidence


def select_budget(candidates, budget):
    selected, covered, spent = [], set(), 0
    remaining = list(candidates)
    while remaining:
        viable = [
            t
            for t in remaining
            if t.get("feasible", True)
            and not t.get("needs_confirmation")
            and any(g not in covered for g in t["gap_ids"])
            and (budget is None or spent + t["estimated_effort_min"] <= budget)
        ]
        if not viable:
            break
        best = max(
            viable,
            key=lambda t: (
                sum(t.get("weight", 1) for g in t["gap_ids"] if g not in covered)
                / max(1, t["estimated_effort_min"])
            ),
        )
        selected.append(best["id"])
        covered.update(best["gap_ids"])
        spent += best["estimated_effort_min"]
        remaining.remove(best)
    return selected, covered, spent


def plan_tasks(gaps, requirements, evidence, budget, demo=False):
    tasks = []
    reqs = {r["id"]: r for r in requirements}
    evs = {e["id"]: e for e in evidence}
    for gap in gaps:
        if gap["status"] in ("resolved", "dismissed") or gap["optional"]:
            continue
        req = reqs[gap["requirement_id"]]
        reference_ids = select_key_evidence(evidence, gap["evidence_ids"], limit=2)
        references = [evs[e] for e in reference_ids]
        known = "；".join(
            dict.fromkeys(
                s for e in references for s in e.get("subjects", []) if s != "unknown"
            )
        )
        continuity = (
            f"保持已有参考中的主体与场景一致：{known}"
            if known
            else "主体、服装、场景尚未确认；请由创作者补充，不虚构具体属性。"
        )
        options = (
            [("reedit", 5)]
            if gap["alternative_edit"]["feasible"]
            else [("import_existing", 3), ("reshoot", 15), ("generate", 8)]
        )
        recommendation = gap.get("recommendation")
        if recommendation:
            options = [(recommendation["kind"], 5 if recommendation["kind"] == "reedit" else 15)]
        for kind, effort in options:
            instruction = {
                "reedit": gap["alternative_edit"]["reason"],
                "import_existing": f"查找尚未上传的素材，补入能表达“{req['description']}”的片段。",
                "reshoot": f"围绕“{req['description']}”补拍 4—8 秒镜头；主体与动作保持可见，动作前后各留 1 秒余量。",
                "generate": f"在外部视频工具生成表达“{req['description']}”的片段，下载后上传验证。",
            }[kind]
            checks = [
                f"观众能够辨认：{req['description']}",
                "关键表达没有被遮挡或截断",
                "与参考素材的主体、场景连续性一致或有合理交代",
            ]
            if recommendation:
                instruction = recommendation["instruction"]
                checks = recommendation["acceptance_checks"]
            tasks.append(
                {
                    "id": uid(),
                    "type": kind,
                    "gap_ids": [gap["id"]],
                    "requirement_id": req["id"],
                    "requirement_description": req["description"],
                    "instruction": instruction,
                    "anchor": gap.get("anchor"),
                    "recommendation": recommendation,
                    "acceptance_checks": checks,
                    "prerequisites": ["先找到对应的已有素材"]
                    if kind == "import_existing"
                    else ["外部生成工具可用"]
                    if kind == "generate"
                    else [],
                    "estimated_effort_min": effort,
                    "shooting_min": effort if kind == "reshoot" else 0,
                    "editing_min": effort if kind != "reshoot" else 0,
                    "generation_wait_min": None,
                    "continuity": continuity,
                    "prompt": f"镜头目的：{req['description']}。画面动作需清晰可见，建议 4—8 秒，景别以看清目标信息为准。{continuity} 不添加参考中没有依据的人物或环境细节。"
                    if kind == "generate"
                    else "",
                    "reference_evidence_ids": reference_ids,
                    "reference_frames": [
                        {
                            "asset_id": e["asset_id"],
                            "time_s": e["source_start_s"],
                            "url": f"/api/v1/assets/{e['asset_id']}/frame?at={e['source_start_s']}",
                            "caption": e["action"],
                        }
                        for e in references
                        if e.get("evidence_type") != "audio"
                    ],
                    "needs_confirmation": gap["status"] != "confirmed"
                    or gap["uncertain"],
                    "feasible": kind != "import_existing",
                    "weight": 3 if req["priority"] == "must" else 2,
                    "demo_required_role": "process"
                    if demo and "制作" in req["description"]
                    else None,
                }
            )
    selected, covered, spent = select_budget(tasks, budget)
    for task in tasks:
        task["selected"] = task["id"] in selected
    return {
        "tasks": tasks,
        "budget_min": budget,
        "estimated_effort_min": spent,
        "uncovered_gap_ids": [
            g["id"]
            for g in gaps
            if g["status"] not in ("resolved", "dismissed")
            and not g["optional"]
            and g["id"] not in covered
        ],
        "note": "已有素材补入需先确认素材可用；待确认问题不自动进入必做计划。预算按人工时间估算，生成等待时间未知。",
    }
