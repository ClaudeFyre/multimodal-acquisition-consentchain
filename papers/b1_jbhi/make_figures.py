"""Figures for the B1 manuscript. Reads frozen B1/H1/H2 outputs; writes figures/*.pdf and *.png.

Colors: reference categorical slots 1-3 (blue, orange, aqua) + neutral gray for the random baseline.
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
from scipy.interpolate import PchipInterpolator

HERE = Path(__file__).resolve().parent
EXP = HERE.parent.parent / "experiments"
B1 = EXP / "b1_cost_acquisition" / "results"
FIG = HERE / "figures"
FIG.mkdir(exist_ok=True)

BLUE, ORANGE, AQUA, GRAY = "#2a78d6", "#eb6834", "#1baf7a", "#8a8984"
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e4e3df"
VERS = {"B_stage_group": ("With pathologic stage", BLUE), "A_no_stage": ("Without stage", ORANGE)}
plt.rcParams.update({"font.family": "serif", "font.size": 8, "axes.edgecolor": INK2, "axes.labelcolor": INK,
                     "xtick.color": INK2, "ytick.color": INK2, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.5, "lines.linewidth": 1.5,
                     "legend.frameon": False, "pdf.fonttype": 42, "savefig.dpi": 300})

cost = json.loads((HERE / "cost_vector.json").read_text("utf-8"))
SCEN = {"Low RNA:WSI ratio": cost["cost_scenarios_usd"]["low_ratio"],
        "High RNA:WSI ratio": cost["cost_scenarios_usd"]["high_ratio"]}
res = json.loads((B1 / "results.json").read_text("utf-8"))["results"]
grid = {v: pd.read_csv(B1 / f"grid_mean_{v}.csv") for v in VERS}


def save(fig, name):
    fig.savefig(FIG / f"{name}.pdf", bbox_inches="tight")
    fig.savefig(FIG / f"{name}.png", bbox_inches="tight")
    plt.close(fig)


# ---------- Fig 0: system architecture (restyled from Multimodal_Blockchain_Sustainability_Architecture.drawio) ----------
AMBER, AMBER_BG, BLUE_BG, GRAY_BG, PAPER = "#b77900", "#fdf3dc", "#e8f0fb", "#f1f1ee", "#ffffff"
KIND = {"eval": (BLUE, PAPER, "-"), "chain": (AMBER, AMBER_BG, "--"), "part": (GRAY, GRAY_BG, "-"), "plain": (INK2, PAPER, "-")}


def _box(ax, x, y, w, h, title, lines=(), kind="eval", tsize=5.9, lsize=4.9, lstep=2.3):
    ec, fc, ls = KIND[kind]
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=0.9", fc=fc, ec=ec,
                                lw=0.9, ls=ls, zorder=2))
    if title:
        ax.text(x + w / 2, y + h - 1.4, title, ha="center", va="top", fontsize=tsize, weight="bold",
                color=AMBER if kind == "chain" else INK, zorder=3)
    for i, ln in enumerate(lines):
        ax.text(x + w / 2, y + h - 4.2 - i * lstep, ln, ha="center", va="top", fontsize=lsize, color=INK2, zorder=3)


def _arrow(ax, p, q, color=INK2, ls="-", lw=0.9, label=None, loff=(0, 0.5), va="bottom"):
    ax.add_patch(FancyArrowPatch(p, q, arrowstyle="-|>", mutation_scale=7, color=color, lw=lw, ls=ls,
                                 zorder=4, shrinkA=0.5, shrinkB=0.5))
    if label:
        ax.text((p[0] + q[0]) / 2 + loff[0], (p[1] + q[1]) / 2 + loff[1], label, fontsize=4.7, color=color,
                ha="center", va=va, style="italic", zorder=5)


def fig_architecture():
    fig, ax = plt.subplots(figsize=(7.16, 4.7))
    ax.set_axis_off(); ax.set_xlim(0, 100); ax.set_ylim(-8, 63)
    ax.add_patch(FancyBboxPatch((0.3, 3.2), 39.4, 54.8, boxstyle="round,pad=0,rounding_size=1.2", fc=GRAY_BG, ec="none", zorder=0))
    ax.add_patch(FancyBboxPatch((40.3, 3.2), 39.4, 54.8, boxstyle="round,pad=0,rounding_size=1.2", fc=AMBER_BG, ec=AMBER,
                                lw=0.8, ls="--", zorder=0, alpha=0.6))
    ax.add_patch(FancyBboxPatch((80.3, 3.2), 19.4, 54.8, boxstyle="round,pad=0,rounding_size=1.2", fc=BLUE_BG, ec="none", zorder=0))
    ax.text(20, 56.1, "OFF-CHAIN", ha="center", fontsize=5.3, color=INK2, weight="bold")
    ax.text(60, 56.1, "ON-CHAIN  (blockchain: interface reserved)", ha="center", fontsize=5.3, color=AMBER, weight="bold")
    ax.text(90, 56.1, "DECISION", ha="center", fontsize=5.3, color=INK2, weight="bold")
    for x, t in [(1, "Multimodal Data"), (21, "Multimodal Analysis"), (41, "Smart Contracts"),
                 (61, "Records & Metrics"), (81, "Sustainable Development")]:
        ax.text(x + 9.5, 60.2, t, ha="center", fontsize=5.9, weight="bold", color=INK)
    # column 1: data
    _box(ax, 1.5, 31.5, 17, 22.5, "Multimodal inputs", ["Clinicopathologic", "stage, histology, smoking",
         "H&E whole-slide image", "TITAN slide embedding", "RNA-seq", "bulk transcriptome",
         "source ID + collection time"])
    _box(ax, 1.5, 5, 17, 23.5, "Evidence repository", ["off-chain storage (medlake)", "raw data + full reports",
         "provenance + license", "evidence URI", "hash = SHA-256(report)", "inspectable source evidence"])
    # column 2: analysis
    _box(ax, 21.5, 46.5, 17, 7.5, "Preprocessing", ["clean, align, fold-local PCA"])
    _box(ax, 21.5, 35.5, 17, 8.5, "Multimodal model", ["Cox ladder fC, fCW, fCWR", "fusion + 3-year risk"])
    _box(ax, 21.5, 24.5, 17, 8.5, "Acquisition policy", ["VoI / random / static", "budgets bW, bR"])
    _box(ax, 21.5, 5, 17, 17, "Structured conclusion", ["finding / decision", "evidence references",
         "confidence (bootstrap CI)", "model version + time"])
    # column 3: smart contracts (bottom-up)
    _box(ax, 41.5, 5, 17, 9.5, "Submission payload", ["conclusion + evidence", "hash + URI"], "chain")
    _box(ax, 41.5, 17, 17, 5, "Authorized signer", [], "chain")
    _box(ax, 41.5, 24.5, 17, 12, "Smart contract", ["check submitter + schema", "store conclusion + hash", "emit event"], "chain")
    _box(ax, 41.5, 39, 17, 15, "Blockchain", ["confirmed transaction", "compact record linked", "to off-chain evidence"], "chain")
    # column 4: records & metrics
    _box(ax, 61.5, 31, 17, 23, "On-chain records", ["conclusion / evidence hash", "model version",
         "evidence URI / record ID", "tx hash / block / status", "submitter / contract"], "chain")
    _box(ax, 61.5, 5, 17, 23.5, "Performance monitoring", ["gas fee: cost per tx", "TPS: successful tx/s",
         "latency: confirmation delay", "gas used / success rate", "receipts + timing logs", "fixed measurement window"], "chain")
    # column 5: decision support
    _box(ax, 81.5, 5, 17, 49, "", [], "plain")
    ax.text(90, 52.6, "Sustainability", ha="center", va="top", fontsize=5.9, weight="bold", color=INK)
    ax.text(90, 50.2, "decision support", ha="center", va="top", fontsize=5.9, weight="bold", color=INK)
    _box(ax, 82.5, 37, 15, 9.5, "Traceable decisions", ["accountable record", "of each conclusion"], "chain", tsize=4.9, lsize=4.6, lstep=2.1)
    _box(ax, 82.5, 24.5, 15, 9.5, "Cost-aware allocation", ["Pareto frontier", "US$ per patient"], "eval", tsize=4.9, lsize=4.6, lstep=2.1)
    _box(ax, 82.5, 12, 15, 9.5, "Environmental impact", ["kg CO2e per modality", "(RNA wet lab missing)"], "part", tsize=4.9, lsize=4.6, lstep=2.1)
    ax.text(90, 9.6, "vs. baseline: stage-inclusive", ha="center", va="top", fontsize=4.7, color=INK2, style="italic")
    ax.text(90, 7.6, "clinical model at US$0", ha="center", va="top", fontsize=4.7, color=INK2, style="italic")
    # flows
    _arrow(ax, (18.5, 50), (21.5, 50))
    _arrow(ax, (10, 31.5), (10, 28.5), label="archive", loff=(2.8, -0.9), va="center")
    for y0, y1 in [(46.5, 44), (35.5, 33), (24.5, 22)]:
        _arrow(ax, (30, y0), (30, y1))
    _arrow(ax, (18.5, 9.5), (21.5, 9.5), ls=":", label="evidence", loff=(0, -2.6))
    _arrow(ax, (38.5, 9.5), (41.5, 9.5), color=AMBER, ls="--", label="submit", loff=(0, 0.6))
    for y0, y1 in [(14.5, 17), (22, 24.5), (36.5, 39)]:
        _arrow(ax, (50, y0), (50, y1), color=AMBER)
    _arrow(ax, (58.5, 44), (61.5, 44), color=AMBER, label="store", loff=(0, 0.6))
    _arrow(ax, (58.5, 26), (61.5, 15), color=AMBER, label="receipts", loff=(-1.2, -3.6))
    _arrow(ax, (78.5, 42), (82.5, 42), color=AMBER, label="read", loff=(0, 0.6))
    _arrow(ax, (78.5, 20), (82.5, 27), color=AMBER, ls="--")
    # feedback loop below the zones
    ax.plot([90, 90, 6, 6], [5, 0.2, 0.2, 5], color=INK2, lw=0.9, zorder=1)
    ax.add_patch(FancyArrowPatch((6, 1.5), (6, 5), arrowstyle="-|>", mutation_scale=7, color=INK2, lw=0.9, zorder=4))
    ax.text(48, -0.9, "outcome feedback for the next assessment", fontsize=5.0, color=INK2, ha="center", va="top", style="italic")
    lx = 4
    for kind, lab in [("eval", "evaluated in this study"),
                      ("chain", "blockchain component: interface reserved, not evaluated"),
                      ("part", "partially quantified")]:
        ec, fc, ls = KIND[kind]
        ax.add_patch(FancyBboxPatch((lx, -7.2), 3.0, 2.2, boxstyle="round,pad=0,rounding_size=0.4", fc=fc, ec=ec, lw=0.9, ls=ls))
        ax.text(lx + 3.8, -6.1, lab, fontsize=5.2, color=INK2, va="center")
        lx += 6 + len(lab) * 0.82
    save(fig, "fig0_architecture")


# ---------- Fig 1: framework ----------
def fig_framework():
    fig, ax = plt.subplots(figsize=(7.0, 2.1))
    ax.set_axis_off(); ax.set_xlim(0, 10); ax.set_ylim(0, 3)
    boxes = [(0.2, "Level 0\nClinicopathologic\n(incl. pathologic stage)", "routine, $0"),
             (3.6, "Level 1\n+ H&E WSI\n(slide embedding)", "US$12-78 / patient"),
             (7.0, "Level 2\n+ RNA-seq\n(transcriptome)", "US$300-2,919 / patient")]
    for x, t, c in boxes:
        ax.add_patch(FancyBboxPatch((x, 1.15), 2.6, 1.45, boxstyle="round,pad=0.04,rounding_size=0.12",
                                    fc="#f4f3f0", ec=INK2, lw=0.8))
        ax.text(x + 1.3, 2.05, t, ha="center", va="center", fontsize=7.5, color=INK)
        ax.text(x + 1.3, 1.32, c, ha="center", va="center", fontsize=6.8, color=INK2, style="italic")
    for x0, lab in [(2.85, "acquire WSI for top-$b_W$\nby predicted $\\hat d_W$"),
                    (6.25, "acquire RNA for top-$b_R$\nby predicted $\\hat d_R$")]:
        ax.add_patch(FancyArrowPatch((x0, 1.9), (x0 + 0.7, 1.9), arrowstyle="-|>", mutation_scale=10, color=BLUE, lw=1.2))
        ax.text(x0 + 0.35, 0.72, lab, ha="center", va="center", fontsize=6.5, color=INK2)
    ax.text(5.0, 0.12, "Each patient is scored by the model of the highest level acquired: 3-year risk $1-\\hat S(\\tau\\,|\\,x)$, "
            "$\\hat d$ = predicted change in risk (VoI proxy)", ha="center", fontsize=6.8, color=INK)
    save(fig, "fig1_framework")


# ---------- Fig 2: static policies ----------
def fig_static():
    fig, ax = plt.subplots(figsize=(3.5, 2.3))
    levels = [((0.0, 0.0), "Clinicopathologic"), ((1.0, 0.0), "+ WSI"), ((1.0, 1.0), "+ WSI + RNA")]
    for k, (v, (lab, col)) in enumerate(VERS.items()):
        g = grid[v]
        for i, (key, _) in enumerate(levels):
            r = g[(g.bW == key[0]) & (g.bR == key[1])].iloc[0]
            x = i + (k - 0.5) * 0.22
            ax.errorbar(x, r.C_voi, yerr=[[r.C_voi - r.C_lo], [r.C_hi - r.C_voi]], fmt="o", ms=5, color=col,
                        mec="white", mew=0.8, elinewidth=1.2, capsize=0, label=lab if i == 0 else None)
            ax.text(x + 0.07, r.C_voi, f"{r.C_voi:.3f}", fontsize=6.3, color=INK2, va="center", bbox=dict(fc="white", ec="none", pad=0.3))
    ax.set_xticks(range(3), [l for _, l in levels]); ax.set_xlim(-0.5, 2.6)
    ax.set_ylabel("3-year Uno C-index"); ax.grid(axis="x", visible=False)
    ax.legend(loc="lower right", fontsize=7)
    save(fig, "fig2_static")


# ---------- Fig 3: Q1 non-inferiority ----------
def smooth(x, y, n=200):
    """Shape-preserving (PCHIP) curve through the evaluated points: no overshoot, passes every point exactly."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    xs = np.linspace(x.min(), x.max(), n)
    return xs, PchipInterpolator(x, y)(xs)


def fig_q1():
    fig, axes = plt.subplots(1, 2, figsize=(7.0, 2.3), sharey=True)
    for ax, (v, (lab, col)) in zip(axes, VERS.items()):
        q = pd.DataFrame(res[v]["q1"])
        lo, hi = np.array([c[0] for c in q.ci]), np.array([c[1] for c in q.ci])
        xs, lo_s = smooth(q.bR * 100, lo)
        _, hi_s = smooth(q.bR * 100, hi)
        ax.fill_between(xs, lo_s, hi_s, color=col, alpha=0.15, lw=0)
        ax.plot(*smooth(q.bR * 100, q.delta_vs_full), "-", color=col)
        ax.plot(q.bR * 100, q.delta_vs_full, "o", color=col, ms=4, mec="white", mew=0.6)
        ax.axhline(0, color=INK2, lw=0.8); ax.axhline(-0.01, color=INK2, lw=0.8, ls="--")
        ax.text(2, -0.0115, "non-inferiority margin $-\\delta$", fontsize=6.5, color=INK2, va="top")
        b = res[v]["b_star"]
        ax.axvline(b * 100, color=INK2, lw=0.6, ls=":")
        ax.text(b * 100 - 1, 0.017, f"$b_R^*$ = {b:.1f}", fontsize=6.8, color=INK, ha="right")
        ax.set_title(lab, fontsize=8, color=INK); ax.set_xlabel("RNA-seq budget $b_R$ (% of patients; WSI for all)")
    axes[0].set_ylabel("$\\Delta$C vs. RNA-seq for all (95% CI)")
    save(fig, "fig3_noninferiority")


# ---------- Fig 4: Pareto in USD ----------
def pareto(g, cw, cr):
    g = g.assign(cost=g.bW * cw + g.bR * cr).sort_values(["cost", "C_voi"], ascending=[True, False])
    best, keep = -np.inf, []
    for i, r in g.iterrows():
        if r.C_voi > best + 1e-12:
            best = r.C_voi; keep.append(i)
    return g, g.loc[keep]


def fig_pareto():
    fig, axes = plt.subplots(2, 2, figsize=(7.0, 4.4), sharey="row")
    for row, (v, (lab, col)) in enumerate(VERS.items()):
        for c, (sname, s) in enumerate(SCEN.items()):
            ax = axes[row, c]
            g, f = pareto(grid[v], s["wsi"], s["rna"])
            ax.scatter(g.cost, g.C_voi, s=9, color=GRAY, alpha=0.45, lw=0, label="all budget pairs")
            ax.step(f.cost, f.C_voi, where="post", color=col, lw=1.5)
            ax.scatter(f.cost, f.C_voi, s=22, color=col, edgecolor="white", lw=0.7, zorder=3, label="Pareto frontier")
            for key, txt in [((0.0, 0.0), "clinicopath."), ((1.0, 0.0), "WSI all"), ((1.0, 1.0), "WSI+RNA all")]:
                r = g[(g.bW == key[0]) & (g.bR == key[1])].iloc[0]
                ax.annotate(txt, (r.cost, r.C_voi), xytext=(4, -9 if key == (1.0, 0.0) else 4),
                            textcoords="offset points", fontsize=6.3, color=INK2)
            ax.set_xscale("symlog", linthresh=10); ax.set_xlim(-1, (s["wsi"] + s["rna"]) * 4)
            if row == 0:
                ax.set_title(sname + rf": WSI US\${s['wsi']:.0f}, RNA US\${s['rna']:,}", fontsize=7.5, color=INK)
            if c == 0:
                ax.set_ylabel(f"{lab}\n3-year Uno C-index")
    fig.supxlabel(r"Expected acquisition cost per patient (US\$, symmetric log scale)", fontsize=8, y=0.01)
    axes[0, 0].legend(loc="center left", fontsize=6.5)
    save(fig, "fig4_pareto_usd")


# ---------- Fig 5: VoI vs random vs oracle ----------
def fig_voi():
    fig, axes = plt.subplots(1, 2, figsize=(7.0, 2.3))
    for ax, (v, (lab, col)) in zip(axes, VERS.items()):
        g = grid[v][grid[v].bW == 1.0].sort_values("bR")
        x = g.bR * 100
        for y, c, ls, lw, ms, lab_ in [(g.C_oracle, AQUA, "--", 1.2, 2.6, "risk-change oracle (diagnostic)"),
                                       (g.C_random, GRAY, "-", 1.5, 2.6, "random (mean of 100)"),
                                       (g.C_voi, col, "-", 1.5, 3.5, "VoI policy")]:
            ax.plot(*smooth(x, y), ls, color=c, lw=lw)
            ax.plot(x, y, "o", color=c, ms=ms, mec="white", mew=0.5)
            ax.plot([], [], ls, marker="o", color=INK2 if lab_ == "VoI policy" else c, lw=lw, ms=ms, mec="white", mew=0.5,
                    label="VoI policy (blue / orange)" if lab_ == "VoI policy" else lab_)
        ax.set_title(lab, fontsize=8, color=INK); ax.set_xlabel("RNA-seq budget $b_R$ (% of patients; WSI for all)")
    axes[0].set_ylabel("3-year Uno C-index")
    h, l = axes[0].get_legend_handles_labels()
    fig.legend(h, l, fontsize=6.5, loc="upper center", ncol=3, bbox_to_anchor=(0.5, -0.02))
    save(fig, "fig5_voi_vs_random")


# ---------- Fig 6: stage attenuation, internal + 7 external cohorts ----------
def fig_forest():
    h1 = json.loads((EXP / "h1_stage_recheck" / "results.json").read_text("utf-8"))["results"]
    h2 = {k: json.loads((EXP / "rna_transport" / "results" / f).read_text("utf-8"))
          for k, f in [("with", "primary.json"), ("without", "s1_no_stage.json")]}
    rows = [("Internal (TCGA+CPTAC), WSI+RNA", h1["A_no_stage"]["uno"], h1["B_stage_group"]["uno"], None)]
    for g in h2["with"]["cohorts"]:
        w, wo = h2["with"]["cohorts"][g], h2["without"]["cohorts"][g]
        rows.append((f"{g} (n={w['n']}), RNA", {"delta": wo["delta"]["delta"], "ci": wo["delta"]["ci"]},
                     {"delta": w["delta"]["delta"], "ci": w["delta"]["ci"]}, None))
    rows.append(("External pooled (random effects)", {"delta": h2["without"]["pooled"]["pooled_delta"], "ci": h2["without"]["pooled"]["ci"]},
                 {"delta": h2["with"]["pooled"]["pooled_delta"], "ci": h2["with"]["pooled"]["ci"]}, "bold"))
    fig, ax = plt.subplots(figsize=(3.5, 3.4))
    for i, (lab, wo, w, wt) in enumerate(rows):
        y = len(rows) - 1 - i
        for d, off, col, mk in [(wo, 0.17, ORANGE, "s"), (w, -0.17, BLUE, "o")]:
            ax.plot(d["ci"], [y + off] * 2, color=col, lw=1.2)
            ax.plot(d["delta"], y + off, mk, color=col, ms=4.5 if wt else 3.8, mec="white", mew=0.6)
    ax.axvline(0, color=INK2, lw=0.8)
    ax.set_yticks(range(len(rows)), [r[0] for r in rows][::-1], fontsize=6.5)
    for t, r in zip(ax.get_yticklabels(), rows[::-1]):
        if r[3]:
            t.set_fontweight("bold")
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("$\\Delta$C (multimodal $-$ clinical), 3-year Uno")
    ax.plot([], [], "s-", color=ORANGE, label="clinical baseline without stage")
    ax.plot([], [], "o-", color=BLUE, label="clinical baseline with stage")
    ax.legend(fontsize=6.3, loc="upper center", bbox_to_anchor=(0.4, -0.16), ncol=1)
    save(fig, "fig6_stage_attenuation")


if __name__ == "__main__":
    fig_architecture(); fig_framework(); fig_static(); fig_q1(); fig_pareto(); fig_voi(); fig_forest()
    print(sorted(p.name for p in FIG.iterdir()))
