# Multimodal Acquisition & ConsentChain

NSCLC 术后多模态预后的成本感知采集研究（B1），与同意账本 / 可验证遗忘研究（A2）共用的代码仓库。两篇论文共享 `Ledger` 接口：分析代码只调用 `Ledger`。B1 的 `ANALYSIS_RECORD` 已接入 EVM 模型证据合约并部署在 Ethereum Sepolia（合约 `0xF3A2732f7521ED01A0AeaB874F9b2E46aB6B0155`）；A2 的链后端仍未实现。

> 私有仓库，未授权公开或再分发（All rights reserved）。不含任何数据、患者级特征、预测结果或钱包密钥。合并记录见 [MERGE_NOTES.md](MERGE_NOTES.md)。

## 目录

```
experiments/
  chain_interface/        共用账本接口（事件格式 = 合约 ABI）+ 性能监测脚本      ← 区块链接口位置
  b1_cost_acquisition/    B1：冻结协议、逐步采集实验、结果、结论上链脚本
  a2_consent_unlearning/  A2：样本登记与加盐承诺、分片训练与遗忘、冒烟测试（骨架）
  h1_stage_recheck/       加入病理分期后的内部融合增益复核（B1 引用）
  rna_transport/          H2：7 个 GEO 外部队列的 RNA 分支迁移（B1 引用）
  lung_missingness/       队列准备、预处理与 Cox 模型（B1 / H1 依赖）
papers/
  b1_jbhi/                B1 论文 v2（IEEE JBHI 模板，9 页）、作图脚本、成本向量、draw.io 源文件、Overleaf 打包
  b1_jbhi/review/         v3 稿件评审
  b1_jbhi_v3/             B1 论文 v3（含 Sepolia 链实验），单独存放
  a2_consentchain/        A2 论文骨架
registry/datasets.yaml    公开数据集元数据（来源、license）
docs/RESEARCH_INDEX.md    实验与论文的总索引
```

## 架构与区块链接口

论文 B1 图 1：多模态数据 → 链下证据库（SHA-256）→ 多模态分析 → 结构化结论 → 提交载荷（结论 + 证据哈希 + URI）→ **智能合约锚定 → 链上记录 → 性能监测（gas / TPS / 延迟）** → 可持续决策支持 → 结果反馈。加粗部分是区块链层。

| 位置 | 内容 | 状态 |
|---|---|---|
| `experiments/chain_interface/ledger.py` → `Ledger` | `append / events / verify`，提交者授权与字段检查，`Receipt`（tx hash、区块号、状态、gas、延迟） | 接口已定 |
| 同上 → `LocalHashChainLedger` | 本机哈希链日志，作为"中心化审计日志"对照 | 已实现 |
| 同上 → `BlockchainLedger` | B1 `ANALYSIS_RECORD` 的 EVM 后端（经 `evm/scripts/ledger_bridge.mjs`） | 已实现；A2 事件不在支持范围 |
| `experiments/chain_interface/evm/` | Solidity 合约、30 项合约测试、本地基准、Sepolia 部署与审计脚本、结果 | 详见该目录 README |
| `experiments/chain_interface/benchmark.py` | 固定测量窗口内的成功率、TPS、延迟 p50/p95、gas | 可用 |
| `experiments/b1_cost_acquisition/anchor_results.py` | 把 B1 冻结结果写成 `ANALYSIS_RECORD`，审计方重算证据哈希核对 | 可用 |
| `experiments/a2_consent_unlearning/` | 同意登记、撤回、分片遗忘与回执 | 骨架可用 |

接入步骤和事件字段说明见 [`experiments/chain_interface/README.md`](experiments/chain_interface/README.md)。

## 复现

环境：Python 3.12，依赖见 `experiments/lung_missingness/requirements.txt`（numpy 2.3.4、pandas 2.3.3、scikit-learn 1.9.1、scikit-survival 0.28.0 等）。B1 全部为 CPU 计算。

**数据不在仓库中。** 需要先从 GDC（TCGA-LUAD/LUSC、CPTAC-LUAD/LSCC）、MMIST-LUNG 作者发布的特征和 GEO 下载数据，并用 `experiments/lung_missingness/prepare.py` 生成 `experiments/lung_missingness/prepared/`（cohort.csv、features.npz、summary.json）。

```bash
# B1 主实验（约 10 分钟，CPU）
CUDA_VISIBLE_DEVICES=-1 python -X utf8 experiments/b1_cost_acquisition/run_b1.py
# 结论上链（默认写入本机哈希链）
python -X utf8 experiments/b1_cost_acquisition/anchor_results.py
# 账本接口自检与性能监测
python -X utf8 experiments/a2_consent_unlearning/smoke_test.py
python -X utf8 experiments/chain_interface/benchmark.py 500
# 论文作图
python -X utf8 papers/b1_jbhi/make_figures.py
```

`run_b1.py` 运行时会核对 `PROTOCOL_B1.md` 的 SHA-256（`ad1acf74…`），协议被改动时拒绝运行。

## 主要结果（B1）

| 3 年 Uno C-index | 只用临床病理 | + WSI | + WSI + RNA |
|---|---:|---:|---:|
| 含病理分期 | 0.644 | 0.638 | 0.645 |
| 不含分期 | 0.580 | 0.610 | 0.622 |

- 含分期时，没有任何更贵的采集方案在 bootstrap 区间之外优于零成本方案；VoI 选择在多重校正后不优于随机选择。
- 不含分期时，成本–性能前沿为"先 WSI、后 RNA"。
- 外部 7 个 GEO 队列（1,690 例）：RNA 增益加入分期后由 +0.073 降至 +0.022。

## 限制

- 撤回同意是模拟的（公开队列患者无法真正撤回）；账本只能证明遗忘流程执行过。
- B1 链实验已测本地 gas 与运行开销、检查授权与哈希一致性，并在 Sepolia 完成部署、两条登记和一次元数据修订；只有单一账户写入，多医院背书、共识安全和 A2 链事件未验证。
- 链上证据哈希对应本仓库中 LF 换行的文件（见 `experiments/chain_interface/README.md`）。
- 成本为文献情景值；RNA 湿实验碳排放缺少同行评审数据。
