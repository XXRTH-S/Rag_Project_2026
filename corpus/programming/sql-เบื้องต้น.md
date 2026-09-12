# SQL เบื้องต้น

## ภาพรวมของภาษา SQL

SQL เป็นภาษาสำหรับสั่งงานฐานข้อมูลเชิงสัมพันธ์ ต่างจากภาษาทั่วไปตรงที่เราบอกว่า "ต้องการข้อมูลอะไร" ไม่ใช่ "ให้ไปหาอย่างไร" ฐานข้อมูลจะวางแผนวิธีค้นเองเพื่อให้ได้ผลเร็วที่สุด

ฐานข้อมูลที่ใช้ SQL ได้แก่ PostgreSQL, MySQL, SQL Server, Oracle และ SQLite ไวยากรณ์หลักเหมือนกัน ต่างกันที่รายละเอียดของฟังก์ชันเฉพาะตัว

## การดึงข้อมูลด้วย SELECT

```sql
SELECT name, email FROM users;

SELECT * FROM users WHERE age >= 18;

SELECT name FROM users
WHERE department = 'IT' AND is_active = true
ORDER BY name ASC
LIMIT 10;
```

`SELECT *` ดึงทุกคอลัมน์ ซึ่งสะดวกตอนทดลอง แต่ในโค้ดจริงควรระบุชื่อคอลัมน์ที่ต้องการ เพราะจะไม่พังเมื่อมีคนเพิ่มคอลัมน์ใหม่และไม่ดึงข้อมูลเกินความจำเป็น

## การกรองข้อมูลด้วย WHERE

```sql
SELECT * FROM products WHERE price BETWEEN 100 AND 500;

SELECT * FROM users WHERE department IN ('IT', 'HR', 'Sales');

SELECT * FROM users WHERE name LIKE 'สม%';

SELECT * FROM users WHERE phone IS NULL;
```

`LIKE 'สม%'` หาข้อความที่ขึ้นต้นด้วย "สม" โดยเครื่องหมายเปอร์เซ็นต์แทนอักขระกี่ตัวก็ได้

ค่าว่างต้องเทียบด้วย `IS NULL` เท่านั้น เขียน `= NULL` จะไม่มีวันเป็นจริง เพราะ NULL หมายถึง "ไม่รู้ค่า" การเทียบสิ่งที่ไม่รู้ค่ากับอะไรก็ตามจึงให้ผลว่าไม่รู้ ไม่ใช่จริง

## การรวมข้อมูลจากหลายตารางด้วย JOIN

```sql
SELECT orders.id, users.name, orders.total
FROM orders
INNER JOIN users ON users.id = orders.user_id;

SELECT users.name, orders.id
FROM users
LEFT JOIN orders ON orders.user_id = users.id;
```

`INNER JOIN` คืนเฉพาะแถวที่จับคู่กันได้ทั้งสองฝั่ง ส่วน `LEFT JOIN` คืนทุกแถวของตารางซ้ายแม้ไม่มีคู่ทางขวา โดยเติมค่า NULL ให้

ตัวอย่างที่สองจึงได้ผู้ใช้ทุกคนรวมถึงคนที่ยังไม่เคยสั่งซื้อ ถ้าใช้ `INNER JOIN` คนกลุ่มนั้นจะหายไปจากผลลัพธ์

## การสรุปข้อมูลด้วย GROUP BY

```sql
SELECT department, COUNT(*) AS total
FROM users
GROUP BY department;

SELECT department, AVG(salary) AS avg_salary
FROM users
GROUP BY department
HAVING AVG(salary) > 30000
ORDER BY avg_salary DESC;
```

ฟังก์ชันสรุปที่ใช้บ่อยคือ `COUNT`, `SUM`, `AVG`, `MIN` และ `MAX`

`WHERE` กรองก่อนจัดกลุ่ม ส่วน `HAVING` กรองหลังจัดกลุ่มแล้ว จึงใช้ `HAVING` กับผลของฟังก์ชันสรุปได้ แต่ใช้ `WHERE` ไม่ได้

## การเพิ่ม แก้ไข และลบข้อมูล

```sql
INSERT INTO users (name, email, age)
VALUES ('สมชาย', 'somchai@example.com', 30);

UPDATE users
SET age = 31
WHERE id = 5;

DELETE FROM users WHERE id = 5;
```

`UPDATE` และ `DELETE` ที่ลืมใส่ `WHERE` จะทำกับทุกแถวในตาราง ซึ่งเป็นอุบัติเหตุที่เกิดขึ้นจริงบ่อยมาก วิธีป้องกันคือเขียน `SELECT` ด้วยเงื่อนไขเดียวกันก่อนเสมอ เพื่อดูว่าจะกระทบกี่แถว

## ทรานแซกชัน

```sql
BEGIN;

UPDATE accounts SET balance = balance - 1000 WHERE id = 1;
UPDATE accounts SET balance = balance + 1000 WHERE id = 2;

COMMIT;
```

ทรานแซกชันทำให้คำสั่งหลายคำสั่งสำเร็จทั้งหมดหรือไม่สำเร็จเลย ถ้าคำสั่งที่สองล้ม สามารถสั่ง `ROLLBACK` เพื่อย้อนคำสั่งแรกกลับได้ เงินจึงไม่หายไปกลางทาง

## ดัชนี

```sql
CREATE INDEX idx_users_email ON users (email);
```

ดัชนีทำให้การค้นด้วยคอลัมน์นั้นเร็วขึ้นมาก เพราะฐานข้อมูลไม่ต้องไล่อ่านทุกแถว เปรียบได้กับสารบัญท้ายเล่มหนังสือ

ข้อแลกเปลี่ยนคือดัชนีกินพื้นที่เก็บและทำให้การเพิ่มหรือแก้ข้อมูลช้าลงเล็กน้อย เพราะต้องปรับดัชนีตามไปด้วย จึงควรสร้างเฉพาะคอลัมน์ที่ใช้ค้นบ่อยจริง ๆ

## SQL injection

ห้ามนำค่าที่รับจากผู้ใช้มาต่อเป็นข้อความคำสั่ง SQL โดยตรง เพราะผู้ใช้อาจใส่คำสั่ง SQL แทรกเข้ามาแล้วอ่านหรือลบข้อมูลทั้งฐาน

วิธีที่ถูกต้องคือใช้ parameterized query ซึ่งส่งค่าแยกจากตัวคำสั่ง ฐานข้อมูลจึงถือว่าค่านั้นเป็นข้อมูลเสมอ ไม่ใช่คำสั่ง ทุกภาษาและทุกไลบรารีมีวิธีนี้ให้ใช้อยู่แล้ว
