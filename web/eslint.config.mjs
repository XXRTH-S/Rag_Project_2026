import coreWebVitals from "eslint-config-next/core-web-vitals";
import nextTypescript from "eslint-config-next/typescript";

// Next 16 ตัดคำสั่ง `next lint` ออกแล้ว ต้องเรียก eslint ตรง ๆ
// eslint-config-next 16 ส่งออกเป็น flat config array มาให้เลย จึง spread ได้ตรง ๆ
// ไม่ต้องผ่าน FlatCompat (ซึ่งพังด้วย "Converting circular structure to JSON")
export default [
  {
    // ของที่เครื่องสร้างเอง ไม่ใช่โค้ดที่เราเขียน
    ignores: [".next/**", "node_modules/**", "next-env.d.ts", "public/**"],
  },
  ...coreWebVitals,
  ...nextTypescript,
  {
    rules: {
      // ตัวแปรที่ขึ้นต้นด้วย _ คือการบอกว่า "รู้ว่าไม่ได้ใช้ ตั้งใจ"
      // เช่นพารามิเตอร์ที่ต้องรับมาเพื่อให้ signature ตรงแต่ไม่ได้ใช้จริง
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],

      // ปิดเพราะให้ false positive กับทุกหน้าในโปรเจกต์นี้
      //
      // กฎนี้เตือนเรื่อง setState ที่ถูกเรียก **แบบ synchronous** ในตัว effect
      // ซึ่งทำให้ render ซ้อนกันเป็นทอด ๆ · แต่ทั้ง 5 จุดที่มันจับได้เป็นการ
      // โหลดข้อมูลตอน mount ผ่านฟังก์ชัน async — setState เกิดหลัง await
      // คือคนละ microtask ไม่ใช่ระหว่างที่ effect กำลังทำงาน
      //
      // ตรวจแล้วทีละจุด (analytics, chat, documents, playground, users)
      // ไม่มีที่ไหนเรียก setState แบบ synchronous จริง และการเขียนเป็น
      // async IIFE พร้อมธงยกเลิกก็ยังโดนจับอยู่ดี
      //
      // เปิดกลับเมื่อไหร่: ถ้าย้ายไปใช้ไลบรารีโหลดข้อมูล (react-query หรือ
      // Server Component) แล้วไม่เหลือ pattern โหลดตอน mount ด้วย useEffect
      "react-hooks/set-state-in-effect": "off",
    },
  },
];
