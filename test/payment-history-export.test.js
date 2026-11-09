import {test} from 'node:test';
import assert from 'node:assert/strict';
import {freshBoot,getDb} from '../test-helpers/boot.js';
import {placeBooking} from '../lib/modules/booking/service.js';
import {simulateSucceeded} from '../lib/modules/payments/gateway.js';
import {paymentHistory} from '../scripts/export-payments-history.mjs';
import {futureWeekday} from '../test-helpers/auth.js';

freshBoot();
test('history export takes a coherent financial snapshot without credentials, OTP or source writes',()=>{
  const placed=placeBooking(1,{provider_id:1,service_date:futureWeekday(3),starting_time:'09:00',
    items:[{service_id:2,quantity:1}],payment_method:'gateway'},'history-export');
  simulateSucceeded(placed.body.order.id,1);
  const db=getDb();
  const before=db.prepare('SELECT total_changes() AS n').get().n;
  const snapshot=paymentHistory(db,'fixture-source');
  assert.equal(db.prepare('SELECT total_changes() AS n').get().n,before);
  assert.equal(snapshot.orders[0].payment_status,'paid');
  assert.equal(snapshot.intents[0].status,'succeeded');
  assert.equal(snapshot.transactions[0].kind,'charge');
  assert.equal(snapshot.orders[0].commission_cents,Math.round(placed.body.order.total_cents*placed.body.order.commission_pct/100));
  assert.doesNotMatch(JSON.stringify(snapshot),/password|otp|email|address/i);
  assert.throws(()=>paymentHistory(db,''),/source identifier/);
});
