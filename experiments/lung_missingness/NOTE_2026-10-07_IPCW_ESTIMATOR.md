# 说明：v2 IPCW C-index 实现与标准定义不一致（2026-10-07）

本文件不修改任何已冻结的 v2 结果，只记录事后发现的问题。详细数值见 `experiments/h1_stage_recheck/REPORT.md`。

- `ipcw_bootstrap.py` 和 `grid_ipcw_bootstrap.py`（已核实，第 16、39、47 行）在计算 3 年 IPCW C-index 前，
  删除了所有 `time_days >= 1095` 的测试患者。标准 Uno 估计量（scikit-survival `concordance_index_ipcw(tau=1095)`）
  保留这些患者作为比较对象，只是不让他们作为先发生事件的一方。
- 影响：主比较"早期融合 Cox vs 临床 Cox"由 +0.0711 [0.0340, 0.1101] 变为标准估计量下的 **+0.042 [+0.008, +0.077]**（p = 0.012）。
  `FOLLOWUP_ANALYSIS_2026-10-04.md` 表中"临床 Cox 0.5800"来自标准估计量，与 +0.0711 的差值来自不同写法，二者不应并列解读。
- 此外，临床基线加入病理分期后，该增益降为 +0.001 [−0.024, +0.029]（事后分析）。
- 依赖 v2 IPCW 数值的其他结论（随机丢弃 vs masked、迁移结果）也应按标准估计量复核。
