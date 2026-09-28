"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { Icon } from "@/components/Icon";
import { Shell } from "@/components/Shell";
import {
  ApiError,
  api,
  formatBytes,
  formatDateTime,
  formatDuration,
  type DocumentOut,
  type JobOut,
  type Me,
  type Page,
  type Quota,
  type UploadAccepted,
} from "@/lib/api";

const ACTIVE_STATES = new Set(["pending", "processing"]);

/** จำนวนแถวต่อหนึ่งหน้า — ตรงกับค่าเริ่มต้นของ API */
const PAGE_SIZE = 50;

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

  const docPct = quota.documents.limit ? (quota.documents.used / quota.documents.limit) * 100 : 0;
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

/** นามสกุลที่ backend รับ — บอกเบราว์เซอร์ไว้เพื่อให้กล่องเลือกไฟล์กรองให้เลย */
const ACCEPT = ".pdf,.png,.jpg,.jpeg,.webp,.tif,.tiff,.docx,.txt,.md,.markdown,.html,.htm";

function DocumentsInner({ user }: { user: Me }) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [picked, setPicked] = useState<File[]>([]);
  const [dragging, setDragging] = useState(false);
  const [quota, setQuota] = useState<Quota | null>(null);
  const [documents, setDocuments] = useState<DocumentOut[]>([]);
  const [jobs, setJobs] = useState<Record<string, JobOut>>({});
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  // เพิ่ม limit แล้วแทนที่ทั้งรายการ เพื่อไม่ให้ข้อมูลซ้ำหรือหายระหว่าง polling
  const [visibleLimit, setVisibleLimit] = useState(PAGE_SIZE);
  const [totalDocuments, setTotalDocuments] = useState(0);

  const refresh = useCallback(async () => {
    try {
      const [q, page] = await Promise.all([
        api<Quota>("/api/me/quota"),
        api<Page<DocumentOut>>(`/api/documents?limit=${visibleLimit}`),
      ]);
      const docs = page.items;
      setQuota(q);
      setDocuments(docs);
      setTotalDocuments(page.total);

      // ดึงสถานะงานเฉพาะเอกสารที่ยังไม่จบ ไม่ยิงทุกแถวทุกรอบ
      const active = docs.filter((d) => ACTIVE_STATES.has(d.status));
      const results = await Promise.all(
        active.map((d) => api<JobOut>(`/api/documents/${d.id}/job`).catch(() => null)),
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
  }, [visibleLimit]);

  const hasActiveWork = documents.some((d) => ACTIVE_STATES.has(d.status));

  // poll เฉพาะเมื่อมีงานกำลังประมวลผล
  useEffect(() => {
    refresh();

    // ไม่มีงานค้าง = ไม่ต้องถามซ้ำ ผู้ใช้กดอัปโหลดเมื่อไหร่ refresh ถูกเรียกเองอยู่แล้ว
    if (!hasActiveWork) return;

    let timer: ReturnType<typeof setInterval> | null = null;

    const start = () => {
      if (timer === null) timer = setInterval(refresh, 5000);
    };
    const stop = () => {
      if (timer !== null) {
        clearInterval(timer);
        timer = null;
      }
    };

    // หยุด polling เมื่อซ่อนแท็บ และ refresh ทันทีเมื่อกลับมา
    const onVisibility = () => {
      if (document.hidden) {
        stop();
      } else {
        refresh();
        start();
      }
    };

    if (!document.hidden) start();
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      stop();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [refresh, hasActiveWork]);

  const maxBytes = quota?.max_upload_bytes;

  /** รับไฟล์จากทั้งการกดเลือกและการลากมาวาง แล้วคัดตัวที่ใหญ่เกินออกตั้งแต่ตรงนี้
   *
   * บอกตั้งแต่ก่อนส่ง ไม่ใช่ให้รออัปจนจบแล้วค่อยเจอ 413 — ไฟล์ 200 MB
   * บนเน็ตบ้านคือรอหลายนาทีเพื่อไปเจอ error ที่รู้ได้ตั้งแต่แรก
   */
  const accept = useCallback(
    (incoming: FileList | null) => {
      const files = Array.from(incoming ?? []);
      if (files.length === 0) return;

      const tooBig = maxBytes ? files.filter((f) => f.size > maxBytes) : [];
      const ok = maxBytes ? files.filter((f) => f.size <= maxBytes) : files;

      setPicked(ok);
      setNotice(null);
      setError(
        tooBig.length
          ? `ข้ามไฟล์ที่ใหญ่เกินเพดาน ${formatBytes(maxBytes!)}: ${tooBig
              .map((f) => `${f.name} (${formatBytes(f.size)})`)
              .join(", ")}`
          : null,
      );
    },
    [maxBytes],
  );

  function clearPicked() {
    setPicked([]);
    if (fileInput.current) fileInput.current.value = "";
  }

  async function upload(event: React.FormEvent) {
    event.preventDefault();
    if (picked.length === 0) return;

    setBusy(true);
    setError(null);
    setNotice(null);

    try {
      // admin ที่อัปหลายไฟล์ใช้ทาง bulk ซึ่งไม่คิดโควตา — ทางนี้มีไว้ตั้งคลังครั้งแรก
      // ไฟล์ที่มีปัญหาจะถูกข้ามและรายงานกลับ ไม่ทำให้ทั้งชุดล้ม
      if (user.role === "admin" && picked.length > 1) {
        const form = new FormData();
        picked.forEach((f) => form.append("files", f));
        const result = await api<{ accepted: DocumentOut[]; rejected: { reason?: string }[] }>(
          "/api/admin/documents/bulk",
          { method: "POST", body: form },
        );
        const skipped = result.rejected.length ? ` · ข้าม ${result.rejected.length} ไฟล์` : "";
        setNotice(`รับแล้ว ${result.accepted.length} ไฟล์${skipped}`);
        clearPicked();
        await refresh();
        return;
      }

      // ที่เหลืออัปทีละไฟล์ เพื่อให้โควตาถูกนับตามจริง
      // ถ้าโควตาหมดกลางทางให้หยุดแล้วบอกว่าอัปไปได้กี่ไฟล์ ไม่ใช่ล้มเงียบ ๆ
      const done: string[] = [];
      for (const file of picked) {
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
          done.push(picked.length === 1 ? `${result.document.filename} · ${eta}` : file.name);
        } catch (err) {
          if (err instanceof ApiError && err.status === 429) {
            setError(
              done.length
                ? `อัปได้ ${done.length} ไฟล์แล้วโควตาหมด: ${err.message}`
                : `โควตาไม่พอ: ${err.message}`,
            );
            break;
          }
          throw err;
        }
      }
      if (done.length) setNotice(`รับไฟล์แล้ว: ${done.join(" · ")}`);
      clearPicked();
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "อัปโหลดไม่สำเร็จ");
    } finally {
      setBusy(false);
    }
  }

  /** สั่งประมวลผลใหม่ — เห็นเฉพาะ admin เพราะ API กำหนดสิทธิ์ไว้อย่างนั้น
   *
   * ไม่คิดโควตาซ้ำ เพราะผู้ใช้จ่ายไปแล้วตอนอัปครั้งแรก · ผล OCR ที่ไม่ดี
   * เป็นข้อจำกัดของระบบ ไม่ใช่ความผิดของผู้ใช้
   */
  async function reprocess(doc: DocumentOut) {
    if (!confirm(`ประมวลผล "${doc.filename}" ใหม่?\n\nข้อความเดิมจะถูกแทนที่ทั้งหมด`)) return;
    setError(null);
    try {
      await api(`/api/admin/documents/${doc.id}/reprocess`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      setNotice(`ส่ง ${doc.filename} เข้าคิวประมวลผลใหม่แล้ว`);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "สั่งประมวลผลใหม่ไม่สำเร็จ");
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

  const filteredDocuments = documents.filter(
    (d) =>
      d.filename.toLowerCase().includes(query.toLowerCase()) &&
      (filter === "all" || d.status === filter),
  );
  const outOfQuota =
    !!quota && !quota.unlimited && (quota.documents.remaining === 0 || quota.pages.remaining === 0);

  return (
    <>
      <div className="guide-grid">
        <div className="guide-item">
          <Icon name="upload" />
          <div>
            <strong>1. เพิ่มเอกสาร</strong>
            <p>รองรับ PDF รูปภาพ และไฟล์ข้อความ</p>
          </div>
        </div>
        <div className="guide-item">
          <Icon name="search" />
          <div>
            <strong>2. เตรียมความรู้</strong>
            <p>ระบบอ่านข้อความและจัดเก็บเพื่อค้นหา</p>
          </div>
        </div>
        <div className="guide-item">
          <Icon name="chat" />
          <div>
            <strong>3. เริ่มถามได้เลย</strong>
            <p>เมื่อสถานะพร้อม ให้ไปที่ผู้ช่วยแชท</p>
          </div>
        </div>
      </div>
      <QuotaCard quota={quota} />

      <form className="card" onSubmit={upload}>
        {error && (
          <div className="alert" role="alert">
            {error}
          </div>
        )}
        {notice && (
          <div className="alert info" role="status">
            {notice}
          </div>
        )}

        <div className="field">
          {/* label ห่อ input ที่ซ่อนอยู่ ทำให้ทั้งกล่องเป็นเป้าคลิกโดยที่ยัง
              เข้าถึงด้วยคีย์บอร์ดและ screen reader ได้ตามปกติ
              ซ่อนด้วย clip ไม่ใช่ display:none ซึ่งจะทำให้ focus ไปไม่ถึง */}
          <label
            className={`dropzone ${dragging ? "is-dragging" : ""}`}
            onDragOver={(e) => {
              e.preventDefault();
              if (!busy && !outOfQuota) setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragging(false);
              if (busy || outOfQuota) return;
              accept(e.dataTransfer.files);
            }}
          >
            <input
              id="file"
              type="file"
              className="visually-hidden"
              ref={fileInput}
              accept={ACCEPT}
              multiple
              disabled={busy || outOfQuota}
              onChange={(e) => accept(e.target.files)}
            />
            <Icon name="upload" size={30} />
            <strong>
              {picked.length === 0
                ? "ลากไฟล์มาวาง หรือกดเพื่อเลือก"
                : picked.length === 1
                  ? picked[0].name
                  : `เลือกไว้ ${picked.length} ไฟล์`}
            </strong>
            <span className="hint">
              {picked.length === 0
                ? "PDF · รูปภาพ · DOCX · TXT · Markdown · HTML"
                : formatBytes(picked.reduce((sum, f) => sum + f.size, 0))}
            </span>
          </label>
          {/* ประกาศให้ screen reader รู้ว่าเลือกอะไรไปแล้ว การเปลี่ยนข้อความ
              ในปุ่มอย่างเดียวไม่ถูกอ่านออกมา */}
          <p className="visually-hidden" aria-live="polite">
            {picked.length === 0 ? "ยังไม่ได้เลือกไฟล์" : `เลือกแล้ว ${picked.length} ไฟล์`}
          </p>
        </div>

        <div className="btn-row">
          <button className="btn" type="submit" disabled={busy || outOfQuota || !picked.length}>
            <Icon name="upload" size={18} />
            {busy
              ? "กำลังอัปโหลด…"
              : picked.length > 1
                ? `อัปโหลด ${picked.length} ไฟล์`
                : "อัปโหลดเอกสาร"}
          </button>
          {picked.length > 0 && !busy && (
            <button className="btn ghost" type="button" onClick={clearPicked}>
              ล้างที่เลือก
            </button>
          )}
          {outOfQuota && <span className="fail">โควตาวันนี้หมดแล้ว</span>}
          {user.role === "admin" && picked.length > 1 && (
            <span className="hint">อัปหลายไฟล์ในฐานะ admin — ไม่คิดโควตา</span>
          )}
        </div>
      </form>

      <h2>
        รายการเอกสาร
        {/* บอกให้ชัดว่ายังมีอีก — เดิมตัดที่ 50 แถวเงียบ ๆ ผู้ใช้จึงเข้าใจผิด
            ว่าเอกสารเก่าหายไปแล้ว */}
        {totalDocuments > documents.length && (
          <span className="muted" style={{ fontSize: "0.85rem", fontWeight: 400 }}>
            {" "}
            แสดง {documents.length} จาก {totalDocuments}
          </span>
        )}
      </h2>
      <div className="toolbar">
        <div className="search-field">
          <Icon name="search" size={18} />
          <input
            aria-label="ค้นหาชื่อเอกสารที่โหลดแล้ว"
            placeholder="ค้นหาชื่อเอกสารที่โหลดแล้ว"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <select
          aria-label="กรองสถานะเอกสาร"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        >
          <option value="all">ทุกสถานะ</option>
          <option value="ready">พร้อมใช้งาน</option>
          <option value="processing">กำลังประมวลผล</option>
          <option value="pending">รอประมวลผล</option>
          <option value="failed">ไม่สำเร็จ</option>
        </select>
        <span className="muted">
          {filteredDocuments.length} / {documents.length} รายการที่โหลดแล้ว
        </span>
      </div>
      {filteredDocuments.length === 0 ? (
        <div className="empty-state">
          <Icon name="documents" size={36} />
          <h3>
            {documents.length ? "ไม่พบเอกสารที่ตรงกับตัวกรอง" : "เริ่มสร้างคลังความรู้ของคุณ"}
          </h3>
          <p>
            {documents.length
              ? "ลองเปลี่ยนคำค้นหรือเลือกสถานะอื่น"
              : "เลือกไฟล์ด้านบนเพื่อเพิ่มเอกสารแรก แล้วเริ่มถามผู้ช่วยได้เมื่อประมวลผลเสร็จ"}
          </p>
        </div>
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
              {filteredDocuments.map((doc) => {
                const job = jobs[doc.id];
                return (
                  <tr key={doc.id}>
                    <td className="wrap">
                      {doc.filename}
                      {job?.error && <div className="detail fail">{job.error}</div>}
                    </td>
                    <td>
                      <span className={`badge ${doc.status}`}>
                        {{
                          ready: "พร้อมใช้งาน",
                          processing: "กำลังประมวลผล",
                          pending: "รอประมวลผล",
                          failed: "ไม่สำเร็จ",
                        }[doc.status] ?? doc.status}
                      </span>
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
                      {doc.page_count_estimated && <span className="detail"> (ประเมิน)</span>}
                    </td>
                    <td>{doc.ocr_page_count}</td>
                    <td>{formatBytes(doc.size_bytes)}</td>
                    <td>{formatDateTime(doc.created_at)}</td>
                    <td>
                      <div className="row-actions">
                        {user.role === "admin" && (
                          <button
                            className="btn ghost"
                            aria-label={`ประมวลผล ${doc.filename} ใหม่`}
                            disabled={ACTIVE_STATES.has(doc.status)}
                            title={
                              ACTIVE_STATES.has(doc.status)
                                ? "เอกสารนี้กำลังประมวลผลอยู่"
                                : "อ่านเอกสารใหม่ทั้งฉบับ ไม่คิดโควตาซ้ำ"
                            }
                            onClick={() => reprocess(doc)}
                          >
                            <Icon name="history" size={16} /> ประมวลผลใหม่
                          </button>
                        )}
                        <button
                          className="btn ghost danger"
                          aria-label={`ลบเอกสาร ${doc.filename}`}
                          onClick={() => remove(doc)}
                        >
                          <Icon name="trash" size={16} /> ลบ
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {totalDocuments > documents.length && (
        <div className="btn-row" style={{ marginTop: "0.75rem" }}>
          <button className="btn ghost" onClick={() => setVisibleLimit((n) => n + PAGE_SIZE)}>
            โหลดเพิ่มอีก {Math.min(PAGE_SIZE, totalDocuments - documents.length)} รายการ
          </button>
        </div>
      )}
    </>
  );
}

export default function DocumentsPage() {
  return <Shell>{(user) => <DocumentsInner user={user} />}</Shell>;
}
