import type { Metadata } from "next";
import localFont from "next/font/local";
import "./globals.css";
const thaiFont = localFont({
  src: [
    { path: "../../public/fonts/noto-sans-thai-0.ttf", weight: "400", style: "normal" },
    { path: "../../public/fonts/noto-sans-thai-1.ttf", weight: "500", style: "normal" },
    { path: "../../public/fonts/noto-sans-thai-2.ttf", weight: "600", style: "normal" },
    { path: "../../public/fonts/noto-sans-thai-3.ttf", weight: "700", style: "normal" },
  ],
  variable: "--font-thai",
  display: "swap",
});

export const metadata: Metadata = {
  title: "RAG Workshop",
  description: "ระบบ RAG chatbot พร้อม ingestion + OCR",
};

// ต้องทำงานก่อนวาดหน้าแรก ไม่งั้นคนที่เลือกโหมดมืดไว้จะเห็นหน้าสว่างวาบหนึ่งเฟรม
// ก่อนจะสลับ · อยู่ใน <head> แบบ blocking โดยตั้งใจ สคริปต์สั้นพอที่จะไม่หน่วงอะไร
//
// ไม่แตะอะไรเลยเมื่อยังไม่เคยเลือก — CSS จะใช้ prefers-color-scheme ตามเครื่องเอง
const THEME_BOOTSTRAP = `try{var t=localStorage.getItem("rag-theme");if(t==="dark"||t==="light")document.documentElement.dataset.theme=t}catch(e){}`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="th" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOTSTRAP }} />
      </head>
      <body className={thaiFont.variable}>{children}</body>
    </html>
  );
}
