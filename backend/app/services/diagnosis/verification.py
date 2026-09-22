"""Ground verification checks in the newly submitted asset's evidence only."""


def validate_verification_result(result, task, evidence):
    checks = result["checks"]
    if [check["check"] for check in checks] != task["acceptance_checks"]:
        raise ValueError("模型未逐项返回原任务验收条件")
    allowed = {item["id"] for item in evidence}
    if any(eid not in allowed for check in checks for eid in check["evidence_ids"]):
        raise ValueError("验收引用了不存在的新素材证据；原片参考证据不能作为新素材验收引用")
    if any(check["status"] == "passed" and not check["evidence_ids"] for check in checks):
        raise ValueError("通过的验收项缺少新素材证据")
    return result
