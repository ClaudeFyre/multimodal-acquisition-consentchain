# A2：数据溯源、同意账本与可验证遗忘（代码骨架）

建于 2026-10-18。状态：**接口骨架 + 冒烟测试通过；没有任何正式实验结果。** 区块链部分按 2026-10-08 的决定**不在本机做**，只留接口。
论文骨架：`papers/a2_consentchain/`；题目和摘要草稿：`docs/A2_title_abstract_draft_2026-10-08.md`。

## 结构（三层，只通过 `Ledger` 接口相连）

```
records.py   离线登记：每条训练样本的来源、license、patient_key + 盐 → 承诺值（只在本机）
   │  commitment（加盐哈希）
   ▼
ledger.py    账本接口 Ledger ──┬── LocalHashChainLedger   本机哈希链日志（= 论文里的"中心化审计日志"基线，已实现）
   ▲                           └── BlockchainLedger        【区块链接口位置】许可链后端，未实现
   │  只传承诺值 / Merkle 根 / 模型哈希 / license id
sisa.py      分片训练 + Merkle 证明 + 遗忘流程（train_all / unlearn）
   │
   └── ShardTrainer             【医学模型接口位置】接真实模型（B1 的 Cox / 多模态生存模型，或小 VLM 的 LoRA）
```

| 文件 | 内容 | 状态 |
|---|---|---|
| `ledger.py` | 事件类型、字段约定、`Ledger` 抽象类、本机哈希链实现、区块链后端占位 | 接口已定，本机实现可用 |
| `records.py` | 从 `lung_missingness/prepared` 和 `registry/datasets.yaml` 生成 1,313 条样本记录；加盐承诺；撤回后销毁盐值 | 可用 |
| `sisa.py` | 按承诺值分片、Merkle 根和成员证明、`train_all`、`unlearn` | 可用；训练器为接口 |
| `smoke_test.py` | 用哑训练器跑通"登记 → 训练 → 撤回 → 单分片重训 → 回执"，12 项检查 | 2026-10-18 全部通过 |

运行冒烟测试（输出写到临时目录，不污染项目）：

```powershell
experiments\.venv\Scripts\python.exe -X utf8 experiments\a2_consent_unlearning\smoke_test.py
```

## 区块链接口约定（给做链上实验的人）

后端只需实现 `ledger.Ledger` 的三个方法：`append(event) -> Receipt`、`events(kind)`、`verify()`。

### 事件类型与字段（`ledger.EVENT_FIELDS`，链上合约/链码必须一一对应）

| 事件 | 字段 | 何时产生 |
|---|---|---|
| `REGISTER_SAMPLE` | commitment, license_id, dataset_commitment, shard_id | 样本进入受管数据池 |
| `SET_CONSENT` | commitment, state（granted / revoked） | 患者授权或撤回 |
| `ANCHOR_MODEL` | model_id, model_hash, shard_roots, parent_model_hash | 每次训练或重训出新模型 |
| `UNLEARNING_RECEIPT` | commitment, shard_id, old/new_shard_root, old/new_model_hash, consent_tx | 遗忘完成，回执关联撤回交易 |
| `LICENSE_AUDIT` | model_id, policy, n_samples, violations | 训练前的许可合规检查 |

**禁止上链的字段**（`FORBIDDEN_KEYS`，`Event.validate` 会拒绝）：patient_key、patient_id、salt、features、source_patient_id。

### 区块链实验待补（论文中对应位置已留空）

1. 选型与部署：Hyperledger Fabric（多组织 MSP、背书策略）或 EVM 私链；节点数、组织数。
2. 实现 `BlockchainLedger`，跑通 `smoke_test.py`（把 `LocalHashChainLedger` 换成链后端即可）。
3. 测量：每个事件的提交到确认延迟、吞吐量、每个事件的存储开销、背书开销；与 `LocalHashChainLedger` 对比。
4. 防篡改与多方核查：单方篡改历史时，本机日志（单一管理者可整体重写）与许可链（需要多方背书）的差异。这是回答"为什么不用中心化日志"的关键实验。

## 机器学习侧待做（本机可做，尚未开始）

1. 用真实模型实现 `ShardTrainer`：先用 B1 的 Cox 生存模型（便宜，分片数可以做到几十个），再考虑 ≤2B VLM + LoRA。
2. 分片数与精度、遗忘成本的权衡；撤回比例 1%–20% 的扩展性。
3. 成员推断攻击（MIA）检验被撤回样本是否仍可被识别。
4. license 违规检测：故意混入许可不兼容的样本，看审计能否查出。
5. 运行前先写冻结协议（沿用 B1 的 `PROTOCOL_*.md` + SHA-256 冻结流程）。

## 限制（写论文时必须如实说明）

- 公开数据集（TCGA / CPTAC）的患者不能真正撤回同意；撤回请求是**模拟**的。
- 账本只能证明遗忘**流程执行过**；"模型确实不受该样本影响"的保证来自分片精确重训，并由 MIA 做实证检验。
