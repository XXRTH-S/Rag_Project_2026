"""เทสการเดาชนิดไฟล์จากเนื้อหา

เจอจริงตอนอัปคู่มือสอนเขียนโปรแกรม: ไฟล์ .md ที่ยกตัวอย่างโค้ด C หรือ Java
ถูก libmagic ตอบเป็น text/x-c หรือ text/x-java แล้วระบบปฏิเสธว่า "ยังไม่รองรับ"
ทั้งที่เป็นข้อความล้วนที่อ่านได้ตามปกติ
"""
from app.quota.page_count import TEXT_MIMES
from app.routers.documents import _detect_mime

C_DOCUMENT = """# ภาษา C เบื้องต้น

## โครงสร้างโปรแกรม

```c
#include <stdio.h>

int main(void) {
    printf("สวัสดี\\n");
    return 0;
}
```
"""

JAVA_DOCUMENT = """# Java เบื้องต้น

```java
public class HelloWorld {
    public static void main(String[] args) {
        System.out.println("สวัสดี");
    }
}
```
"""


def _detect(text: str, filename: str) -> str:
    return _detect_mime(text.encode("utf-8")[:4096], filename)


def test_markdown_quoting_c_code_is_still_accepted() -> None:
    mime = _detect(C_DOCUMENT, "c-เบื้องต้น.md")
    assert mime in TEXT_MIMES, f"ได้ {mime} ซึ่งไม่อยู่ในรายการที่รองรับ"


def test_markdown_quoting_java_code_is_still_accepted() -> None:
    mime = _detect(JAVA_DOCUMENT, "java-เบื้องต้น.md")
    assert mime in TEXT_MIMES, f"ได้ {mime} ซึ่งไม่อยู่ในรายการที่รองรับ"


def test_markdown_extension_normalises_to_one_type() -> None:
    """ไฟล์ .md ต้องได้ชนิดเดียวกันเสมอ ไม่ขึ้นกับว่าข้างในยกตัวอย่างภาษาอะไร
    ไม่งั้นเอกสารชุดเดียวกันจะถูกเก็บเป็นคนละชนิดโดยไม่มีเหตุผล
    """
    plain = _detect("# หัวข้อ\n\nเนื้อหาภาษาไทยล้วน ไม่มีโค้ดเลย\n", "ธรรมดา.md")
    assert plain == _detect(C_DOCUMENT, "c-เบื้องต้น.md") == "text/markdown"


def test_plain_text_without_md_extension_stays_plain() -> None:
    assert _detect("ระเบียบการลาของพนักงาน\nลาพักร้อนปีละสิบวัน\n", "hr.txt") == "text/plain"


def test_html_keeps_its_own_type() -> None:
    """html ต้องไม่ถูกยุบเป็น text/plain เพราะ extract_text ถอดแท็กให้ต่างหาก
    ถ้ายุบทิ้ง ผู้ใช้จะได้แท็ก html ปนเข้าไปใน chunk
    """
    html = "<html><head><title>ทดสอบ</title></head><body><p>เนื้อหา</p></body></html>"
    assert _detect(html, "page.html") == "text/html"


def test_binary_is_never_mistaken_for_text() -> None:
    """เหตุผลเดิมของการเชื่อเนื้อไฟล์คือกันคนเปลี่ยนนามสกุลไฟล์ไบนารีเป็น .md
    การยุบชนิดย่อยของข้อความต้องไม่ทำให้คุณสมบัตินี้หายไป
    """
    # ไม่สนว่า libmagic จะตอบชนิดไหน ขอแค่ต้องไม่ใช่ text/* เพราะ text/*
    # คือประตูที่ผ่านรายการอนุญาตเข้าไปได้
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    assert not _detect_mime(png, "แอบเปลี่ยนนามสกุล.md").startswith("text/")

    zeros = bytes(64)
    assert not _detect_mime(zeros, "ปลอม.md").startswith("text/")
