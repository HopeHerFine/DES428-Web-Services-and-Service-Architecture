import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { rm } from 'node:fs/promises';
import { PactV3, MatchersV3 as M } from '@pact-foundation/pact';

// Pact merges interactions into existing files; regenerate so removed consumer
// interactions cannot survive from an earlier run.
await rm(fileURLToPath(new URL('./pacts/HomeserviceWeb-Notifications.json', import.meta.url)), {force:true});

const pact = new PactV3({consumer: 'HomeserviceWeb', provider: 'Notifications',
  dir: fileURLToPath(new URL('./pacts', import.meta.url)), logLevel: 'error'});
const notification = {id: M.integer(41), type: 'rating_request', title: M.like('How did it go?'),
  body: M.like('Booking #8001 is complete'), order_id: 8001, read_at: null,
  created_at: M.like('2026-01-01T00:00:00')};
const json = {'Content-Type': 'application/json'};
pact.given('customer has unread notification').uponReceiving('list own inbox')
  .withRequest({method:'GET',path:'/api/notifications',headers:{Authorization:'Bearer pact-customer'}})
  .willRespondWith({status:200,headers:json,body:M.eachLike(notification,1)});
pact.given('customer has unread notification').uponReceiving('mark own notification read with idempotency key')
  .withRequest({method:'POST',path:'/api/notifications/41/read',headers:{Authorization:'Bearer pact-customer',
    'Idempotency-Key':M.regex('^[a-f0-9-]{36}$','11111111-1111-4111-8111-111111111111')}})
  .willRespondWith({status:200,headers:json,body:{...notification,read_at:M.like('2026-01-01T00:01:00')}});
pact.given('customer has unread notification').uponReceiving('reject another customer marking notification read')
  .withRequest({method:'POST',path:'/api/notifications/41/read',headers:{Authorization:'Bearer pact-other',
    'Idempotency-Key':M.regex('^[a-f0-9-]{36}$','22222222-2222-4222-8222-222222222222')}})
  .willRespondWith({status:403,headers:json,body:{detail:'not your notification'}});
pact.given('empty inbox').uponReceiving('list empty inbox')
  .withRequest({method:'GET',path:'/api/notifications',headers:{Authorization:'Bearer pact-other'}})
  .willRespondWith({status:200,headers:json,body:[]});
pact.given('empty inbox').uponReceiving('reject invalid credentials')
  .withRequest({method:'GET',path:'/api/notifications',headers:{Authorization:'Bearer invalid'}})
  .willRespondWith({status:401,headers:json,body:{detail:'invalid token'}});

await pact.executeTest(async server => {
  process.env.NOTIFICATIONS_SERVICE_URL = server.url + '/api/notifications';
  const {remoteNotifications} = await import('../lib/modules/notifications/client.js');
  const rows = await remoteNotifications('pact-customer');
  assert.equal(rows[0].id,41);
  assert.equal(rows[0].read_at,null);
  const read = await remoteNotifications('pact-customer','/41/read','POST');
  assert.equal(typeof read.read_at,'string');
  await assert.rejects(remoteNotifications('pact-other','/41/read','POST'), error => error.statusCode === 403);
  assert.deepEqual(await remoteNotifications('pact-other'),[]);
  await assert.rejects(remoteNotifications('invalid'), error => error.statusCode === 401);
});
console.log('PASS: five consumer interactions generated using the real Notifications client.');
