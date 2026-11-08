# Notifications: ขอบเขตและคู่มือส่งต่อ

## เปิดใช้งาน

ต้องมี Docker Desktop ที่ใช้ Linux containers ผ่าน WSL 2 และอินเทอร์เน็ตในครั้งแรก
เปิด PowerShell ในโฟลเดอร์โปรเจกต์แล้วรัน:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start-notifications.ps1
```

คำสั่งสร้างการตั้งค่าเฉพาะเครื่อง เปิดระบบ เชื่อม Keycloak นำเข้าแจ้งเตือนเก่า
และทดสอบการทำงานจริง ไม่ต้องติดตั้ง Node หรือ Python บนเครื่องเพื่อเปิดระบบ
ไฟล์ `.env.notifications` เป็นความลับเฉพาะเครื่องและไม่ส่งขึ้น Git

| หน้าจอ | URL |
|---|---|
| เว็บไซต์ | http://localhost:8080 |
| กล่องแจ้งเตือน | http://localhost:8080/notifications |
| Dashboard | http://localhost:3000/d/notifications |
| Trace | http://localhost:16686 |
| API docs | http://localhost:8080/notification-docs |

บัญชีเดโม: `nong@example.com` (ลูกค้า), `sparkle@example.com` (ผู้ให้บริการ),
`admin@edemand.test` (ผู้ดูแล) รหัสผ่านร่วม `eDemand-2026!` สำหรับเดโมเท่านั้น
ใช้ชื่อ localhost เพื่อให้ตรงกับการเข้าสู่ระบบ

## สิ่งที่อยู่ในงานนี้

```mermaid
flowchart LR
  Browser[Browser] --> Gateway[nginx Gateway]
  Gateway --> Identity[Keycloak]
  Gateway --> Web[Next.js Monolith]
  Web --> SQLite[(Domain SQLite + Outbox)]
  SQLite --> Publisher[Confirmed Publisher]
  Publisher --> Rabbit[RabbitMQ]
  Rabbit --> Worker[Notifications Worker]
  Worker --> PG[(Notifications PostgreSQL)]
  Gateway --> API[Notifications API]
  API --> PG
  Web --> Gateway
```

- API แยกและฐานข้อมูลของ Notifications เอง พร้อมตรวจเจ้าของข้อมูล
- เข้าสู่ระบบผ่าน Keycloak และสมัครบัญชีใหม่เชื่อมกับ Keycloak
- เหตุการณ์ธุรกิจผ่าน transactional outbox, RabbitMQ และการป้องกันข้อความซ้ำ
- กดอ่านแล้วด้วย Idempotency-Key และ retry แบบมี timeout/backoff/jitter
- ย้ายแจ้งเตือนเก่า เก็บเจ้าของ เวลา ภาษาไทย และสถานะอ่านไว้ รันซ้ำไม่เพิ่มข้อมูลซ้ำ
- Dashboard, Trace และ logs สำหรับตามหาปัญหา
- Pact HTTP contract 5 กรณี และไฟล์ GitHub Actions สำหรับทดสอบและสร้าง image

## ตรวจรับรอบสุดท้าย

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\check-notifications-final.ps1 -CleanStart
```

คำสั่งนี้เปิดระบบ ตรวจการนำเข้าซ้ำ ตรวจสิทธิ์ จำลองระบบช้า/ล่ม ตรวจการกู้คืน
และตรวจ Dashboard/Trace จากนั้นหยุดเว็บเดิมชั่วคราวเพื่อเปิดจาก source ที่ไม่ติดไฟล์
เฉพาะเครื่องและใช้ volumes ใหม่ เมื่อจบจะคืนระบบเดิม โดยเก็บฐานข้อมูลเดิมไว้
เฉพาะ volumes ของโครงการทดสอบที่สร้างใหม่จะถูกลบ โฟลเดอร์ทดสอบชั่วคราวอาจยังอยู่
จึงควรรันช่วงที่ทีมไม่ได้ใช้งานเว็บ

ผลจะถูกบันทึกเมื่อผ่านจริงเท่านั้นใน `docs/evidence/notifications-final-latest.json`
ถ้าล้มเหลวให้แก้แล้วรันใหม่ อย่าใช้ไฟล์ PASS เก่ามาอ้างว่าเวอร์ชันล่าสุดผ่าน
การตรวจ source ใหม่ไม่ต้องติดตั้ง Git และไม่ได้ส่งโค้ดออกไป
รายการ source มาจาก `.clean-source.json` โดยตัดรหัสผ่าน ฐานข้อมูล และไฟล์ที่สร้างตอนรันออก

## ผลที่ตรวจผ่านของชุด Notifications

- ชุดเดิมผ่าน Node 72 รายการ และ Python 39 รายการ; รอบ offline เพิ่มอีก 5 กรณี โดยดูผล CI ของ commit ล่าสุดประกอบ
- Pact ฝั่งเว็บและ FastAPI ผ่าน 5 กรณี และตรวจพบสัญญาตอบกลับที่ผิดโดยตั้งใจ
- บน Docker ผ่านการสมัคร/เข้าสู่ระบบจริง ตรวจ token/สิทธิ์ ระบบช้า/ล่ม
  ข้อความซ้ำ การ restart broker/worker และ Dashboard/Trace
- ชุดนำเข้าข้อมูลเก่าและการเปิดจาก source สะอาด/ฐานข้อมูลใหม่ผ่านบนเครื่องเจ้าของงานแล้ว
- ชุดเดิมรวมเข้า main และ [CI ผ่านครบ](https://github.com/HopeHerFine/DES428-Web-Services-and-Service-Architecture/actions/runs/42493551442)
  และ Pact แบบ Docker Compose รวมเข้า main ผ่าน [CI ของ PR #2](https://github.com/HopeHerFine/DES428-Web-Services-and-Service-Architecture/actions/runs/42512532452) แล้ว
- เปิดชุด images ที่เตรียมไว้ด้วย volumes ใหม่แบบ offline ผ่าน; RAM รวมสูงสุดที่สุ่มวัดได้ 1.13 GiB
  ภายใต้งบ Engine 7.76 GiB ดู [ผลและวิธีวัด](offline-memory.md)

## Contract Test ตาม brief

ใช้คำสั่งเดียวกับ CI โดยไม่ต้องเปิดเว็บหรือตั้งค่า `.env.notifications` ก่อน:

```powershell
docker compose -f compose.contracts.yml run --build --rm contract-tests
```

ชุดทดสอบใช้ PostgreSQL แยก ไม่แตะฐานข้อมูลเว็บ ผล JSON อยู่ใน `runtime/contracts/pacts/`
หลังทดสอบใช้ `docker compose -f compose.contracts.yml down --volumes --remove-orphans`
เพื่อหยุดเฉพาะชุดทดสอบ ดูรายละเอียดและผลที่ควรได้ใน [คู่มือ Contract/CI](contracts-and-ci.md)

## แนวเดโม

1. เปิดด้วยคำสั่งเดียวและแสดงผลตรวจรับ
2. เข้าบัญชีลูกค้า สร้างการจอง แล้วเข้าบัญชีผู้ให้บริการดูแจ้งเตือน
3. กดอ่านแล้ว แสดงว่าบัญชีอื่นแก้แจ้งเตือนนี้ไม่ได้
4. แสดงผลทดสอบระบบช้า/ล่มและข้อความซ้ำ พร้อมหลักฐานว่ามีผลครั้งเดียว
5. เปิด Dashboard แล้วใช้ trace ID ตามคำขอจากเว็บไปยังบริการ
6. แสดง Contract Test และผล CI ของ commit ที่ส่งงานจริง

## ข้อจำกัดและงานของทีม

Notifications เป็น service ที่แยกแล้วหนึ่งตัว ส่วน Booking, Provider และ Payments
ยังอยู่ใน monolith การทำ Service ที่ 2 และ Saga ไม่รวมอยู่ในชุดนี้
Keycloak ใช้โหมดพัฒนาและ H2 ส่วน Jaeger เก็บ trace ในหน่วยความจำและหายเมื่อ restart
Logs อยู่ใน Docker stdout ยังไม่มีระบบรวม logs แยกต่างหาก
Access token มีอายุ 5 นาทีแล้วต้องเข้าสู่ระบบใหม่
ชุด Notifications ทดสอบภายใต้งบ 8 GiB แล้ว แต่ต้องวัดซ้ำเมื่อเพิ่ม Service ที่ 2/Saga
ยังต้องปิดข้อกำหนดเปิด raw clone ตาม brief และเตรียมคลิป/รายงานรวมของทีม
การทดสอบข้อความซ้ำไม่ใช่หลักฐานว่าแก้ race condition เดิมของโจทย์แล้ว

เอกสารแยก: [migration](notifications-migration.md), [contracts/CI](contracts-and-ci.md),
[resilience](notifications-resilience.md), [recovery](broker-worker-recovery.md),
[observability](observability.md), [registration](registration-keycloak.md)

ติดตามงานทั้งทีมใน [checklist ตาม brief](progress-checklist.md)
