"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { Icon } from "@/components/Icon";
import { Shell } from "@/components/Shell";
import { API_BASE, apiFetch, formatDate, type Page } from "@/lib/api";
import { citationLabel, stripCitationMarkers, type Citation } from "@/lib/citations";
type Message = {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  messageId?: string;
  answeredFromContext?: boolean;
  feedback?: 1 | -1;
  /** ขั้นที่กำลังทำอยู่ ใช้บอกความคืบหน้าระหว่างรอ token แรก */
  stage?: "searching" | "composing";
};

type SessionSummary = {
  id: string;
  title: string;
  message_count: number;
  last_message_at: string;
  created_at: string;
};

type HistoryMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  answered_from_context: boolean;
  citations: Citation[];
  feedback: number | null;
};

/** จำ session ที่เปิดล่าสุดไว้ เพื่อให้ refresh แล้วได้บทสนทนาเดิมกลับมา */
const LAST_SESSION_KEY = "rag.chat.lastSession";

/** จำนวนบทสนทนาต่อหนึ่งหน้า — ตรงกับค่าเริ่มต้นของ API */
const SESSION_PAGE_SIZE = 30;

/** อ่าน SSE จาก POST — EventSource ใช้ไม่ได้เพราะรองรับแค่ GET */
async function* readSse(response: Response): AsyncGenerator<{ event: string; data: string }> {
  const reader = response.body?.getReader();
  if (!reader) return;
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let split: number;
    while ((split = buffer.indexOf("\n\n")) !== -1) {
      const block = buffer.slice(0, split);
      buffer = buffer.slice(split + 2);

      let event = "message";
      let data = "";
      for (const line of block.split("\n")) {
        if (line.startsWith("event: ")) event = line.slice(7);
        else if (line.startsWith("data: ")) data = line.slice(6);
      }
      if (data) yield { event, data };
    }
  }
}

function ChatInner({ isAdmin }: { isAdmin: boolean }) {
  const [historyOpen, setHistoryOpen] = useState(false);
  const [opening, setOpening] = useState(false);
  const chatScroll = useRef<HTMLDivElement>(null);
  const composerInput = useRef<HTMLInputElement>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(true);
  // ประวัติสะสมเร็วกว่าเอกสารมาก — คุยวันละครั้งก็ชน 30 รายการใน 1 เดือน
  const [sessionLimit, setSessionLimit] = useState(SESSION_PAGE_SIZE);
  const [totalSessions, setTotalSessions] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const sessionId = useRef<string | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  const refreshSessions = useCallback(async () => {
    try {
      const r = await apiFetch(`${API_BASE}/api/chat/sessions?limit=${sessionLimit}`, {
        credentials: "include",
      });
      if (r.ok) {
        const page: Page<SessionSummary> = await r.json();
        setSessions(page.items);
        setTotalSessions(page.total);
      }
    } catch {
      // รายการบทสนทนาโหลดไม่ได้ ไม่ควรกันไม่ให้ถามคำถามใหม่ จึงปล่อยเงียบ
    }
  }, [sessionLimit]);

  const openSession = useCallback(async (id: string) => {
    setError(null);
    setOpening(true);
    try {
      const r = await apiFetch(`${API_BASE}/api/chat/sessions/${id}`, { credentials: "include" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const body: { messages: HistoryMessage[] } = await r.json();
      setMessages(
        body.messages.map((m) => ({
          role: m.role,
          content: m.content,
          citations: m.citations.length ? m.citations : undefined,
          messageId: m.role === "assistant" ? m.id : undefined,
          answeredFromContext: m.answered_from_context,
          feedback: m.feedback === 1 || m.feedback === -1 ? m.feedback : undefined,
        })),
      );
      setHistoryOpen(false);
      sessionId.current = id;
      setActiveId(id);
      localStorage.setItem(LAST_SESSION_KEY, id);
    } catch (err) {
      setError(err instanceof Error ? `เปิดบทสนทนาไม่ได้: ${err.message}` : "เปิดบทสนทนาไม่ได้");
    } finally {
      setOpening(false);
    }
  }, []);

  // ตอนเข้าหน้า: โหลดรายการ แล้วเปิดบทสนทนาที่ค้างไว้ต่อ
  // เช็คว่า id ที่จำไว้ยังอยู่ในรายการก่อน เพราะอาจถูกลบจากอีกแท็บหรืออีกเครื่อง
  useEffect(() => {
    (async () => {
      try {
        const r = await apiFetch(`${API_BASE}/api/chat/sessions`, { credentials: "include" });
        if (!r.ok) return;
        const page: Page<SessionSummary> = await r.json();
        setSessions(page.items);
        setTotalSessions(page.total);
        const remembered = localStorage.getItem(LAST_SESSION_KEY);
        if (remembered && page.items.some((s) => s.id === remembered)) {
          await openSession(remembered);
        }
      } finally {
        setLoadingHistory(false);
      }
    })();
  }, [openSession]);

  useEffect(() => {
    const el = chatScroll.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  // บนการ์ดนี้กว่า token แรกจะออกมาใช้เวลา 15–37 วินาที ถ้าไม่มีอะไรขยับเลย
  // ผู้ใช้จะคิดว่าระบบค้างแล้วถามซ้ำ — ตัวจับเวลาบอกว่ายังทำงานอยู่
  useEffect(() => {
    if (!busy) return;
    const started = Date.now();
    setElapsed(0);
    const timer = setInterval(() => setElapsed(Math.round((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(timer);
  }, [busy]);

  function startNew() {
    setHistoryOpen(false);
    sessionId.current = null;
    setActiveId(null);
    setMessages([]);
    setError(null);
    localStorage.removeItem(LAST_SESSION_KEY);
  }

  async function removeSession(id: string) {
    if (!confirm("ลบบทสนทนานี้ทิ้ง? กู้คืนไม่ได้")) return;
    const r = await apiFetch(`${API_BASE}/api/chat/sessions/${id}`, {
      method: "DELETE",
      credentials: "include",
    });
    if (!r.ok) {
      setError(`ลบไม่สำเร็จ (HTTP ${r.status})`);
      return;
    }
    if (sessionId.current === id) startNew();
    await refreshSessions();
  }

  async function send(event: React.FormEvent) {
    event.preventDefault();
    const question = input.trim();
    if (!question || busy || opening) return;

    setInput("");
    setError(null);
    setBusy(true);
    setMessages((prev) => [
      ...prev,
      { role: "user", content: question },
      { role: "assistant", content: "", stage: "searching" },
    ]);

    try {
      const response = await apiFetch(`${API_BASE}/api/chat`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: question, session_id: sessionId.current }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);

      for await (const { event: name, data } of readSse(response)) {
        const payload = JSON.parse(data);

        if (name === "session") {
          sessionId.current = payload.session_id;
          setActiveId(payload.session_id);
          localStorage.setItem(LAST_SESSION_KEY, payload.session_id);
        } else if (name === "citations") {
          setMessages((prev) => {
            const next = [...prev];
            next[next.length - 1] = {
              ...next[next.length - 1],
              citations: payload.citations,
              stage: "composing",
            };
            return next;
          });
        } else if (name === "token") {
          setMessages((prev) => {
            const next = [...prev];
            const last = next[next.length - 1];
            next[next.length - 1] = {
              ...last,
              content: last.content + payload.text,
              stage: undefined,
            };
            return next;
          });
        } else if (name === "done") {
          setMessages((prev) => {
            const next = [...prev];
            next[next.length - 1] = {
              ...next[next.length - 1],
              messageId: payload.message_id,
              answeredFromContext: payload.answered_from_context,
            };
            return next;
          });
        } else if (name === "error") {
          setError(payload.detail);
        }
      }
      // หัวข้อกับจำนวนข้อความเปลี่ยนไปแล้ว ต้องดึงรายการใหม่
      await refreshSessions();
    } catch (err) {
      setError(err instanceof Error ? err.message : "ส่งคำถามไม่สำเร็จ");
    } finally {
      setBusy(false);
    }
  }

  async function rate(index: number, rating: 1 | -1) {
    const message = messages[index];
    if (!message.messageId) return;
    setMessages((prev) => {
      const next = [...prev];
      next[index] = { ...next[index], feedback: rating };
      return next;
    });
    await apiFetch(`${API_BASE}/api/feedback`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message_id: message.messageId, rating }),
    }).catch(() => undefined);
  }

  return (
    <>
      {error && (
        <div className="alert" role="alert">
          {error}
        </div>
      )}

      <div className="chat-layout">
        <button
          type="button"
          className="btn ghost history-toggle"
          aria-expanded={historyOpen}
          aria-controls="chat-history"
          onClick={() => setHistoryOpen(!historyOpen)}
        >
          <Icon name="history" size={18} />
          {historyOpen ? "ซ่อนประวัติ" : "ประวัติการสนทนา"}
        </button>
        <aside id="chat-history" className={`session-pane ${historyOpen ? "is-open" : ""}`}>
          <button className="btn ghost" onClick={startNew} disabled={busy || opening}>
            <Icon name="plus" size={18} /> บทสนทนาใหม่
          </button>
          {loadingHistory && <p className="muted">กำลังโหลดประวัติ…</p>}
          {!loadingHistory && sessions.length === 0 && <p className="muted">ยังไม่มีประวัติ</p>}
          <ul className="session-list">
            {sessions.map((s) => (
              <li key={s.id} className={s.id === activeId ? "session-item active" : "session-item"}>
                <button
                  className="session-open"
                  onClick={() => openSession(s.id)}
                  disabled={busy || opening}
                  title={s.title}
                >
                  <span className="session-title">{s.title}</span>
                  <span className="muted session-meta">
                    {s.message_count} ข้อความ · {formatDate(s.last_message_at)}
                  </span>
                </button>
                <button
                  className="session-del"
                  onClick={() => removeSession(s.id)}
                  disabled={busy || opening}
                  aria-label={`ลบบทสนทนา ${s.title}`}
                  title="ลบบทสนทนานี้"
                >
                  <Icon name="trash" size={15} />
                </button>
              </li>
            ))}
          </ul>
          {/* บอกว่ายังมีอีกแทนที่จะตัดเงียบ ๆ ที่ 30 รายการ */}
          {totalSessions > sessions.length && (
            <button
              className="btn ghost"
              onClick={() => setSessionLimit((n) => n + SESSION_PAGE_SIZE)}
              disabled={busy || opening}
            >
              โหลดเพิ่ม ({sessions.length}/{totalSessions})
            </button>
          )}
        </aside>

        <div className="chat-main">
          <div className="chat" ref={chatScroll} aria-busy={busy || opening}>
            {messages.length === 0 && !loadingHistory && (
              <div className="chat-empty">
                <span className="empty-icon">
                  <Icon name="chat" size={32} />
                </span>
                <h2>วันนี้อยากรู้อะไร?</h2>
                <p>เลือกแนวคำถาม แล้วเติมหัวข้อหรือชื่อเอกสารที่อยู่ในคลังของคุณก่อนส่ง</p>
                <div className="suggestions">
                  {[
                    {
                      icon: "documents",
                      title: "สรุปใจความสำคัญ",
                      text: "ช่วยสรุปใจความสำคัญของเอกสาร ",
                    },
                    {
                      icon: "search",
                      title: "ค้นหาข้อมูลเฉพาะ",
                      text: "ในเอกสารมีข้อมูลเกี่ยวกับ ",
                    },
                    { icon: "book", title: "อธิบายให้เข้าใจง่าย", text: "ช่วยอธิบายเรื่อง " },
                    {
                      icon: "playground",
                      title: "เปรียบเทียบข้อมูล",
                      text: "ช่วยเปรียบเทียบข้อมูลเรื่อง ",
                    },
                  ].map((item) => (
                    <button
                      type="button"
                      className="suggestion"
                      key={item.title}
                      onClick={() => {
                        setInput(item.text);
                        composerInput.current?.focus();
                      }}
                    >
                      <Icon name={item.icon} size={18} />
                      {item.title}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {opening && (
              <p role="status" className="muted">
                กำลังเปิดบทสนทนา…
              </p>
            )}
            {messages.map((message, index) => (
              <div key={index} className={`msg ${message.role}`}>
                {message.role === "assistant" && !isAdmin
                  ? stripCitationMarkers(message.content, message.citations?.length ?? 0)
                  : message.content}

                {message.stage && index === messages.length - 1 && (
                  <div className="working">
                    <span className="dots" aria-hidden />
                    {/* ผู้ใช้ทั่วไปไม่เห็นรายการที่มา จึงไม่บอกจำนวน — พูดถึงสิ่งที่เขาจะไม่ได้เห็น
                        ทำให้สงสัยว่าของหายไปไหน แต่ยังต้องบอกว่าค้นเจอแล้วเพื่อให้รู้ว่าไม่ค้าง */}
                    {message.stage === "searching"
                      ? "กำลังค้นเอกสาร…"
                      : isAdmin
                        ? `พบ ${message.citations?.length ?? 0} แหล่งอ้างอิง · กำลังเรียบเรียงคำตอบ…`
                        : "ค้นเจอเอกสารที่เกี่ยวข้องแล้ว · กำลังเรียบเรียงคำตอบ…"}
                    <span className="muted"> {elapsed} วิ</span>
                    {elapsed >= 20 && (
                      <div className="detail">
                        ครั้งแรกหลังพักไปนานจะช้ากว่าปกติ เพราะต้องโหลดโมเดลเข้าการ์ดจอก่อน
                      </div>
                    )}
                  </div>
                )}

                {/* รายการที่มาเป็นเครื่องมือตรวจคุณภาพ retrieval ไม่ใช่ข้อมูลที่ผู้ใช้ทั่วไปต้องอ่าน
                    admin ยังต้องเห็นเพื่อดูว่า chunk ไหนถูกดึงมาและคะแนนเท่าไหร่ */}
                {isAdmin && message.role === "assistant" && !!message.citations?.length && (
                  <div className="cites">
                    {message.citations.map((c) => (
                      <div key={c.rank}>{citationLabel(c)}</div>
                    ))}
                  </div>
                )}

                {message.role === "assistant" && message.messageId && (
                  <div className="cites btn-row">
                    <button
                      className="btn ghost"
                      disabled={!!message.feedback}
                      onClick={() => rate(index, 1)}
                    >
                      {message.feedback === 1 ? "✓ มีประโยชน์" : "มีประโยชน์"}
                    </button>
                    <button
                      className="btn ghost"
                      disabled={!!message.feedback}
                      onClick={() => rate(index, -1)}
                    >
                      {message.feedback === -1 ? "✓ ยังไม่ตรง" : "ยังไม่ตรง"}
                    </button>
                  </div>
                )}
              </div>
            ))}
            <div ref={bottom} />
          </div>

          <form className="composer" onSubmit={send}>
            <input
              ref={composerInput}
              aria-label="คำถามถึงผู้ช่วย"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="พิมพ์คำถาม…"
              disabled={busy || opening}
            />
            <button className="btn" type="submit" disabled={busy || opening || !input.trim()}>
              <Icon name="send" size={19} />
              <span className="send-label">ส่ง</span>
            </button>
          </form>
        </div>
      </div>
    </>
  );
}

export default function ChatPage() {
  return <Shell>{(user) => <ChatInner isAdmin={user.role === "admin"} />}</Shell>;
}
