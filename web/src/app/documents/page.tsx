"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { Shell } from "@/components/Shell";
import {
  ApiError,
  api,
  formatBytes,
  formatDateTime,
  formatDuration,
  type DocumentOut,
  type JobOut,
  type Quota,
  type UploadAccepted,
} from "@/lib/api";

const ACTIVE_STATES = new Set(["pending", "processing"]);

function QuotaCard({ quota }: { quota: Quota | null }) {
  if (!quota) return null;

  if (quota.unlimited) {
    return (
      <div className="card">
        <div className="row">
          <span className="name">โควตาวันนี้</span>
          <span className="ok">ไม่จำกัด (admin)</span>
        </div>
        <div className="detail">
          ใช้ไปแล้ว {quota.documents.used} เอกสาร · {quota.pages.used} หน้า
        </div>
      </div>
    );
  }

  const docPct = quota.documents.limit
    ? (quota.documents.used / quota.documents.limit) * 100
    : 0;
  const pagePct = quota.pages.limit ? (quota.pages.used / quota.pages.limit) * 100 : 0;

  return (
    <div className="grid" style={{ marginBottom: "1rem" }}>
      <div className="stat">
        <div className="label">เอกสารที่เหลือวันนี้</div>
        <div className="value">
          {quota.documents.remaining}
          <span className="hint"> / {quota.documents.limit}</span>
        </div>
        <div className="bar">
          <span style={{ width: `${Math.min(100, docPct)}%` }} />
        </div>
      </div>
      <div className="stat">
        <div className="label">หน้าที่เหลือวันนี้</div>
        <div className="value">
          {quota.pages.remaining}
          <span className="hint"> / {quota.pages.limit}</span>
        </div>
        <div className="bar">
          <span style={{ width: `${Math.min(100, pagePct)}%` }} />
        </div>
      </div>
      <div className="stat">
        <div className="label">รีเซ็ตโควตา</div>
        <div className="value" style={{ fontSize: "1rem" }}>
          {formatDateTime(quota.resets_at)}
        </div>
        <div className="hint">ตามเวลาไทย</div>
      </div>
    </div>
  );
}

function DocumentsInner() {
  const [quota, setQuota] = useState<Quota | null>(null);
  const [documents, setDocuments] = useState<DocumentOut[]>([]);
  const [jobs, setJobs] = useState<Record<string, JobOut>>({});
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    try {
      const [q, docs] = await Promise.all([
        api<Quota>("/api/me/quota"),
        api<DocumentOut[]>("/api/documents"),
      ]);
      setQuota(q);
      setDocuments(docs);

      // ดึงสถานะงานเฉพาะเอกสารที่ยังไม่จบ ไม่ยิงทุกแถวทุกรอบ
      const active = docs.filter((d) => ACTIVE_STATES.has(d.status));
      const results = await Promise.all(
        active.map((d) =>
          api<JobOut>(`/api/documents/${d.id}/job`).catch(() => null),
        ),
      );
      setJobs((prev) => {
        const next = { ...prev };
        results.forEach((job) => {
          if (job) next[job.document_id] = job;
        });
        return next;
      });
    } catch (err) {
      if (!(err instanceof ApiError && err.status === 401)) {
        setError(err instanceof Error ? err.message : "โหลดข้อมูลไม่สำเร็จ");
      }
    }
  }, []);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 5000);
    return () => clearInterval(timer);
  }, [refresh]);

  async function upload(event: React.FormEvent) {
    event.preventDefault();
    const file = fileInput.current?.files?.[0];
    if (!file) return;

    setBusy(true);
    setError(null);
    setNotice(null);

    const form = new FormData();
    form.append("file", file);

    try {
      const result = await api<UploadAccepted>("/api/documents", {
        method: "POST",
        body: form,
      });
      const eta =
        result.ocr_pages > 0
          ? `ต้อง OCR ${result.ocr_pages} หน้า ประเมิน ${formatDuration(result.estimated_seconds)}`
          : "ไม่ต้อง OCR เลย ประมวลผลเสร็จเร็ว";
      setNotice(`รับไฟล์แล้ว: ${result.document.filename} · ${eta}`);
      if (fileInput.current) fileInput.current.value = "";
      await refresh();
    } catch (err) {
      if (err instanceof ApiError && err.status === 429) {
        setError(`โควตาไม่พอ: ${err.message}`);
        await refresh();
      } else {
        setError(err instanceof Error ? err.message : "อัปโหลดไม่สำเร็จ");
      }
    } finally {
      setBusy(false);
    }
  }

  async function remove(doc: DocumentOut) {
    const touchedOcr = doc.ocr_page_count > 0 && doc.status !== "pending";
    const warning = touchedOcr
      ? "เอกสารนี้ผ่าน OCR ไปแล้ว การลบจะไม่คืนโควตา"
      : "ลบแล้วจะคืนโควตาให้ถ้าอยู่ในวันเดียวกับที่อัปโหลด";
    if (!confirm(`ลบ "${doc.filename}"?\n\n${warning}`)) return;

    setError(null);
    try {
      await api(`/api/documents/${doc.id}`, { method: "DELETE" });
      setNotice(`ลบ ${doc.filename} แล้ว`);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "ลบไม่สำเร็จ");
    }
  }

  const outOfQuota =
    !!quota && !quota.unlimited && (quota.documents.remaining === 0 || quota.pages.remaining === 0);

  return (
    <>
      <h1>เอกสาร</h1>
      <p className="sub">อัปโหลดเอกสารเข้าคลังความรู้ ระบบจะ OCR เฉพาะหน้าที่จำเป็น</p>

      <QuotaCard quota={quota} />

      <form className="card" onSubmit={upload}>
        {error && <div className="alert">{error}</div>}
        {notice && <div className="alert info">{notice}</div>}

        <div className="field">
          <label htmlFor="file">เลือกไฟล์ (PDF, รูปภาพ, docx, txt, html)</label>
          <input id="file" type="file" ref={fileInput} disabled={busy || outOfQuota} required />
        </div>

        <div className="btn-row">
          <button className="btn" type="submit" disabled={busy || outOfQuota}>
            {busy ? "กำลังอัปโหลด…" : "อัปโหลด"}
          </button>
          {outOfQuota && <span className="fail">โควตาวันนี้หมดแล้ว</span>}
        </div>
      </form>

      <h2>รายการเอกสาร</h2>
      {documents.length === 0 ? (
        <p className="muted">ยังไม่มีเอกสาร</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>ชื่อไฟล์</th>
                <th>สถานะ</th>
                <th>หน้า</th>
                <th>OCR</th>
                <th>ขนาด</th>
                <th>อัปโหลดเมื่อ</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {documents.map((doc) => {
                const job = jobs[doc.id];
                return (
                  <tr key={doc.id}>
                    <td className="wrap">
                      {doc.filename}
                      {job?.error && <div className="detail fail">{job.error}</div>}
                    </td>
                    <td>
                      <span className={`badge ${doc.status}`}>{doc.status}</span>
                      {job && ACTIVE_STATES.has(doc.status) && (
                        <>
                          <div className="detail">
                            {job.stage} · {job.pages_done}/{job.pages_total} หน้า
                          </div>
                          <div className="bar">
                            <span style={{ width: `${job.progress}%` }} />
                          </div>
                        </>
                      )}
                    </td>
                    <td>
                      {doc.page_count}
                      {doc.page_count_estimated && (
                        <span className="detail"> (ประเมิน)</span>
                      )}
                    </td>
                    <td>{doc.ocr_page_count}</td>
                    <td>{formatBytes(doc.size_bytes)}</td>
                    <td>{formatDateTime(doc.created_at)}</td>
                    <td>
                      <button className="btn ghost" onClick={() => remove(doc)}>
                        ลบ
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

export default function DocumentsPage() {
  return <Shell>{() => <DocumentsInner />}</Shell>;
}
