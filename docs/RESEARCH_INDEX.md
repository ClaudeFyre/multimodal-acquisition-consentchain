# 研究总索引：实验 → 论文

更新于 2026-10-18。只覆盖肺癌预后主线和 B1 / A2 两篇论文；数据湖本身见根目录 `README.md`，其他研究路线见 `RESEARCH_ROUTES_2026-10-15.md`。

## 两篇论文（相互独立）

| | B1 | A2 |
|---|---|---|
| 题目 | Stage Before Sequencing: Cost-Aware Sequential Modality Acquisition for Multimodal Survival Prediction in NSCLC | ConsentChain: Blockchain-Anchored Provenance and Consent Ledger with Verifiable Unlearning |
| 征稿方向 | AI-Driven Multimodal Intelligence for Sustainable Healthcare Systems | Blockchain and MLLMs for Precision and Preventive Healthcare |
| 目标期刊 | 原拟 IEEE JBHI；2025版中科院大类医学 **2区**。2026-10-20二区优先规划：CMPB/BMC Medical Research Methodology，详见下方投稿规划 | 待定；完整实验后评估 JBHI/JBI |
| 论文目录 | `papers/b1_jbhi/`（初稿 6 页，含 6 图 1 表） | `papers/a2_consentchain/`（骨架，2 页） |
| 实验目录 | `experiments/b1_cost_acquisition/` | `experiments/a2_consent_unlearning/` |
| 状态 | 实验完成；初稿完成；待核对作者、单位、参考文献卷期、汇率 | 接口骨架和冒烟测试完成；ML 实验未开始；**区块链部分不在本机做，接口已留** |
| 摘要草稿 | `docs/B1_JBHI_title_abstract_draft_2026-10-08.md` | `docs/A2_title_abstract_draft_2026-10-08.md` |

两篇唯一的联系：A2 的"医学模型接口"（`sisa.ShardTrainer`）计划直接复用 B1 的 Cox 生存模型和同一队列。

投稿选择与阶段安排见 [2026-10-20投稿规划](JOURNAL_SUBMISSION_PLAN_2026-10-20.md)。该规划使用2025版中科院大类分区，区分当前稿件适配性与完成新实验后的候选期刊，不代表已投稿。

进一步探索与已有研究/数据对照见 [2026-10-20研究探索分析](RESEARCH_EXPLORATION_2026-10-20.md)。新增核查指出B1的“oracle”仅按风险变化量排序，不是对真实预测收益的最优采集上界；历史实验保持原样，解读以新分析的边界为准。

## 实验依赖关系

```
lung_missingness/prepared      1,313 例 TCGA+CPTAC NSCLC：临床、WSI（TITAN）、RNA 特征
   ├── lung_missingness (v2)   融合 vs 临床（不含分期）；发现 IPCW 实现偏差
   ├── h1_stage_recheck        加入分期后内部融合增益 +0.042 → +0.001
   ├── rna_transport (H2)      7 个 GEO 外部队列：RNA 增益 +0.073 → +0.022（加分期）
   ├── b1_cost_acquisition     逐步采集策略、Pareto 前沿 ──────────────→ 论文 B1（H1、H2 结果也写入 B1）
   └── a2_consent_unlearning   登记、账本、分片遗忘（接口） ─────────────→ 论文 A2
```

| 实验 | 冻结协议 | 报告 | 关键结论 |
|---|---|---|---|
| `lung_missingness` | `protocol_v2.json` | `REPORT_PROTOCOL_V2_2026-10-04.md` 等 | 方法分支收敛；v2 的 +0.071 用了非标准 IPCW 写法 |
| `h1_stage_recheck` | `ADDENDUM.md`（`f4a809ad…`） | `REPORT.md` | 标准 Uno：+0.042；加分期 +0.001 |
| `rna_transport` | `PROTOCOL_H2.md`（`01049de6…`） | `REPORT_H2.md` | 外部合并 +0.022 [−0.001, +0.045]，主假设不成立 |
| `b1_cost_acquisition` | `PROTOCOL_B1.md`（`ad1acf74…`） | `REPORT_B1.md` | 含分期时零成本策略 Pareto 最优；VoI 不优于随机 |
| `a2_consent_unlearning` | 尚未写 | — | 仅接口；冒烟测试 12/12 通过 |

## 区块链接口位置（A2）

| 位置 | 文件 | 说明 |
|---|---|---|
| 账本后端 | `experiments/a2_consent_unlearning/ledger.py` → `BlockchainLedger` | 实现 `append / events / verify` 三个方法即可接入；事件和字段约定见同目录 README |
| 基线 | 同文件 `LocalHashChainLedger` | 本机哈希链日志，已实现，作为"中心化审计日志"对照 |
| 论文 | `papers/a2_consentchain/main.tex` 中的蓝色 `[BLOCKCHAIN]` 框 | 链的选型、部署、开销与防篡改实验共 7 处；红色 `[TODO]` 为本机可做的 ML 部分（12 处） |

## 公共约定

- 运行环境：`experiments\.venv`；GPU 常被其他实验占用，CPU 任务设 `CUDA_VISIBLE_DEVICES=-1` 并限制线程数，不抢占 GPU。
- 新实验先写协议，用 SHA-256 冻结后再运行；偏离写 `DEVIATIONS.md`，不改协议原文。
- 临床基线必须包含分期；C-index 用 `sksurv.concordance_index_ipcw`（标准 Uno）。
