"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Icon } from "@/components/Icon";
import { ThemeToggle } from "@/components/ThemeToggle";
import { api } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      router.replace("/documents");
    } catch (err) {
      setError(err instanceof Error ? err.message : "เข้าสู่ระบบไม่สำเร็จ");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="login-layout">
      <section className="login-story">
        <div className="brand">
          <span className="brand-icon">
            <Icon name="leaf" size={26} />
          </span>
          <span>
            RAG Workshop<small>พื้นที่ความรู้ของคุณ</small>
          </span>
        </div>
        <h2>
          ความรู้ที่เก็บไว้
          <br />
          กลายเป็นคำตอบ
          <br />
          ที่เข้าถึงได้
        </h2>
        <p>เชื่อมต่อเอกสารกับผู้ช่วยของคุณ เพื่อค้นหา สรุป และเข้าใจข้อมูลได้ในบทสนทนาเดียว</p>
        <div className="story-steps">
          <span>
            <Icon name="documents" />
            รวบรวมเอกสาร
          </span>
          <span>
            <Icon name="search" />
            ค้นข้อมูล
          </span>
          <span>
            <Icon name="chat" />
            ถามคำถาม
          </span>
        </div>
      </section>
      <section className="login-panel">
        {/* หน้านี้ไม่มีแถบนำทาง จึงต้องมีปุ่มสลับโหมดของตัวเอง
            ไม่งั้นคนที่เข้ามาหน้าแรกสุดจะเปลี่ยนโหมดไม่ได้จนกว่าจะล็อกอินผ่าน */}
        <div className="login-theme">
          <ThemeToggle />
        </div>
        <div>
          <h1>เข้าสู่ระบบ</h1>
          <p className="sub">ระบบสาธิตสำหรับการสัมภาษณ์ ใช้บัญชีทดสอบที่ผู้ดูแลเตรียมให้</p>

          <form onSubmit={submit} className="card">
            {error && (
              <div className="alert" role="alert">
                {error}
              </div>
            )}

            <div className="field">
              <label htmlFor="email">อีเมล</label>
              <input
                id="email"
                type="email"
                autoComplete="username"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>

            <div className="field">
              <label htmlFor="password">รหัสผ่าน</label>
              <div className="password-field">
                <input
                  id="password"
                  type={showPassword ? "text" : "password"}
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                />
                <button
                  className="icon-button"
                  type="button"
                  aria-label={showPassword ? "ซ่อนรหัสผ่าน" : "แสดงรหัสผ่าน"}
                  aria-pressed={showPassword}
                  onClick={() => setShowPassword(!showPassword)}
                >
                  <Icon name="eye" />
                </button>
              </div>
            </div>

            <button className="btn" type="submit" disabled={busy}>
              {busy ? "กำลังเข้าสู่ระบบ…" : "เข้าสู่ระบบ"}
            </button>
          </form>
          <p className="login-note">
            <Icon name="shield" size={16} />
            ใช้ข้อมูลสมมติเท่านั้น · แต่ละบัญชีเข้าถึงข้อมูลของตนเอง
          </p>
        </div>
      </section>
    </main>
  );
}
