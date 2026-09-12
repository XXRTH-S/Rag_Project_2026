"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import type { Me } from "@/lib/api";
import { useLogout } from "@/lib/useAuth";

const LINKS: { href: string; label: string; adminOnly?: boolean }[] = [
  { href: "/documents", label: "เอกสาร" },
  { href: "/chat", label: "แชท" },
  { href: "/playground", label: "Playground", adminOnly: true },
  { href: "/analytics", label: "Analytics", adminOnly: true },
  { href: "/users", label: "ผู้ใช้", adminOnly: true },
  { href: "/status", label: "สถานะระบบ" },
];

export function Nav({ user }: { user: Me | null }) {
  const pathname = usePathname();
  const logout = useLogout();
  const isAdmin = user?.role === "admin";

  return (
    <nav className="nav">
      <div className="nav-inner">
        <span className="brand">RAG Workshop</span>
        <div className="nav-links">
          {LINKS.filter((l) => !l.adminOnly || isAdmin).map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className={pathname === link.href ? "nav-link active" : "nav-link"}
            >
              {link.label}
            </Link>
          ))}
        </div>
        {user && (
          <div className="nav-user">
            <span className="muted">
              {user.email}
              {isAdmin && <span className="badge admin">admin</span>}
            </span>
            <button className="btn ghost" onClick={logout}>
              ออกจากระบบ
            </button>
          </div>
        )}
      </div>
    </nav>
  );
}
