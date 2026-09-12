import Link from "next/link";

/** หน้า 404 ของระบบ
 *
 * ค่าเริ่มต้นของ Next เป็นหน้าภาษาอังกฤษเปล่า ๆ ไม่มีทางกลับ
 * ผู้ใช้ที่พิมพ์ URL ผิดจะไม่รู้ว่าต้องไปไหนต่อ
 */
export default function NotFound() {
  return (
    <main className="narrow">
      <h1>ไม่พบหน้านี้</h1>
      <p className="sub">ลิงก์อาจพิมพ์ผิด หรือหน้านี้ถูกย้ายไปแล้ว</p>

      <div className="card">
        <div className="btn-row">
          <Link className="btn" href="/documents">
            ไปหน้าเอกสาร
          </Link>
          <Link className="btn ghost" href="/chat">
            ไปหน้าแชท
          </Link>
        </div>
      </div>
    </main>
  );
}
