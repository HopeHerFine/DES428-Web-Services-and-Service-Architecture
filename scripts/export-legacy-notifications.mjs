import Database from 'better-sqlite3';
import {writeFileSync} from 'node:fs';
const source = process.env.LEGACY_SOURCE_ID;
if (!source) throw new Error('LEGACY_SOURCE_ID is required; run start-notifications.ps1');
const db = new Database(process.env.LEGACY_DB_PATH || '/app/data/edemand.db', {readonly:true,fileMustExist:true});
try {
  const rows = db.transaction(() => db.prepare(`SELECT id,recipient_role,recipient_id,type,title,body,
    order_id,read_at,created_at FROM notifications ORDER BY id`).all())();
  const document = JSON.stringify({version:1,source,rows});
  if (process.env.LEGACY_EXPORT_FILE) {
    writeFileSync(process.env.LEGACY_EXPORT_FILE, document, {encoding:'utf8',flag:'wx',mode:0o644});
    console.log('Historical snapshot exported.');
  } else process.stdout.write(document);
} finally {db.close();}
