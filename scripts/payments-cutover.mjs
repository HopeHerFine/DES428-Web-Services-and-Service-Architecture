// Trusted offline operator container; never exposed by HTTP.
import Database from 'better-sqlite3';
import {createHash,randomUUID} from 'node:crypto';
import {readFileSync,writeFileSync,mkdirSync,chmodSync,renameSync} from 'node:fs';
import {paymentHistory} from './export-payments-history.mjs';
import {cutoverState,prepareCutover,transitionCutover} from './cutover-state.mjs';

const action=process.argv[2] || 'status';
if(action!=='status' && process.env.PAYMENTS_MAINTENANCE!=='true') throw new Error('Stop ingress and all writers before cutover operations.');
const db=new Database('/app/data/edemand.db',{fileMustExist:true,readonly:action==='status'});
db.pragma('busy_timeout=5000');
function canonical(value) {
  if(Array.isArray(value)) return '['+value.map(canonical).join(',')+']';
  if(value && typeof value==='object') return '{'+Object.keys(value).sort().map(key=>JSON.stringify(key)+':'+canonical(value[key])).join(',')+'}';
  return JSON.stringify(value).replace(/[\u007f-\uffff]/g,c=>'\\u'+c.charCodeAt(0).toString(16).padStart(4,'0'));
}
const hash=document=>createHash('sha256').update(canonical(document)).digest('hex');
function runId(value) {
  if(!/^[a-f0-9-]{36}$/.test(value)) throw new Error('Invalid cutover run identifier');
  return value;
}
function save(state) {
  const result={result:'PASS',...(state || {phase:'legacy'})};
  mkdirSync('/migration/source',{recursive:true});
  const temporary='/migration/source/status-'+randomUUID()+'.json';
  writeFileSync(temporary,JSON.stringify(result),{mode:0o644});
  renameSync(temporary,'/migration/source/status.json');
  if(state?.run_id) {
    mkdirSync('/migration/marker',{recursive:true});
    const file='/migration/marker/state-'+randomUUID()+'.json';
    writeFileSync(file,JSON.stringify(result),{mode:0o644});
    renameSync(file,'/migration/marker/state.json');
  }
  console.log(JSON.stringify(result));
}
try {
  const old=cutoverState(db);
  if(action==='status') {
    if(!old) {
      const exists=db.prepare("SELECT 1 FROM sqlite_master WHERE type='table' AND name='payments_runtime_mode'").get();
      if(exists && db.prepare("SELECT 1 FROM payments_runtime_mode WHERE mode='external'").get()) {
        save({phase:'external-pilot'});
      } else save(null);
    } else save(old);
  } else if(action==='prepare') {
    if(old && old.phase!=='rolled_back') throw new Error('Resume the existing cutover instead of creating another snapshot');
    const document=paymentHistory(db,process.env.LEGACY_SOURCE_ID);
    const digest=hash(document);
    const id=randomUUID();
    const backupDirectory='/app/data/payments-cutover-backups';
    mkdirSync(backupDirectory,{recursive:true,mode:0o700});
    const backup=backupDirectory+'/'+id+'.db';
    await db.backup(backup);
    chmodSync(backup,0o600);
    if(hash(paymentHistory(db,process.env.LEGACY_SOURCE_ID))!==digest) throw new Error('Source changed while backing up; stop all writers and retry');
    const directory='/migration/source/'+id;
    mkdirSync(directory,{mode:0o755});
    writeFileSync(directory+'/history.json',JSON.stringify(document),{encoding:'utf8',flag:'wx',mode:0o444});
    save(prepareCutover(db,id,digest,document.orders));
  } else {
    if(!old) throw new Error('No prepared cutover exists');
    const id=runId(old.run_id);
    const proof=JSON.parse(readFileSync('/migration/report/'+id+'-check.json','utf8'));
    if(proof.run_id!==id) throw new Error('Proof belongs to a different cutover run');
    const current=hash(paymentHistory(db,process.env.LEGACY_SOURCE_ID));
    save(transitionCutover(db,action,proof,current));
  }
} finally {db.close();}
