# B1：按成本逐步采集模态的 NSCLC 术后生存预测

对应论文：`papers/b1_jbhi/`（IEEE JBHI 初稿）。状态：**已完成**（2026-10-08 运行，未偏离协议）。

| 文件 | 内容 |
|---|---|
| `PROTOCOL_B1.md` | 冻结协议（运行前写定） |
| `PROTOCOL_B1.freeze.json` | 协议 SHA-256 `ad1acf74…` 与输入数据哈希；`run_b1.py` 运行时会校验 |
| `run_b1.py` | 全部分析（CPU only，约 10 分钟） |
| `results/results.json` | Q1–Q4 汇总、Pareto 前沿、逐折信息 |
| `results/grid_mean_*.csv`、`grid_per_fold_*.csv` | 66 个预算组合的 C-index（VoI / 随机 / 神谕） |
| `REPORT_B1.md` | 结果与解读 |
| `run.log` | 运行日志 |

依赖：`experiments/lung_missingness/prepared/`（队列和特征）、`lung_missingness/models.py`（预处理和 Cox）、`h1_stage_recheck/run_recheck.py`（分期重建规则）。

重跑（不会覆盖冻结结果以外的东西；GPU 被占用时也安全）：

```powershell
$env:CUDA_VISIBLE_DEVICES="-1"; $env:OMP_NUM_THREADS="6"; experiments\.venv\Scripts\python.exe -X utf8 experiments\b1_cost_acquisition\run_b1.py
```

一句话结论：含病理分期时，WSI 和 RNA-seq 都不带来可检测的预后区分度增益，零额外成本的临床病理模型在成本–性能前沿上；不含分期时，前沿是"先 WSI、后 RNA"。非劣检验的 b* = 0.8 是界值过严导致的检验力不足，不是"80% 的患者需要 RNA-seq"。
