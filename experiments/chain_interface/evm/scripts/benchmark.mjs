import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import {spawn,execFileSync} from 'node:child_process';
import {once} from 'node:events';
import {ContractFactory,NonceManager,Wallet,getBytes,toBeHex,verifyMessage} from 'ethers';
import {ROOT,readJSON,writeJSON,sha,canonical,now,analysisInput,analysisDigest,artifact,providerFor,summary,checkProtocol,measuredTransaction} from './common.mjs';

const protocol=readJSON('config/protocol.json');
const protocolHash=checkProtocol();
const local=protocol.local;
const resultDir=path.join(ROOT,'results'); fs.mkdirSync(resultDir,{recursive:true});
const logHandle=fs.openSync(path.join(resultDir,'anvil.log'),'a');
const port=Number(process.env.MODEL_LOCAL_PORT || 18545);
const child=spawn('anvil',['--host','127.0.0.1','--port',String(port),'--chain-id',String(local.chainId),
  '--hardfork',local.hardfork,'--block-time',String(local.blockTimeSeconds),'--gas-limit',String(local.blockGasLimit),
  '--dump-state',path.join(resultDir,'anvil_state.json'),'--preserve-historical-states','--quiet'],
  {stdio:['ignore',logHandle,logHandle]});
const provider=providerFor('http://127.0.0.1:'+port,local.chainId,local.receiptPollingMilliseconds);
const receipts=[];
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const overrides={gasLimit:1500000n,maxFeePerGas:2000000000n,maxPriorityFeePerGas:1000000000n};

async function ready() {
  for(let i=0;i<80;i++) {
    if(child.exitCode!==null) throw new Error('Anvil exited before readiness');
    try {if(Number(BigInt(await provider.send('eth_chainId',[])))===local.chainId) return;} catch {}
    await wait(100);
  }
  throw new Error('Anvil readiness timeout');
}

function verifyFiles(p) {
  const bytes=fs.readFileSync(path.join(ROOT,p.evidenceFile));
  if(sha(bytes)!==p.evidenceHash) return false;
  const manifest=readJSON('evidence/b1_evidence_manifest.json');
  for(const [relative,digest] of Object.entries(manifest.files)) {
    if(sha(fs.readFileSync(path.resolve(ROOT,'../../..',relative))).slice(2)!==digest) return false;
  }
  return sha(fs.readFileSync(path.join(ROOT,'evidence/model_specification.json')))===p.modelSpecHash
    && sha(fs.readFileSync(path.join(ROOT,p.resultFile)))===p.canonicalPayloadSha256
    && analysisDigest(p)===p.resultHash;
}

function syntheticPayload(kind,rep,index) {
  const prefix=`${kind.name}/${rep}/${index}`;
  const p={recordId:sha(Buffer.from(prefix)),evidenceHash:sha(Buffer.from('evidence/'+prefix)),
    modelSpecHash:sha(Buffer.from('model-spec/'+prefix)),
    evidenceURI:'urn:sha256:'+sha(Buffer.from('evidence/'+prefix)).slice(2),
    dataName:'N'.repeat(kind.nameBytes),description:'D'.repeat(kind.descriptionBytes),
    sourceRecordId:prefix,conclusion:'Synthetic registry load record; no model inference.',
    modelVersion:'benchmark-v1',confidence:'not applicable'};
  p.resultHash=analysisDigest(p); return p;
}

async function logBenchmark(wallet,payloads,kind,rep) {
  const relative=`results/central_${kind.name}_${rep}.jsonl`;
  const file=path.join(ROOT,relative); const fd=fs.openSync(file,'w');
  let head='0x'+'0'.repeat(64); const entries=[],latencies=[]; const begin=now();
  try {
    for(const payload of payloads) {
      const start=now(); const body={index:entries.length,previousHash:head,payload};
      const entryHash=sha(Buffer.from(canonical(body)));
      const signature=await wallet.signMessage(getBytes(entryHash));
      const entry={...body,entryHash,signature,signer:wallet.address};
      fs.writeSync(fd,canonical(entry)+'\n'); fs.fsyncSync(fd);
      latencies.push(now()-start); entries.push(entry); head=entryHash;
    }
  } finally {fs.closeSync(fd);}
  const duration=now()-begin;
  const valid=(rows,pinnedHead)=>{
    let previous='0x'+'0'.repeat(64);
    for(let i=0;i<rows.length;i++) {
      const e=rows[i];
      if(e.index!==i || e.previousHash!==previous) return false;
      const hash=sha(Buffer.from(canonical({index:e.index,previousHash:e.previousHash,payload:e.payload})));
      if(hash!==e.entryHash || verifyMessage(getBytes(hash),e.signature)!==wallet.address) return false;
      previous=hash;
    }
    return pinnedHead===undefined || previous===pinnedHead;
  };
  const changed=structuredClone(entries); changed[0].payload.resultHash=sha(Buffer.from('changed'));
  const prefix=entries.slice(0,-1);
  const checks={intact:valid(entries,head),modifiedEntryRejected:!valid(changed,head),
    truncatedLogAcceptedWithoutCheckpoint:valid(prefix),truncatedLogRejectedWithCheckpoint:!valid(prefix,head)};
  if(!checks.intact || !checks.modifiedEntryRejected || !checks.truncatedLogRejectedWithCheckpoint) throw new Error('Central log functional check failed');
  return {backend:'signed_fsynced_central_log',payloadClass:kind.name,replicate:rep,n:payloads.length,
    elapsedMilliseconds:duration,observedWritesPerSecond:payloads.length*1000/duration,
    latencyMilliseconds:summary(latencies),individualLatencyMilliseconds:latencies,checkpointHash:head,logFile:relative,checks};
}

try {
  await ready();
  const wallet=Wallet.createRandom().connect(provider);
  await provider.send('anvil_setBalance',[wallet.address,toBeHex(1000n*10n**18n)]);
  const signer=new NonceManager(wallet);
  const build=artifact(); const factory=new ContractFactory(build.abi,build.bytecode.object,signer);
  const start=now(); const contract=await factory.deploy({gasLimit:3000000n,...Object.fromEntries(Object.entries(overrides).filter(([k])=>k!=='gasLimit'))});
  const deploymentTx=contract.deploymentTransaction();
  const deploymentReceipt=await provider.waitForTransaction(deploymentTx.hash,1,30000);
  const address=await contract.getAddress();
  const deployment={contractAddress:address,owner:wallet.address,txHash:deploymentTx.hash,blockNumber:deploymentReceipt.blockNumber,
    gasUsed:deploymentReceipt.gasUsed.toString(),receiptLatencyMilliseconds:now()-start};
  console.log(JSON.stringify({phase:'local_deployed',address,gasUsed:deployment.gasUsed}));

  const payloads=readJSON('evidence/payloads.json'); const anchorReceipts=[];
  for(const p of payloads) {
    if(!verifyFiles(p)) throw new Error('Evidence bundle verification failed: '+p.key);
    await measuredTransaction(p.key,()=>contract.anchorAnalysis(analysisInput(p),overrides),provider,anchorReceipts);
    const stored=await contract.getRecord(p.recordId);
    if(stored.evidenceHash!==p.evidenceHash || stored.modelSpecHash!==p.modelSpecHash || stored.resultHash!==p.resultHash) throw new Error('On-chain round-trip mismatch');
  }
  const first=payloads[0]; const before=await contract.getRecord(first.recordId);
  const revision=await measuredTransaction('metadata_revision',()=>contract.updateMetadata(first.recordId,'FINAL_NAME_TEST','Description revision test; author metadata remains pending.',overrides),provider);
  const after=await contract.getRecord(first.recordId);
  const immutableAfterRename=before.evidenceHash===after.evidenceHash && before.modelSpecHash===after.modelSpecHash
    && before.resultHash===after.resultHash && before.evidenceURI===after.evidenceURI && Number(after.metadataVersion)===2;
  if(!immutableAfterRename) throw new Error('Metadata revision changed evidence');
  let detected=0;
  const bytes=fs.readFileSync(path.join(ROOT,first.evidenceFile));
  for(let i=0;i<protocol.functional.evidenceBitFlipTrials;i++) {
    const changed=Buffer.from(bytes); changed[i%changed.length]^=(1<<(i%8));
    if(!await contract.verifyEvidence(first.recordId,sha(changed))) detected++;
  }
  const revisionEvents=await contract.queryFilter(contract.filters.MetadataUpdated(first.recordId),deploymentReceipt.blockNumber);
  if(detected!==protocol.functional.evidenceBitFlipTrials || revisionEvents.length!==2) throw new Error('Integrity or metadata history check failed');

  const rows=[];
  for(const kind of local.payloadClasses) {
    for(let rep=0;rep<local.benchmarkReplicates;rep++) {
      const workload=Array.from({length:local.recordsPerReplicate},(_,i)=>syntheticPayload(kind,rep,i));
      const evmRun=async()=>{
        const all=[],begin=now();
        for(let i=0;i<workload.length;i+=local.concurrentSubmissions) {
          await Promise.all(workload.slice(i,i+local.concurrentSubmissions).map(p=>measuredTransaction(
            `${kind.name}/${rep}/${p.recordId}`,()=>contract.anchorAnalysis(analysisInput(p),overrides),provider,all)));
        }
        const elapsed=now()-begin; receipts.push(...all.map(x=>({...x,payloadClass:kind.name,replicate:rep})));
        return {backend:'local_evm',payloadClass:kind.name,replicate:rep,n:all.length,elapsedMilliseconds:elapsed,
          observedWritesPerSecond:all.length*1000/elapsed,latencyMilliseconds:summary(all.map(x=>x.receiptLatencyMilliseconds)),
          gasUsed:summary(all.map(x=>Number(x.gasUsed)))};
      };
      if(rep%2===0) {rows.push(await evmRun()); rows.push(await logBenchmark(wallet,workload,kind,rep));}
      else {rows.push(await logBenchmark(wallet,workload,kind,rep)); rows.push(await evmRun());}
      writeJSON('results/local_receipts.json',receipts);
      writeJSON('results/local_benchmark_partial.json',rows);
      console.log(JSON.stringify({phase:'benchmark_replicate',payloadClass:kind.name,replicate:rep+1,total:local.benchmarkReplicates}));
    }
  }
  const text=command=>{try{return execFileSync(command[0],command.slice(1),{encoding:'utf8'}).trim();}catch{return 'unavailable';}};
  const result={schema:'registry-local-experiment/v1',status:'passed',createdAtUTC:new Date().toISOString(),
    protocolSha256:protocolHash,scope:protocol.scope,
    environment:{platform:os.platform(),release:os.release(),architecture:os.arch(),cpu:os.cpus()[0]?.model,
      logicalCpus:os.cpus().length,totalMemoryBytes:os.totalmem(),node:process.version,
      forge:text(['forge','--version']),anvil:text(['anvil','--version']),solc:text(['solc','--version'])},
    chain:{chainId:local.chainId,blockTimeSeconds:local.blockTimeSeconds,hardfork:local.hardfork,
      concurrentSubmissions:local.concurrentSubmissions,receiptPollingMilliseconds:local.receiptPollingMilliseconds},
    deployment,functional:{anchorReceipts,metadataRevisionReceipt:revision,evidenceByteFlipTrials:protocol.functional.evidenceBitFlipTrials,
      evidenceByteFlipsDetected:detected,metadataEvents:revisionEvents.length,immutableEvidenceAfterRename:immutableAfterRename,
      sourceModelTrainingRepeated:false},benchmarkRows:rows};
  writeJSON('results/local_benchmark.json',result);
  console.log(JSON.stringify({phase:'complete',status:result.status,benchmarkWrites:receipts.length,
    integrityChecksDetected:detected,deploymentGas:deployment.gasUsed}));
} catch(error) {
  writeJSON('results/local_failure.json',{createdAtUTC:new Date().toISOString(),message:error.shortMessage||error.message});
  console.error(error.shortMessage||error.message); process.exitCode=1;
} finally {
  provider.destroy(); child.kill('SIGINT');
  await Promise.race([once(child,'exit'),wait(3000)]); fs.closeSync(logHandle);
}
