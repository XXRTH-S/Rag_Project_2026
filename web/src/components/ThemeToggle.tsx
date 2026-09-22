"use client";

import { useEffect, useState } from "react";

import { Icon } from "./Icon";

export const THEME_KEY = "rag-theme";

type Theme = "light" | "dark";

/** ปุ่มสลับโหมดสว่าง/มืด
 *
 * ค่าเริ่มต้นคือตามเครื่อง (CSS ใช้ prefers-color-scheme) การกดปุ่มคือการเลือกเอง
 * ซึ่งเขียนทับค่าของเครื่องผ่าน data-theme บน <html> และจำไว้ใน localStorage
 *
 * สคริปต์ใน layout.tsx อ่านค่าที่จำไว้ก่อนวาดหน้าแรก ไม่งั้นจะเห็นหน้าสว่างวาบ
 * หนึ่งเฟรมก่อนจะสลับเป็นมืด
 */
export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme | null>(null);

  useEffect(() => {
    // อ่านสิ่งที่เห็นอยู่จริง ไม่ใช่สิ่งที่จำไว้ — ถ้ายังไม่เคยเลือก ค่าจะมาจากเครื่อง
    const chosen = document.documentElement.dataset.theme as Theme | undefined;
    if (chosen) {
      setTheme(chosen);
      return;
    }
    setTheme(window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  }, []);

  const toggle = () => {
    const next: Theme = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    setTheme(next);
    try {
      localStorage.setItem(THEME_KEY, next);
    } catch {
      // โหมดส่วนตัวของบางเบราว์เซอร์ห้ามเขียน — สลับได้อยู่ แค่ไม่จำข้ามหน้า
    }
  };

  // ยังไม่รู้ว่าเครื่องตั้งไว้แบบไหนจนกว่าจะถึงฝั่ง browser
  // เว้นที่ไว้เท่าเดิมเพื่อไม่ให้ปุ่มอื่นขยับตอน hydrate
  if (theme === null) return <span className="icon-button" aria-hidden="true" />;

  const goingDark = theme === "light";
  return (
    <button
      type="button"
      className="icon-button"
      onClick={toggle}
      title={goingDark ? "เปลี่ยนเป็นโหมดมืด" : "เปลี่ยนเป็นโหมดสว่าง"}
      aria-label={goingDark ? "เปลี่ยนเป็นโหมดมืด" : "เปลี่ยนเป็นโหมดสว่าง"}
      aria-pressed={theme === "dark"}
    >
      <Icon name={goingDark ? "moon" : "sun"} size={18} />
    </button>
  );
}
