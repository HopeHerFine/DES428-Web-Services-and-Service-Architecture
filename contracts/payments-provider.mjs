import {spawn} from 'node:child_process';
import {createServer} from 'node:net';
import {fileURLToPath} from 'node:url';
import {resolve} from 'node:path';
import {Verifier} from '@pact-foundation/pact';

const root = fileURLToPath(new URL('../',import.meta.url));
const socket = createServer();
await new Promise(resolve => socket.listen(0,'127.0.0.1',resolve));
const port = socket.address().port;
await new Promise(resolve => socket.close(resolve));
const base = `http://127.0.0.1:${port}`;
const python = process.env.PACT_PYTHON || 'python';
const child = spawn(python,['-m','uvicorn','payments_provider_fixture:app','--host','127.0.0.1','--port',String(port),'--log-level','warning'],{
  cwd:root,stdio:['ignore','inherit','inherit'],env:{...process.env,
    PYTHONPATH:[fileURLToPath(new URL('./',import.meta.url)),fileURLToPath(new URL('../services/payments',import.meta.url))].join(process.platform==='win32'?';':':'),
    OTEL_EXPORTER_OTLP_ENDPOINT:'',NOTIFICATIONS_FAULT_FILE:''}});
let spawnError;
child.on('error', error => {spawnError=error;});
try {
  let ready=false;
  for(let i=0;i<100;i++) {
    if(spawnError) throw spawnError;
    if(child.exitCode!==null) throw new Error('Pact fixture exited before startup');
    try {if((await fetch(base+'/ready')).ok) {ready=true;break;}} catch {}
    await new Promise(resolve=>setTimeout(resolve,100));
  }
  if(!ready) throw new Error('Pact provider startup timed out');
  const setup = async state => {
    const response=await fetch(base+'/_pact/state',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({state})});
    if(!response.ok) throw new Error('Provider state setup failed');
  };
  await new Verifier({provider:'Payments',providerBaseUrl:base,
    pactUrls:[process.env.PACT_PAYMENTS_FILE ? resolve(process.env.PACT_PAYMENTS_FILE) : fileURLToPath(new URL('./pacts/HomeserviceWeb-Payments.json',import.meta.url))],
    stateHandlers:Object.fromEntries(['payable booking','settled booking','settled completed booking'].map(name=>[name,()=>setup(name)])),logLevel:'error'}).verifyProvider();
  console.log('PASS: real Payments FastAPI provider verified all six consumer interactions.');
} finally {
  if(child.exitCode===null) {
    const stopped=new Promise(resolve=>child.once('exit',resolve));
    child.kill();
    await stopped;
  }
}
