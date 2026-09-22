// เก็บภาพหน้าจอทุกหน้า ทั้งโหมดสว่างและมืด
//
// ทำไมต้องมี: การตรวจ UI ด้วยตาไม่ผ่านเสมอ เพราะคนที่แก้เพิ่งเห็นหน้าจอนั้นมา
// การมีภาพชุดเดิมทุกครั้งทำให้เทียบก่อน/หลังได้จริง และจับกรณีที่โหมดมืด
// มีจุดสีสว่างค้างอยู่ซึ่งมองข้ามได้ง่ายมากถ้าไม่ได้เปิดดูทุกหน้า
//
//   $env:PLAYWRIGHT_MODULE = "<พาธของ playwright>"
//   node scripts/ui-screenshots.cjs
//
// อ่านรหัสผ่านจาก .env ในหน่วยความจำเท่านั้น ไม่พิมพ์ออกและไม่เขียนลงไฟล์
const fs = require("fs");
const path = require("path");
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");

const root = path.resolve(__dirname, "..");
const env = Object.fromEntries(
  fs
    .readFileSync(path.join(root, ".env"), "utf8")
    .split(/\r?\n/)
    .filter((l) => /^[A-Z0-9_]+=/.test(l))
    .map((l) => {
      const i = l.indexOf("=");
      return [l.slice(0, i), l.slice(i + 1).replace(/^"|"$/g, "")];
    }),
);

const base = process.env.UI_SHOT_URL || "http://localhost";
const out = path.join(root, "artifacts", process.env.UI_SHOT_DIR || "ui-both-modes");

// admin เห็นทุกหน้า จึงถ่ายได้ครบในรอบเดียว
const EMAIL = env.ADMIN_EMAIL;
const PASSWORD = env.ADMIN_PASSWORD;

const PAGES = ["/documents", "/chat", "/playground", "/analytics", "/users", "/status"];
const MODES = ["light", "dark"];
const WIDE = { width: 1440, height: 900 };
const NARROW = { width: 390, height: 844 };

(async () => {
  if (!EMAIL || !PASSWORD) throw new Error("ต้องมี ADMIN_EMAIL และ ADMIN_PASSWORD ใน .env");
  fs.mkdirSync(out, { recursive: true });

  const browser = await chromium.launch({ headless: true, channel: "msedge" });
  const errors = [];
  const taken = [];

  try {
    for (const mode of MODES) {
      for (const viewport of [WIDE, NARROW]) {
        const ctx = await browser.newContext({ viewport });
        // ตั้งโหมดก่อนสคริปต์ของหน้าทำงาน ไม่งั้นจะติดภาพตอนกำลังสลับ
        await ctx.addInitScript((m) => {
          try {
            localStorage.setItem("rag-theme", m);
          } catch (e) {}
        }, mode);

        const page = await ctx.newPage();
        page.on("pageerror", (e) => errors.push(`${mode} ${viewport.width}: ${e.message}`));

        const tag = `${mode}-${viewport.width}`;
        await page.goto(base + "/login");
        await page.waitForLoadState("networkidle");
        await page.screenshot({ path: path.join(out, `login-${tag}.png`), fullPage: true });
        taken.push(`login-${tag}`);

        await page.locator("#email").fill(EMAIL);
        await page.locator("#password").fill(PASSWORD);
        await page.locator("button[type=submit]").click();
        await page.waitForURL("**/documents");

        for (const route of PAGES) {
          await page.goto(base + route);
          await page.waitForLoadState("networkidle");
          // หน้าที่ยังโหลดข้อมูลอยู่จะได้ภาพเป็นโครงเปล่า รอให้เนื้อหาโผล่ก่อน
          await page.waitForTimeout(700);
          const name = `${route.slice(1)}-${tag}`;
          await page.screenshot({ path: path.join(out, `${name}.png`), fullPage: true });
          taken.push(name);
        }
        await ctx.close();
      }
    }
  } finally {
    await browser.close();
  }

  console.log(JSON.stringify({ directory: out, count: taken.length, errors }, null, 2));
  if (errors.length) process.exit(1);
})().catch((e) => {
  console.error(e.message);
  process.exit(1);
});
