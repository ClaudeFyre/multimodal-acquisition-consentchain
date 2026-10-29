import fs from 'node:fs';
import path from 'node:path';
import {randomBytes} from 'node:crypto';
import {Contract,ContractFactory,NonceManager,Wallet,formatEther,formatUnits,parseUnits,getCreateAddress} from 'ethers';
import {ROOT,readJSON,writeJSON,sha,now,analysisInput,analysisDigest,artifact,providerFor,metadataDigest,checkProtocol} from './common.mjs';

const mode=process.argv[2]||'status';
if(!['prepare','status','deploy','update-metadata'].includes(mode)) throw new Error('Unknown mode');
const config=readJSON('config/sepolia.json');
if(config.chainId!==11155111) throw new Error('This deployment script is restricted to Ethereum Sepolia');
const provider=providerFor(process.env.SEPOLIA_RPC_URL||config.rpcUrl,config.chainId,1000);
const secretDir=path.resolve(process.env.MODEL_REGISTRY_SECRET_DIR||path.join(ROOT,'secrets'));
const keystoreFile=path.join(secretDir,'sepolia-keystore.json');
const passwordFile=path.join(secretDir,'keystore-password.txt');
const stateRelative='results/sepolia_deployment.json';
const statePath=path.join(ROOT,stateRelative);
const state=fs.existsSync(statePath)?readJSON(stateRelative):{schema:'registry-sepolia-experiment/v1',chainId:config.chainId,status:'prepared',transactions:[],records:[]};
const persist=()=>writeJSON(stateRelative,state);
const timers=new Map();
const receiptFields=receipt=>({status:receipt.status,blockNumber:receipt.blockNumber,gasUsed:receipt.gasUsed.toString(),
  gasPriceWei:receipt.gasPrice.toString(),feeWei:(receipt.gasUsed*receipt.gasPrice).toString(),
  receiptObservedUTC:new Date().toISOString(),confirmationsRequested:config.receiptConfirmations});

async function recoverReceipts() {
  for(const row of state.transactions) {
    if(row.status!==undefined) continue;
    const receipt=await provider.getTransactionReceipt(row.txHash);
    if(receipt) Object.assign(row,receiptFields(receipt),{latencyUnavailableAfterProcessResume:true});
  }
  persist();
}

async function gasAllowance(estimate) {
  const gasLimit=(estimate*BigInt(100+config.gasEstimateMarginPercent)+99n)/100n;
  if(gasLimit>BigInt(config.maximumTransactionGas)) throw new Error('Estimated transaction exceeds configured per-transaction gas ceiling');
  return {estimatedGas:estimate.toString(),gasLimit:gasLimit.toString(),gasEstimateMarginPercent:config.gasEstimateMarginPercent};
}

async function wallet() {
  if(!fs.existsSync(keystoreFile)) {
    if(!['prepare','status'].includes(mode)) throw new Error('Run npm run sepolia:prepare first');
    fs.mkdirSync(secretDir,{recursive:true,mode:0o700}); fs.chmodSync(secretDir,0o700);
    const fresh=Wallet.createRandom(), password=randomBytes(32).toString('hex');
    const encrypted=await fresh.encrypt(password);
    fs.writeFileSync(passwordFile,password,{mode:0o600});
    fs.writeFileSync(keystoreFile,encrypted,{mode:0o600});
    return fresh.connect(provider);
  }
  return (await Wallet.fromEncryptedJson(fs.readFileSync(keystoreFile,'utf8'),fs.readFileSync(passwordFile,'utf8'))).connect(provider);
}

async function fees() {
  const block=await provider.getBlock('latest');
  let tip; try{tip=BigInt(await provider.send('eth_maxPriorityFeePerGas',[]));}catch{tip=parseUnits('1','gwei');}
  const cap=parseUnits(config.maximumFeePerGasGwei,'gwei');
  const base=block.baseFeePerGas||0n;
  if(base+tip>cap) throw new Error('Current base fee plus suggested tip exceeds configured 3-gwei experiment cap');
  return {maxFeePerGas:base*2n+tip>cap?cap:base*2n+tip,maxPriorityFeePerGas:tip};
}

async function tracked(label,send,extra={},allowance=null) {
  let row=state.transactions.filter(x=>x.label===label).at(-1);
  if(row?.status===1) return row;
  if(row?.status===0) row=null;
  if(!row) {
    if(!allowance) throw new Error('An RPC gas estimate is required before a new transaction');
    const nextGasLimit=BigInt(allowance.gasLimit);
    const usedGas=state.transactions.reduce((n,t)=>n+BigInt(t.gasUsed||t.gasLimit||0),0n);
    const usedFee=state.transactions.reduce((n,t)=>n+BigInt(t.feeWei||0),0n);
    const quotedFee=await fees();
    if(usedGas+nextGasLimit>BigInt(config.maximumExperimentGas)) throw new Error('Total experiment gas budget exceeded, including failed attempts');
    if(usedFee+nextGasLimit*quotedFee.maxFeePerGas>BigInt(config.maximumExperimentFeeWei)) throw new Error('Total quoted experiment fee exceeds its test-ETH ceiling');
    const startedUTC=new Date().toISOString(),start=now();
    const tx=await send({...quotedFee,gasLimit:nextGasLimit});
    row={label,txHash:tx.hash,nonce:tx.nonce,startedUTC,submissionMilliseconds:now()-start,
      explorerURL:config.explorerBase+'/tx/'+tx.hash,attempt:state.transactions.filter(x=>x.label===label).length+1,
      ...allowance,...extra};
    timers.set(tx.hash,start); state.transactions.push(row); persist();
  }
  const receipt=await provider.waitForTransaction(row.txHash,config.receiptConfirmations,180000);
  if(!receipt) throw new Error(label+' has not received a receipt');
  Object.assign(row,receiptFields(receipt));
  if(timers.has(row.txHash)) row.receiptLatencyMilliseconds=now()-timers.get(row.txHash);
  else row.latencyUnavailableAfterProcessResume=true;
  persist(); console.log(JSON.stringify({phase:'sepolia_receipt',label,txHash:row.txHash,gasUsed:row.gasUsed}));
  if(receipt.status!==1) throw new Error(label+' received a failed receipt; it is retained for the next attempt');
  return row;
}

try {
  const account=await wallet();
  const chainId=Number(BigInt(await provider.send('eth_chainId',[])));
  if(chainId!==11155111) throw new Error('RPC chain mismatch; refusing to sign');
  await recoverReceipts();
  const balance=await provider.getBalance(account.address), fee=await fees();
  const maximumBudget=BigInt(config.maximumExperimentFeeWei)+BigInt(config.reserveWei);
  const quotedTotal=BigInt(config.maximumExperimentGas)*fee.maxFeePerGas;
  const requiredBudget=(quotedTotal>BigInt(config.maximumExperimentFeeWei)?BigInt(config.maximumExperimentFeeWei):quotedTotal)+BigInt(config.reserveWei);
  const plan={chainId,address:account.address,rpcUrl:process.env.SEPOLIA_RPC_URL?'environment override':config.rpcUrl,
    balanceWei:balance.toString(),balanceSepoliaETH:formatEther(balance),
    suggestedMaxFeePerGasGwei:formatUnits(fee.maxFeePerGas,'gwei'),
    maximumFeeCapGwei:config.maximumFeePerGasGwei,maximumExperimentGas:config.maximumExperimentGas,
    maximumExperimentFeeWei:config.maximumExperimentFeeWei,maximumTransactionGas:config.maximumTransactionGas,
    maximumRequiredBalanceWei:maximumBudget.toString(),maximumRequiredBalanceSepoliaETH:formatEther(maximumBudget),
    requiredBalanceAtQuotedFeesWei:requiredBudget.toString(),requiredBalanceAtQuotedFeesSepoliaETH:formatEther(requiredBudget),
    shortfallSepoliaETH:formatEther(balance>=requiredBudget?0n:requiredBudget-balance),
    addressExplorerURL:config.explorerBase+'/address/'+account.address,
    deploymentReady:balance>=requiredBudget,metadataFile:'config/metadata.json',
    walletStoredLocally:true,privateKeyIncludedInDeliverables:false};
  writeJSON('results/sepolia_plan.json',plan);
  console.log(JSON.stringify({phase:'sepolia_plan',...plan}));
  if(mode==='prepare'||mode==='status') {state.deployer=account.address;state.status=state.contractAddress?state.status:'awaiting_testnet_funding';state.lastCheckedUTC=new Date().toISOString();persist();}
  else {
    checkProtocol();
    const tests=readJSON('results/forge_tests.json');
    const statuses=Object.values(tests).flatMap(s=>Object.values(s.test_results||{}).map(t=>t.status));
    if(!statuses.length || statuses.some(s=>s!=='Success')) throw new Error('Contract tests must pass before deployment');
    if(readJSON('results/local_benchmark.json').status!=='passed') throw new Error('Local experiment must pass before deployment');
    if(balance<requiredBudget) throw new Error('Sepolia test ETH required; see results/sepolia_plan.json');
    const signer=new NonceManager(account); const build=artifact();
    if(!state.contractAddress) {
      const existing=state.transactions.filter(x=>x.label==='deployment').at(-1);
      if(existing?.predictedContractAddress && existing.status!==0) {
        await tracked('deployment',()=>{throw new Error('Existing deployment has no recoverable transaction');});
        state.contractAddress=existing.predictedContractAddress;
      } else {
        const nonce=await account.getNonce('pending');
        const predicted=getCreateAddress({from:account.address,nonce});
        const factory=new ContractFactory(build.abi,build.bytecode.object,signer);
        const request=await factory.getDeployTransaction();
        const allowance=await gasAllowance(await provider.estimateGas({...request,from:account.address,...fee}));
        await tracked('deployment',async limits=>{
          const contract=await factory.deploy(limits);
          return contract.deploymentTransaction();
        },{predictedContractAddress:predicted},allowance);
        state.contractAddress=predicted;
      }
      state.contractExplorerURL=config.explorerBase+'/address/'+state.contractAddress;
      state.contractSourceSha256=sha(fs.readFileSync(path.join(ROOT,'src/ModelEvidenceRegistry.sol')));
      state.deployer=account.address; persist();
    }
    const contract=new Contract(state.contractAddress,build.abi,signer);
    if((await contract.owner()).toLowerCase()!==account.address.toLowerCase()) throw new Error('Contract owner mismatch');
    const payloads=readJSON('evidence/payloads.json');
    const metadata=new Map(readJSON('config/metadata.json').records.map(x=>[x.key,x]));
    for(const p of payloads) {
      if(sha(fs.readFileSync(path.join(ROOT,p.evidenceFile)))!==p.evidenceHash || analysisDigest(p)!==p.resultHash) throw new Error('Evidence or analysis hash mismatch');
      if(mode==='deploy') {
        const input=analysisInput({...p,...metadata.get(p.key)});
        const previous=state.transactions.filter(x=>x.label==='anchor_'+p.key).at(-1);
        const allowance=previous?.status===1?null:await gasAllowance(await contract.anchorAnalysis.estimateGas(input,fee));
        await tracked('anchor_'+p.key,limits=>contract.anchorAnalysis(input,limits),{},allowance);
      } else {
        const m=metadata.get(p.key),before=await contract.getRecord(p.recordId);
        if(before.metadataHash!==metadataDigest(m)) {
          const allowance=await gasAllowance(await contract.updateMetadata.estimateGas(p.recordId,m.dataName,m.description,fee));
          await tracked('rename_'+p.key+'_'+metadataDigest(m).slice(2,18),limits=>contract.updateMetadata(p.recordId,m.dataName,m.description,limits),{},allowance);
        }
      }
      const stored=await contract.getRecord(p.recordId);
      if(stored.evidenceHash!==p.evidenceHash || stored.modelSpecHash!==p.modelSpecHash || stored.resultHash!==p.resultHash) throw new Error('Sepolia record mismatch');
      const row={key:p.key,recordId:p.recordId,evidenceHash:stored.evidenceHash,modelSpecHash:stored.modelSpecHash,
        resultHash:stored.resultHash,metadataHash:stored.metadataHash,metadataVersion:Number(stored.metadataVersion),
        dataName:stored.dataName,description:stored.description,evidenceURI:stored.evidenceURI,
        sourceRecordId:stored.sourceRecordId,conclusion:stored.conclusion,modelVersion:stored.modelVersion,confidence:stored.confidence};
      const index=state.records.findIndex(x=>x.key===p.key);
      if(index<0) state.records.push(row); else state.records[index]=row;
      persist();
    }
    if(mode==='deploy') {
      const p=payloads[0],m=metadata.get(p.key);
      const revisedDescription=m.description+' Metadata revision verified.';
      const before=await contract.getRecord(p.recordId);
      const previous=state.transactions.filter(x=>x.label==='metadata_revision_check').at(-1);
      const allowance=previous?.status===1?null:await gasAllowance(await contract.updateMetadata.estimateGas(p.recordId,m.dataName,revisedDescription,fee));
      await tracked('metadata_revision_check',limits=>contract.updateMetadata(p.recordId,m.dataName,revisedDescription,limits),{},allowance);
      const after=await contract.getRecord(p.recordId);
      if(before.evidenceHash!==after.evidenceHash) throw new Error('Evidence changed during metadata revision');
      Object.assign(state.records[0],{metadataVersion:Number(after.metadataVersion),metadataHash:after.metadataHash,description:after.description});
    }
    const p=payloads[0],changed=Buffer.from(fs.readFileSync(path.join(ROOT,p.evidenceFile)));changed[0]^=1;
    state.integrity={originalVerified:await contract.verifyEvidence(p.recordId,p.evidenceHash),
      alteredRejected:!await contract.verifyEvidence(p.recordId,sha(changed))};
    const head=await provider.getBlock('latest');
    let finalized=null;try{finalized=Number(BigInt((await provider.send('eth_getBlockByNumber',['finalized',false])).number));}catch{}
    state.headAtVerification=head.number;state.finalizedBlockAtVerification=finalized;
    state.totalGasUsedIncludingFailedAttempts=state.transactions.reduce((n,t)=>n+BigInt(t.gasUsed||0),0n).toString();
    state.totalFeeWeiIncludingFailedAttempts=state.transactions.reduce((n,t)=>n+BigInt(t.feeWei||0),0n).toString();
    state.failedAttempts=state.transactions.filter(t=>t.status===0).length;
    state.publicGasPolicy='RPC estimate plus 20% margin; ceilings 16M gas/transaction, 40M gas total including failures, and 0.0001 SepoliaETH total quoted fees';
    delete state.lastError;
    state.inclusionIsConsensusFinality=false;state.status='confirmed_on_sepolia';state.completedAtUTC=new Date().toISOString();persist();
    console.log(JSON.stringify({phase:'complete',status:state.status,contractAddress:state.contractAddress,records:state.records.length}));
  }
} catch(error) {
  state.lastError=error.shortMessage||error.message;
  state.lastCheckedUTC=new Date().toISOString();persist();
  console.error(state.lastError);process.exitCode=1;
} finally {provider.destroy();}
