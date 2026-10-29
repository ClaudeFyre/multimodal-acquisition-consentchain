# 研究总索引：实验 → 论文

## 2026-10-27 新增：3D CT 定量/定位真值（ct_quant，第 1 阶段）

独立方向：3D CT 视觉-语言模型是否真的“量得准、找得对”。`experiments/ct_quant/` 从本地分割标注生成测量真值（TotalSegmentator-CT 1,228 例、LIDC 多阅片者结节、7 个病灶 SEG 数据集）和带“可判定性”标注的问题（`cache/ct_quant/questions.parquet`，版本 q-v1）。仅用 CPU、不联网。CT-RATE 改为只下有尺寸问答的 505 例（≈84 GB，分两批，需 HF_TOKEN）。3060 下载工具包：`dist/medlake_3060_kit.zip`（`python tools/build_kit.py` 重新生成）。详见 [ct_quant README](../experiments/ct_quant/README.md)。

## 2026-10-27 新增：TBME 数字孪生专题可行性

2026-10-29 共同作者讨论稿：新增 [9页IEEE双栏预期投稿PDF](../papers/tbme_digital_twin/submission_discussion_2026-10-29/TBME_expected_submission_discussion_2026-10-29.pdf) 与 [完整讨论包](../papers/tbme_digital_twin/TBME_coauthor_discussion_package_2026-10-29.zip)，含可编辑Word、5图5表及医生/计算研究者合作说明。独立虚拟示例红字，拟议和未核实内容高亮；真实研究稿与冻结实验未替换，148人预留仍未评分。

2026-10-29 后续：[首轮内部审稿](../papers/tbme_digital_twin/INTERNAL_REVIEW_2026-10-29.md)及正文修订已完成，当前为 [审稿修订版](../papers/tbme_digital_twin/manuscript_internal_review_v1_2026-10-29.md)。补到REV02/04基线完整裁剪DCE，统一五例临床审阅材料并形成未签署裁定稿。尚无新增最终专家意见，临床裁定、确认方案冻结和148人预留评估仍待完成；下段T0 DCE缺口为此前阶段状态。

2026-10-29 补充：已接收 R1/R2 预审及最新 R2 v2，完成固定五例源 FTV_PE 计数核对、开发集测量边界/逐中心/病例影响实验，重写 [英文全文](../papers/tbme_digital_twin/manuscript_draft_2026-10-29.md)。新增 [实验报告](../papers/tbme_digital_twin/EXPERIMENT_REPORT_2026-10-29.md)、[补充表](../papers/tbme_digital_twin/SUPPLEMENTARY_METHODS_RESULTS_2026-10-29.md) 和一次集中临床审阅清单。REV02/04 已补 T0 SER/掩膜，T0 DCE、解剖对应和最终医学裁定尚缺；实际给药仍缺。最终确认未冻结，148 人预留未评分。

独立于下方 B1/A2，新增 `papers/tbme_digital_twin/` 和 `experiments/tbme_twin_feasibility/`。692 人纵向队列中，544 人完成中心分组基线、不确定性 v1、分位数对照 v2 与测量稳健性 v3；三次校准划分重复使用同一队列。原候选评分等价于已有预测剖面投影，不作为新算法。既有分位数模型改善部分体积条件覆盖，但源零值覆盖较弱，没有统一优胜或机制孪生证据。五例源掩膜计数已复现，不等于解剖病灶金标准；独立确认仍未完成，稿件不可直接投稿。下方旧索引保留原两篇论文的范围与状态。

更新于 2026-10-18。只覆盖肺癌预后主线和 B1 / A2 两篇论文；数据湖本身见根目录 `README.md`，其他研究路线见 `RESEARCH_ROUTES_2026-10-15.md`。

## 两篇论文（相互独立）

| | B1 | A2 |
|---|---|---|
| 题目 | Stage Before Sequencing: Cost-Aware Sequential Modality Acquisition for Multimodal Survival Prediction in NSCLC | ConsentChain: Blockchain-Anchored Provenance and Consent Ledger with Verifiable Unlearning |
| 征稿方向 | AI-Driven Multimodal Intelligence for Sustainable Healthcare Systems | Blockchain and MLLMs for Precision and Preventive Healthcare |
| 目标期刊 | 原拟 IEEE JBHI；2025版中科院大类医学 **2区**。2026-10-20二区优先规划：CMPB/BMC Medical Research Methodology，详见下方投稿规划 | 待定；完整实验后评估 JBHI/JBI |
| 论文目录 | `papers/b1_jbhi/`（v2 精细稿 9 页，7 图 5 表，含架构图；区块链内容高亮；Overleaf 包 `b1_jbhi_overleaf_2026-10-20.zip`；v1 存于 `archive/`） | `papers/a2_consentchain/`（骨架，2 页） |
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
| 账本后端 | `experiments/chain_interface/ledger.py` → `BlockchainLedger`（2026-10-20 从 A2 目录移出，B1/A2 共用） | 实现 `append / events / verify` 三个方法即可接入；事件和字段约定见同目录 README |
| 基线 | 同文件 `LocalHashChainLedger` | 本机哈希链日志，已实现，作为"中心化审计日志"对照 |
| 论文 | `papers/a2_consentchain/main.tex` 中的蓝色 `[BLOCKCHAIN]` 框 | 链的选型、部署、开销与防篡改实验共 7 处；红色 `[TODO]` 为本机可做的 ML 部分（12 处） |

## 公共约定

- 运行环境：`experiments\.venv`；GPU 常被其他实验占用，CPU 任务设 `CUDA_VISIBLE_DEVICES=-1` 并限制线程数，不抢占 GPU。
- 新实验先写协议，用 SHA-256 冻结后再运行；偏离写 `DEVIATIONS.md`，不改协议原文。
- 临床基线必须包含分期；C-index 用 `sksurv.concordance_index_ipcw`（标准 Uno）。

## 代码仓库（2026-10-20）

私有仓库 `ClaudeFyre/multimodal-acquisition-consentchain`，内容由 `tools/export_github_b1_a2.py` 按白名单导出到 `dist/multimodal-acquisition-consentchain/`（不含数据和患者级文件）。区块链接口统一在 `experiments/chain_interface/`（B1 的 `anchor_results.py` 与 A2 共用）。

## 2026-10-29：v3 稿件、评审与工程合并

- v3 稿件（含 Sepolia 链实验）单独存放在 `papers/b1_jbhi_v3/`；`papers/b1_jbhi/` 仍是 v2，未改动。
- v3 评审：`papers/b1_jbhi/review/REVIEW_v3_2026-10-29.md`（图 1 与正文矛盾、本地/Sepolia gas 差异、被删除的限定语、S01–S07 状态）。
- Sepolia EVM 后端已合并到 `experiments/chain_interface/evm/`，`BlockchainLedger` 已实现（仅 B1）；合并记录见 `dist/multimodal-acquisition-consentchain/MERGE_NOTES.md`。
- 链上证据哈希对应 LF 换行文件；本机原始结果为 CRLF，审计用仓库副本。
- 匿名评审工程：`dist/anon-stage-before-sequencing/`（由 `tools/export_anonymous.py` 生成）。
