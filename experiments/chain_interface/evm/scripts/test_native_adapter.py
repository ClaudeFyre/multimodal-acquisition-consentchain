#!/usr/bin/env python3
"""Run the original B1 anchor() through BlockchainLedger on a fresh local EVM."""
from pathlib import Path
import importlib.util
import json
import subprocess
import sys
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
REPO=ROOT.parents[2]
PORT=18546
RPC=f'http://127.0.0.1:{PORT}'

def rpc(method,params=None):
    req=urllib.request.Request(RPC,data=json.dumps({'jsonrpc':'2.0','id':1,'method':method,'params':params or []}).encode(),headers={'Content-Type':'application/json'})
    return json.load(urllib.request.urlopen(req,timeout=5))['result']

def main():
    log=(ROOT/'results/native_adapter_anvil.log').open('a')
    node=subprocess.Popen(['anvil','--port',str(PORT),'--chain-id','31337','--hardfork','shanghai','--block-time','1','--quiet'],stdout=log,stderr=log)
    try:
        for _ in range(100):
            try:
                if int(rpc('eth_chainId'),16)==31337:break
            except Exception:time.sleep(.1)
        else:raise RuntimeError('Local EVM startup timeout')
        options={'action':'deploy_local','rpc_url':RPC,'chain_id':31337}
        run=subprocess.run(['node',str(ROOT/'scripts/ledger_bridge.mjs')],input=json.dumps(options),text=True,capture_output=True,check=True)
        deployment=json.loads(run.stdout)
        sys.path.insert(0,str(REPO/'experiments/chain_interface'))
        from ledger import BlockchainLedger,Event,ANALYSIS_RECORD
        spec=importlib.util.spec_from_file_location('native_b1',REPO/'experiments/b1_cost_acquisition/anchor_results.py')
        b1=importlib.util.module_from_spec(spec);spec.loader.exec_module(b1)
        ledger=BlockchainLedger(rpc_url=RPC,contract_address=deployment['contract_address'],chain_id=31337,
            deployment_block=deployment['deployment_block'],authorized_orgs={'b1-analysis'})
        receipts=b1.anchor(ledger)
        rows=list(ledger.events(ANALYSIS_RECORD))
        checks={'two_native_records':len(rows)==2,'ledger_verifies':ledger.verify(),
            'native_evidence_matches':b1.verify_against_evidence(ledger),
            'conclusions_match':{e.payload['record_id']:e.payload['conclusion'] for _,e in rows}=={c['record_id']:c['conclusion'] for c in b1.conclusions()},
            'actual_gas_receipts':all(r.gas_used>0 for r,_ in rows)}
        accounts=rpc('eth_accounts');before=rpc('eth_getTransactionCount',[accounts[0],'latest'])
        b1.anchor(ledger)
        after=rpc('eth_getTransactionCount',[accounts[0],'latest'])
        checks['identical_replay_reuses_two_receipts']=ledger.reused_receipts==2 and before==after
        payload=dict(rows[0][1].payload)
        try:
            ledger.append(Event(ANALYSIS_RECORD,{**payload,'patient_id':'forbidden-test-key'},org='b1-analysis'))
            checks['forbidden_field_rejected_before_rpc']=False
        except ValueError:checks['forbidden_field_rejected_before_rpc']=True
        try:
            ledger.append(Event(ANALYSIS_RECORD,payload,org='unapproved-org'))
            checks['unauthorized_logical_org_rejected']=False
        except PermissionError:checks['unauthorized_logical_org_rejected']=True
        try:
            ledger.append(Event(ANALYSIS_RECORD,{**payload,'conclusion':'changed immutable conclusion'},org='b1-analysis'))
            checks['different_content_same_record_id_rejected']=False
        except RuntimeError:checks['different_content_same_record_id_rejected']=True
        result={'schema':'b1-native-ledger-adapter-test/v1','deployment':deployment,'checks':checks,
            'all_passed':all(checks.values()),'receipts':receipts,
            'evidence_hash':b1.evidence_bundle()[0],
            'model_training_repeated':False,'a2_consent_unlearning_tested':False}
        (ROOT/'results/native_adapter_test.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps({'checks':len(checks),'passed':sum(checks.values()),'all_passed':result['all_passed']}))
        if not result['all_passed']:raise RuntimeError('Native adapter check failed')
    finally:
        node.terminate()
        try:node.wait(timeout=5)
        except subprocess.TimeoutExpired:node.kill();node.wait()
        log.close()

if __name__=='__main__':main()
