#!/usr/bin/env python3
"""Prepare original B1 frozen results using the existing evidence commitment."""
from pathlib import Path
import hashlib
import importlib.util
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
B1 = REPO/'experiments/b1_cost_acquisition'

def sha(data):
    return hashlib.sha256(data).hexdigest()

def save(path, value):
    data = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return '0x'+sha(data)

def analysis_abi(record):
    values = [record['sourceRecordId'], record['conclusion'], record['evidenceHash'],
              record['evidenceURI'], record['modelVersion'], record['confidence']]
    head, tail, offset = [], [], 6*32
    for i, value in enumerate(values):
        if i == 2:
            head.append(bytes.fromhex(value.removeprefix('0x')))
        else:
            data = value.encode()
            encoded = len(data).to_bytes(32, 'big') + data + b'\0'*((-len(data)) % 32)
            head.append(offset.to_bytes(32, 'big')); tail.append(encoded); offset += len(encoded)
    return b''.join(head+tail)

def main():
    sys.path.insert(0, str(REPO/'experiments/chain_interface'))
    spec = importlib.util.spec_from_file_location('b1_anchor_source', B1/'anchor_results.py')
    original = importlib.util.module_from_spec(spec); spec.loader.exec_module(original)
    evidence_hash, manifest = original.evidence_bundle()
    freeze = json.loads((B1/'PROTOCOL_B1.freeze.json').read_text())
    if sha((B1/'PROTOCOL_B1.md').read_bytes()) != freeze['protocol_sha256']:
        raise SystemExit('Original B1 protocol SHA-256 does not match its freeze record')
    run = json.loads((B1/'results/results.json').read_text())
    if run['protocol_sha256'] != freeze['protocol_sha256']:
        raise SystemExit('Frozen B1 results and protocol digest differ')
    preimage = json.dumps(sorted(manifest.items())).encode()
    assert sha(preimage) == evidence_hash
    (ROOT/'evidence').mkdir(exist_ok=True)
    (ROOT/'evidence/b1_commitment_preimage.json').write_bytes(preimage)
    save(ROOT/'evidence/b1_evidence_manifest.json', {'evidence_hash': evidence_hash, 'files': manifest,
        'encoding': 'SHA-256 of original json.dumps(sorted(manifest.items())).encode()'})
    model_spec = {'schema':'b1-reported-model-specification/v1',
        'model_version': f"protocol:{freeze['protocol_sha256'][:12]}|run:{run['run_at_utc']}",
        'protocol_sha256': freeze['protocol_sha256'], 'outer_folds':5, 'outer_seed':20261004,
        'tau_days':1095, 'model_family':'Breslow Cox with ridge penalty',
        'alpha_candidates':[1,10,100], 'variance_features_per_block':256, 'pca_components':16,
        'code_sha256':{f:sha((REPO/f).read_bytes()) for f in [
            'experiments/b1_cost_acquisition/run_b1.py','experiments/lung_missingness/models.py']},
        'trained_weights_included':False,'model_training_repeated_for_ledger_experiment':False}
    model_hash = save(ROOT/'evidence/model_specification.json', model_spec)
    labels = {x['key']:x for x in json.loads((ROOT/'config/metadata.json').read_text())['records']}
    payloads=[]
    for conclusion in original.conclusions():
        key = conclusion['record_id'].split('/')[1]
        native_payload = {**conclusion,'evidence_hash':evidence_hash,
            'evidence_uri':'repo://experiments/b1_cost_acquisition/results/results.json',
            'model_version':model_spec['model_version']}
        result_file=f'evidence/analysis_{key}.json'
        canonical_hash=save(ROOT/result_file, native_payload)
        p={'key':key,'recordId':'0x'+sha(conclusion['record_id'].encode()),
           'evidenceHash':'0x'+evidence_hash,'modelSpecHash':model_hash,
           'evidenceURI':native_payload['evidence_uri'],'dataName':labels[key]['dataName'],
           'description':labels[key]['description'],'sourceRecordId':conclusion['record_id'],
           'conclusion':conclusion['conclusion'],'modelVersion':native_payload['model_version'],
           'confidence':conclusion['confidence'],
           'evidenceFile':'evidence/b1_commitment_preimage.json','resultFile':result_file,
           'canonicalPayloadSha256':canonical_hash}
        p['resultHash']='0x'+sha(analysis_abi(p))
        if len(p['conclusion'].encode())>512:raise SystemExit('Conclusion exceeds contract bound')
        payloads.append(p)
    assert len(payloads)==2
    save(ROOT/'evidence/payloads.json',payloads)
    protocol_hash=sha((ROOT/'config/protocol.json').read_bytes())
    frozen=ROOT/'results/protocol_sha256.txt';frozen.parent.mkdir(exist_ok=True)
    if frozen.exists() and frozen.read_text().strip()!=protocol_hash:
        raise SystemExit('Ledger experiment protocol changed after freeze; create a new version')
    frozen.write_text(protocol_hash+'\n')
    print(json.dumps({'records':len(payloads),'source':'original frozen B1 files',
        'b1_evidence_hash':evidence_hash,'b1_protocol_verified':True,
        'ledger_protocol_sha256':protocol_hash,'model_training_repeated':False}))

if __name__=='__main__':main()
