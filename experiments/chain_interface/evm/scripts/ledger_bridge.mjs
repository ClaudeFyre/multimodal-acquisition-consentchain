import fs from 'node:fs';
import path from 'node:path';
import {Contract,ContractFactory,Wallet} from 'ethers';
import {ROOT,readJSON,writeJSON,sha,analysisInput,analysisDigest,artifact,providerFor} from './common.mjs';

let input=''; for await(const chunk of process.stdin) input+=chunk;
const request=JSON.parse(input);
if(![31337,11155111].includes(request.chain_id)) throw new Error('Unsupported chain');
const provider=providerFor(request.rpc_url,request.chain_id,request.chain_id===31337?100:1000);
let contract;
async function signingAccount() {
  if(request.chain_id===31337) return provider.getSigner(request.sender||0);
  const dir=path.resolve(process.env.MODEL_REGISTRY_SECRET_DIR||path.join(ROOT,'secrets'));
  return (await Wallet.fromEncryptedJson(fs.readFileSync(path.join(dir,'sepolia-keystore.json'),'utf8'),
    fs.readFileSync(path.join(dir,'keystore-password.txt'),'utf8'))).connect(provider);
}
const payloadFromRecord=r=>({record_id:r.sourceRecordId,conclusion:r.conclusion,evidence_hash:r.evidenceHash.slice(2),
  evidence_uri:r.evidenceURI,model_version:r.modelVersion,confidence:r.confidence});
const pFromPayload=(p,m)=>({recordId:sha(Buffer.from(p.record_id)),sourceRecordId:p.record_id,
  conclusion:p.conclusion,evidenceHash:'0x'+p.evidence_hash.replace(/^0x/,''),evidenceURI:p.evidence_uri,
  modelVersion:p.model_version,confidence:p.confidence,modelSpecHash:sha(fs.readFileSync(path.join(ROOT,'evidence/model_specification.json'))),
  dataName:m?.dataName||p.record_id,description:m?.description||'B1 model-experiment evidence'});
async function rows() {
  const logs=await contract.queryFilter(contract.filters.AnalysisRecorded(),request.deployment_block||0,'latest');
  const result=[];
  for(const log of logs) {
    const r=await contract.getRecord(log.args.recordId);
    const receipt=await provider.getTransactionReceipt(log.transactionHash),block=await provider.getBlock(log.blockNumber);
    const p={sourceRecordId:r.sourceRecordId,conclusion:r.conclusion,evidenceHash:r.evidenceHash,evidenceURI:r.evidenceURI,
      modelVersion:r.modelVersion,confidence:r.confidence};
    const valid=receipt.status===1 && receipt.blockHash===block.hash &&
      receipt.to.toLowerCase()===request.contract_address.toLowerCase() &&
      sha(Buffer.from(r.sourceRecordId))===log.args.recordId && analysisDigest(p)===r.resultHash;
    result.push({receipt:{tx_id:log.transactionHash,index:log.blockNumber,prev_hash:block.parentHash,status:'confirmed',
      submitter:r.submitter,contract:request.contract_address,submitted_at:0,confirmed_at:0,gas_used:Number(receipt.gasUsed)},
      event:{kind:'ANALYSIS_RECORD',payload:payloadFromRecord(r),org:request.logical_org||'b1-analysis',ts:Number(r.createdAt)},
      verification:{valid,block_hash:block.hash,result_hash:r.resultHash,metadata_version:Number(r.metadataVersion)}});
  }
  return result;
}

try {
  if(Number(BigInt(await provider.send('eth_chainId',[])))!==request.chain_id) throw new Error('RPC chain mismatch');
  const build=artifact();
  if(request.action==='deploy_local') {
    if(request.chain_id!==31337) throw new Error('Local helper cannot deploy to public networks');
    const factory=new ContractFactory(build.abi,build.bytecode.object,await signingAccount());
    const c=await factory.deploy(),receipt=await c.deploymentTransaction().wait();
    process.stdout.write(JSON.stringify({contract_address:await c.getAddress(),deployment_block:receipt.blockNumber,tx_hash:receipt.hash}));
  } else {
    contract=new Contract(request.contract_address,build.abi,provider);
    if(request.action==='events'||request.action==='verify') {
      const history=await rows();
      process.stdout.write(JSON.stringify(request.action==='events'?history:{valid:history.length>0 && history.every(x=>x.verification.valid),records:history.length,
        verificationScope:'RPC receipt/block linkage and contract payload digests; consensus delegated to the RPC node'}));
    } else if(request.action==='append') {
      const event=request.event;
      if(event.kind!=='ANALYSIS_RECORD') throw new Error('This backend implements B1 ANALYSIS_RECORD only; A2 events are out of scope');
      const key=event.payload.record_id.split('/')[1];
      const metadata=readJSON('config/metadata.json').records.find(x=>x.key===key);
      const p=pFromPayload(event.payload,metadata);p.resultHash=analysisDigest(p);
      const previous=(await rows()).find(x=>x.event.payload.record_id===event.payload.record_id);
      if(previous) {
        const old=previous.event.payload;
        if(old.conclusion!==event.payload.conclusion || old.evidence_hash!==event.payload.evidence_hash ||
          old.model_version!==event.payload.model_version || old.evidence_uri!==event.payload.evidence_uri || old.confidence!==event.payload.confidence) {
          throw new Error('Record id already exists with different immutable content');
        }
        process.stdout.write(JSON.stringify({receipt:previous.receipt,reused:true}));
      } else {
        contract=contract.connect(await signingAccount());
        const submitted=Date.now()/1000;
        const tx=await contract.anchorAnalysis(analysisInput(p));
        const receipt=await provider.waitForTransaction(tx.hash,1,180000),confirmed=Date.now()/1000;
        if(receipt.status!==1) throw new Error('Anchor transaction failed');
        const block=await provider.getBlock(receipt.blockNumber);
        process.stdout.write(JSON.stringify({receipt:{tx_id:tx.hash,index:receipt.blockNumber,prev_hash:block.parentHash,
          status:'confirmed',submitter:await contract.runner.getAddress(),contract:request.contract_address,
          submitted_at:submitted,confirmed_at:confirmed,gas_used:Number(receipt.gasUsed)},reused:false}));
      }
    } else throw new Error('Unsupported bridge action');
  }
} catch(error) {console.error(error.shortMessage||error.message);process.exitCode=1;}
finally {provider.destroy();}
