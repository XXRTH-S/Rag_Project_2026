// เรียก API ผ่าน path สัมพัทธ์เป็นค่าเริ่มต้น เพื่อให้ผ่าน Caddy ที่ http://localhost
// แล้วเป็น origin เดียวกัน — cookie httpOnly จึงถูกส่งไปด้วยโดยไม่ต้องตั้งค่าอะไรเพิ่ม
// ตั้ง NEXT_PUBLIC_API_URL เมื่อต้องการยิงตรงไปที่ :8000 ตอน dev
export const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "";

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
    return text;
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
  const res = await fetch(`${API_BASE}${path}`, {
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

// ---------- types ----------

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

// ---------- helpers ----------

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

export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString("th-TH", {
    dateStyle: "short",
    timeStyle: "short",
  });
}
