import {test} from 'node:test';
import assert from 'node:assert/strict';
import Database from 'better-sqlite3';
import {ensureCutoverSchema,prepareCutover,transitionCutover,guardCutover,cutoverState,verifyCutoverTarget} from '../lib/modules/payments/cutover-state.js';

function fixture() {
  const db=new Database(':memory:');
  db.exec('CREATE TABLE broker_outbox(type TEXT);');
  ensureCutoverSchema(db);
  return db;
}
const id='11111111-1111-4111-8111-111111111111';
const hash='a'.repeat(64);
const proof={snapshot_sha256:hash,unchanged_since_import:true,target_empty:false};

test('cutover closes startup until verified, then requires the imported target',async()=>{
  const db=fixture();
  try {
    prepareCutover(db,id,hash,[]);
    assert.throws(()=>guardCutover(db,false),/maintenance/);
    assert.throws(()=>guardCutover(db,true,true),/maintenance/);
    assert.throws(()=>transitionCutover(db,'activate',{...proof,target_empty:true},hash),/not imported/);
    transitionCutover(db,'activate',proof,hash);
    assert.throws(()=>guardCutover(db,true),/not been released/);
    guardCutover(db,true,true);
    await assert.rejects(verifyCutoverTarget(db,'http://payments:8000/api/payments',async()=>({ok:true,json:async()=>({history_snapshot_sha256:null})})),/does not match/);
    await verifyCutoverTarget(db,'http://payments:8000/api/payments',async()=>({ok:true,json:async()=>({history_snapshot_sha256:hash,history_cutover_run_id:id})}));
    transitionCutover(db,'release',proof,hash);
    guardCutover(db,true);
    assert.throws(()=>guardCutover(db,false),/both Compose/);
    assert.throws(()=>transitionCutover(db,'rollback',proof,hash),/rollback after public/);
  } finally {db.close();}
});

test('rollback before release restores legacy mode and preserves the source witness',()=>{
  const db=fixture();
  try {
    prepareCutover(db,id,hash,[{order_id:8001,customer_id:1,provider_id:1,amount_cents:107000,payment_status:'paid'}]);
    transitionCutover(db,'activate',proof,hash);
    assert.throws(()=>transitionCutover(db,'rollback',proof,'b'.repeat(64)),/source changed/);
    assert.throws(()=>transitionCutover(db,'rollback',{...proof,unchanged_since_import:false},hash),/proof/);
    transitionCutover(db,'rollback',proof,hash);
    guardCutover(db,false);
    assert.equal(db.prepare('SELECT COUNT(*) AS n FROM payments_runtime_mode').get().n,0);
    assert.equal(db.prepare('SELECT COUNT(*) AS n FROM payments_legacy_orders').get().n,1);
    assert.equal(cutoverState(db).phase,'rolled_back');
  } finally {db.close();}
});

test('old billing producer history prevents a legacy cutover',()=>{
  const db=fixture();
  try {
    db.prepare('INSERT INTO broker_outbox(type) VALUES(?)').run('billing.booking_created');
    assert.throws(()=>prepareCutover(db,id,hash,[]),/billing events/);
    assert.equal(cutoverState(db),null);
  } finally {db.close();}
});
