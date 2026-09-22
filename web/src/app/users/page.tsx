"use client";

import { useCallback, useEffect, useState } from "react";

import { Icon } from "@/components/Icon";
import { Shell } from "@/components/Shell";
import { api, formatDateTime, type Me } from "@/lib/api";

type UserRow = Me & {
  documents_today: number;
  pages_today: number;
  quota_unlimited: boolean;
};

function UsersInner({ me }: { me: Me }) {
  const [showPassword, setShowPassword] = useState(false);
  const [query, setQuery] = useState("");
  const [users, setUsers] = useState<UserRow[]>([]);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<"user" | "admin">("user");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setUsers(await api<UserRow[]>("/api/admin/users"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "โหลดรายชื่อไม่สำเร็จ");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function create(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await api("/api/admin/users", {
        method: "POST",
        body: JSON.stringify({ email, password, role }),
      });
      setNotice(`สร้างบัญชี ${email} แล้ว`);
      setEmail("");
      setPassword("");
      setRole("user");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "สร้างบัญชีไม่สำเร็จ");
    } finally {
      setBusy(false);
    }
  }

  async function patch(user: UserRow, body: Record<string, unknown>, label: string) {
    setError(null);
    try {
      await api(`/api/admin/users/${user.id}`, { method: "PATCH", body: JSON.stringify(body) });
      setNotice(`${label} ${user.email} แล้ว`);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "แก้ไขไม่สำเร็จ");
    }
  }

  async function resetPassword(user: UserRow) {
    const next = prompt(`รหัสผ่านใหม่ของ ${user.email} (อย่างน้อย 8 ตัวอักษร)`);
    if (!next) return;
    if (next.length < 8) {
      setError("รหัสผ่านต้องยาวอย่างน้อย 8 ตัวอักษร");
      return;
    }
    await patch(user, { password: next }, "ตั้งรหัสผ่านใหม่ให้");
  }

  async function remove(user: UserRow) {
    if (!confirm(`ลบบัญชี ${user.email}?\n\nเอกสารและ chunk ของเขาจะถูกลบไปด้วย`)) return;
    setError(null);
    try {
      await api(`/api/admin/users/${user.id}`, { method: "DELETE" });
      setNotice(`ลบบัญชี ${user.email} แล้ว`);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "ลบไม่สำเร็จ");
    }
  }

  return (
    <>
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

      <div className="grid">
        <div className="stat">
          <div className="label">สมาชิกทั้งหมด</div>
          <div className="value">{users.length}</div>
        </div>
        <div className="stat">
          <div className="label">บัญชีที่ใช้งานได้</div>
          <div className="value">{users.filter((u) => u.is_active).length}</div>
        </div>
        <div className="stat">
          <div className="label">ผู้ดูแลระบบ</div>
          <div className="value">{users.filter((u) => u.role === "admin").length}</div>
        </div>
      </div>
      <h2>
        <Icon name="users" /> เพิ่มสมาชิกในพื้นที่ทำงาน
      </h2>
      <form className="card" onSubmit={create}>
        <div className="grid">
          <div className="field">
            <label htmlFor="email">อีเมล</label>
            <input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>
          <div className="field">
            <label htmlFor="password">รหัสผ่าน (อย่างน้อย 8 ตัว)</label>
            <div className="password-field">
              <input
                id="password"
                type={showPassword ? "text" : "password"}
                minLength={8}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
              <button
                type="button"
                className="icon-button"
                aria-label={showPassword ? "ซ่อนรหัสผ่าน" : "แสดงรหัสผ่าน"}
                aria-pressed={showPassword}
                onClick={() => setShowPassword(!showPassword)}
              >
                <Icon name="eye" />
              </button>
            </div>
          </div>
          <div className="field">
            <label htmlFor="role">สิทธิ์</label>
            <select
              id="role"
              value={role}
              onChange={(e) => setRole(e.target.value as "user" | "admin")}
            >
              <option value="user">user — โควตาจำกัด เห็นเฉพาะเอกสารตัวเอง</option>
              <option value="admin">admin — ไม่จำกัด เห็นทุกอย่าง</option>
            </select>
          </div>
        </div>
        <button className="btn" type="submit" disabled={busy}>
          {busy ? "กำลังสร้าง…" : "สร้างบัญชี"}
        </button>
      </form>

      <div className="toolbar">
        <h2 style={{ margin: 0 }}>รายชื่อสมาชิก</h2>
        <div className="search-field">
          <Icon name="search" size={18} />
          <input
            aria-label="ค้นหาสมาชิก"
            placeholder="ค้นหาด้วยอีเมล"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>อีเมล</th>
              <th>สิทธิ์</th>
              <th>สถานะ</th>
              <th>ใช้วันนี้</th>
              <th>สร้างเมื่อ</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {users.filter((u) => u.email.toLowerCase().includes(query.toLowerCase())).length ===
              0 && (
              <tr>
                <td colSpan={6} className="muted">
                  ไม่พบสมาชิกที่ตรงกับคำค้น
                </td>
              </tr>
            )}
            {users
              .filter((u) => u.email.toLowerCase().includes(query.toLowerCase()))
              .map((user) => {
                const isSelf = user.id === me.id;
                return (
                  <tr key={user.id}>
                    <td className="wrap">
                      {user.email}
                      {isSelf && <span className="badge">คุณ</span>}
                    </td>
                    <td>
                      {user.role}
                      {user.quota_unlimited && <span className="badge">ไม่จำกัด</span>}
                    </td>
                    <td>
                      {user.is_active ? (
                        <span className="badge ready">ใช้งานได้</span>
                      ) : (
                        <span className="badge failed">ปิดอยู่</span>
                      )}
                    </td>
                    <td>
                      {user.documents_today} เอกสาร · {user.pages_today} หน้า
                    </td>
                    <td>{formatDateTime(user.created_at)}</td>
                    <td>
                      <div className="btn-row">
                        <button className="btn ghost" onClick={() => resetPassword(user)}>
                          ตั้งรหัสใหม่
                        </button>
                        {/* ปุ่มที่ล็อกตัวเองออกจากระบบได้ ไม่ควรมีให้กดตั้งแต่แรก */}
                        {!isSelf && (
                          <>
                            <button
                              className="btn ghost"
                              onClick={() =>
                                patch(
                                  user,
                                  { is_active: !user.is_active },
                                  user.is_active ? "ปิดบัญชี" : "เปิดบัญชี",
                                )
                              }
                            >
                              {user.is_active ? "ปิดบัญชี" : "เปิดบัญชี"}
                            </button>
                            <button
                              className="btn ghost"
                              onClick={() =>
                                patch(
                                  user,
                                  { role: user.role === "admin" ? "user" : "admin" },
                                  "เปลี่ยนสิทธิ์",
                                )
                              }
                            >
                              {user.role === "admin" ? "ลดเป็น user" : "ตั้งเป็น admin"}
                            </button>
                            <button className="btn ghost danger" onClick={() => remove(user)}>
                              ลบ
                            </button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
          </tbody>
        </table>
      </div>
    </>
  );
}

export default function UsersPage() {
  return <Shell requireAdmin>{(me) => <UsersInner me={me} />}</Shell>;
}
