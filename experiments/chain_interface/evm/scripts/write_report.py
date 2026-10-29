#!/usr/bin/env python3
"""Build the scoped manuscript addition from recorded measurements, without training."""
import json
import re
import statistics as st
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
PAPER = REPO / 'papers/b1_jbhi'

def read(name):
    return json.loads((ROOT / name).read_text())

def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError(f'Expected one source occurrence: {old[:100]}')
    return text.replace(old, new, 1)

def main():
    local = read('results/local_benchmark.json')
    native = read('results/native_adapter_test.json')
    tests = [t for suite in read('results/forge_tests.json').values()
             for t in suite.get('test_results', {}).values()]
    assert local['status'] == 'passed' and native['all_passed']
    assert len(tests) == 30 and all(t['status'] == 'Success' for t in tests)
    spath = ROOT / 'results/sepolia_deployment.json'
    public = json.loads(spath.read_text()) if spath.exists() else {}
    deployed = public.get('status') == 'confirmed_on_sepolia'
    methods = r'''\subsection{Model-Evidence Registry Experiment}
\label{sec:chain-methods}
We implemented the B1 \texttt{ANALYSIS\_RECORD} route in Solidity and connected it to the existing Python \texttt{Ledger} interface through an ethers adapter. This experiment reuses the frozen aggregate model outputs; it does not refit a survival model or change an acquisition policy. The two records summarize the stage-inclusive and stage-excluded analyses. The original six-file evidence bundle comprises the frozen protocol, its freeze record, the aggregate result JSON, two grid-mean CSV files and the B1 report. We retain the native commitment exactly: SHA-256 of Python's default JSON serialization of the sorted (relative path, file SHA-256) pairs. An auditor recomputes both file hashes and the manifest commitment.

Each contract record stores its source ID, conclusion, evidence commitment and repository URI, model version, confidence statement, and separate model-specification and analysis digests. The model-specification digest covers the supplied training specification and code checksums; trained weight files were unavailable. The analysis digest is SHA-256 of the ABI encoding of the six native analysis fields. The contract recomputes it and binds the record key to SHA-256 of the source ID. Registration is restricted to the owner or an authorized submitter, duplicate keys are rejected, and stored analysis fields have no update function. Data name and description are separate display fields; an authorized revision increments a version counter and emits the old and new metadata hashes. The Python adapter rejects patient identifiers, salts, feature values and unsupported event types before submission. Free-text content still requires the submitter to ensure that it contains aggregate information only. The A2 consent and unlearning events are outside this implementation.

The registry protocol (version 1.1.0; commitment beginning \texttt{6a7b9710cb27}) was saved before measurement. We ran 28 unit tests and two fuzz properties with 256 cases each, then nine checks through the native B1 adapter. The functional workload registered the two actual conclusions, revised one description and tested 128 single-bit mutations of the commitment preimage. For overhead measurement, two synthetic load classes used 16/64 and 128/512 UTF-8 bytes for data name/description, with the same analysis schema. Each backend and class had three technical repetitions of 16 writes (96 writes per backend). Backend order alternated between repetitions. The comparison was a single-writer EIP-191-signed SHA-256 hash-chained JSONL log with \texttt{fsync} after every append; this is an additional benchmark baseline, separate from the original unsigned local reference log.

Local measurements used an Apple M3 (8 logical CPUs, 16 GiB RAM), Node 25.2.1, ethers 6.17.0, Foundry/Anvil 1.7.1 and Solidity 0.8.34 (optimizer 200 runs, Shanghai target). Anvil used chain ID 31337, 1-s blocks and a 30-million-gas block limit. EVM writes were submitted in batches of four with 100-ms receipt polling; the signed log appended sequentially. Latency was client elapsed time from submission start to observing a successful one-confirmation receipt; log latency ended after the signed append was flushed. Observed throughput was successful writes divided by the first-submission-to-last-completion span. These endpoints and submission patterns have different trust and durability semantics. We report descriptive medians and repetition ranges, without treating individual transactions as independent statistical replicates or interpreting this workload as network capacity.

The public-network demonstration uses Ethereum Sepolia (chain ID 11155111) and a dedicated test account. For the four successful operations reported here, live-network gas estimates received 20\% headroom, subject to a 16-million-gas per-transaction ceiling and a 3-gwei per-gas ceiling. Deployment, two registrations and one display-metadata revision are logged separately. We verify transaction status, gas used and effective gas price against RPC receipts, and inclusion timestamps against their canonical block headers. The actual fee is gas used multiplied by effective gas price, with $10^{18}$ wei per SepoliaETH. Submission start and receipt observation use the original client log; elapsed receipt latency uses the original monotonic timer. Table~\ref{tab:sepolia} reports these four successful transactions, with all wall-clock times in UTC. One successful receipt establishes observed inclusion; it does not establish consensus finality. Public-network timing is kept separate from the controlled local benchmark; the account-funding transfer is excluded from contract experiment costs.
'''
    rows = []
    chinese_rows = []
    for backend, label in [('local_evm', 'Local EVM'), ('signed_fsynced_central_log', 'Signed log')]:
        for cls in ['compact', 'extended']:
            group = [r for r in local['benchmarkRows'] if r['backend'] == backend and r['payloadClass'] == cls]
            lat = st.median(r['latencyMilliseconds']['median'] for r in group)
            tps = [r['observedWritesPerSecond'] for r in group]
            gas = f"{int(st.median(r['gasUsed']['median'] for r in group)):,}" if backend == 'local_evm' else '--'
            rows.append(f'{label} & {cls} & {gas} & {lat:.2f} & {st.median(tps):.2f} ({min(tps):.2f}--{max(tps):.2f}) \\\\')
            chinese_rows.append(f'| {label} | {cls} | {gas} | {lat:.2f} | {st.median(tps):.2f} ({min(tps):.2f}–{max(tps):.2f}) |')
    results = r'''\subsection{Model-Evidence Registration and Overhead}
\label{sec:chain-results}
All 30 contract tests passed, including both fuzz properties, and all nine native-adapter checks passed. Both original B1 conclusions were registered and reconstructed from the contract. Replaying identical native records reused the two existing receipts without new writes; changing immutable content under the same source ID was rejected. The auditor reproduced the original evidence commitment, beginning \texttt{50c74c7a39f4}, for both records. All 128 altered commitment preimages failed the hash check. A display-metadata revision preserved the analysis, model-specification and evidence digests. These checks establish the implemented consistency and authorization behavior under the tested inputs; they do not establish the truth of the submitted model conclusions or security against every attack.

Local deployment used 1,428,475 gas. Registration of the actual stage-inclusive and stage-excluded records used 682,909 and 682,825 gas, respectively; one description revision used 61,528 gas. The synthetic load results appear in Table~\ref{tab:registry}. Longer display metadata increased storage gas. The signed log completed this local workload more quickly. Both signed-log modification and truncation with a pinned head checkpoint were detected; a valid signed prefix was accepted when no trusted head checkpoint was supplied. Thus, signatures and hash chaining alone do not prove completeness of a presented log.

\begin{table*}[t]
\centering
\caption{Controlled local registry workload: three repetitions of 16 writes per backend and payload class}
\label{tab:registry}
\setlength{\tabcolsep}{8pt}
\begin{tabular}{@{}llrrr@{}}
\toprule
Backend & Display payload & Gas per registration & Receipt / append latency (ms) & Observed writes/s (range) \\
\midrule
''' + '\n'.join(rows) + r'''
\bottomrule
\end{tabular}
\begin{minipage}{0.94\textwidth}\footnotesize
Values are medians of the three within-repetition medians (gas, latency) or repetition throughput values; parentheses give the throughput range. Compact/extended labels use 16/64 and 128/512 name/description bytes, respectively. The EVM was configured for 1-s blocks and four outstanding writes. Log completion includes signing and \texttt{fsync}. The comparison measures these client configurations and their different completion endpoints; it does not measure peak blockchain capacity, public-network throughput or consensus finality.
\end{minipage}
\end{table*}
'''
    if deployed:
        txs = public['transactions']
        labels = {'deployment', 'anchor_B_stage_group', 'anchor_A_no_stage', 'metadata_revision_check'}
        successful = [t for t in txs if t.get('status') == 1 and t['label'] in labels]
        assert len(successful) == 4 and {t['label'] for t in successful} == labels
        metrics = read('results/sepolia_transaction_metrics.json')
        assert metrics['audit']['allPassed'] and metrics['chainId'] == 11155111
        metric_rows = metrics['transactions']
        assert [t['txHash'] for t in metric_rows] == [t['txHash'] for t in successful]
        assert all(t['status'] == 1 for t in metric_rows)
        gas_total = sum(int(t['gasUsed']) for t in successful)
        fee_total_wei = sum(int(t['feeWei']) for t in successful)
        fee_total = Decimal(fee_total_wei) / Decimal(10**18)
        assert gas_total == int(metrics['totals']['gasUsed'])
        assert fee_total_wei == int(metrics['totals']['feeWei'])
        addr = public['contractAddress']
        result_public = (r'On Ethereum Sepolia, deployment, both registrations and one metadata revision all received successful receipts. '
                         f'Table~\\ref{{tab:sepolia}} lists gas, actual fees and timing for these four successful operations. '
                         f'Together they consumed {gas_total:,} gas and {fee_total:.18f} SepoliaETH at the observed fees. '
                         r'The original commitment verified and a changed commitment was rejected. '
                         r'The contract address and full transaction receipts are recorded in the accompanying artifact, with the contract at '
                         '\\href{https://sepolia.etherscan.io/address/' + addr + r'}{the Sepolia explorer}. '
                         r'These four successful transactions demonstrate deployment and read-back behavior on the selected test network; they provide no public-network throughput estimate.' + '\n')
        names = {'deployment': 'Deployment', 'anchor_B_stage_group': 'Stage-inclusive record',
                 'anchor_A_no_stage': 'Stage-excluded record', 'metadata_revision_check': 'Metadata revision'}
        public_rows = []
        for t in metric_rows:
            latency = f"{t['receiptLatencyMilliseconds']/1000:.2f}"
            fee_nano = Decimal(t['feeWei']) / Decimal(10**9)
            submit_time = t['submissionStartedUTC'][11:23]
            block_time = t['blockTimeUTC'][11:19]
            public_rows.append(f"{names[t['label']]} & {t['blockNumber']:,} & {int(t['gasUsed']):,} & {fee_nano:.9f} & {submit_time} & {block_time} & {latency} \\\\")
        result_public += r'''
\begin{table*}[t]
\centering
\caption{Sepolia gas, actual transaction fees and timing: four successful operations on 22 October 2026 (UTC)}
\label{tab:sepolia}
\small
\setlength{\tabcolsep}{4pt}
\begin{tabular}{@{}lrrrccr@{}}
\toprule
Operation & Block & Gas used & \shortstack{Fee ($10^{-9}$\\SepoliaETH)} & \shortstack{Submission\\start (UTC)} & \shortstack{Block time\\(UTC)} & \shortstack{Receipt\\latency (s)} \\
\midrule
''' + '\n'.join(public_rows) + r'''
\midrule
Total & -- & ''' + f'{gas_total:,} & {Decimal(fee_total_wei) / Decimal(10**9):.9f}' + r''' & -- & -- & -- \\
\bottomrule
\end{tabular}
\par\smallskip
\begin{minipage}{0.98\textwidth}\footnotesize
All four receipts have status 1. Effective gas price was 1,316 wei/gas ($0.000001316$ gwei/gas) for every row; fee equals gas used times this price. The fee column uses $10^{-9}$ SepoliaETH, and its total equals $0.000000021657202756$ SepoliaETH. Submission start comes from the original client log; block time is the inclusion-block timestamp (1-s resolution). Receipt latency is the original monotonic client time from submission start to observing a one-confirmation receipt, including RPC and polling delay; it is not consensus finality. UTC+8 times are obtained by adding 8 h. Full hashes and unrounded measurements are supplied in the transaction-metrics artifact. Each operation has one observation; no public-network throughput is estimated.
\end{minipage}
\end{table*}
'''
        deployment_summary = f"Sepolia 部署和两条登记、一次元数据修订均已有成功回执。合约：{addr}。论文表 VII 列出这四笔成功交易的区块号、gas 用量、实际费用、提交开始时间、区块时间和回执延迟；gas 合计 {gas_total:,}，费用 {fee_total:.18f} SepoliaETH。表内时间采用 UTC，换算北京时间加 8 小时。费用列单位为 10^-9 SepoliaETH，所有行实际 gas price 均为 1,316 wei/gas。完整精度数据与交易哈希见 results/sepolia_transaction_metrics.json 和同名 CSV，链上原始回执与区块头见 results/sepolia_metrics_rpc_snapshot.json。费用汇总仅覆盖表内四笔成功交易。"
    else:
        result_public = r'The Sepolia deployment script and payloads are prepared. A successful public-network deployment has not yet been recorded; no Sepolia performance result is claimed.' + '\n'
        deployment_summary = 'Sepolia 合约与载荷已准备；尚无成功公链部署回执。测试币领取仍在处理，当前版本明确保留该缺项。'
    results += '\n' + result_public
    (PAPER / 'blockchain_methods.tex').write_text(methods)
    (PAPER / 'blockchain_results.tex').write_text(results)
    text = (ROOT / 'source/main_before_blockchain.tex').read_text()
    text = text.replace('% Blockchain components are specified as interfaces and are NOT evaluated; all such text is highlighted.', '% B1 model-evidence registry implemented and measured; clinical analyses unchanged.')
    text = text.replace('\\newif\\ifchainhl \\chainhltrue', '\\newif\\ifchainhl \\chainhlfalse')
    text = replace_once(text, r'\thanks{\ifchainhl\bc{Highlighted text} marks blockchain components of the proposed architecture. They are specified as software interfaces and were not deployed or evaluated in this study.\fi}', '')
    text = replace_once(text, r'\bc{reserves a smart-contract layer for anchoring each conclusion with its evidence hash}', 'registers aggregate model conclusions and evidence commitments through an implemented EVM smart contract')
    text = replace_once(text, r'\bc{reserves an on-chain layer for compact, verifiable records of each conclusion}. This paper evaluates the analysis layers; \bc{the blockchain layers are specified as interfaces for later evaluation}', r'implements an on-chain registry for compact, verifiable records of the aggregate model conclusions. We evaluate record consistency, metadata revision and operational overhead separately from predictive performance')
    text = replace_once(text, r'\bc{A governance architecture and a backend-agnostic ledger interface that anchors each analysis conclusion with the hash of its evidence, with a working local reference implementation and a reserved blockchain backend.}', r'An EVM registry connected to the native B1 ledger interface, with immutable evidence and analysis commitments, revisable display metadata, functional tests and a controlled overhead comparison with a signed centralized log.')
    start = text.index('\\caption{System architecture, restyled')
    end = text.index('\n\\label{fig:arch}', start)
    text = text[:start] + r'\caption{Implemented B1 model-evidence route. The original frozen model outputs generate two aggregate analysis records through the ledger adapter. Full protocol and result files remain off-chain, while the EVM contract stores their evidence commitment and compact analysis fields. Data names and descriptions have versioned revisions. An auditor checks file hashes and contract records; operational measurements are reported separately from predictive performance.}' + text[end:]
    text = replace_once(text, 'We therefore specify the ledger as an interface with a centralized hash-chained log as its reference backend, so that a later evaluation can compare the two directly.', 'We retain the ledger interface and implement its B1 analysis route on an EVM contract, comparing controlled local overhead with a signed centralized log. The experiment addresses evidence registration rather than multi-hospital endorsement.')
    text = replace_once(text, r'\textit{Performance monitoring.} Gas per transaction, throughput (successful transactions per second) and confirmation latency are computed off-chain from receipts and timing logs over a fixed measurement window.', r'\textit{Performance monitoring.} Receipt gas, client-observed completion latency and observed write throughput are computed off-chain under the workload in Section~\ref{sec:chain-methods}. Display metadata can be revised while the original analysis commitments remain fixed.')
    text = replace_once(text, 'Backends & local hash-chained log (implemented); permissioned blockchain (interface reserved, not evaluated)', 'Backends & local hash-chained log; EVM B1 registry (implemented); A2 chain events remain outside scope')
    text = replace_once(text, 'Contract checks & authorized submitter; complete schema', 'Contract checks & authorized signer; record ID and analysis digest; bounded fields; duplicate rejection')
    text = replace_once(text, 'conclusion ($\\le$512 characters)', 'conclusion ($\\le$512 UTF-8 bytes)')
    text = replace_once(text, r'\bc{As a reference for the governance layer, the frozen results were turned into two \texttt{ANALYSIS\_RECORD} payloads and appended to the local hash-chained log through the ledger interface; an auditor step recomputes the evidence hash from the files.}', r'The blockchain experiment registers these same two frozen aggregate conclusions through the implemented B1 registry. An auditor recomputes the native evidence commitment; no model training was repeated for this addition.' + '\n\n' + r'\input{blockchain_methods}')
    pattern = r'\\subsection\{\\bct\{Reference Implementation of the Governance Interface\}\}.*?\\end\{chainbox\}'
    text, n = re.subn(pattern, lambda _: r'\input{blockchain_results}', text, count=1, flags=re.S)
    assert n == 1
    start = text.index('Anchoring conclusions on a ledger addresses a governance problem')
    end = text.index('\n\\end{chainbox}', start)
    discussion = ('The registry makes the registered version and evidence commitment independently retrievable and separates stable analysis content from revisable display labels. The signed log had substantially lower overhead in the measured local workload. This trade-off makes independent access to a shared registration history a deployment consideration, while model correctness continues to depend on the off-chain analysis and its availability. A hash verifies consistency with a registered byte sequence and does not validate a clinical conclusion. Our tests do not evaluate hospital endorsement, consensus attacks, key compromise or a malicious submitter registering incorrect aggregate content.')
    text = text[:start] + discussion + text[end:]
    text = replace_once(text, r'\bc{Seventh, the blockchain layers were specified and tested only as a local reference implementation; no deployment, cost or security evaluation was performed.}', 'Seventh, the registry experiment covers two aggregate B1 records and a small synthetic workload. Local Anvil timing depends on its configured block interval and client concurrency. Security checks cover specified authorization and consistency properties; they do not evaluate consensus security or deployment in hospitals. The original trained weights were unavailable, so the additional model digest covers the model specification and source code.')
    text = replace_once(text, r'\bc{The third is to implement the reserved blockchain backend, run the same anchoring workload on a permissioned chain and on the centralized log, and report gas, throughput, latency and tamper resistance over a fixed measurement window.}', 'The third is to evaluate a larger multi-writer registry deployment, independent evidence availability and recovery, and organization-level governance under realistic operational requirements.')
    text = replace_once(text, r'\bc{An architecture that anchors each conclusion with its evidence hash can make such cost-aware decisions traceable; its blockchain layer remains to be evaluated.}', 'The implemented EVM registry makes the aggregate model conclusions and evidence commitments traceable, with measured storage and completion overhead; it adds no evidence of predictive improvement.')
    text = replace_once(text, r'\bc{and the ledger interface}', 'and the B1 EVM registry, tests and measured receipts')
    (PAPER / 'main.tex').write_text(text)
    guide = f'''# B1 模型结果上链实验说明

本次补充使用你新提供的 multimodal-acquisition-consentchain-main 项目。其 B1 论文与最初论文包的 main.tex 相同；原项目已有 ANALYSIS_RECORD 接口、冻结结果和六文件证据清单。已将这些真实聚合结果接到新合约，没有重新训练或增加医学实验。

{deployment_summary}

## 交付与命名

两条记录分别为 B1/B_stage_group/policy 与 B1/A_no_stage/policy。显示名称暂用 MODEL_RECORD_001 和 MODEL_RECORD_002；描述也为占位内容。最终名称与描述由作者提供，编辑 config/metadata.json 后运行 npm run metadata:update。名称上限 128 UTF-8 字节，描述上限 512 字节。中文常用字通常占 3 字节。

名称与描述每次修订都会留下事件与版本号。证据、模型规范、分析结果哈希以及原结论保持固定。若要修改模型结论或证据文件，需要登记新的版本记录。

## 已有证据

- 合约测试 30/30 项通过，其中两项模糊测试各运行 256 个案例。
- 原项目接口验证 9/9 项通过，包括两条原结论回读、重复提交复用回执、字段限制和冲突记录拒绝。
- 两条真实记录的证据哈希均为 50c74c7a39f4c8e1555a33ae5fa6ba369e1c9c96ead569105266f613907f0976。
- 128 次单比特修改均未通过证据核验；一次显示描述修改保留了不可变哈希。
- 本地部署 gas 1,428,475；实际两条 B1 登记 gas 682,909 和 682,825；描述修订 gas 61,528。
- 性能部分使用合成负载，每个后端共 96 次写入，分两个长度类别、每类三次技术重复；原 B1 模型记录为两条。

| 后端 | 载荷类别 | gas | 延迟中位数 ms | 吞吐中位数与范围 条/秒 |
|---|---|---:|---:|---:|
''' + '\n'.join(chinese_rows) + '''

表中延迟为三次重复内部中位数的中位数；吞吐范围来自三次重复。本地 EVM 固定 1 秒出块、并发 4；有签名中心日志每条 fsync。两个后端完成条件不同，数据反映本次配置的运行开销。日志具有明显速度优势。有效签名的日志前缀在缺少可信头检查点时仍可通过验证，单靠签名与哈希链无法证明日志完整性。

## 论文写法与边界

英文方法位于 papers/b1_jbhi/blockchain_methods.tex，结果位于 blockchain_results.tex，均已纳入 main.tex。架构图、贡献、讨论、限制和结论同步修改，以免保留“接口尚未实现”的旧表述。原模型结果与统计结论保持原值。

可支持的表述：B1 聚合模型证据登记已实现；特定授权、哈希一致性、去重和元数据修订行为通过测试；本地运行开销已测量。公链结果以 results/sepolia_deployment.json 的成功回执为准。

这些实验无法推出模型预测更准确、临床有效性增强、跨医院多组织背书已实现或共识攻击已验证。模型权重文件未提供，modelSpecHash 对应训练规范及源码校验和。一次成功交易回执代表观察到入块，文中没有将其写为共识最终性。A2 同意撤回与遗忘的链后端仍为后续工作。

证据 URI 使用原项目 repo:// 路径；公共链不会替你托管文件。复核者需要获得相应项目与文件访问权。私有仓库授权条款继续适用。

## 作者仍需处理

提供两条记录的最终显示名称和描述后可直接更新。论文原有作者/单位、机构数据使用说明、正式仓库链接仍待作者填写；这些原有占位项不属于此次链实验的测量结果。公开投稿前需按原仓库授权安排代码和证据的可用性。
'''
    (ROOT / 'docs/中文说明.md').write_text(guide)
    mapping = {
        'two_native_model_records': 'results/native_adapter_test.json; evidence/analysis_*.json',
        'contract_authorization_schema_digest_metadata': 'test/ModelEvidenceRegistry.t.sol; results/forge_tests.json',
        'native_evidence_commitment': 'evidence/b1_commitment_preimage.json; evidence/b1_evidence_manifest.json',
        '128_mutations_and_revision': 'results/local_benchmark.json:functional',
        'overhead_table': 'results/local_benchmark.json:benchmarkRows; results/local_receipts.json',
        'signed_log_checks': 'results/central_*.jsonl; local_benchmark.json:benchmarkRows[].checks',
        'public_network': 'results/sepolia_deployment.json (claim only when status=confirmed_on_sepolia)',
        'public_transaction_table': 'results/sepolia_transaction_metrics.json; results/sepolia_metrics_rpc_snapshot.json; original client timing logs in sepolia_deployment.json; four successful operations only',
        'unchanged_clinical_results': 'original B1 frozen evidence bundle; no training repeated',
        'not_evaluated': 'consensus security, clinical improvement, trained weight integrity, A2 chain events'
    }
    (ROOT / 'docs/claim_evidence_map.json').write_text(json.dumps(mapping, indent=2) + '\n')
    print(json.dumps({'paper_updated': True, 'sepolia_confirmed': deployed, 'contract_tests': len(tests), 'native_checks': len(native['checks'])}))

if __name__ == '__main__':
    main()
