// Synthetic migration rehearsal only: no host/source database is opened.
import Database from 'better-sqlite3';
import {writeFileSync} from 'node:fs';
import {paymentHistory} from './export-payments-history.mjs';
if(process.env.HISTORY_FIXTURE!=='synthetic') throw new Error('Synthetic fixture mode is required');
const db=new Database(':memory:');
try {
  db.exec(`
    CREATE TABLE orders(id INTEGER,customer_id INTEGER,provider_id INTEGER,total_cents INTEGER,commission_pct REAL,payment_method TEXT,status TEXT,payment_status TEXT);
    CREATE TABLE payment_intents(id INTEGER,order_id INTEGER,amount_cents INTEGER,gateway_ref TEXT,status TEXT,created_at TEXT);
    CREATE TABLE transactions(id INTEGER,order_id INTEGER,customer_id INTEGER,provider_id INTEGER,kind TEXT,amount_cents INTEGER,method TEXT,gateway_ref TEXT,status TEXT,created_at TEXT);
    CREATE TABLE provider_wallets(provider_id INTEGER,balance_cents INTEGER,commission_owed_cents INTEGER);
    INSERT INTO orders VALUES(8001,1,1,107000,10,'gateway','completed','paid'),(8002,1,1,21400,15,'cod','completed','pending'),(8003,1,1,21400,15,'gateway','awaiting','pending');
    INSERT INTO payment_intents VALUES(1,8001,107000,'legacy-paid','succeeded','2026-01-01T00:00:00Z'),(2,8003,21400,'legacy-pending','requires_payment','2026-01-02T00:00:00Z');
    INSERT INTO transactions VALUES(81,8001,1,1,'charge',107000,'gateway','legacy-paid','succeeded','2026-01-01T00:00:00Z'),(95,8001,1,1,'payout_credit',96300,'gateway',NULL,'succeeded','2026-01-01T01:00:00Z'),(96,8002,1,1,'commission_owed',3210,'cod',NULL,'succeeded','2026-01-02T01:00:00Z');
    INSERT INTO provider_wallets VALUES(1,50000,1200),(2,3000,0);
  `);
  const snapshot=paymentHistory(db,'synthetic-history-fixture');
  writeFileSync('/app/data/payment-history.json',JSON.stringify(snapshot),{encoding:'utf8',mode:0o644});
  console.log('Synthetic SQLite financial history exported. No application database was opened.');
} finally {db.close();}

