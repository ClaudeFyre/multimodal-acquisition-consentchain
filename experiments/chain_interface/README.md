# chain_interface：B1 / A2 共用的区块链接口

建于 2026-10-20。对应论文 `papers/b1_jbhi` 图 1 的架构：

```
多模态数据 ─▶ 证据库（链下：原始数据、完整报告、SHA-256）
                │ evidence_hash = H(证据清单), evidence_uri
                ▼
           多模态分析（B1：分级 Cox + 逐步采集策略）─▶ 结构化结论（结论、证据引用、置信度、模型版本）
                │ 提交载荷 = 结论 + 证据哈希 + URI
                ▼
   ┌────────【区块链部分：接口已留，本机不实现】─────────────────────────┐
   │ 智能合约锚定：检查提交者与记录格式 → 存结论与证据哈希 → 发事件   │
   │ 链上记录：结论 / 证据哈希 / 模型版本；交易哈希 / 区块号 / 状态     │
   │ 性能监测：gas、TPS、确认延迟（benchmark.py）                         │
   └──────────────────────────────────────────────────────────────────────┘
                ▼
           可持续决策支持：可追溯决策、按成本分配资源、环境影响评估 ─▶ 结果反馈到下一轮评估
```

## 文件

| 文件 | 内容 | 状态 |
|---|---|---|
| `ledger.py` | 事件格式（相当于合约 ABI）、`Ledger` 抽象类、提交者授权与格式检查、本机哈希链实现、区块链后端占位 | 本机实现可用；**`BlockchainLedger` 留空** |
| `benchmark.py` | 固定测量窗口内的成功率、TPS、确认延迟 p50/p95、平均 gas | 可用；gas 只有链后端才有 |
| `../b1_cost_acquisition/anchor_results.py` | 把冻结的 B1 结果做成 `ANALYSIS_RECORD` 写入账本，并让审计方重新计算证据哈希核对 | 可用 |
| `../a2_consent_unlearning/` | 同意登记、撤回、分片遗忘与回执，使用同一接口 | 骨架可用 |

## 事件格式

| 事件 | 字段 | 使用方 |
|---|---|---|
| `ANALYSIS_RECORD` | record_id, conclusion（≤512 字符）, evidence_hash, evidence_uri, model_version, confidence | B1 |
| `REGISTER_SAMPLE` | commitment, license_id, dataset_commitment, shard_id | A2 |
| `SET_CONSENT` | commitment, state（granted / revoked） | A2 |
| `ANCHOR_MODEL` | model_id, model_hash, shard_roots, parent_model_hash | A2 |
| `UNLEARNING_RECEIPT` | commitment, shard_id, old/new_shard_root, old/new_model_hash, consent_tx | A2 |
| `LICENSE_AUDIT` | model_id, policy, n_samples, violations | A2 |

禁止上链：patient_key、patient_id、salt、features、source_patient_id（`Event.validate` 直接拒绝）。

交易回执 `Receipt`：tx_id、区块号 index、prev_hash、status、submitter、contract、submitted_at、confirmed_at、gas_used，以及由此计算的 latency_s。

## 接入区块链要做的事

1. 选型：Hyperledger Fabric（多组织背书，适合医院之间互不信任的场景）或 EVM 私链（gas 计量更直接）。
2. 写合约 / 链码：每种事件一个函数，参数与 `EVENT_FIELDS` 一致；在合约里复做"提交者授权 + 字段检查"，存储压缩记录并发出事件。
3. 实现 `BlockchainLedger` 的 `append / events / verify`，按上面的字段填好 `Receipt`。
4. 依次跑：
   - `a2_consent_unlearning/smoke_test.py`（把 `LocalHashChainLedger` 换成链后端），12 项检查应全部通过；
   - `b1_cost_acquisition/anchor_results.py`，确认链上记录与证据哈希一致；
   - `benchmark.py`，与本机哈希链在同一固定窗口下对比 gas、TPS、延迟。
5. 防篡改对照：单一管理者重写本机日志（可以做到）与在许可链上改写历史（需要多方背书）。这一项回答"为什么不用中心化日志"。

## 本机实测（只是接口自检，不是区块链性能）

`benchmark.py 500`：500/500 成功，约 1,568 条/秒，延迟中位数约 1 ms，gas 无。这只说明本机文件日志的开销可以忽略，不能当作链上性能写进论文。
