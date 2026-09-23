import assert from "node:assert/strict";
import test from "node:test";
import { verificationPresentation } from "../src/lib/verification.ts";

test("processing failure shows the error without claiming the shot failed review", () => {
  const view = verificationPresentation({
    id: "submission", verification_status: "error",
    processing_error: "模型配置已改变",
  });
  assert.equal(view.label, "补拍分析未完成");
  assert.equal(view.detail, "模型配置已改变");
  assert.equal(view.pending, false);
  assert.equal(view.passed, false);
});

test("legacy interrupted submissions never retain the analysing placeholder", () => {
  const view = verificationPresentation({ id: "old", verification_status: "failed" });
  assert.equal(view.label, "补拍分析未完成");
  assert.equal(view.pending, false);
  assert.doesNotMatch(view.detail, /正在/);
});

test("a completed negative verdict retains its actual reason", () => {
  const view = verificationPresentation({
    id: "review", verification_status: "failed", reason: "没有看到倒水动作",
  });
  assert.equal(view.label, "未满足补拍要求");
  assert.equal(view.detail, "没有看到倒水动作");
  assert.equal(view.pending, false);
});

test("retry waiting and running states hide the previous error and verdict", () => {
  for (const status of ["queued", "running"]) {
    const view = verificationPresentation({
      id: "retry", verification_status: status, processing_error: "旧错误", reason: "旧结论",
    });
    assert.equal(view.pending, true);
    assert.doesNotMatch(view.detail, /旧/);
    assert.match(view.detail, /正在/);
  }
});

test("completed results without a reason do not look like a running job", () => {
  for (const status of ["passed", "partial", "uncertain"]) {
    const view = verificationPresentation({ id: "review", verification_status: status });
    assert.equal(view.pending, false);
    assert.doesNotMatch(view.detail, /正在/);
    assert.equal(view.passed, status === "passed");
  }
});
