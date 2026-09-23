"""Application-owned output schemas for the exact media being inspected."""

from copy import deepcopy
import math

from pydantic import Field, ValidationInfo, create_model, field_validator

from app.schemas import EvidenceDraft, EvidenceOutput


def clip_evidence_schema(start_s: float, end_s: float) -> type[EvidenceOutput]:
    """Keep evidence inside its sampled window without altering timestamps.

    Dynamic bounds appear in JSON Schema, so structured-generation retries can
    identify and repair the specific invalid field using the original images.
    """
    if (
        isinstance(start_s, bool)
        or isinstance(end_s, bool)
        or not isinstance(start_s, (int, float))
        or not isinstance(end_s, (int, float))
        or not math.isfinite(start_s)
        or not math.isfinite(end_s)
        or not 0 <= start_s < end_s
    ):
        raise ValueError("画面证据窗口必须是有限的原片时间区间，且0<=start_s<end_s")

    def validate_time_order(cls, value: float, info: ValidationInfo) -> float:
        observed_start = info.data.get("source_start_s")
        if observed_start is not None and value <= observed_start:
            raise ValueError(
                "source_end_s必须严格大于source_start_s；使用采样窗口内有画面依据的"
                "原片绝对时间，不返回零时长或逆序区间，不任意调整或伪造时间。"
            )
        return value

    bounded_evidence = create_model(
        "ClipEvidenceDraft",
        __base__=EvidenceDraft,
        __validators__={
            "validate_time_order": field_validator("source_end_s")(validate_time_order),
        },
        source_start_s=(float, Field(
            ge=start_s, lt=end_s, allow_inf_nan=False,
            description=(
                "证据开始的原片绝对时间（秒），不是相对当前片段的偏移。"
                "必须处于给定采样窗口内，且source_start_s<source_end_s。"
                "保留有依据的原始精度，不为满足边界而任意裁剪、取整或伪造。"
            ),
        )),
        source_end_s=(float, Field(
            gt=start_s, le=end_s, allow_inf_nan=False,
            description=(
                "证据结束的原片绝对时间（秒），不是相对当前片段的偏移。"
                "必须处于给定采样窗口内，且source_end_s必须严格大于source_start_s。"
                "不允许零时长或逆序；保留有依据的原始精度，不任意裁剪、取整或伪造。"
            ),
        )),
    )
    # Retain the output field's constraints/defaults and all inherited model
    # configuration instead of duplicating (and potentially relaxing) them.
    return create_model(
        "ClipEvidenceOutput",
        __base__=EvidenceOutput,
        evidence=(list[bounded_evidence], deepcopy(EvidenceOutput.model_fields["evidence"])),
    )
