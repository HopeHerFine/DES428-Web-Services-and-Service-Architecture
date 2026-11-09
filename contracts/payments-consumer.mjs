import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
import {rm} from 'node:fs/promises';
import {PactV3, MatchersV3 as M} from '@pact-foundation/pact';

await rm(fileURLToPath(new URL('./pacts/HomeserviceWeb-Payments.json',import.meta.url)),{force:true});
const pact = new PactV3({consumer:'HomeserviceWeb',provider:'Payments',
  dir:fileURLToPath(new URL('./pacts',import.meta.url)),logLevel:'error'});
const json = {'Content-Type':'application/json'};
const headers = token => ({Authorization:`Bearer ${token}`});
const charge = {id:M.integer(1),order_id:8001,kind:'charge',amount_cents:107000,
  method:'gateway',status:'succeeded',created_at:M.like('2026-01-01T00:00:00+00:00')};

pact.given('payable booking').uponReceiving('read own payment intent')
  .withRequest({method:'GET',path:'/api/payments/intents/8001',headers:headers('pact-customer')})
  .willRespondWith({status:200,headers:json,body:{order_id:8001,amount_cents:107000,status:'requires_payment',method:'gateway'}});
pact.given('payable booking').uponReceiving('settle own payment using an idempotency key')
  .withRequest({method:'POST',path:'/api/payments/simulate',headers:{...headers('pact-customer'),
    'Content-Type':'application/json','Idempotency-Key':'pact-payment-once'},body:{order_id:8001}})
  .willRespondWith({status:200,headers:json,body:{ok:true,order_id:8001,status:'succeeded'}});
pact.given('payable booking').uponReceiving('reject another customer reading payment')
  .withRequest({method:'GET',path:'/api/payments/intents/8001',headers:headers('pact-other')})
  .willRespondWith({status:403,headers:json,body:{detail:'You do not own this payment'}});
pact.given('payable booking').uponReceiving('reject invalid payment credentials')
  .withRequest({method:'GET',path:'/api/payments/intents/8001',headers:headers('invalid')})
  .willRespondWith({status:401,headers:json,body:{detail:'Invalid bearer token'}});
pact.given('settled completed booking').uponReceiving('read provider wallet with remote ledger')
  .withRequest({method:'GET',path:'/api/payments/wallet',headers:headers('pact-provider')})
  .willRespondWith({status:200,headers:json,body:{provider_id:1,balance_cents:96300,commission_owed_cents:0,
    transactions:[{...charge,id:M.integer(2),kind:'payout_credit',amount_cents:96300},charge]}});
pact.given('settled booking').uponReceiving('read customer payment transactions')
  .withRequest({method:'GET',path:'/api/payments/transactions',headers:headers('pact-customer')})
  .willRespondWith({status:200,headers:json,body:M.eachLike(charge,1)});

await pact.executeTest(async server => {
  process.env.PAYMENTS_SERVICE_URL=server.url+'/api/payments';
  const {remotePayments}=await import('../lib/modules/payments/client.js');
  assert.equal((await remotePayments('pact-customer','/intents/8001')).amount_cents,107000);
  assert.deepEqual(await remotePayments('pact-customer','/simulate',{method:'POST',body:{order_id:8001},key:'pact-payment-once'}),
    {ok:true,order_id:8001,status:'succeeded'});
  await assert.rejects(remotePayments('pact-other','/intents/8001'),error=>error.statusCode===403);
  await assert.rejects(remotePayments('invalid','/intents/8001'),error=>error.statusCode===401);
  const wallet=await remotePayments('pact-provider','/wallet');
  assert.equal(wallet.balance_cents,96300);
  assert.equal(wallet.transactions[0].kind,'payout_credit');
  assert.equal((await remotePayments('pact-customer','/transactions'))[0].kind,'charge');
});
console.log('PASS: six Payments interactions generated using the real web client.');
