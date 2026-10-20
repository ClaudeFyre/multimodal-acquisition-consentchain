# 肺癌多模态生存实验：协议 v2 执行报告

> 本文记录了最初内部主批次。后续依用户要求补完的 IPCW bootstrap、MLP-Cox 网格、多时点校准、双向迁移和条件缺失结果见 [FOLLOWUP_ANALYSIS_2026-10-04.md](FOLLOWUP_ANALYSIS_2026-10-04.md)；后续执行台账已追加。下方“未完成或偏离”是初稿状态，后续状态以补充报告为准。

执行日期：2026-10-04。所有新产物写入 `runs/`、`audit_v2/`、`results_v2_final/`；既有 `results/` 与 `robustness_results/` 未覆盖。原始缓存未下载或修改。

## 数据可信度与研究定位

本地缓存共有 1,365 例，满足明确状态和有效生存时间的回顾性分析队列为 1,313 例（484 个死亡事件；TCGA 1,005、CPTAC 308）。每患者终点时间来源、队列、组织学编码和模态可用性见 `audit_v2/patient_provenance.csv`；52 个排除病例另见 `audit_v2/excluded_patient_provenance.csv`。字段日期、WSI/RNA/影像采集时间均无可靠逐患者缓存，统一记为 unknown，不推断先后。故停止诊断时前瞻性预测主张，结果仅支持回顾性技术评估。

`diagnoses.age_bin` 源自出生日期换算年龄后按十年分箱，当前特征未保存连续年龄；主模型按类别独热编码。可能术后的 AJCC 病理分期从主要临床输入中排除。`audit_v2/feature_provenance.md` 列出基线候选字段、病理增强字段和时间限制。作者 RNA 预选/归一化拟合范围与 WSI encoder 训练人群未核实，fold-local PCA 不能消除上游泄漏风险。

## 冻结划分与运行

先生成并冻结 `protocol_v2.json`，患者级五折、按来源/事件分层；每个外层折使用固定的内层验证划分。实际主批次覆盖 5 折 × 3 个训练种子（41/42/43），内部经典基线和融合模型、masked TokenCox、随机模态丢弃 TokenCox；每个测试患者在一个外折测试。另有首批含病理字段的错误性中间运行以及去掉分期但将年龄 bin 视为数值的中间运行，全部保留但**不纳入最终结果**。最终运行目录为 `runs/internal5x3_final_categorical_age/`。

设备为 NVIDIA P104-100（8 GB，CC 6.1），PyTorch 2.14.0+cu126。阶段 0 smoke 使用真实划分 840/210/263 人跑 5 epoch；最大 CUDA 分配 34.96 MB，训练段 0.466 秒，预处理 CPU 1.228 秒。CPU/GPU 固定权重最大预测差 2.98e-7、Cox 损失差 0，checkpoint 恢复预测差 0；模型与输入均在 CUDA。Transformer backward 触发 CUDA 内存高效注意力非确定性警告，已启用 deterministic algorithms warn-only 并保留说明。见 `audit_v2/gpu_smoke_retry1/gpu_smoke.json`。

## 内部交叉验证结果

自然模态可用条件下，三年 IPCW C-index 为五折和三种子运行的均值（SD）：临床 0.5800、WSI 0.5910、RNA 0.6181、早期融合 0.6219、后期融合 0.6398、masked TokenCox 0.6240、随机丢弃 TokenCox 0.6323。后期融合高于临床基线的表面增益为 0.0597；随机丢弃高于同架构 masked TokenCox 的表面增益为 0.0083。内部折之间存在差异，不能将各折风险分数直接拼接。

两项预设比较已有 2,000 次患者配对 bootstrap 和 Holm 校正，当前实现计算的是 **Harrell C**（作为辅助比较），而不是冻结方案指定的主要三年 IPCW C；区间固定已拟合模型且没有重训练不确定性。数值见 `results_v2_final/primary_comparisons.csv`：早期融合对临床 Harrell C 差 0.0509，95% 区间 [0.0179, 0.0832]；丢弃对 masked TokenCox 在 50% 人工删除条件下差 0.0185，区间 [0.0083, 0.0298]。目前不据此宣称达到方法收益门槛。

随机丢弃 TokenCox 的三年 IPCW C-index 在自然条件为 0.6323，仅临床为 0.5694，50% 随机删除为 0.5989，90% 为 0.5800。人工删除不证明真实 MNAR 鲁棒性。曲线见 `results_v2_final/figures/missingness_curve.png`。

跨队列 TCGA→CPTAC 三种子探索结果在首批目录 `runs/internal5x3_seeded/`，该批临床字段包含病理分期，只能视为病理增强探索且未纳入本报告主结果。反向迁移没有运行。CPTAC 已在此前实验使用，不是未见测试集。

## 协议覆盖与偏离

已完成：GPU 入口和 float32 Cox 完整风险集/Breslow ties；smoke 与 checkpoint 核验；患者来源/时间审计；protocol v2 冻结；五折三种子内部基线；人工模态删除/置换；汇总表、缺失曲线和中文报告。六项既有完整性检查通过（`test_integrity.py`）。

未完成或偏离：当前实验入口没有实现 MLP-Cox、内层学习率网格 `{0.0003, 0.001}` × weight decay `{0.001, 0.01}`、dropout `{0.1, 0.3, 0.5}` 全候选、PCA32/WSI768 敏感性、独立 stage-enhanced 明确时点实验、1/2/3 年 AUC/Brier、支持范围 integrated Brier、校准曲线、来源/组织学分层和 IPCW 主比较 bootstrap；`robustness.py` 仍是旧 CPU 接口，本轮未迁移；Cox 风险预测的完整校准器也未跨时间评测。冻结文件记录了完整计划，当前交付必须称为协议的部分执行版本，不是阶段 0–6 全验收完成。后续应优先补主比较 IPCW 患者 bootstrap与多时间点校准，再决定是否扩展架构/超参网格。

## 文件索引

- `protocol_v2.json`：冻结方案与缓存/代码哈希。
- `audit_v2/`：患者溯源、时间起点、年龄编码、排除流和 smoke 证据。
- `runs/internal5x3_final_categorical_age/`：最终内部预测、划分、逐候选指标、预处理器、best checkpoint、环境哈希和运行状态。
- `results_v2_final/`：指标摘要、缺失曲线、两项配对比较和图片。
- `runs/` 下其余目录：失败空跑和未纳入的中间/探索运行，按目录 status 留档。

