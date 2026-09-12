# Python เบื้องต้น

## ภาพรวมของภาษา Python

Python เป็นภาษาที่อ่านง่ายและใช้การย่อหน้าแทนวงเล็บปีกกาในการบอกขอบเขตของบล็อกคำสั่ง จึงบังคับให้โค้ดจัดรูปแบบเป็นระเบียบโดยอัตโนมัติ นิยมใช้กับงานวิเคราะห์ข้อมูล ปัญญาประดิษฐ์ งานเว็บฝั่งเซิร์ฟเวอร์ และสคริปต์อัตโนมัติ

Python เป็นภาษาแบบ dynamic typing คือไม่ต้องประกาศชนิดข้อมูลของตัวแปรล่วงหน้า ตัวแปลภาษาจะรู้ชนิดตอนที่โปรแกรมทำงาน

## ตัวแปรและชนิดข้อมูลใน Python

ประกาศตัวแปรได้ทันทีโดยกำหนดค่าให้ ไม่ต้องระบุชนิด

```python
name = "สมชาย"
age = 30
height = 172.5
is_active = True
nothing = None
```

ตรวจชนิดข้อมูลด้วย `type()` และแปลงชนิดด้วย `int()`, `float()`, `str()` ตัวแปรเดียวกันเปลี่ยนไปเก็บค่าคนละชนิดได้ ซึ่งสะดวกแต่ก็เป็นที่มาของบั๊กที่หายาก

## การรับค่าและแสดงผลใน Python

แสดงผลด้วย `print()` และรับค่าจากผู้ใช้ด้วย `input()` ซึ่งคืนค่าเป็นข้อความเสมอ ถ้าต้องการตัวเลขต้องแปลงเอง

```python
name = input("ชื่ออะไร: ")
age = int(input("อายุเท่าไร: "))
print(f"สวัสดีคุณ {name} อายุ {age} ปี")
```

ข้อความที่ขึ้นต้นด้วย `f` เรียกว่า f-string ใช้แทรกค่าตัวแปรลงในข้อความได้โดยตรง เป็นวิธีที่อ่านง่ายที่สุดใน Python รุ่นใหม่

## เงื่อนไขใน Python

ใช้ `if` `elif` และ `else` โดยจบบรรทัดเงื่อนไขด้วยเครื่องหมายทวิภาคแล้วย่อหน้าเนื้อในเข้าไป

```python
score = 75

if score >= 80:
    grade = "A"
elif score >= 70:
    grade = "B"
else:
    grade = "C"

print(grade)
```

Python ถือว่าค่าที่ "ว่าง" เป็นเท็จโดยปริยาย ได้แก่ 0, ข้อความว่าง, ลิสต์ว่าง และ None จึงเขียน `if items:` แทน `if len(items) > 0:` ได้

## การวนซ้ำใน Python

`for` ใช้วนบนลำดับข้อมูล ส่วน `while` วนจนกว่าเงื่อนไขจะเป็นเท็จ

```python
for fruit in ["แอปเปิล", "กล้วย", "ส้ม"]:
    print(fruit)

for i in range(1, 6):
    print(i)

count = 3
while count > 0:
    print(count)
    count -= 1
```

`range(1, 6)` ให้ค่า 1 ถึง 5 ไม่รวม 6 เพราะ Python นับแบบรวมค่าเริ่มต้นแต่ไม่รวมค่าสุดท้าย ใช้ `break` เพื่อออกจากลูปทันที และ `continue` เพื่อข้ามไปรอบถัดไป

## ฟังก์ชันใน Python

ประกาศด้วยคำสั่ง `def` และคืนค่าด้วย `return` ถ้าไม่เขียน `return` ฟังก์ชันจะคืนค่า None

```python
def calculate_total(price, quantity, discount=0):
    total = price * quantity
    return total - discount

print(calculate_total(100, 3))
print(calculate_total(100, 3, discount=50))
```

พารามิเตอร์ที่กำหนดค่าเริ่มต้นไว้จะเป็นค่าที่ใช้เมื่อผู้เรียกไม่ส่งมา และต้องวางไว้ท้ายรายการพารามิเตอร์เสมอ

## ลิสต์และดิกชันนารีใน Python

ลิสต์เก็บค่าเรียงตามลำดับและแก้ไขได้ ส่วนดิกชันนารีเก็บคู่คีย์กับค่า

```python
fruits = ["แอปเปิล", "กล้วย"]
fruits.append("ส้ม")
print(fruits[0])
print(len(fruits))

person = {"name": "สมชาย", "age": 30}
person["email"] = "somchai@example.com"
print(person["name"])
print(person.get("phone", "ไม่ระบุ"))
```

`person["phone"]` ที่ไม่มีคีย์นั้นจะเกิดข้อผิดพลาด KeyError ส่วน `person.get("phone", "ไม่ระบุ")` คืนค่าสำรองแทน จึงปลอดภัยกว่าเมื่อไม่แน่ใจว่ามีคีย์อยู่

## List comprehension ใน Python

เป็นวิธีเขียนลูปสร้างลิสต์ให้สั้นลงในบรรทัดเดียว

```python
numbers = [1, 2, 3, 4, 5, 6]
squares = [n * n for n in numbers]
evens = [n for n in numbers if n % 2 == 0]
```

อ่านง่ายเมื่อเงื่อนไขไม่ซับซ้อน แต่ถ้าต้องซ้อนหลายชั้นควรกลับไปเขียนเป็นลูปธรรมดาเพื่อให้คนอ่านตามทัน

## การจัดการข้อผิดพลาดใน Python

ครอบคำสั่งที่อาจพังไว้ใน `try` แล้วดักด้วย `except`

```python
try:
    value = int(input("ใส่ตัวเลข: "))
    result = 100 / value
except ValueError:
    print("กรุณาใส่ตัวเลขเท่านั้น")
except ZeroDivisionError:
    print("หารด้วยศูนย์ไม่ได้")
else:
    print(result)
finally:
    print("จบการทำงาน")
```

ควรดักข้อผิดพลาดเฉพาะชนิดที่คาดไว้ การเขียน `except:` เปล่า ๆ จะกลืนข้อผิดพลาดทุกชนิดรวมถึงบั๊กที่เราควรได้เห็น

## การอ่านเขียนไฟล์ใน Python

ใช้ `with open()` ซึ่งปิดไฟล์ให้เองแม้เกิดข้อผิดพลาดกลางทาง

```python
with open("data.txt", "w", encoding="utf-8") as f:
    f.write("บรรทัดแรก\n")

with open("data.txt", "r", encoding="utf-8") as f:
    for line in f:
        print(line.strip())
```

ไฟล์ภาษาไทยต้องระบุ `encoding="utf-8"` เสมอ เพราะค่าปริยายบนวินโดวส์ไม่ใช่ UTF-8 และจะทำให้อ่านได้เป็นตัวอักษรเพี้ยน

## คลาสใน Python

```python
class BankAccount:
    def __init__(self, owner, balance=0):
        self.owner = owner
        self.balance = balance

    def deposit(self, amount):
        if amount <= 0:
            raise ValueError("จำนวนเงินต้องมากกว่าศูนย์")
        self.balance += amount
        return self.balance

account = BankAccount("สมชาย")
account.deposit(500)
print(account.balance)
```

`__init__` คือเมท็อดที่ทำงานตอนสร้างวัตถุ ส่วน `self` คือตัวอ้างถึงวัตถุนั้นเอง ต้องเขียนเป็นพารามิเตอร์ตัวแรกของทุกเมท็อดในคลาส
