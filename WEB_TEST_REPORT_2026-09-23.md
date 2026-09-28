# รายงานทดสอบ RAG Workshop — 23 กันยายน 2026

เป้าหมาย: https://rag-project-2026.vercel.app
สภาพแวดล้อม: Next.js บน Vercel → HTTPS ngrok → Docker API/worker/Postgres/Redis/โมเดลบนเครื่อง

## ผลรวม

- API regression: **317 passed** ใน 137.68 วินาที ใช้ฐานข้อมูล `_test` แยกและ Redis database 15
- Frontend: **17 passed**; format, ESLint, TypeScript และการตรวจคู่สี contrast ทั้ง light/dark ผ่าน
- Production audit: **22 กรณีผ่าน** (รวม cleanup 2 กรณี) ไม่มี uncaught page errors ในหน้าที่เก็บผล
- Format audit: **5 กรณีผ่าน** ได้แก่ PDF, PNG OCR, search empty state และ cleanup เอกสาร 2 รายการ
- ไม่พบข้อผิดพลาดที่ทำให้กรณีทดสอบเหล่านี้ล้มเหลว ไม่ได้หมายความว่าทุกพฤติกรรมที่เป็นไปได้ไม่มีบั๊ก

## ตรวจผ่านเว็บจริง

| ส่วน | วิธีตรวจ / ผล |
|---|---|
| ผู้ไม่ล็อกอิน | protected APIs ตอบ 401 |
| Login | ฟอร์มว่างส่งไม่ได้; ล็อกอิน user และ admin ผ่าน browser ได้ |
| Session | พบ cookie Secure + HttpOnly; logout แล้ว /me ตอบ 401 |
| รหัสผ่านผิด | ตอบ 401 |
| ธีมและ responsive | หน้า Login ที่ 320/390/768/1440px สลับธีมและจำค่าหลัง reload; ปุ่มไม่ทับหัวข้อ |
| หน้าผู้ใช้ | documents, chat, status เปิดที่ 390/1440px; ไม่มี page-level horizontal overflow |
| หน้าแอดมิน | documents, chat, status, users, analytics, playground เปิดที่ 390/1440px; ไม่พบ API 5xx ระหว่างช่วงโหลดที่ตรวจ |
| สิทธิ์แอดมิน | user เปิด users/analytics/playground แล้วถูกส่งกลับ documents; API users ตอบ 403 |
| จัดการบัญชี | สร้างและระงับบัญชีสมมติผ่าน API ได้; ลบทิ้งหลังทดสอบ ไม่แก้บัญชีเดิม |
| Markdown | เลือกไฟล์และอัปโหลดผ่าน UI → ready → Playground ค้นคืนเอกสารที่สร้างได้ |
| PDF | สร้าง PDF ที่มี text layer; upload ผ่าน API → ready → ค้นคืนยอด 150 ได้; รวมประมาณ 6 วินาที; ไม่ใช้ OCR |
| PNG OCR | สร้างภาพใบรายการสมมติ; upload ผ่าน API → OCR 1 หน้า → ready → ค้นคืนยอด 150 ได้; รวมประมาณ 25 วินาที |
| ค้นหาเอกสาร | คำที่ไม่ตรงกับเอกสารให้รายการว่าง |
| Playground | เรียก retrieval โดยปิด LLM และพบ fixture ที่อัปโหลด |
| แชต | ส่งคำถามใหม่ผ่าน production API; ได้ SSE session/citations/token/done ไม่มี error event; อ่านประวัติ session กลับได้ |
| สุขภาพระบบ | /health/deep ตอบ 200; postgres, redis, llm, ocr, embeddings เป็น ok |

## ข้อมูลทดสอบและหลักฐาน

ลบ Markdown, PDF, PNG และบัญชีชั่วคราวที่สร้างในรอบนี้สำเร็จแล้ว ประวัติแชตทดสอบใหม่ยังอยู่ในบัญชี Demo เพื่อดูผลย้อนหลัง รายงานไม่เก็บรหัสผ่าน token หรือ cookie

- `output/playwright/detailed-1790143909272/report.json`
- `output/playwright/detailed-1790143909272/*.png`
- `output/playwright/format-audit.json`
- สคริปต์ทำซ้ำ: `scripts/detailed-web-audit.cjs`, `scripts/format-web-audit.cjs`

## ขอบเขตและสิ่งที่ยังต้องวัดเพิ่มเติม

- Browser เป็น Microsoft Edge/Chromium จำลอง viewport ไม่ใช่อุปกรณ์ iOS Safari หรือ Android จริง
- แชตตอบสำเร็จ แต่ครั้งนี้ไม่ได้จับเวลา first token หรือช่องว่างระหว่าง tokens; ไม่ใช้ผลนี้ยืนยันว่า latency หรือการส่งทีละ token ผ่าน proxy สมบูรณ์
- ไม่ได้ load test ผู้ใช้พร้อมกัน, ทดสอบไฟล์ 500 หน้า/วันจริง หรือประเมิน OCR ภาษาไทยจากสแกนคุณภาพต่ำ
- การเปิดหน้า UI ครบไม่ได้เท่ากับคลิกทุกปุ่ม: bulk/reprocess, prompt activation, feedback, reset password และ edge cases อื่นตรวจใน regression suite ตามกรณีที่มี ไม่ได้เปลี่ยนค่าจริงทั้งหมดบน production
- Embeddable widget บนเว็บไซต์ภายนอก, การกู้ backup และ retention ตามเวลาจริง 90 วันไม่ได้ทดสอบ end-to-end รอบนี้
- Demo ยังพึ่งเครื่อง Docker/ngrok เปิดอยู่ และต้องอัปเดต Vercel หาก tunnel URL เปลี่ยน