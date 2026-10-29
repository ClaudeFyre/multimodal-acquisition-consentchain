import fs from 'node:fs';
import path from 'node:path';
import {spawn} from 'node:child_process';
import {Contract} from 'ethers';
import {ROOT,readJSON,writeJSON,providerFor,artifact} from './common.mjs';

const child=spawn('anvil',['--host','127.0.0.1','--port','18547','--chain-id','31337','--hardfork','shanghai',
  '--load-state',path.join(ROOT,'results/anvil_state.json'),'--quiet'],{stdio:'ignore'});
const provider=providerFor('http://127.0.0.1:18547',31337,100);
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
try{
  let ready=false;
  for(let i=0;i<60;i++){
    if(child.exitCode!==null)throw Error('Replay node exited');
    try{ready=Number(BigInt(await provider.send('eth_chainId',[])))===31337;if(ready)break;}catch{}
    await wait(100);
  }
  if(!ready)throw Error('Replay readiness timeout');
  const local=readJSON('results/local_benchmark.json'),payloads=readJSON('evidence/payloads.json');
  const contract=new Contract(local.deployment.contractAddress,artifact().abi,provider);
  const expected=[local.deployment,...local.functional.anchorReceipts,
    local.functional.metadataRevisionReceipt,...readJSON('results/local_receipts.json')];
  let receiptChecks=0;
  for(const e of expected){
    const r=await provider.getTransactionReceipt(e.txHash);
    if(!r||r.status!==1||r.gasUsed.toString()!==e.gasUsed||r.blockNumber!==e.blockNumber)throw Error('Receipt replay mismatch');
    receiptChecks++;
  }
  for(const p of payloads){
    const r=await contract.getRecord(p.recordId);
    if(r.evidenceHash!==p.evidenceHash||r.resultHash!==p.resultHash||r.modelSpecHash!==p.modelSpecHash
      ||r.conclusion!==p.conclusion||r.sourceRecordId!==p.sourceRecordId)throw Error('Record replay mismatch');
  }
  const first=await contract.getRecord(payloads[0].recordId);
  if(Number(first.metadataVersion)!==2||first.dataName!=='FINAL_NAME_TEST')throw Error('Metadata replay mismatch');
  const events=await contract.queryFilter(contract.filters.AnalysisRecorded(),local.deployment.blockNumber);
  if(events.length!==98)throw Error('Expected 2 native plus 96 synthetic analysis events');
  writeJSON('results/replay_audit.json',{allPassed:true,readOnlyReplay:true,chainId:31337,
    receiptChecks,analysisEvents:events.length,nativeRecords:2,metadataRevisionPreserved:true,
    source:'results/anvil_state.json',snapshotWritten:false});
  console.log(JSON.stringify({allPassed:true,receiptChecks,analysisEvents:events.length}));
}finally{provider.destroy();child.kill('SIGTERM');}
