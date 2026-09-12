# Java เบื้องต้น

## ภาพรวมของภาษา Java

Java เป็นภาษาแบบ static typing คือต้องประกาศชนิดข้อมูลของตัวแปรให้ชัดเจนตั้งแต่ตอนเขียน ตัวแปลภาษาจะตรวจชนิดให้ก่อนโปรแกรมทำงาน จึงจับข้อผิดพลาดหลายอย่างได้ตั้งแต่ยังไม่รัน

โค้ด Java ถูกคอมไพล์เป็น bytecode แล้วทำงานบน Java Virtual Machine ทำให้โปรแกรมเดียวรันได้บนหลายระบบปฏิบัติการ นิยมใช้กับระบบองค์กรขนาดใหญ่และแอปแอนดรอยด์

## โครงสร้างโปรแกรม Java

ทุกอย่างใน Java ต้องอยู่ในคลาส และโปรแกรมเริ่มทำงานที่เมท็อดชื่อ `main`

```java
public class HelloWorld {
    public static void main(String[] args) {
        System.out.println("สวัสดีชาวโลก");
    }
}
```

ชื่อคลาสต้องตรงกับชื่อไฟล์ คลาส `HelloWorld` ต้องอยู่ในไฟล์ `HelloWorld.java` ไม่งั้นคอมไพล์ไม่ผ่าน

## ตัวแปรและชนิดข้อมูลใน Java

```java
int age = 30;
double height = 172.5;
boolean isActive = true;
char grade = 'A';
String name = "สมชาย";
final int MAX_USERS = 100;
```

Java แบ่งชนิดข้อมูลเป็นสองกลุ่ม คือชนิดพื้นฐาน (`int`, `double`, `boolean`, `char`) ซึ่งเก็บค่าโดยตรง กับชนิดอ้างอิง (`String`, อาร์เรย์, วัตถุ) ซึ่งเก็บที่อยู่ของข้อมูล

คำสั่ง `final` ทำให้ตัวแปรกำหนดค่าใหม่ไม่ได้ ใช้กับค่าคงที่

## เงื่อนไขใน Java

```java
int score = 75;
String grade;

if (score >= 80) {
    grade = "A";
} else if (score >= 70) {
    grade = "B";
} else {
    grade = "C";
}

switch (grade) {
    case "A" -> System.out.println("ดีเยี่ยม");
    case "B" -> System.out.println("ดี");
    default -> System.out.println("ผ่าน");
}
```

การเปรียบเทียบข้อความต้องใช้ `.equals()` ไม่ใช่ `==` เพราะ `==` เทียบว่าเป็นวัตถุตัวเดียวกันในหน่วยความจำหรือไม่ ไม่ได้เทียบเนื้อข้อความ นี่คือข้อผิดพลาดคลาสสิกของผู้เริ่มต้น

## การวนซ้ำใน Java

```java
String[] fruits = {"แอปเปิล", "กล้วย", "ส้ม"};

for (int i = 0; i < fruits.length; i++) {
    System.out.println(fruits[i]);
}

for (String fruit : fruits) {
    System.out.println(fruit);
}

int count = 3;
while (count > 0) {
    System.out.println(count);
    count--;
}
```

รูปแบบที่สองเรียกว่า enhanced for loop อ่านง่ายกว่าเมื่อไม่ต้องใช้เลขตำแหน่ง

## เมท็อดใน Java

```java
public class Calculator {
    public static int add(int a, int b) {
        return a + b;
    }

    public double average(int[] numbers) {
        int sum = 0;
        for (int n : numbers) {
            sum += n;
        }
        return (double) sum / numbers.length;
    }
}
```

ต้องประกาศชนิดของค่าที่คืนไว้หน้าชื่อเมท็อด ถ้าไม่คืนค่าให้ใช้ `void` ส่วน `static` หมายถึงเรียกใช้ได้จากคลาสโดยตรงโดยไม่ต้องสร้างวัตถุก่อน

`(double) sum` คือการแปลงชนิด ถ้าไม่ใส่ Java จะหารแบบจำนวนเต็มแล้วปัดเศษทิ้ง

## อาร์เรย์และ ArrayList

```java
int[] numbers = new int[5];
numbers[0] = 10;

List<String> names = new ArrayList<>();
names.add("สมชาย");
names.add("สมหญิง");
System.out.println(names.get(0));
System.out.println(names.size());
```

อาร์เรย์มีขนาดคงที่ตั้งแต่สร้าง ส่วน `ArrayList` เพิ่มลดสมาชิกได้ตามต้องการ จึงใช้บ่อยกว่าในงานจริง

## คลาสและวัตถุใน Java

```java
public class BankAccount {
    private String owner;
    private double balance;

    public BankAccount(String owner) {
        this.owner = owner;
        this.balance = 0;
    }

    public void deposit(double amount) {
        if (amount <= 0) {
            throw new IllegalArgumentException("จำนวนเงินต้องมากกว่าศูนย์");
        }
        this.balance += amount;
    }

    public double getBalance() {
        return balance;
    }
}
```

`private` ทำให้ฟิลด์เข้าถึงได้เฉพาะภายในคลาส ภายนอกต้องผ่านเมท็อดที่เปิดให้ หลักการนี้เรียกว่า encapsulation ช่วยกันไม่ให้ค่าถูกแก้จนอยู่ในสถานะที่ผิด

## การจัดการข้อผิดพลาดใน Java

```java
try {
    int value = Integer.parseInt(input);
    System.out.println(100 / value);
} catch (NumberFormatException e) {
    System.out.println("กรุณาใส่ตัวเลขเท่านั้น");
} catch (ArithmeticException e) {
    System.out.println("หารด้วยศูนย์ไม่ได้");
} finally {
    System.out.println("จบการทำงาน");
}
```

Java แบ่งข้อยกเว้นเป็น checked ซึ่งคอมไพเลอร์บังคับให้ดักหรือประกาศต่อ กับ unchecked ซึ่งไม่บังคับ `NullPointerException` เป็นแบบ unchecked และเป็นข้อผิดพลาดที่พบบ่อยที่สุดในโปรแกรม Java
