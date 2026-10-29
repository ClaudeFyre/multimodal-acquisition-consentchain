import fs from 'node:fs';
import path from 'node:path';
import {getBytes,verifyMessage} from 'ethers';
import {ROOT,readJSON,writeJSON,sha,canonical,analysisDigest,checkProtocol} from './common.mjs';

const checks={};
const local=readJSON('results/local_benchmark.json');
checks.protocolCommitment=checkProtocol()===local.protocolSha256;
const manifest=readJSON('evidence/b1_evidence_manifest.json');
checks.sixNativeFiles=Object.entries(manifest.files).length===6 && Object.entries(manifest.files).every(([file,hash])=>
  sha(fs.readFileSync(path.resolve(ROOT,'../../..',file))).slice(2)===hash);
const payloads=readJSON('evidence/payloads.json');
checks.originalEvidenceAndAnalysis=payloads.length===2 && payloads.every(p=>
  sha(fs.readFileSync(path.join(ROOT,p.evidenceFile)))===p.evidenceHash &&
  sha(fs.readFileSync(path.join(ROOT,'evidence/model_specification.json')))===p.modelSpecHash &&
  sha(fs.readFileSync(path.join(ROOT,p.resultFile)))===p.canonicalPayloadSha256 &&
  analysisDigest(p)===p.resultHash && sha(Buffer.from(p.sourceRecordId))===p.recordId);
const tests=Object.values(readJSON('results/forge_tests.json')).flatMap(s=>Object.values(s.test_results||{}));
checks.contractTests=tests.length===30 && tests.every(t=>t.status==='Success');
checks.nativeAdapter=readJSON('results/native_adapter_test.json').all_passed===true;
const receipts=readJSON('results/local_receipts.json');
checks.loadReceipts=receipts.length===96 && new Set(receipts.map(r=>r.txHash)).size===96 && receipts.every(r=>r.status===1);
checks.functionalMutations=local.functional.evidenceByteFlipTrials===128 && local.functional.evidenceByteFlipsDetected===128;
checks.metadataImmutability=local.functional.immutableEvidenceAfterRename===true;
const signed=local.benchmarkRows.filter(r=>r.backend==='signed_fsynced_central_log');
const logAudits=[];
for(const row of signed){
  const entries=fs.readFileSync(path.join(ROOT,row.logFile),'utf8').trim().split('\n').map(JSON.parse);
  let head='0x'+'0'.repeat(64);
  for(let i=0;i<entries.length;i++){
    const e=entries[i];
    const hash=sha(Buffer.from(canonical({index:e.index,previousHash:e.previousHash,payload:e.payload})));
    if(e.index!==i||e.previousHash!==head||e.entryHash!==hash||verifyMessage(getBytes(hash),e.signature)!==local.deployment.owner) throw new Error('Signed log verification failed');
    head=hash;
  }
  if(head!==row.checkpointHash||entries.length!==16) throw new Error('Log checkpoint/count mismatch');
  logAudits.push({file:row.logFile,entries:entries.length,checkpointMatched:true});
}
checks.signedLogSignaturesAndCheckpoints=logAudits.length===6;
checks.benchmarkAccounting=local.benchmarkRows.length===12 && local.benchmarkRows.every(row=>
  row.n===16 && Math.abs(row.observedWritesPerSecond-row.n*1000/row.elapsedMilliseconds)<1e-9);
const publicPath=path.join(ROOT,'results/sepolia_deployment.json');
const sepolia=fs.existsSync(publicPath)?readJSON('results/sepolia_deployment.json'):null;
if(sepolia?.status==='confirmed_on_sepolia'){
  checks.sepoliaSuccessfulReceipts=sepolia.chainId===11155111 && sepolia.transactions.filter(t=>t.status===1).length>=4;
  checks.sepoliaTwoNativeRecords=sepolia.records.length===2 && sepolia.records.every(r=>payloads.some(p=>p.recordId===r.recordId&&p.evidenceHash===r.evidenceHash&&p.resultHash===r.resultHash));
  checks.sepoliaIntegrity=sepolia.integrity.originalVerified&&sepolia.integrity.alteredRejected;
}
const result={schema:'b1-registry-artifact-audit/v1',allPassed:Object.values(checks).every(Boolean),checks,
  logAudits,publicNetworkStatus:sepolia?.status||'not_deployed',
  note:'Offline audit of delivered evidence and recorded outcomes; live chain checks are performed by deployment/adapter scripts.'};
writeJSON('results/artifact_audit.json',result);
console.log(JSON.stringify(result));
if(!result.allPassed)process.exitCode=1;
