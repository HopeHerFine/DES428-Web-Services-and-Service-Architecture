import Database from 'better-sqlite3';
import {writeFileSync} from 'node:fs';

export function paymentHistory(db, source) {
  if (!source || typeof source !== 'string' || source.length > 128) throw new Error('Stable source identifier is required');
  return db.transaction(() => ({version:1,source,
    orders:db.prepare(`SELECT id AS order_id, customer_id, provider_id, total_cents AS amount_cents,
      commission_pct, payment_method AS method, status, payment_status FROM orders ORDER BY id`).all()
      .map(({commission_pct,...order})=>({...order,commission_cents:Math.round(order.amount_cents*commission_pct/100)})),
    intents:db.prepare('SELECT id,order_id,amount_cents,gateway_ref,status,created_at FROM payment_intents ORDER BY id').all(),
    transactions:db.prepare(`SELECT id,order_id,customer_id,provider_id,kind,amount_cents,method,
      gateway_ref,status,created_at FROM transactions ORDER BY id`).all(),
    wallets:db.prepare('SELECT provider_id,balance_cents,commission_owed_cents FROM provider_wallets ORDER BY provider_id').all(),
  }))();
}

// Exported separately so tests can exercise real SQLite without opening a host DB.
if (process.argv[1] && import.meta.url === (await import('node:url')).pathToFileURL(process.argv[1]).href) {
  if (process.env.PAYMENTS_SOURCE_OFFLINE !== 'true') throw new Error('Stop all legacy writers and set PAYMENTS_SOURCE_OFFLINE=true before export');
  if (!process.env.LEGACY_EXPORT_FILE) throw new Error('LEGACY_EXPORT_FILE is required; snapshots must not travel through terminal output');
  const db = new Database(process.env.LEGACY_DB_PATH || '/app/data/edemand.db',{readonly:true,fileMustExist:true});
  try {
    const document=paymentHistory(db,process.env.LEGACY_SOURCE_ID);
    writeFileSync(process.env.LEGACY_EXPORT_FILE,JSON.stringify(document),{encoding:'utf8',flag:'wx',mode:0o644});
    console.log('Payments history snapshot exported; source was not changed.');
  } finally {db.close();}
}
