import type { Submission } from "../types";

const labels: Record<string, string> = {
  queued: "等待补拍分析",
  running: "正在分析补拍",
  passed: "符合补拍要求",
  partial: "部分满足要求",
  failed: "未满足补拍要求",
  uncertain: "需要人工复核",
  error: "补拍分析未完成",
};

export function verificationPresentation(submission: Submission) {
  // Older workers used "failed" for both a negative verdict and an exception.
  // An interrupted job without a result must never look like a verdict.
  const legacyError =
    submission.verification_status === "failed" &&
    !submission.reason &&
    !submission.checks?.length;
  const status = legacyError ? "error" : submission.verification_status;
  const pending = ["queued", "running"].includes(status);
  const detail =
    status === "error"
      ? submission.processing_error ||
        "本次分析未完成，请在“任务与消息”中查看原因并重试。"
      : pending
        ? status === "queued"
          ? "正在等待分析。"
          : "正在对照补拍要求分析新素材…"
        : submission.reason || "请查看下方逐项分析结果。";
  return {
    label: labels[status] || status,
    detail,
    pending,
    passed: status === "passed",
  };
}
