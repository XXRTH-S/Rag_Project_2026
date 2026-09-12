/** ตรรกะเกี่ยวกับการอ้างอิงที่มาของคำตอบ
 *
 * แยกออกมาจากหน้าแชทเพราะเป็นตรรกะล้วน ๆ ไม่ผูกกับ React
 * ทำให้เทสได้โดยไม่ต้อง render component และไม่ต้องมี DOM
 */

export type Citation = {
  rank: number;
  document_id: string | null;
  /** null ได้เมื่อ chunk ต้นทางถูกลบก่อนที่ระบบจะเริ่มเก็บชื่อเอกสารไว้ในแถวอ้างอิง */
  document_name: string | null;
  page_no: number | null;
  score: number;
};

export function citationLabel(c: Citation): string {
  // ชื่อว่างเกิดได้กับข้อความเก่าที่ chunk หายไปก่อนระบบจะเริ่มเก็บชื่อไว้ในแถวอ้างอิง
  // บอกตามจริงว่าหาย ดีกว่าโชว์บรรทัดเปล่าให้ผู้ใช้เดาเอง
  const name = c.document_name ?? "เอกสารถูกลบแล้ว";
  const page = c.page_no ? ` หน้า ${c.page_no}` : "";
  return `[${c.rank}] ${name}${page} · คะแนน ${c.score.toFixed(3)}`;
}

/** ตัดเลขอ้างอิง [1] [2] ออกจากคำตอบ สำหรับคนที่ไม่ได้เห็นรายการที่มา
 *
 * ถ้าซ่อนรายการแต่ปล่อยเลขไว้ ผู้ใช้จะเห็น "…สิบวันทำการครับ [1]" โดยที่ [1]
 * ไม่ได้ชี้ไปไหนเลย ซึ่งดูเหมือนระบบแสดงผลพัง มากกว่าจะดูเป็นการอ้างอิง
 *
 * ตัดเฉพาะเลขที่อยู่ในช่วงของที่มาจริง เพราะวงเล็บเหลี่ยมในเนื้อความก็มีได้
 * ("ประกาศข้อ [3] ระบุว่า…" ที่ OCR อ่านมาจากเอกสาร) ถ้าตัดทุกตัวเลขในวงเล็บ
 * ข้อความของเอกสารจะหายไปด้วยโดยที่ไม่มีใครรู้
 *
 * กฎสุดท้ายตัดวงเล็บที่ยังพิมพ์ไม่จบ ("[" หรือ "[1") ที่ท้ายสุดระหว่างสตรีม
 * ไม่งั้นจะเห็นเลขโผล่แล้วหายวับทุกครั้งที่ token ใหม่มาถึง
 */
export function stripCitationMarkers(text: string, citationCount: number): string {
  if (citationCount < 1) return text;
  return text
    .replace(/\s*\[(\d+)\]/g, (match, digits: string) => {
      const rank = Number(digits);
      return rank >= 1 && rank <= citationCount ? "" : match;
    })
    .replace(/\s*\[\d*$/, "")
    .trimEnd();
}
