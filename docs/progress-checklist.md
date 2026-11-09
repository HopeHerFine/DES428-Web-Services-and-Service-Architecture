# Checklist ตาม Capstone brief

ใช้แยกงาน Notifications ที่ตรวจแล้วออกจากข้อกำหนดส่งงานทั้งทีม
เครื่องหมายผ่านหมายถึงมีผลทดสอบตามขอบเขตที่ระบุ ไม่ใช่การยืนยันคะแนนจากผู้สอน

## Notifications ที่ตรวจผ่าน

- [x] แยก FastAPI และ PostgreSQL ของ Notifications
- [x] เชื่อมเว็บผ่าน nginx; ตรวจ Keycloak token และเจ้าของข้อมูล
- [x] สมัครบัญชีใหม่เชื่อม Keycloak
- [x] Transactional outbox, RabbitMQ, publisher confirms และ deduplication
- [x] กดอ่านแล้วด้วย Idempotency-Key; timeout/retry/backoff/jitter
- [x] Fault switches สามกรณี และการกู้คืน broker/worker
- [x] ย้ายแจ้งเตือนเก่าแบบรันซ้ำไม่ซ้ำ
- [x] Prometheus/Grafana/Jaeger และ structured logs
- [x] Pact ห้ากรณี รันด้วย Docker Compose คำสั่งเดียวกับ CI
- [x] เปิดจาก source สะอาดและ volumes ใหม่บนเครื่องเจ้าของงาน
- [x] เปิดแบบ offline หลังเตรียม images/settings พร้อมปิด external network
- [x] วัด RAM ระหว่างรันจริง: สูงสุดที่สุ่มวัดได้ 1.13 GiB จาก 45 samples
  ภายใต้งบ Engine 7.76 GiB; มี 19 samples ระหว่าง workload
- [x] โค้ด Notifications/Pact และ Actions รุ่นใหม่บน main ผ่าน CI แล้ว

ผลและขอบเขต: [offline/RAM](offline-memory.md), [ผลวัดที่ตัดข้อมูลเฉพาะเครื่องออก](offline-memory-result.json)

## ข้อกำหนดทีมที่ยังต้องปิด

- [ ] Service ที่ 2 ด้วย FastAPI และฐานข้อมูล PostgreSQL/MySQL ของตัวเอง
  เริ่ม Payments & Wallet แบบ opt-in pilot แล้ว ดู services/payments/README.md;
  Windows pilot ผ่านแล้ว; เพิ่ม HTTP Pact ของ Payments หกกรณีแล้ว
  เพิ่มตัว export/import ประวัติพร้อมตรวจยอดและซ้อมข้อมูลจำลองแล้ว;
  ยังไม่ย้ายหรือสลับข้อมูลจริงของระบบเดิม
  ยังต้องปิด migration/observability/faults/Saga ก่อนยืนยันทั้ง seam
- [ ] JWT/ownership และ traces ครบทั้งสอง seams
- [ ] ข้อกำหนดสอง events ของทีมและ Saga พร้อม compensating actions
- [ ] เหตุผลเลือก orchestration/choreography จากหลักฐานของทีมเอง
- [ ] หาและแก้ BOLA ใน inherited code พร้อมสาธิตการโจมตีก่อน/หลัง
- [ ] หาและแก้ unsafe race ที่ README ระบุ พร้อมทดสอบคำขอพร้อมกัน
- [ ] Dashboard rate/error/response time และ Pact ครบทั้งสอง boundaries
- [x] ยืนยัน root canonical clone ที่เปิดด้วย docker compose up โดยไม่ใช้ host settings
  PR #5 ผ่าน CI และเจ้าของงานซ้อม check-clean-start.ps1 ผ่านแล้ว
  (ต้องตรวจซ้ำสำหรับ commit ส่งจริงเมื่อเพิ่มบริการครบ)
  ดู [วิธีเปิดและขอบเขตการทดสอบ](canonical-boot.md)
- [ ] วัด RAM และตรวจ offline ซ้ำเมื่อระบบรวมมี Service ที่ 2/Saga

## สิ่งส่งงาน

- [ ] Repository ชื่อตาม brief และแชร์สิทธิ์ให้อาจารย์
- [ ] OWNERS.md: เจ้าของ A–E และลิงก์ commits/PR ของสมาชิก
- [ ] README: คำสั่งเริ่ม/reset, seeded logins และผลที่คาดหวังของ demo ทั้งสี่
- [ ] scripts/beat1-happy-path.sh
- [ ] scripts/beat2-failure-recovery.sh
- [ ] scripts/beat3-auth-rejection.sh
- [ ] scripts/beat4-find-the-trace.sh
- [ ] docs/dossier.md: เจ็ดส่วน, boundary map/บัญชีทุก boundary, seam defence,
  industrial landscape และบรรทัดแจ้งการใช้ AI ตาม brief
- [ ] capstone-demo.mp4 ความยาว 8–12 นาที
- [ ] tag capstone-final ที่ commit ส่งจริง
- [ ] ตรวจผล CI ของ commit capstone-final ก่อนส่งงาน
- [ ] Peer review และเตรียม live defence ของสมาชิกทุกคน

ผลทดสอบและเหตุผลป้องกันสถาปัตยกรรมต้องมาจากงานจริงของทีม
ผลวัดนี้ใช้กับ Notifications increment เท่านั้น ไม่ใช่หลักฐานว่าข้อกำหนดทีมครบทั้งหมด
