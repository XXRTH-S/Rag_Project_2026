"use client";

import type { Me } from "@/lib/api";
import { useAuth } from "@/lib/useAuth";

import { Nav } from "./Nav";

/** ห่อทุกหน้าที่ต้องล็อกอิน — เช็คสิทธิ์ก่อนแล้วค่อย render เนื้อหา */
export function Shell({
  requireAdmin = false,
  children,
}: {
  requireAdmin?: boolean;
  children: (user: Me) => React.ReactNode;
}) {
  const { user, loading } = useAuth({ requireAdmin });

  if (loading) {
    return (
      <>
        <Nav user={null} />
        <main>
          <p className="muted">กำลังโหลด…</p>
        </main>
      </>
    );
  }

  if (!user) {
    return (
      <>
        <Nav user={null} />
        <main>
          <div className="alert" role="alert">
            ต่อ API ไม่ได้ ตรวจว่า backend ทำงานอยู่ด้วย <code>.\dc.ps1 logs -f api</code>
          </div>
        </main>
      </>
    );
  }

  return (
    <>
      <Nav user={user} />
      <main>{children(user)}</main>
    </>
  );
}
