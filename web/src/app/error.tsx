"use client";

import { useEffect } from "react";

/** จอรับ error ที่หลุดออกมาจาก component
 *
 * ถ้าไม่มีไฟล์นี้ Next จะแสดงหน้าขาวเปล่า ๆ ตอน production เมื่อ component พัง
 * ผู้ใช้ไม่รู้ว่าเกิดอะไรขึ้นและไม่มีทางไปต่อนอกจากปิดแท็บทิ้ง
 */
export default function ErrorBoundary({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // ส่งเข้า console ของเบราว์เซอร์ไว้ให้คนที่มาช่วยดูหน้างานเปิดอ่านได้
    console.error("หน้าเว็บทำงานผิดพลาด", error);
  }, [error]);

  return (
    <main className="narrow">
      <h1>หน้านี้ทำงานผิดพลาด</h1>
      <p className="sub">ระบบยังทำงานอยู่ เฉพาะหน้านี้ที่แสดงผลไม่สำเร็จ</p>

      <div className="card">
        <div className="alert" role="alert">
          {error.message || "ไม่ทราบสาเหตุ"}
          {/* digest คือรหัสที่ Next ผูกไว้กับ error ตัวจริงใน log ฝั่งเซิร์ฟเวอร์
              ตอน production ข้อความจะถูกซ่อน เหลือแต่รหัสนี้ให้ตามต่อได้ */}
          {error.digest && <div className="detail">รหัสอ้างอิง {error.digest}</div>}
        </div>

        <div className="btn-row">
          <button className="btn" onClick={reset}>
            ลองใหม่
          </button>
          <a className="btn ghost" href="/documents">
            กลับหน้าเอกสาร
          </a>
        </div>
      </div>
    </main>
  );
}
