// เรียก API ผ่าน path สัมพัทธ์เป็นค่าเริ่มต้น เพื่อให้ผ่าน Caddy ที่ http://localhost
// แล้วเป็น origin เดียวกัน — cookie httpOnly จึงถูกส่งไปด้วยโดยไม่ต้องตั้งค่าอะไรเพิ่ม
// ตั้ง NEXT_PUBLIC_API_URL เมื่อต้องการยิงตรงไปที่ :8000 ตอน dev
export const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "";

export function apiFetch(input: RequestInfo | URL, init: RequestInit = {}) {
  const headers = new Headers(init.headers);
  headers.set("ngrok-skip-browser-warning", "1");
  return fetch(input, { ...init, headers });
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public body?: unknown,
  ) {
    super(message);
  }
}

async function parseBody(res: Response): Promise<unknown> {
  const text = await res.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    throw new ApiError(res.status, "ขณะนี้ไม่สามารถเชื่อมต่อบริการได้ กรุณาติดต่อผู้ดูแลระบบ");
  }
}

function messageFrom(body: unknown, fallback: string): string {
  if (typeof body === "string") return body;
  if (body && typeof body === "object") {
    const detail = (body as { detail?: unknown; reason?: unknown }).detail;
    if (typeof detail === "string") return detail;
    const reason = (body as { reason?: unknown }).reason;
    if (typeof reason === "string") return reason;
  }
  return fallback;
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await apiFetch(`${API_BASE}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      ...(init?.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...init?.headers,
    },
  });

  const body = await parseBody(res);
  if (!res.ok) {
    throw new ApiError(res.status, messageFrom(body, `HTTP ${res.status}`), body);
  }
  return body as T;
}

// types

/** ผลลัพธ์แบบแบ่งหน้า
 *
 * total ทำให้หน้าเว็บบอกได้ว่า "แสดง 50 จาก 137" และรู้ว่ายังมีให้โหลดอีก
 * เดิม API คืน array เปล่า ๆ พร้อม limit ตายตัว ผู้ใช้จึงเข้าใจผิดว่า
 * ที่เห็นคือทั้งหมดที่มี
 */
export type Page<T> = {
  items: T[];
  total: number;
  limit: number;
  offset: number;
};

export type Me = {
  id: string;
  email: string;
  role: "user" | "admin";
  is_active: boolean;
  created_at: string;
};

export type QuotaBucket = { used: number; limit: number | null; remaining: number | null };

export type Quota = {
  documents: QuotaBucket;
  pages: QuotaBucket;
  unlimited: boolean;
  resets_at: string;
  /** เพดานขนาดไฟล์จากเซิร์ฟเวอร์ ไม่ตั้งเองฝั่งเว็บเพื่อไม่ให้สองฝั่งเพี้ยนกัน */
  max_upload_bytes: number;
};

export type DocumentOut = {
  id: string;
  filename: string;
  mime_type: string;
  status: "pending" | "processing" | "ready" | "failed";
  collection: string;
  page_count: number;
  page_count_estimated: boolean;
  ocr_page_count: number;
  size_bytes: number;
  created_at: string;
};

export type JobOut = {
  id: string;
  document_id: string;
  stage: string;
  progress: number;
  pages_done: number;
  pages_total: number;
  queue: string;
  error: string | null;
  processor_note: string | null;
  queued_at: string;
  started_at: string | null;
  finished_at: string | null;
};

export type UploadAccepted = {
  document: DocumentOut;
  job: JobOut;
  estimated_seconds: number;
  ocr_pages: number;
};

export type Hit = {
  rank: number;
  score: number;
  document_id: string;
  document_name: string;
  page_no: number | null;
  source: string;
  text: string;
};

export type PlaygroundResult = {
  question: string;
  hits: Hit[];
  answer: string | null;
  answered_from_context: boolean;
  latency_ms?: number;
  message_id?: string | null;
};

export type PromptConfig = {
  id: string;
  name: string;
  system_prompt: string;
  top_k: number;
  temperature: number;
  min_score: number;
  enable_thinking: boolean;
  is_active: boolean;
};

// helpers

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function formatDuration(seconds: number): string {
  if (seconds <= 0) return "ไม่ต้องรอ";
  if (seconds < 60) return `${Math.round(seconds)} วินาที`;
  const minutes = seconds / 60;
  if (minutes < 60) return `${Math.round(minutes)} นาที`;
  return `${(minutes / 60).toFixed(1)} ชั่วโมง`;
}

/** วันที่พร้อมเวลา เช่น "9 ก.ย. 2569 15:59"
 *
 * ใช้ medium ไม่ใช่ short · short ของ th-TH ให้ "9/9/69" ซึ่งปีพุทธศักราชสองหลัก
 * อ่านแล้วสับสนกับ ค.ศ. และเดือนกับวันสลับกันได้ในสายตาคนที่ชินกับรูปแบบอื่น
 */
export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString("th-TH", {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

/** วันที่อย่างเดียว เช่น "9 ก.ย. 2569" — ใช้ที่ที่พื้นที่จำกัดอย่างรายการบทสนทนา
 *
 * อยู่ที่นี่เพื่อให้ทุกหน้าจัดรูปแบบวันที่เหมือนกัน ก่อนหน้านี้หน้าแชทเรียก
 * toLocaleDateString เองแยกต่างหาก ซึ่งจะเพี้ยนไปคนละแบบเมื่อแก้ที่เดียว
 */
export function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("th-TH", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}
