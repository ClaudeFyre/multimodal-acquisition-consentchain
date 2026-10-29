# 合并记录：Sepolia EVM 链实验（2026-10-29）

来源：`papers/b1_jbhi/new/outputs.zip` → `B1_Sepolia_完整项目.zip`（`multimodal-acquisition-consentchain-main`，151 个文件），以及同目录的 v3 Overleaf 包。

## 合并了什么

| 内容 | 处理 |
|---|---|
| `experiments/chain_interface/evm/`（合约、测试、脚本、配置、证据、结果、编译产物） | 新增 |
| `experiments/chain_interface/ledger.py` | 采用对方版本：只改了 `BlockchainLedger`，从占位变为经 Node 桥接调用合约的 B1 后端 |
| `experiments/b1_cost_acquisition/anchor_results.py` | 采用对方版本：新增 `--backend evm` 等参数 |
| `experiments/chain_interface/README.md`、根目录 `README.md` | 两边内容手工合并 |
| v3 论文源码与 PDF | 放入 `papers/b1_jbhi_v3/`，**不覆盖** `papers/b1_jbhi/`（v2） |
| v3 评审 | `papers/b1_jbhi/review/REVIEW_v3_2026-10-29.md` |

## 没有合并的

- 对方包里的 `papers/b1_jbhi/main.tex`、`main.pdf`、图和 `make_figures.py`：会覆盖 v2 稿件，按"不直接修改论文"的要求不合并；v3 以 Overleaf 包为准。
- `DELIVERY_CONTENTS.md`：交付说明，内容已并入本文件。
- `node_modules/`、`cache/`、钱包目录 `secrets/`、`.env`：不进仓库（对方包本来也不含钱包）。

## 合并时发现并处理的问题

1. **换行符与证据哈希。** 链上 `evidence_hash = 50c74c7a…` 对应 LF 换行的仓库文件；本机原始文件是 CRLF，直接计算得 `12bd8f4a…`。导出脚本现在会把文本文件统一转成 LF，仓库副本重算结果为 `50c74c7a…`，与链上一致。
2. **`write_report.py` 会改写 `papers/b1_jbhi/main.tex`。** 已在接口 README 中注明不要在本仓库直接运行。
3. **公共 RPC 偶发失败。** `ledger_bridge.mjs` 无重试，偶尔报 `could not coalesce error`，重跑即可。

## 核验

- 只读链上审计 `audit_sepolia.mjs`：9/9 通过，包括链上字节码与编译产物一致。
- Python `BlockchainLedger.events()`：读回 2 条记录，证据哈希与仓库文件一致；A2 事件被拒绝。
- 本机回归：A2 冒烟测试 12/12，`anchor_results.py`（本机日志）通过，`benchmark.py` 通过。
- 未重跑：forge 合约测试和 Anvil 本地基准（本机没有 Foundry），采用对方记录的结果文件。
