import { describe, expect, it } from "vitest";

import { citationLabel, stripCitationMarkers, type Citation } from "./citations";

function hit(overrides: Partial<Citation> = {}): Citation {
  return {
    rank: 1,
    document_id: "doc-1",
    document_name: "คู่มือพนักงาน.pdf",
    page_no: 3,
    score: 0.7550162751987229,
    ...overrides,
  };
}

describe("citationLabel", () => {
  it("แสดงลำดับ ชื่อเอกสาร เลขหน้า และคะแนน", () => {
    expect(citationLabel(hit())).toBe("[1] คู่มือพนักงาน.pdf หน้า 3 · คะแนน 0.755");
  });

  it("ไม่โชว์เลขหน้าเมื่อไม่มีข้อมูลหน้า", () => {
    expect(citationLabel(hit({ page_no: null }))).toBe("[1] คู่มือพนักงาน.pdf · คะแนน 0.755");
  });

  it("บอกตรง ๆ ว่าเอกสารถูกลบ แทนที่จะโชว์บรรทัดเปล่า", () => {
    // เกิดกับข้อความเก่าที่ chunk หายไปก่อนระบบจะเริ่มเก็บชื่อไว้ในแถวอ้างอิง
    expect(citationLabel(hit({ document_name: null }))).toContain("เอกสารถูกลบแล้ว");
  });
});

describe("stripCitationMarkers", () => {
  it("ตัดเลขอ้างอิงท้ายประโยคออก", () => {
    expect(stripCitationMarkers("ลาพักร้อนได้ปีละสิบวันทำการครับ [1]", 5)).toBe(
      "ลาพักร้อนได้ปีละสิบวันทำการครับ",
    );
  });

  it("ตัดได้หลายตัวในประโยคเดียว", () => {
    expect(stripCitationMarkers("ต้องยื่นใบเสร็จภายใน 30 วันครับ [1] [2]", 5)).toBe(
      "ต้องยื่นใบเสร็จภายใน 30 วันครับ",
    );
  });

  it("ไม่กินเครื่องหมายวรรคตอนที่ตามหลัง", () => {
    expect(stripCitationMarkers("The per-diem is 2,000 Baht [1].", 5)).toBe(
      "The per-diem is 2,000 Baht.",
    );
  });

  it("ไม่แตะเลขในวงเล็บที่เกินจำนวนที่มาจริง", () => {
    // "ประกาศข้อ [7]" เป็นเนื้อความจากเอกสาร ไม่ใช่การอ้างอิง
    // ถ้าตัดทุกตัวเลขในวงเล็บ ข้อความของเอกสารจะหายไปโดยไม่มีใครรู้
    expect(stripCitationMarkers("ประกาศข้อ [7] ระบุว่าห้ามลา [1]", 5)).toBe(
      "ประกาศข้อ [7] ระบุว่าห้ามลา",
    );
  });

  it("ไม่แตะอะไรเลยเมื่อไม่มีที่มา", () => {
    const text = "ประกาศข้อ [3] ระบุว่าห้ามลาเกินสามวัน";
    expect(stripCitationMarkers(text, 0)).toBe(text);
  });

  it("ซ่อนวงเล็บที่ยังพิมพ์ไม่จบระหว่างสตรีม", () => {
    // ไม่งั้นผู้ใช้จะเห็นเลขโผล่แล้วหายวับทุกครั้งที่ token ใหม่มาถึง
    expect(stripCitationMarkers("กำลังพิมพ์ครับ [", 5)).toBe("กำลังพิมพ์ครับ");
    expect(stripCitationMarkers("กำลังพิมพ์ครับ [1", 5)).toBe("กำลังพิมพ์ครับ");
  });

  it("ปล่อยคำตอบที่ไม่มีเลขอ้างอิงไว้เหมือนเดิม", () => {
    const text = "ไม่พบข้อมูลนี้ในเอกสารที่มีอยู่ครับ";
    expect(stripCitationMarkers(text, 5)).toBe(text);
  });
});
