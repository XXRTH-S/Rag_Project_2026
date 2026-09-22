"use client";
import { usePathname } from "next/navigation";
import { Icon } from "./Icon";
const pages: Record<string, [string, string, string]> = {
  documents: [
    "คลังความรู้",
    "จัดการเอกสาร",
    "รวบรวมเอกสารของคุณ แล้วเปลี่ยนข้อมูลให้เป็นคำตอบที่ค้นหาได้",
  ],
  chat: [
    "ผู้ช่วยค้นความรู้",
    "ทุกคำถาม เริ่มจากความรู้ของคุณ",
    "ถาม สรุป และค้นหาคำตอบจากเอกสารในคลัง",
  ],
  playground: [
    "พื้นที่ทดลอง",
    "ปรับคำตอบให้ตรงใจ",
    "ทดลองคำถาม ตรวจแหล่งข้อมูล และปรับคำสั่งของผู้ช่วยในที่เดียว",
  ],
  analytics: [
    "ภาพรวมการใช้งาน",
    "เข้าใจการเติบโตของคลังความรู้",
    "ติดตามคำถาม คุณภาพคำตอบ และข้อมูลที่ควรเพิ่มเติม",
  ],
  users: [
    "จัดการทีม",
    "พื้นที่ความรู้สำหรับทุกคนในทีม",
    "สร้างบัญชี กำหนดสิทธิ์ และดูการใช้โควตาของสมาชิก",
  ],
  status: ["สถานะบริการ", "ดูแลให้ทุกส่วนพร้อมทำงาน", "ตรวจสอบบริการเบื้องหลังและความพร้อมของระบบ"],
};
export function PageIntro() {
  const key = usePathname().split("/")[1];
  const info = pages[key];
  if (!info) return null;
  return (
    <header className="page-intro">
      <div>
        <div className="eyebrow">
          <Icon name={key} />
          {info[0]}
        </div>
        <h1>{info[1]}</h1>
        <p>{info[2]}</p>
      </div>
      <span className="intro-mark">
        <Icon name={key} size={58} />
      </span>
    </header>
  );
}
