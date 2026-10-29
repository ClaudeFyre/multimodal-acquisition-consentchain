import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {performance} from 'node:perf_hooks';
import {AbiCoder, FetchRequest, JsonRpcProvider, keccak256, getBytes} from 'ethers';

export const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
export const now = () => performance.now();
export const sha = bytes => '0x'+createHash('sha256').update(bytes).digest('hex');
export const readJSON = relative => JSON.parse(fs.readFileSync(path.join(ROOT,relative),'utf8'));
export function writeJSON(relative, value) {
  const target=path.join(ROOT,relative); fs.mkdirSync(path.dirname(target),{recursive:true});
  fs.writeFileSync(target, JSON.stringify(value,(_,v)=>typeof v==='bigint'?v.toString():v,2)+'\n');
}
export const canonical = value => {
  if (Array.isArray(value)) return '['+value.map(canonical).join(',')+']';
  if (value !== null && typeof value==='object') return '{'+Object.keys(value).sort().map(k=>JSON.stringify(k)+':'+canonical(value[k])).join(',')+'}';
  return JSON.stringify(value);
};
export const metadataDigest = p => keccak256(AbiCoder.defaultAbiCoder().encode(['string','string'],[p.dataName,p.description]));
export const anchorArgs = p => [p.recordId,p.evidenceHash,p.modelSpecHash,p.resultHash,p.evidenceURI,p.dataName,p.description];
export const analysisDigest = p => sha(getBytes(AbiCoder.defaultAbiCoder().encode(
  ['string','string','bytes32','string','string','string'],
  [p.sourceRecordId,p.conclusion,p.evidenceHash,p.evidenceURI,p.modelVersion,p.confidence])));
export const analysisInput = p => Object.fromEntries(['recordId','evidenceHash','modelSpecHash','resultHash',
  'evidenceURI','dataName','description','sourceRecordId','conclusion','modelVersion','confidence'].map(k=>[k,p[k]]));
export function artifact() {return readJSON('out/ModelEvidenceRegistry.sol/ModelEvidenceRegistry.json');}
export function providerFor(url,chainId,polling=1000) {
  const req=new FetchRequest(url); req.timeout=15000;
  req.setHeader('User-Agent','ModelEvidenceRegistry/1.0');
  const provider=new JsonRpcProvider(req,chainId,{batchMaxCount:1,staticNetwork:true,cacheTimeout:-1});
  provider.pollingInterval=polling;
  return provider;
}
export function quantile(values,q) {
  const a=[...values].sort((x,y)=>x-y); if(!a.length) return null;
  const t=(a.length-1)*q, i=Math.floor(t); return a[i]+(a[Math.min(i+1,a.length-1)]-a[i])*(t-i);
}
export function summary(values) {
  return {n:values.length,median:quantile(values,.5),p95:quantile(values,.95),min:Math.min(...values),max:Math.max(...values)};
}
export async function measuredTransaction(label, send, provider, output) {
  const start=now(); const tx=await send();
  const submitted=now();
  const receipt=await provider.waitForTransaction(tx.hash,1,180000);
  if(!receipt || receipt.status!==1) throw new Error(label+': transaction failed');
  const done=now();
  const row={label,txHash:tx.hash,blockNumber:receipt.blockNumber,gasUsed:receipt.gasUsed.toString(),
    gasPriceWei:receipt.gasPrice.toString(),feeWei:(receipt.gasUsed*receipt.gasPrice).toString(),
    submissionMilliseconds:submitted-start,receiptLatencyMilliseconds:done-start,status:receipt.status};
  output?.push(row); return row;
}
export function checkProtocol() {
  const expected=fs.readFileSync(path.join(ROOT,'results/protocol_sha256.txt'),'utf8').trim();
  const actual=sha(fs.readFileSync(path.join(ROOT,'config/protocol.json'))).slice(2);
  if(actual!==expected) throw new Error('Protocol hash mismatch'); return actual;
}
