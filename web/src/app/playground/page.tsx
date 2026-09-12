"use client";

import { useCallback, useEffect, useState } from "react";

import { Shell } from "@/components/Shell";
import { api, type PlaygroundResult, type PromptConfig } from "@/lib/api";

function PlaygroundInner() {
  const [question, setQuestion] = useState("");
  const [topK, setTopK] = useState(8);
  const [minScore, setMinScore] = useState(0.35);
  const [temperature, setTemperature] = useState(0.2);
  const [callLlm, setCallLlm] = useState(true);
  const [result, setResult] = useState<PlaygroundResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [configs, setConfigs] = useState<PromptConfig[]>([]);
  const [configName, setConfigName] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");

  const loadConfigs = useCallback(async () => {
    const [list, fallback] = await Promise.all([
      api<PromptConfig[]>("/api/admin/prompt-configs"),
      api<{ system_prompt: string }>("/api/admin/prompt-configs/default"),
    ]);
    setConfigs(list);
    setSystemPrompt((prev) => prev || list.find((c) => c.is_active)?.system_prompt || fallback.system_prompt);
  }, []);

  useEffect(() => {
    loadConfigs().catch(() => undefined);
  }, [loadConfigs]);

  async function run(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body = await api<PlaygroundResult>("/api/admin/playground/query", {
        method: "POST",
        body: JSON.stringify({
          message: question,
          top_k: topK,
          min_score: minScore,
          temperature,
          system_prompt: systemPrompt || null,
          call_llm: callLlm,
        }),
      });
      setResult(body);
    } catch (err) {
      setError(err instanceof Error ? err.message : "ยิงคำถามไม่สำเร็จ");
    } finally {
      setBusy(false);
    }
  }

  async function saveConfig() {
    if (!configName.trim() || !systemPrompt.trim()) return;
    setError(null);
    try {
      await api("/api/admin/prompt-configs", {
        method: "POST",
        body: JSON.stringify({
          name: configName,
          system_prompt: systemPrompt,
          top_k: topK,
          temperature,
          min_score: minScore,
        }),
      });
      setConfigName("");
      await loadConfigs();
    } catch (err) {
      setError(err instanceof Error ? err.message : "บันทึกไม่สำเร็จ");
    }
  }

  async function activate(id: string) {
    await api(`/api/admin/prompt-configs/${id}/activate`, { method: "POST" });
    await loadConfigs();
  }

  async function deactivate(id: string) {
    await api(`/api/admin/prompt-configs/${id}/deactivate`, { method: "POST" });
    await loadConfigs();
  }

  async function removeConfig(config: PromptConfig) {
    const extra = config.is_active ? "\n\nconfig นี้กำลังใช้งานอยู่ ลบแล้วระบบจะกลับไปใช้ prompt เริ่มต้น" : "";
    if (!confirm(`ลบ "${config.name}"?${extra}`)) return;
    await api(`/api/admin/prompt-configs/${config.id}`, { method: "DELETE" });
    await loadConfigs();
  }

  return (
    <>
      <h1>Playground</h1>
      <p className="sub">
        คืน chunk ดิบพร้อมคะแนน เพื่อแยกให้ออกว่าคำตอบผิดเพราะ retrieval หาไม่เจอ หรือเจอแล้วแต่โมเดลตอบเพี้ยน
      </p>

      {error && <div className="alert">{error}</div>}

      <form className="card" onSubmit={run}>
        <div className="field">
          <label htmlFor="q">คำถาม</label>
          <input id="q" value={question} onChange={(e) => setQuestion(e.target.value)} required />
        </div>

        <div className="grid">
          <div className="field">
            <label htmlFor="topk">top_k</label>
            <input
              id="topk"
              type="number"
              min={1}
              max={50}
              value={topK}
              onChange={(e) => setTopK(Number(e.target.value))}
            />
          </div>
          <div className="field">
            <label htmlFor="min">min_score</label>
            <input
              id="min"
              type="number"
              step={0.05}
              min={-1}
              max={1}
              value={minScore}
              onChange={(e) => setMinScore(Number(e.target.value))}
            />
          </div>
          <div className="field">
            <label htmlFor="temp">temperature</label>
            <input
              id="temp"
              type="number"
              step={0.1}
              min={0}
              max={2}
              value={temperature}
              onChange={(e) => setTemperature(Number(e.target.value))}
            />
          </div>
        </div>

        <div className="field">
          <label htmlFor="sp">system prompt</label>
          <textarea id="sp" value={systemPrompt} onChange={(e) => setSystemPrompt(e.target.value)} />
        </div>

        <div className="btn-row">
          <button className="btn" type="submit" disabled={busy || !question.trim()}>
            {busy ? "กำลังทดสอบ…" : "ทดสอบ"}
          </button>
          <label className="muted" style={{ display: "flex", gap: "0.4rem", margin: 0 }}>
            <input
              type="checkbox"
              style={{ width: "auto" }}
              checked={!callLlm}
              onChange={(e) => setCallLlm(!e.target.checked)}
            />
            ดูเฉพาะ retrieval (ไม่เรียก LLM — เร็วกว่ามากบนการ์ดนี้)
          </label>
        </div>
      </form>

      {result && (
        <>
          {result.answer !== null && (
            <div className="card">
              <div className="row">
                <span className="name">คำตอบ</span>
                <span className="muted">
                  {result.latency_ms} ms ·{" "}
                  {result.answered_from_context ? "ตอบจาก context" : "ไม่พบข้อมูล"}
                </span>
              </div>
              <p style={{ whiteSpace: "pre-wrap", marginBottom: 0 }}>{result.answer}</p>
            </div>
          )}

          <h2>chunk ที่ค้นเจอ ({result.hits.length})</h2>
          {result.hits.length === 0 && (
            <div className="alert info">
              ไม่มี chunk ไหนผ่านเกณฑ์ min_score — ระบบจะตอบว่าไม่พบข้อมูลโดยไม่เรียก LLM
              ลองลด min_score เพื่อดูว่าใกล้เคียงแค่ไหน
            </div>
          )}
          {result.hits.map((hit) => (
            <div className="card" key={hit.rank}>
              <div className="row">
                <span className="name">
                  [{hit.rank}] {hit.document_name}
                  {hit.page_no ? ` · หน้า ${hit.page_no}` : ""}
                  <span className="badge">{hit.source}</span>
                </span>
                <span className="muted">คะแนน {hit.score.toFixed(4)}</span>
              </div>
              <pre className="chunk">{hit.text}</pre>
            </div>
          ))}
        </>
      )}

      <h2>Prompt config</h2>
      <div className="card">
        <div className="field">
          <label htmlFor="cfgname">บันทึกค่าปัจจุบันเป็น config ใหม่</label>
          <input
            id="cfgname"
            placeholder="เช่น v2-สั้นลง"
            value={configName}
            onChange={(e) => setConfigName(e.target.value)}
          />
        </div>
        <button className="btn ghost" onClick={saveConfig} disabled={!configName.trim()}>
          บันทึก
        </button>
      </div>

      {configs.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>ชื่อ</th>
                <th>top_k</th>
                <th>temp</th>
                <th>min_score</th>
                <th>สถานะ</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {configs.map((cfg) => (
                <tr key={cfg.id}>
                  <td>{cfg.name}</td>
                  <td>{cfg.top_k}</td>
                  <td>{cfg.temperature}</td>
                  <td>{cfg.min_score}</td>
                  <td>{cfg.is_active ? <span className="badge ready">ใช้งานอยู่</span> : "—"}</td>
                  <td>
                    <div className="btn-row">
                      <button
                        className="btn ghost"
                        onClick={() => {
                          setSystemPrompt(cfg.system_prompt);
                          setTopK(cfg.top_k);
                          setTemperature(cfg.temperature);
                          setMinScore(cfg.min_score);
                        }}
                      >
                        โหลด
                      </button>
                      {cfg.is_active ? (
                        <button className="btn ghost" onClick={() => deactivate(cfg.id)}>
                          กลับไปใช้ค่าเริ่มต้น
                        </button>
                      ) : (
                        <button className="btn ghost" onClick={() => activate(cfg.id)}>
                          เปิดใช้
                        </button>
                      )}
                      <button className="btn ghost" onClick={() => removeConfig(cfg)}>
                        ลบ
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

export default function PlaygroundPage() {
  return <Shell requireAdmin>{() => <PlaygroundInner />}</Shell>;
}
