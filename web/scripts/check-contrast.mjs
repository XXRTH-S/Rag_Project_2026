/**
 * ตรวจความต่างของสีตามสูตร WCAG โดยอ่านค่าจริงจาก globals.css
 *
 * ทำไมต้องมี: ตอนยกเครื่อง UI มีการตรวจว่าทุกหน้าไม่ล้นจอและปุ่มมี label ครบ
 * แต่ไม่มีใครวัดความต่างของสี ผลคือขอบของช่องกรอกอยู่ที่ 1.43:1 ซึ่งแทบมองไม่เห็น
 * ว่าช่องเริ่มตรงไหน และตัวอักษรรองบนแถบนำทางอยู่ที่ 3.87:1 ซึ่งต่ำกว่าเกณฑ์
 *
 * ตรวจด้วยตาไม่ได้ผล เพราะคนที่ออกแบบมองเห็นชัดอยู่แล้ว
 *
 *   node scripts/check-contrast.mjs
 *
 * ออกด้วยรหัส 1 เมื่อมีคู่ไหนตก เพื่อให้ CI จับได้
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const css = readFileSync(join(here, "..", "src", "app", "globals.css"), "utf8");

/** อ่าน token จากบล็อกที่ selector ตรงกับ needle */
function tokensFrom(needle) {
  const start = css.indexOf(needle);
  if (start === -1) throw new Error(`หาบล็อก ${needle} ไม่เจอใน globals.css`);
  const open = css.indexOf("{", start);
  const end = css.indexOf("\n  }", open) > -1 ? css.indexOf("\n  }", open) : css.indexOf("\n}", open);
  const body = css.slice(open, end);
  const out = {};
  for (const m of body.matchAll(/--([\w-]+):\s*(#[0-9a-fA-F]{3,8})/g)) out[m[1]] = m[2];
  return out;
}

const light = tokensFrom(":root {");
const dark = tokensFrom(':root[data-theme="dark"]');

function luminance(hex) {
  const h = hex.replace("#", "").slice(0, 6);
  const rgb = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
  const lin = rgb.map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2];
}

function ratio(a, b) {
  const [x, y] = [luminance(a), luminance(b)];
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
}

/**
 * คู่ที่ต้องตรวจ — [ตัวหน้า, ตัวหลัง, เกณฑ์, คำอธิบาย]
 *
 * 4.5 = ตัวอักษรปกติ (WCAG AA 1.4.3)
 * 3.0 = ขอบและองค์ประกอบ UI (WCAG AA 1.4.11) และตัวอักษรขนาดใหญ่
 */
const PAIRS = [
  ["fg", "bg", 4.5, "ตัวอักษรหลักบนพื้นหลัง"],
  ["fg", "card", 4.5, "ตัวอักษรหลักบนการ์ด"],
  ["fg", "raised", 4.5, "ตัวอักษรหลักบนพื้นยก"],
  ["fg", "sunken", 4.5, "ตัวอักษรหลักบนแถบนำทาง"],
  ["muted", "bg", 4.5, "ตัวอักษรรองบนพื้นหลัง"],
  ["muted", "card", 4.5, "ตัวอักษรรองบนการ์ด"],
  ["muted", "sunken", 4.5, "ตัวอักษรรองบนแถบนำทาง"],
  ["muted", "th-bg", 4.5, "หัวตาราง"],
  ["placeholder", "bg", 4.5, "ข้อความตัวอย่างในช่องกรอก"],
  ["accent-fg", "accent", 4.5, "ตัวอักษรบนปุ่มหลัก"],
  ["on-accent-muted", "accent", 4.5, "ตัวอักษรรองบนพื้น accent"],
  ["accent", "bg", 4.5, "ลิงก์และ eyebrow บนพื้นหลัง"],
  ["ok", "ok-bg", 4.5, "ป้ายสถานะสำเร็จ"],
  ["warn", "warn-bg", 4.5, "ป้ายสถานะเตือน"],
  ["fail", "fail-bg", 4.5, "ป้ายสถานะล้มเหลว"],
  ["border-strong", "bg", 3.0, "ขอบช่องกรอกบนพื้นหลัง"],
  ["border-strong", "card", 3.0, "ขอบช่องกรอกบนการ์ด"],
  ["active-dot", "accent", 3.0, "จุดบอกเมนูที่เลือกอยู่"],
  ["focus", "bg", 3.0, "วงแหวนตอน focus"],
  ["focus", "card", 3.0, "วงแหวนตอน focus บนการ์ด"],
];

let failed = 0;
for (const [name, tokens] of [
  ["สว่าง", light],
  ["มืด", dark],
]) {
  console.log(`\n=== โหมด${name} ===`);
  for (const [fg, bg, need, label] of PAIRS) {
    if (!tokens[fg] || !tokens[bg]) {
      console.log(`  ?     ${label} — ไม่มี token --${tokens[fg] ? bg : fg}`);
      failed++;
      continue;
    }
    const r = ratio(tokens[fg], tokens[bg]);
    const ok = r >= need;
    if (!ok) failed++;
    console.log(
      `  ${ok ? "ผ่าน" : "ตก  "}  ${r.toFixed(2).padStart(5)} / ${need.toFixed(1)}  ${label} (--${fg} บน --${bg})`,
    );
  }
}

// โหมดมืดสองบล็อก (prefers-color-scheme กับ data-theme) ต้องมีค่าตรงกันเสมอ
// ไม่งั้นการสลับโหมดเองจะได้สีคนละชุดกับที่ระบบเลือกให้
const media = tokensFrom(':root:not([data-theme="light"])');
for (const key of new Set([...Object.keys(dark), ...Object.keys(media)])) {
  if (dark[key] !== media[key]) {
    console.log(`\nตก    --${key} ไม่ตรงกันระหว่างสองบล็อกของโหมดมืด: ${media[key]} vs ${dark[key]}`);
    failed++;
  }
}

// ทุกสีต้องมาจาก token — ถ้ามีกฎไหนเขียน hex ตรง ๆ กฎนั้นจะค้างสว่างในโหมดมืด
const rulesOnly = css.slice(css.indexOf("\n}", css.indexOf(":root {")));
const strayHex = [
  ...rulesOnly
    .replace(/:root[^{]*\{[^}]*\}/g, "")
    .replace(/url\("[^"]*"\)/g, "")
    .matchAll(/#[0-9a-fA-F]{3,8}\b/g),
];
if (strayHex.length) {
  console.log(`\nตก    มีสีที่เขียนตรง ๆ นอก :root ${strayHex.length} จุด: ${strayHex.slice(0, 5).map((m) => m[0]).join(", ")}`);
  failed += strayHex.length;
}

console.log(failed === 0 ? "\nผ่านทุกคู่" : `\nตก ${failed} รายการ`);
process.exit(failed === 0 ? 0 : 1);
