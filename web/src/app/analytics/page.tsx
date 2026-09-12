"use client";

import { useCallback, useEffect, useState } from "react";

import { Shell } from "@/components/Shell";
import { api, formatDateTime } from "@/lib/api";

type Overview = {
  window_days: number;
  messages: number;
  unanswered: number;
  unanswered_ratio: number;
  latency_ms: { p50: number | null; p95: number | null };
  feedback: { up: number; down: number; negative_ratio: number };
  daily: { day: string; messages: number }[];
};

type Unanswered = {
  message_id: string;
  session_id: string;
  question: string | null;
  asked_at: string;
};

type CitedDocument = {
  document_id: string;
  filename: string;
  citations: number;
  avg_score: number;
};

type Ingestion = {
  window_days: number;
  jobs: number;
  failed: number;
  in_flight: number;
  pages_processed: number;
  gpu_seconds: number;
  seconds_per_page: number | null;
  queue_wait_p95_seconds: number | null;
};

type QuotaUsage = {
  released_events: number;
  users: {
    user_id: string;
    email: string;
    role: string;
    documents: number;
    pages: number;
    unlimited: boolean;
  }[];
};

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="stat">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {hint && <div className="hint">{hint}</div>}
    </div>
  );
}

function AnalyticsInner() {
  const [days, setDays] = useState(7);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [unanswered, setUnanswered] = useState<Unanswered[]>([]);
  const [docs, setDocs] = useState<CitedDocument[]>([]);
  const [ingestion, setIngestion] = useState<Ingestion | null>(null);
  const [quota, setQuota] = useState<QuotaUsage | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [o, u, d, i, q] = await Promise.all([
        api<Overview>(`/api/admin/analytics/overview?days=${days}`),
        api<Unanswered[]>(`/api/admin/analytics/unanswered?days=${days}`),
        api<CitedDocument[]>(`/api/admin/analytics/documents?days=${days}`),
        api<Ingestion>(`/api/admin/analytics/ingestion?days=${days}`),
        api<QuotaUsage>(`/api/admin/quota/usage?days=${days}`),
      ]);
      setOverview(o);
      setUnanswered(u);
      setDocs(d);
      setIngestion(i);
      setQuota(q);
    } catch (err) {
      setError(err instanceof Error ? err.message : "โหลดข้อมูลไม่สำเร็จ");
    }
  }, [days]);

  useEffect(() => {
    load();
  }, [load]);

  const maxDaily = Math.max(1, ...(overview?.daily.map((d) => d.messages) ?? [1]));

  return (
    <>
      <div className="row">
        <div>
          <h1>Analytics</h1>
          <p className="sub">ตัวเลขที่ใช้ตัดสินว่าคลังความรู้ขาดอะไร และเมื่อไหร่ต้องขยายเครื่อง</p>
        </div>
        <select
          style={{ width: "auto" }}
          value={days}
          onChange={(e) => setDays(Number(e.target.value))}
        >
          <option value={1}>1 วัน</option>
          <option value={7}>7 วัน</option>
          <option value={30}>30 วัน</option>
        </select>
      </div>

      {error && <div className="alert">{error}</div>}

      {overview && (
        <>
          <div className="grid">
            <Stat label="ข้อความที่ตอบไป" value={String(overview.messages)} />
            <Stat
              label="ตอบไม่ได้"
              value={`${overview.unanswered}`}
              hint={`${(overview.unanswered_ratio * 100).toFixed(1)}% ของทั้งหมด`}
            />
            <Stat
              label="latency p50 / p95"
              value={`${overview.latency_ms.p50 ?? "—"} / ${overview.latency_ms.p95 ?? "—"}`}
              hint="มิลลิวินาที"
            />
            <Stat
              label="feedback"
              value={`${overview.feedback.up} / ${overview.feedback.down}`}
              hint={`ลบ ${(overview.feedback.negative_ratio * 100).toFixed(0)}%`}
            />
          </div>

          {overview.daily.length > 0 && (
            <>
              <h2>ข้อความต่อวัน</h2>
              <div className="card">
                {overview.daily.map((d) => (
                  <div key={d.day} style={{ marginBottom: "0.4rem" }}>
                    <div className="row">
                      <span className="detail">{d.day}</span>
                      <span className="detail">{d.messages}</span>
                    </div>
                    <div className="bar">
                      <span style={{ width: `${(d.messages / maxDaily) * 100}%` }} />
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </>
      )}

      {ingestion && (
        <>
          <h2>Ingestion</h2>
          <div className="grid">
            <Stat
              label="งานทั้งหมด"
              value={String(ingestion.jobs)}
              hint={`ล้มเหลว ${ingestion.failed} · ค้างคิว ${ingestion.in_flight}`}
            />
            <Stat label="หน้าที่ประมวลผล" value={String(ingestion.pages_processed)} />
            <Stat
              label="วินาที/หน้า (จริง)"
              value={ingestion.seconds_per_page?.toFixed(1) ?? "—"}
              hint="เอาไปแทน OCR_SECONDS_PER_PAGE ใน .env เพื่อให้ ETA แม่นขึ้น"
            />
            <Stat
              label="รอคิว p95"
              value={
                ingestion.queue_wait_p95_seconds !== null
                  ? `${Math.round(ingestion.queue_wait_p95_seconds / 60)} นาที`
                  : "—"
              }
              hint="เกิน 8 ชม. ติดกัน 3 วัน = ถึงเวลาขยายเครื่อง"
            />
          </div>
        </>
      )}

      <h2>คำถามที่ระบบตอบไม่ได้ ({unanswered.length})</h2>
      <p className="muted" style={{ marginTop: "-0.5rem" }}>
        รายการนี้บอกว่าควรเอาเอกสารอะไรเข้าระบบเพิ่ม
      </p>
      {unanswered.length === 0 ? (
        <p className="muted">ไม่มี</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>คำถาม</th>
                <th>เมื่อ</th>
              </tr>
            </thead>
            <tbody>
              {unanswered.map((row) => (
                <tr key={row.message_id}>
                  <td className="wrap">{row.question ?? "—"}</td>
                  <td>{formatDateTime(row.asked_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h2>เอกสารที่ถูกอ้างอิงบ่อย</h2>
      {docs.length === 0 ? (
        <p className="muted">ยังไม่มีการอ้างอิง</p>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>เอกสาร</th>
                <th>จำนวนครั้ง</th>
                <th>คะแนนเฉลี่ย</th>
              </tr>
            </thead>
            <tbody>
              {docs.map((doc) => (
                <tr key={doc.document_id}>
                  <td className="wrap">{doc.filename}</td>
                  <td>{doc.citations}</td>
                  <td>{doc.avg_score.toFixed(3)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {quota && (
        <>
          <h2>การใช้โควตา</h2>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>ผู้ใช้</th>
                  <th>บทบาท</th>
                  <th>เอกสาร</th>
                  <th>หน้า</th>
                </tr>
              </thead>
              <tbody>
                {quota.users.map((u) => (
                  <tr key={u.user_id}>
                    <td className="wrap">{u.email}</td>
                    <td>
                      {u.role}
                      {u.unlimited && <span className="badge">ไม่จำกัด</span>}
                    </td>
                    <td>{u.documents}</td>
                    <td>{u.pages}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </>
  );
}

export default function AnalyticsPage() {
  return <Shell requireAdmin>{() => <AnalyticsInner />}</Shell>;
}
