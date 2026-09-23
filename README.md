# ระบบจัดการร้านขายโทรศัพท์มือถือ (Local Web Application)

โปรเจ็กต์นี้เป็นงานพัฒนาต่อยอดจากโครงสร้างฐานข้อมูล "ระบบจัดการร้านขายโทรศัพท์มือถือ" โดยนำเอาจุดเด่นของทั้ง 2 เวอร์ชันมาผสมกัน:

- ใช้ 9 ตารางจากเวอร์ชันขยาย: Customer, Customer Phone, Employee, User Account, Supplier, Product, Supplier Product, Sale, Sale Detail
- ใช้ `total_amount` เป็นฟิลด์จริงในตาราง `sale` ตามแนวคิดของเวอร์ชันเต็ม เพื่อให้บันทึกราคา ณ เวลาขายได้ตรงตามธุรกิจจริง
- ใช้ SQLite เป็นฐานข้อมูลและทำงานแบบ Local

## คุณสมบัติหลัก

- หน้า Dashboard แสดงสรุปข้อมูล
- หน้าแสดงข้อมูลลูกค้า (SELECT)
- หน้าแสดงข้อมูลสินค้า (SELECT)
- หน้าแสดงข้อมูลการขาย (SELECT)
- ฟอร์มเพิ่มข้อมูลลูกค้า (INSERT)
- ฟอร์มเพิ่มข้อมูลสินค้า (INSERT)
- ฟอร์มบันทึกการขาย (INSERT)
- ระบบ Login สำหรับพนักงาน (USER_ACCOUNT)
- ฐานข้อมูล SQLite แบบ persistent (`mobile_shop.db`)

## โครงสร้างโฟลเดอร์

- `app.py` — แอป Flask หลัก
- `mobile_shop.db` — ฐานข้อมูล SQLite
- `static/styles.css` — ไฟล์ CSS
- `templates/` — หน้าเว็บ HTML
- `requirements.txt` — รายการ dependencies

## วิธีรันโปรเจกต์

1. เปิด Command Prompt / PowerShell
2. ไปที่โฟลเดอร์โปรเจกต์
3. ติดตั้ง dependency:

```bash
python -m pip install -r requirements.txt
```

4. รันแอป:

```bash
python app.py
```

5. เปิดเบราว์เซอร์ที่:

```text
http://127.0.0.1:5000
```

## Login ตัวอย่าง

- username: `admin`
- password: `1234`

## หมายเหตุ

ฐานข้อมูลจะถูกสร้างอัตโนมัติเมื่อรันแอปครั้งแรก หากไฟล์ `mobile_shop.db` ไม่มีอยู่ ระบบจะสร้างขึ้นให้อัตโนมัติ พร้อมข้อมูลตัวอย่างสำหรับทดสอบ

## วัตถุประสงค์ของโปรเจกต์

เพื่อพิสูจน์ว่าโครงสร้างฐานข้อมูลที่ออกแบบไว้สามารถใช้งานจริงกับระบบส่วนหน้าได้ โดยเชื่อมต่อ SQLite เข้ากับ Flask และแสดงข้อมูลผ่านหน้าเว็บแบบ Local Application

# modon
