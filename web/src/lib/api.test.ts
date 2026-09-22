import { afterEach, expect, it, vi } from "vitest";
import { api, formatDate, formatDateTime } from "./api";
afterEach(() => vi.unstubAllGlobals());
it.each([200, 404, 502])("hides HTML responses with status %s", async (status) => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValue(new Response("<!DOCTYPE html><html>internal page</html>", { status })),
  );
  await expect(api("/api/auth/login")).rejects.toThrow("ขณะนี้ไม่สามารถเชื่อมต่อบริการได้");
});
it("preserves JSON authentication errors", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ detail: "Invalid credentials" }), { status: 401 }),
      ),
  );
  await expect(api("/api/auth/login")).rejects.toThrow("Invalid credentials");
});
it("returns valid JSON", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true }))));
  await expect(api("/api/auth/login")).resolves.toEqual({ ok: true });
});

// รูปแบบวันที่ — เดิมใช้ dateStyle "short" ซึ่ง th-TH ให้ "9/9/69"
// ปีพุทธศักราชสองหลักอ่านแล้วสับสนกับ ค.ศ. และวันกับเดือนสลับกันได้ในสายตาคนอ่าน
it("spells out the month instead of printing 9/9/69", () => {
  const out = formatDateTime("2026-09-09T08:59:00Z");
  expect(out).toContain("ก.ย.");
  expect(out).toContain("2569");
  expect(out).not.toMatch(/\d+\/\d+\/\d+/);
});

it("formats a date without a time for tight spaces", () => {
  const out = formatDate("2026-09-09T08:59:00Z");
  expect(out).toContain("ก.ย.");
  expect(out).toContain("2569");
  expect(out).not.toMatch(/\d{2}:\d{2}/);
});
