import test from "node:test";
import assert from "node:assert/strict";
import takeover from "../lib/takeover.js";

const elements = [{ id: "e1", tag: "a", label: "Next" }, { id: "e2", tag: "a", label: "Continue" }];
const plan = () => takeover.parsePlan(JSON.stringify({ summary: "s", steps: [{ action: "click", target: "e1" }, { action: "click", target: "e2" }] }), elements).plan;

test("a step the server reads as consequential waits for the person, though the extension thought it plain", () => {
  const run = takeover.createRun(plan());
  const step = run.next();
  assert.equal(step.index, 0);
  run.requireApproval("srv-approval-1");
  assert.equal(run.snapshot().status, "awaiting_approval");
  assert.equal(run.snapshot().approvalId, "srv-approval-1");
  assert.equal(run.next(), null, "nothing runs before the tap");
  assert.equal(run.approve(1), false, "only the waiting step can be approved");
  assert.equal(run.approve(0), true);
  assert.equal(run.next().index, 0);
  assert.equal(run.next(), null, "the local approval is single use");
  run.requireApproval("srv-approval-2");
  run.approve(0);
  run.next();
  run.completed(0);
  assert.equal(run.snapshot().approvalId, null, "the next step starts with no approval");
  assert.equal(run.next().index, 1);
});

test("stop is terminal even with a server approval pending", () => {
  const run = takeover.createRun(plan());
  run.next();
  run.requireApproval("srv");
  run.stop();
  run.requireApproval("srv-late");
  assert.equal(run.approve(0), false);
  assert.equal(run.next(), null);
  assert.equal(run.snapshot().status, "stopped");
});
