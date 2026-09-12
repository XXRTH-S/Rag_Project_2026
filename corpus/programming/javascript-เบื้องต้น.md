# JavaScript เบื้องต้น

## ภาพรวมของภาษา JavaScript

JavaScript เป็นภาษาที่รันได้ทั้งในเบราว์เซอร์และบนเซิร์ฟเวอร์ผ่าน Node.js เดิมสร้างมาเพื่อทำให้หน้าเว็บโต้ตอบกับผู้ใช้ได้ ปัจจุบันใช้เขียนได้ทั้งหน้าเว็บ แอปมือถือ และงานฝั่งหลังบ้าน

JavaScript ใช้วงเล็บปีกกาบอกขอบเขตของบล็อก และปิดคำสั่งด้วยเซมิโคลอน ภาษานี้เป็น dynamic typing เช่นเดียวกับ Python

## ตัวแปรใน JavaScript

ประกาศตัวแปรด้วย `let` เมื่อค่าจะเปลี่ยน และ `const` เมื่อค่าจะไม่เปลี่ยน หลีกเลี่ยง `var` แบบเก่าเพราะขอบเขตของมันกว้างกว่าที่คนส่วนใหญ่คาด

```javascript
const name = "สมชาย";
let age = 30;
age = 31;
```

`const` ห้ามกำหนดค่าใหม่ให้ตัวแปร แต่ไม่ได้ห้ามแก้ข้างในวัตถุ ดังนั้น `const user = {}` แล้ว `user.name = "ก"` ยังทำได้

## ชนิดข้อมูลใน JavaScript

ชนิดพื้นฐานคือ number, string, boolean, null, undefined, symbol และ bigint ส่วน object ครอบคลุมทั้งวัตถุ อาร์เรย์ และฟังก์ชัน

JavaScript มีค่าว่างสองตัวที่ต่างกัน คือ `undefined` หมายถึงยังไม่เคยกำหนดค่า ส่วน `null` หมายถึงตั้งใจให้ว่าง

ควรเปรียบเทียบด้วย `===` ซึ่งเทียบทั้งค่าและชนิด ไม่ใช่ `==` ที่แปลงชนิดให้อัตโนมัติจนได้ผลแปลก เช่น `0 == "0"` เป็นจริง แต่ `0 === "0"` เป็นเท็จ

## เงื่อนไขใน JavaScript

```javascript
const score = 75;
let grade;

if (score >= 80) {
  grade = "A";
} else if (score >= 70) {
  grade = "B";
} else {
  grade = "C";
}

const status = score >= 50 ? "ผ่าน" : "ไม่ผ่าน";
```

บรรทัดสุดท้ายคือ ternary operator ใช้เขียนเงื่อนไขสั้น ๆ ที่ให้ค่ากลับมา เหมาะกับกรณีเลือกสองทางเท่านั้น

## การวนซ้ำใน JavaScript

```javascript
const fruits = ["แอปเปิล", "กล้วย", "ส้ม"];

for (let i = 0; i < fruits.length; i++) {
  console.log(fruits[i]);
}

for (const fruit of fruits) {
  console.log(fruit);
}

fruits.forEach((fruit, index) => {
  console.log(index, fruit);
});
```

`for...of` วนบนค่าในอาร์เรย์ ส่วน `for...in` วนบนคีย์ซึ่งมักไม่ใช่สิ่งที่ต้องการกับอาร์เรย์ จึงควรใช้ `for...of` เป็นหลัก

## ฟังก์ชันใน JavaScript

```javascript
function calculateTotal(price, quantity, discount = 0) {
  return price * quantity - discount;
}

const double = (n) => n * 2;

console.log(calculateTotal(100, 3));
console.log(double(21));
```

รูปแบบที่สองเรียกว่า arrow function เขียนสั้นกว่าและไม่มี `this` เป็นของตัวเอง จึงนิยมใช้เป็นฟังก์ชันย่อยที่ส่งเข้าไปในฟังก์ชันอื่น

## อาร์เรย์และเมท็อดที่ใช้บ่อย

```javascript
const numbers = [1, 2, 3, 4, 5, 6];

const squares = numbers.map((n) => n * n);
const evens = numbers.filter((n) => n % 2 === 0);
const sum = numbers.reduce((acc, n) => acc + n, 0);

numbers.push(7);
console.log(numbers.includes(3));
```

`map` แปลงทุกสมาชิกได้อาร์เรย์ใหม่ `filter` คัดเฉพาะที่ตรงเงื่อนไข ส่วน `reduce` ยุบทั้งอาร์เรย์ให้เหลือค่าเดียว ทั้งสามตัวไม่แก้อาร์เรย์เดิม

## วัตถุใน JavaScript

```javascript
const person = {
  name: "สมชาย",
  age: 30,
  greet() {
    return `สวัสดี ${this.name}`;
  },
};

const { name, age } = person;
const updated = { ...person, age: 31 };
```

`const { name, age } = person` เรียกว่า destructuring คือดึงค่าออกมาเป็นตัวแปรทีเดียวหลายตัว ส่วนจุดสามจุดเรียกว่า spread ใช้คัดลอกวัตถุแล้วทับบางฟิลด์ โดยไม่แก้ของเดิม

## การทำงานแบบอะซิงโครนัส

งานที่ต้องรอ เช่นเรียก API หรืออ่านไฟล์ จะไม่หยุดโปรแกรมทั้งหมดไว้ แต่คืน Promise ออกมาก่อน

```javascript
async function fetchUser(id) {
  try {
    const response = await fetch(`/api/users/${id}`);
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    return await response.json();
  } catch (error) {
    console.error("โหลดข้อมูลไม่สำเร็จ", error);
    return null;
  }
}
```

`await` ใช้ได้เฉพาะในฟังก์ชันที่ประกาศเป็น `async` และหมายถึงรอให้ Promise ทำงานเสร็จก่อนไปบรรทัดถัดไป

## การจัดการข้อผิดพลาดใน JavaScript

```javascript
try {
  const value = JSON.parse(input);
  console.log(value);
} catch (error) {
  console.error("ข้อมูลไม่ใช่ JSON ที่ถูกต้อง", error.message);
} finally {
  console.log("จบการทำงาน");
}
```

`fetch` จะไม่โยนข้อผิดพลาดเมื่อเซิร์ฟเวอร์ตอบสถานะ 404 หรือ 500 ต้องตรวจ `response.ok` เอง ซึ่งเป็นจุดที่คนพลาดกันบ่อย
