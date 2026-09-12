"use client";

import { useEffect, useState } from "react";

import { Nav } from "@/components/Nav";
import { API_BASE, api, type Me } from "@/lib/api";

type Check = { ok: boolean; detail?: string | null; [k: string]: unknown };
type DeepHealth = {
  status: string;
  tier: string;
  checks: Record<string, Check>;
  gpu?: { loaded_models?: string; warning?: string };
};

const LABELS: Record<string, string> = {
  postgres: "PostgreSQL + pgvector",
  redis: "Redis",
  llm: "LLM (Qwen)",
  ocr: "OCR (typhoon-ocr)",
  embeddings: "Embeddings (bge-m3)",
};

export default function StatusPage() {
  const [health, setHealth] = useState<DeepHealth | null>(null);
  const [user, setUser] = useState<Me | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Me>("/api/auth/me")
      .then(setUser)
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    // /health/deep ตอบ 503 ตอน degraded ซึ่งถูกต้อง จึงอ่าน body เองแทนการโยน error
    const load = () =>
      fetch(`${API_BASE}/health/deep`, { credentials: "include" })
        .then((r) => r.json())
        .then((d) => {
          setHealth(d);
          setError(null);
        })
        .catch((e) => setError(String(e)));

    // หยุดถามเมื่อไม่มีใครดูอยู่
    //
    // การเช็คหนึ่งครั้งไม่ได้ถูก — มันไล่ต่อ Postgres, Redis, TEI และถาม Ollama
    // ว่าโมเดลไหนค้างอยู่ใน VRAM · เปิดแท็บนี้ทิ้งไว้ข้ามคืนคือยิงชุดนั้น
    // แปดพันกว่ารอบโดยไม่มีใครอ่านผลเลย บนเครื่องที่ต้องเอาแรงไปให้ OCR กับ LLM
    let timer: ReturnType<typeof setInterval> | null = null;

    const start = () => {
      if (timer === null) timer = setInterval(load, 10_000);
    };
    const stop = () => {
      if (timer !== null) {
        clearInterval(timer);
        timer = null;
      }
    };

    const onVisibility = () => {
      if (document.hidden) {
        stop();
      } else {
        // กลับมาดูแล้วต้องเห็นของสด ไม่ใช่ค่าค้างจากตอนที่สลับแท็บไป
        load();
        start();
      }
    };

    load();
    if (!document.hidden) start();
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      stop();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, []);

  return (
    <>
      <Nav user={user} />
      <main>
        <h1>สถานะระบบ</h1>
        <p className="sub">
          tier <code>{health?.tier ?? "—"}</code> · อัปเดตทุก 10 วินาที
        </p>

        {error && (
          <div className="alert" role="alert">
            ต่อ API ไม่ได้: {error}
            <div className="detail">
              ตรวจว่า api container ทำงานอยู่ด้วย <code>.\dc.ps1 logs -f api</code>
            </div>
          </div>
        )}

        {health &&
          Object.entries(health.checks).map(([key, check]) => (
            <div className="card" key={key}>
              <div className="row">
                <span className="name">{LABELS[key] ?? key}</span>
                <span className={check.ok ? "ok" : "fail"}>
                  {check.ok ? "พร้อม" : "ยังไม่พร้อม"}
                </span>
              </div>
              {check.detail ? <div className="detail">{String(check.detail)}</div> : null}
            </div>
          ))}

        {health?.gpu && (
          <div className="card">
            <div className="row">
              <span className="name">GPU</span>
              <span className={health.gpu.warning ? "fail" : "ok"}>
                {health.gpu.warning ? "หล่นไป CPU" : "ปกติ"}
              </span>
            </div>
            <div className="detail">{health.gpu.loaded_models ?? "—"}</div>
            {health.gpu.warning ? <div className="detail fail">{health.gpu.warning}</div> : null}
          </div>
        )}
      </main>
    </>
  );
}
