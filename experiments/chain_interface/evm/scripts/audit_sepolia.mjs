import fs from 'node:fs';
import path from 'node:path';
import {Contract,getBytes} from 'ethers';
import {ROOT,readJSON,writeJSON,artifact,providerFor,sha,analysisDigest,metadataDigest} from './common.mjs';

const state=readJSON('results/sepolia_deployment.json'),config=readJSON('config/sepolia.json');
if(state.status!=='confirmed_on_sepolia')throw Error('No completed public demonstration');
const provider=providerFor(config.rpcUrl,11155111,1000),checks={};
try{
  checks.chainId=Number(BigInt(await provider.send('eth_chainId',[])))===11155111;
  const build=artifact(),contract=new Contract(state.contractAddress,build.abi,provider);
  checks.owner=(await contract.owner()).toLowerCase()===state.deployer.toLowerCase();
  const runtime=Buffer.from(build.deployedBytecode.object.replace(/^0x/,''),'hex');
  const immutableGroups=Object.values(build.deployedBytecode.immutableReferences);
  if(immutableGroups.length!==1)throw Error('Expected only the immutable owner in compiled runtime');
  for(const ref of immutableGroups[0]){
    const owner=Buffer.from(state.deployer.slice(2).toLowerCase().padStart(ref.length*2,'0'),'hex');
    owner.copy(runtime,ref.start);
  }
  const code=await provider.getCode(state.contractAddress);
  checks.deployedRuntimeMatchesCompiler=Buffer.from(getBytes(code)).equals(runtime);
  checks.contractSourceMatches=sha(fs.readFileSync(path.join(ROOT,'src/ModelEvidenceRegistry.sol')))===state.contractSourceSha256;
  const receipts=[];
  for(const t of state.transactions){
    const r=await provider.getTransactionReceipt(t.txHash);
    const block=await provider.getBlock(r.blockNumber);
    const valid=r.status===t.status&&r.gasUsed.toString()===t.gasUsed&&r.blockHash===block.hash&&
      (r.gasUsed*r.gasPrice).toString()===t.feeWei;
    receipts.push({txHash:t.txHash,label:t.label,status:r.status,blockNumber:r.blockNumber,
      gasUsed:r.gasUsed.toString(),blockLinkVerified:valid});
  }
  checks.allRecordedReceiptStatusesAndCosts=receipts.length>=4&&receipts.every(r=>r.blockLinkVerified);
  const payloads=readJSON('evidence/payloads.json'),records=[];
  for(const p of payloads){
    const r=await contract.getRecord(p.recordId),stored=state.records.find(x=>x.recordId===p.recordId);
    const analysis={sourceRecordId:r.sourceRecordId,conclusion:r.conclusion,evidenceHash:r.evidenceHash,
      evidenceURI:r.evidenceURI,modelVersion:r.modelVersion,confidence:r.confidence};
    const valid=r.evidenceHash===p.evidenceHash&&r.modelSpecHash===p.modelSpecHash&&r.resultHash===p.resultHash&&
      analysisDigest(analysis)===p.resultHash&&metadataDigest(r)===r.metadataHash&&
      r.metadataHash===stored.metadataHash&&Number(r.metadataVersion)===stored.metadataVersion;
    records.push({recordId:p.recordId,sourceRecordId:r.sourceRecordId,immutableAndMetadataDigestsVerified:valid,
      metadataVersion:Number(r.metadataVersion),dataName:r.dataName});
  }
  checks.twoNativeRecordDigests=records.length===2&&records.every(r=>r.immutableAndMetadataDigestsVerified);
  const deploymentBlock=state.transactions.find(t=>t.label==='deployment'&&t.status===1).blockNumber;
  const events=await contract.queryFilter(contract.filters.MetadataUpdated(payloads[0].recordId),deploymentBlock);
  checks.metadataRevisionHistory=events.length>=2&&events.every((event,i)=>Number(event.args.version)===i+1&&
    (i===0||event.args.previousMetadataHash===events[i-1].args.metadataHash));
  const totalGas=receipts.reduce((n,r)=>n+BigInt(r.gasUsed),0n);
  const totalFee=state.transactions.reduce((n,r)=>n+BigInt(r.feeWei),0n);
  checks.totalCostsIncludeFailure=totalGas.toString()===state.totalGasUsedIncludingFailedAttempts&&
    totalFee.toString()===state.totalFeeWeiIncludingFailedAttempts;
  checks.withinPublicExperimentLimits=totalGas<=BigInt(config.maximumExperimentGas)&&totalFee<=BigInt(config.maximumExperimentFeeWei);
  const result={schema:'b1-registry-live-sepolia-audit/v1',checkedAtUTC:new Date().toISOString(),
    allPassed:Object.values(checks).every(Boolean),checks,contractAddress:state.contractAddress,receipts,records,
    scope:'Read-only RPC verification of runtime, owner, receipt/block linkage, costs, digests and metadata history; no consensus-security claim.'};
  writeJSON('results/sepolia_live_audit.json',result);console.log(JSON.stringify(result));
  if(!result.allPassed)process.exitCode=1;
}finally{provider.destroy();}
