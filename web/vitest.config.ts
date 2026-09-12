import { defineConfig } from "vitest/config";
import { fileURLToPath } from "node:url";

export default defineConfig({
  resolve: {
    // ให้ alias "@/" ตรงกับที่ตั้งไว้ใน tsconfig.json ไม่งั้น import ในเทสจะหาไฟล์ไม่เจอ
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  test: {
    // ทดสอบตรรกะล้วน ๆ ยังไม่ต้องมี DOM — เพิ่ม environment: "jsdom" เมื่อเริ่มเทส component
    environment: "node",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
  },
});
