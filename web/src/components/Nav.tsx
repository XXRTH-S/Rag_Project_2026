"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import type { Me } from "@/lib/api";
import { useLogout } from "@/lib/useAuth";
import { Icon } from "./Icon";
import { ThemeToggle } from "./ThemeToggle";
const LINKS = [
  { href: "/documents", label: "เอกสาร", icon: "documents" },
  { href: "/chat", label: "ผู้ช่วยแชท", icon: "chat" },
  { href: "/playground", label: "ทดลองคำตอบ", icon: "playground", adminOnly: true },
  { href: "/analytics", label: "ภาพรวมการใช้งาน", icon: "analytics", adminOnly: true },
  { href: "/users", label: "จัดการผู้ใช้", icon: "users", adminOnly: true },
  { href: "/status", label: "สถานะระบบ", icon: "status" },
];
export function Nav({ user }: { user: Me | null }) {
  const pathname = usePathname();
  const logout = useLogout();
  const [open, setOpen] = useState(false);
  const isAdmin = user?.role === "admin";
  return (
    <>
      <a className="skip-link" href="#main-content">
        ข้ามไปเนื้อหา
      </a>
      <nav className="nav" aria-label="เมนูหลัก">
        <Link className="brand" href="/documents">
          <span className="brand-icon">
            <Icon name="leaf" size={25} />
          </span>
          <span>
            RAG Workshop<small>พื้นที่ความรู้ของคุณ</small>
          </span>
        </Link>
        <button
          className="icon-button mobile-menu"
          aria-label={open ? "ปิดเมนู" : "เปิดเมนู"}
          aria-expanded={open}
          aria-controls="navigation"
          onClick={() => setOpen(!open)}
        >
          <Icon name={open ? "close" : "menu"} />
        </button>
        <div id="navigation" className={`nav-content ${open ? "is-open" : ""}`}>
          <p className="nav-caption">พื้นที่ทำงาน</p>
          <div className="nav-links">
            {LINKS.filter((l) => !l.adminOnly || isAdmin).map((l) => (
              <Link
                key={l.href}
                href={l.href}
                onClick={() => setOpen(false)}
                className={`nav-link ${pathname === l.href ? "active" : ""}`}
                aria-current={pathname === l.href ? "page" : undefined}
              >
                <Icon name={l.icon} />
                {l.label}
                {pathname === l.href && <span className="active-dot" />}
              </Link>
            ))}
          </div>
          <div className="nav-guide">
            <Icon name="book" size={28} />
            <strong>เริ่มต้นจากเอกสาร</strong>
            <p>อัปโหลดข้อมูลที่คุณต้องการ แล้วให้ผู้ช่วยค้นคำตอบจากคลัง</p>
            <Link href="/documents" onClick={() => setOpen(false)}>
              ไปที่คลังความรู้ <Icon name="arrow" size={16} />
            </Link>
          </div>
          {user && (
            <div className="nav-user">
              <span className="avatar">{user.email.slice(0, 1).toUpperCase()}</span>
              <div className="user-info">
                <strong title={user.email}>{user.email}</strong>
                <small>{isAdmin ? "ผู้ดูแลระบบ" : "สมาชิก"}</small>
              </div>
              <ThemeToggle />
              <button
                className="icon-button"
                onClick={logout}
                title="ออกจากระบบ"
                aria-label="ออกจากระบบ"
              >
                <Icon name="logout" size={18} />
              </button>
            </div>
          )}
        </div>
      </nav>
    </>
  );
}
