# chain_interface：B1 / A2 共用的账本接口与 B1 EVM 实验

2026-10-20 建立接口；2026-10-29 合并 Sepolia EVM 实验（来源：`papers/b1_jbhi/new/outputs.zip` 中的完整项目包）。

## 当前状态

| 后端 | 文件 | 支持的事件 | 状态 |
|---|---|---|---|
| `LocalHashChainLedger` | `ledger.py` | 全部 6 类 | 本机哈希链日志，作为"中心化日志"对照 |
| `BlockchainLedger` | `ledger.py` → `evm/scripts/ledger_bridge.mjs` → `evm/src/ModelEvidenceRegistry.sol` | 仅 B1 `ANALYSIS_RECORD` | **已实现**；部署在 Ethereum Sepolia，合约 `0xF3A2732f7521ED01A0AeaB874F9b2E46aB6B0155` |
| A2 事件的链后端 | — | `REGISTER_SAMPLE` 等 5 类 | **未实现**；`BlockchainLedger` 收到 A2 事件时会抛出 `NotImplementedError` |

```
冻结的 B1 结果 ─▶ 证据清单（6 个文件的 SHA-256）─▶ evidence_hash
        │
        ▼
anchor_results.py ─▶ ANALYSIS_RECORD ─▶ Ledger.append()
                                         ├── LocalHashChainLedger（本机 JSONL）
                                         └── BlockchainLedger ─▶ ledger_bridge.mjs (ethers) ─▶ ModelEvidenceRegistry (Sepolia)
审计：重算证据哈希 + 读回链上记录 + 核对回执与区块
```

## 文件

| 路径 | 内容 |
|---|---|
| `ledger.py` | 事件格式（字段约束）、`Ledger` 抽象类、本机哈希链、B1 EVM 后端 |
| `benchmark.py` | 原有的本机接口性能脚本（成功率、TPS、延迟） |
| `../b1_cost_acquisition/anchor_results.py` | 两条 B1 结论上链；`--backend local`（默认）或 `--backend evm` |
| `evm/src/ModelEvidenceRegistry.sol` | 授权登记、不可变分析字段、可修订的显示名称与描述 |
| `evm/test/ModelEvidenceRegistry.t.sol` | 30 项合约测试（含 2 项模糊测试，各 256 例） |
| `evm/scripts/` | 证据准备、本地基准、Sepolia 部署与审计、作图、报告生成 |
| `evm/results/` | 测试结果、本地回执、Sepolia 部署记录与交易指标 |
| `evm/out/` | 编译产物，用于核对链上字节码 |
| `evm/docs/` | 术语、范围、Sepolia 偏差说明、中文说明 |

## 事件格式

| 事件 | 字段 | 使用方 |
|---|---|---|
| `ANALYSIS_RECORD` | record_id, conclusion（≤512 字节）, evidence_hash, evidence_uri, model_version, confidence | B1 |
| `REGISTER_SAMPLE` | commitment, license_id, dataset_commitment, shard_id | A2 |
| `SET_CONSENT` | commitment, state（granted / revoked） | A2 |
| `ANCHOR_MODEL` | model_id, model_hash, shard_roots, parent_model_hash | A2 |
| `UNLEARNING_RECEIPT` | commitment, shard_id, old/new_shard_root, old/new_model_hash, consent_tx | A2 |
| `LICENSE_AUDIT` | model_id, policy, n_samples, violations | A2 |

禁止上链的字段：patient_key、patient_id、salt、features、source_patient_id（`Event.validate` 直接拒绝）。自由文本 `conclusion` 仍需提交者自行检查。

## 必须注意

1. **证据哈希以仓库中的 LF 文件为准。** 链上登记的 `evidence_hash = 50c74c7a…` 是对 LF 换行的仓库文件计算的。本机 `experiments/` 下的原始结果文件是 Windows 的 CRLF 换行，直接计算会得到 `12bd8f4a…`，文件内容相同。审计请在仓库副本（`dist/multimodal-acquisition-consentchain/`）中运行；导出脚本 `tools/export_github_b1_a2.py` 会把文本文件统一转成 LF。
2. **`evm/scripts/write_report.py` 会改写 `papers/b1_jbhi/main.tex`。** 本机的 `papers/b1_jbhi/` 是 v2 稿件，不要在这里运行它；v3 稿件单独存放在 `papers/b1_jbhi_v3/`。
3. **公共 RPC 节点偶发出错**（ethers 报 `could not coalesce error`）。`ledger_bridge.mjs` 没有重试逻辑；遇到这种报错，重新运行一次即可。
4. **钱包不在仓库中。** 写入 Sepolia 需要通过环境变量 `MODEL_REGISTRY_SECRET_DIR` 指定加密钱包目录；只读操作（`events`、`verify`、`audit_sepolia.mjs`）不需要钱包。
5. 本地 Anvil 采用 Shanghai 规则，gas 与当前 Sepolia 相差 3–7 倍（见 `evm/docs/SEPOLIA_DEVIATIONS.md`），两组数字不能混用。

## 复现

```bash
cd experiments/chain_interface/evm
npm ci --ignore-scripts --no-audit --no-fund
node scripts/audit_sepolia.mjs        # 只读核验链上合约、回执与记录（会改写 results/sepolia_live_audit.json）
```

```bash
python -X utf8 experiments/b1_cost_acquisition/anchor_results.py                 # 本机日志
python -X utf8 experiments/b1_cost_acquisition/anchor_results.py --backend evm   # Sepolia；内容相同的记录会复用原回执，不发新交易
```

合约测试和本地基准需要 Foundry（forge / anvil），步骤见 `evm/README.md`。

## 2026-10-29 合并时的核验结果

| 检查 | 结果 |
|---|---|
| `audit_sepolia.mjs`（只读，公共 RPC） | 9/9 通过：链 ID、owner、链上字节码与编译产物一致、源码哈希一致、5 笔交易（含 1 笔失败）回执与费用一致、2 条记录摘要、元数据修订历史 |
| Python `BlockchainLedger.events()` | 读回 2 条记录，证据哈希与仓库文件一致 |
| A2 事件发往 EVM 后端 | 按设计拒绝 |
| A2 冒烟测试（本机日志） | 12/12 通过 |
| `anchor_results.py`（本机日志） | 链完整、证据一致 |
| 合约测试 / 本地基准 | 未重跑（本机没有 Foundry）；采用对方记录的 `evm/results/forge_tests.json` 与 `local_benchmark.json` |
