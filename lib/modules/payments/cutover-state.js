// Offline operator state. This is not a business Saga or a public API.
export function ensureCutoverSchema(db) {
  db.exec(`CREATE TABLE IF NOT EXISTS payments_runtime_mode(mode TEXT PRIMARY KEY);
    CREATE TABLE IF NOT EXISTS payments_cutover (
      id INTEGER PRIMARY KEY CHECK(id=1),run_id TEXT NOT NULL,snapshot_sha256 TEXT NOT NULL,
      phase TEXT NOT NULL CHECK(phase IN ('prepared','activated','released','rolled_back'))
    );
    CREATE TABLE IF NOT EXISTS payments_legacy_orders (
      order_id INTEGER PRIMARY KEY,customer_id INTEGER NOT NULL,provider_id INTEGER NOT NULL,
      amount_cents INTEGER NOT NULL,payment_status TEXT NOT NULL
    );`);
}

export function cutoverState(db) {
  if (!db.prepare("SELECT 1 FROM sqlite_master WHERE type='table' AND name='payments_cutover'").get()) return null;
  return db.prepare('SELECT run_id,snapshot_sha256,phase FROM payments_cutover WHERE id=1').get() || null;
}

export function guardCutover(db, external, probeMode=false) {
  ensureCutoverSchema(db);
  const state=cutoverState(db);
  if (state?.phase==='prepared') throw new Error('Payments maintenance is in progress; resume or roll back the offline cutover.');
  if (state?.phase==='activated' && (!external || !probeMode)) {
    throw new Error('Payments has not been released; use the cutover verification mode.');
  }
  if (state?.phase==='released' && !external) throw new Error('Use both Compose files for this migrated Payments project.');
}

export async function verifyCutoverTarget(db,paymentsUrl,fetcher=fetch) {
  const state=cutoverState(db);
  if (!state || !['activated','released'].includes(state.phase)) return;
  const url=paymentsUrl.replace(/\/api\/payments\/?$/,'')+'/ready';
  const response=await fetcher(url,{signal:AbortSignal.timeout(5000),cache:'no-store'});
  const target=response.ok ? await response.json() : {};
  if (!response.ok || target.history_snapshot_sha256!==state.snapshot_sha256 || target.history_cutover_run_id!==state.run_id) {
    throw new Error('Payments target does not match the committed history snapshot; startup refused.');
  }
}

export function prepareCutover(db,runId,hash,orders) {
  ensureCutoverSchema(db);
  return db.transaction(()=>{
    const old=cutoverState(db);
    if (old && old.phase!=='rolled_back') throw new Error('A cutover already exists; resume it instead of replacing its snapshot.');
    if (db.prepare("SELECT 1 FROM payments_runtime_mode WHERE mode='external'").get()) throw new Error('Payments is already external.');
    if (db.prepare("SELECT 1 FROM broker_outbox WHERE type LIKE 'billing.%' LIMIT 1").get()) throw new Error('Existing billing events require reconciliation before migration.');
    db.prepare('INSERT OR REPLACE INTO payments_cutover(id,run_id,snapshot_sha256,phase) VALUES(1,?,?,?)').run(runId,hash,'prepared');
    db.prepare('DELETE FROM payments_legacy_orders').run();
    const insert=db.prepare('INSERT INTO payments_legacy_orders(order_id,customer_id,provider_id,amount_cents,payment_status) VALUES(?,?,?,?,?)');
    for(const order of orders) insert.run(order.order_id,order.customer_id,order.provider_id,order.amount_cents,order.payment_status);
    return cutoverState(db);
  }).immediate();
}

export function transitionCutover(db,action,proof,currentHash) {
  ensureCutoverSchema(db);
  return db.transaction(()=>{
    const state=cutoverState(db);
    if (!state || state.snapshot_sha256!==currentHash) throw new Error('Frozen source changed; maintenance must remain closed.');
    if (proof?.snapshot_sha256!==state.snapshot_sha256 || proof.unchanged_since_import!==true) {
      throw new Error('Payments import/reconciliation proof is missing or does not match.');
    }
    if (action!=='rollback' && proof.target_empty===true) throw new Error('Payments has not imported this snapshot.');
    if (action==='activate' && state.phase==='prepared') {
      db.prepare("INSERT OR IGNORE INTO payments_runtime_mode(mode) VALUES('external')").run();
      db.prepare("UPDATE payments_cutover SET phase='activated' WHERE id=1").run();
    } else if (action==='release' && state.phase==='activated') {
      db.prepare("UPDATE payments_cutover SET phase='released' WHERE id=1").run();
    } else if (action==='rollback' && ['prepared','activated','rolled_back'].includes(state.phase)) {
      db.prepare("DELETE FROM payments_runtime_mode WHERE mode='external'").run();
      db.prepare("UPDATE payments_cutover SET phase='rolled_back' WHERE id=1").run();
    } else throw new Error('Invalid cutover transition; rollback after public release is not permitted.');
    return cutoverState(db);
  }).immediate();
}
