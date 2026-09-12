import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "RAG Workshop",
  description: "ระบบ RAG chatbot พร้อม ingestion + OCR",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="th">
      <body>{children}</body>
    </html>
  );
}
