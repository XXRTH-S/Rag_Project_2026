"use client";

import { useEffect, useState } from "react";

import { PageIntro } from "@/components/PageIntro";
import { Icon } from "@/components/Icon";
import { Nav } from "@/components/Nav";
import { API_BASE, apiFetch, api, type Me } from "@/lib/api";

type Check = { ok: boolean; detail?: string | null; [k: string]: unknown };

// tier และ gpu มาเฉพาะเมื่อผู้เรียกเป็น admin — /health/deep ตอบได้โดยไม่ต้องล็อกอิน
// (monitor ภายนอกต้องเรียกได้) แต่ไม่แจกรุ่นซอฟต์แวร์กับชื่อโมเดลให้คนที่ไม่ใช่ admin
type DeepHealth = {
  status: string;
  tier?: string;
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
      apiFetch(`${API_BASE}/health/deep`, { credentials: "include" })
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
      <main id="main-content" className="workspace status-page">
        <PageIntro />

        <p className="sub">
          {health?.tier ? (
            <>
              tier <code>{health.tier}</code> ·{" "}
            </>
          ) : null}
          อัปเดตทุก 10 วินาที
        </p>

        {error && (
          <div className="alert" role="alert">
            ต่อ API ไม่ได้: {error}
            <div className="detail">
              ตรวจว่า api container ทำงานอยู่ด้วย <code>.\dc.ps1 logs -f api</code>
            </div>
          </div>
        )}

        {health && (
          <div className="grid">
            <div className="stat">
              <div className="label">บริการที่พร้อมใช้งาน</div>
              <div className="value">
                {Object.values(health.checks).filter((c) => c.ok).length} /{" "}
                {Object.keys(health.checks).length}
              </div>
            </div>
            <div className="stat">
              <div className="label">บริการที่ควรตรวจสอบ</div>
              <div className="value">
                {Object.values(health.checks).filter((c) => !c.ok).length}
              </div>
            </div>
          </div>
        )}
        {health &&
          Object.entries(health.checks).map(([key, check]) => (
            <div className="card" key={key}>
              <div className="row">
                <span className="name service-name">
                  <Icon name={key === "llm" ? "chat" : "status"} />
                  {LABELS[key] ?? key}
                </span>
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
            <div className="detail">
              {health.gpu.loaded_models === "no model loaded"
                ? "ยังไม่มีโมเดลอยู่ในหน่วยความจำ โมเดลจะโหลดเมื่อมีคำขอ"
                : (health.gpu.loaded_models ?? "ยังไม่มีข้อมูล")}
            </div>
            {health.gpu.warning ? <div className="detail fail">{health.gpu.warning}</div> : null}
          </div>
        )}
        <details className="help">
          <summary>สถานะเหล่านี้หมายถึงอะไร?</summary>
          <p>
            ฐานข้อมูลเก็บเอกสารและประวัติ Redis จัดคิวงาน ส่วน OCR อ่านหน้าสแกน Embeddings
            ช่วยค้นข้อมูล และ LLM เรียบเรียงคำตอบ สถานะพร้อมหมายถึงบริการตอบการตรวจสอบได้
            ไม่ใช่การรับรองคุณภาพคำตอบ
          </p>
        </details>
      </main>
    </>
  );
}
