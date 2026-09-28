"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { ApiError, api, type Me } from "./api";

type State = { user: Me | null; loading: boolean };

/** โหลดผู้ใช้ปัจจุบัน และเด้งไป /login ถ้ายังไม่ได้เข้าสู่ระบบ */
export function useAuth(options?: { requireAdmin?: boolean }): State {
  const router = useRouter();
  const [state, setState] = useState<State>({ user: null, loading: true });
  const requireAdmin = options?.requireAdmin ?? false;

  useEffect(() => {
    let cancelled = false;

    api<Me>("/api/auth/me")
      .then((user) => {
        if (cancelled) return;
        if (requireAdmin && user.role !== "admin") {
          router.replace("/documents");
          // เคลียร์ loading ก่อนเปลี่ยนหน้า เพื่อไม่ให้ค้างหาก navigation ไม่สำเร็จ
          setState({ user: null, loading: false });
          return;
        }
        setState({ user, loading: false });
      })
      .catch((err) => {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 401) {
          router.replace("/login");
        } else {
          setState({ user: null, loading: false });
        }
      });

    return () => {
      cancelled = true;
    };
  }, [router, requireAdmin]);

  return state;
}

export function useLogout(): () => Promise<void> {
  const router = useRouter();
  return useCallback(async () => {
    await api("/api/auth/logout", { method: "POST" }).catch(() => undefined);
    router.replace("/login");
  }, [router]);
}
