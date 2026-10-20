import assert from "node:assert/strict";
import test from "node:test";
import { captchaFrame, captchaPayload, captchaView } from "../src/lib/supplier-captcha";

const id = "11111111-1111-4111-8111-111111111111";
const request = { selection: { notice: { purchase_number: "0848300054826000154", version_number: 1,
  notice_xml_sha256: "a".repeat(64) }, source_index: 1 } };
test("start binds a retained request and active engine without a client URL/query", () => {
  const v = { request, run_id: id, engine: "GOOGLE" };
  assert.equal(captchaPayload("start", v), true);
  assert.equal(captchaPayload("start", { ...v, query: "another query" }), false);
  assert.equal(captchaPayload("start", { ...v, url: "http://localhost/" }), false);
  assert.equal(captchaPayload("start", { ...v, engine: "BRAVE" }), false);
  assert.equal(captchaPayload("start", { ...v, run_id: "../escape" }), false);
});
test("control is bounded and cannot submit script/navigation/browser shortcuts", () => {
  const input = (event: unknown) => captchaPayload("input", { session_id: id, event });
  assert.equal(input({ kind: "click", x: 1279, y: 719 }), true);
  assert.equal(input({ kind: "click", x: 1280, y: 0 }), false);
  assert.equal(input({ kind: "click", x: 1.5, y: 0 }), false);
  assert.equal(input({ kind: "type", text: "ответ" }), true);
  assert.equal(input({ kind: "type", text: "x\nhttp://elsewhere/" }), false);
  assert.equal(input({ kind: "type", text: "x".repeat(129) }), false);
  assert.equal(input({ kind: "key", key: "Control+L" }), false);
  assert.equal(input({ kind: "eval", script: "document.cookie" }), false);
  assert.equal(captchaPayload("navigate", { session_id: id }), false);
});
test("verification is separate from permission to retry and has an aware expiry", () => {
  const v = { session_id: id, run_id: id, engine: "GOOGLE", status: "VERIFIED",
    expires_at: "2026-10-07T10:00:00Z", retry_after_seconds: 15, retry_ready: false };
  assert.equal(captchaView(v), true);
  assert.equal(captchaView({ ...v, finalizing: true }), true);
  assert.equal(captchaView({ ...v, finalizing: "ready" }), false);
  assert.equal(captchaView({ ...v, retry_ready: undefined }), false);
  assert.equal(captchaView({ ...v, expires_at: "2026-10-07T10:00:00" }), false);
  assert.equal(captchaView({ ...v, status: "PASS" }), false);
  assert.equal(captchaView({ ...v, retry_after_seconds: 600 }), false);
});
test("only a bounded JPEG frame can be displayed", () => {
  const v = { data: "/9j/AA==", mime_type: "image/jpeg", width: 1280, height: 720 };
  assert.equal(captchaFrame(v), true);
  assert.equal(captchaFrame({ ...v, mime_type: "text/html" }), false);
  assert.equal(captchaFrame({ ...v, data: "<svg onload='bad()'/>" }), false);
  assert.equal(captchaFrame({ ...v, width: 3840 }), false);
  assert.equal(captchaFrame({ ...v, data: "/9j/" + "A".repeat(710000) }), false);
});
