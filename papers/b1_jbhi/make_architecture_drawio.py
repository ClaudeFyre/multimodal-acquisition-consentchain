"""Write figures/fig0_architecture.drawio: an editable draw.io version of Fig. 1 (fig_architecture in make_figures.py).

Uses the same layout (axis units x 0..100, y -8..63), colors and text as the matplotlib figure.
Every box, label and arrow is a separate draw.io object. Re-run after changing the layout below.
"""
from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

OUT = Path(__file__).resolve().parent / "figures" / "fig0_architecture.drawio"
S = 16                      # px per axis unit
Y_TOP = 63                  # axis y at the top edge of the page
W, H = 100 * S, (63 + 8) * S

BLUE, AMBER, AMBER_BG, BLUE_BG, GRAY, GRAY_BG = "#2a78d6", "#b77900", "#fdf3dc", "#e8f0fb", "#8a8984", "#f1f1ee"
INK, INK2 = "#0b0b0b", "#52514e"
FONT = "fontFamily=Times New Roman;"
KIND = {"eval": (BLUE, "#ffffff", 0), "chain": (AMBER, AMBER_BG, 1), "part": (GRAY, GRAY_BG, 0), "plain": (INK2, "#ffffff", 0)}

cells: list[str] = []
_n = 0


def nid(prefix: str) -> str:
    global _n
    _n += 1
    return f"{prefix}{_n}"


def geo(x, y, w, h):
    """Axis box (x, y = bottom-left) -> draw.io geometry (top-left origin)."""
    return x * S, (Y_TOP - (y + h)) * S, w * S, h * S


def vertex(value, style, x, y, w, h, prefix="v"):
    gx, gy, gw, gh = geo(x, y, w, h)
    i = nid(prefix)
    cells.append(f'<mxCell id="{i}" value="{escape(value, {chr(34): "&quot;"})}" style="{style}" vertex="1" parent="1">'
                 f'<mxGeometry x="{gx:.1f}" y="{gy:.1f}" width="{gw:.1f}" height="{gh:.1f}" as="geometry"/></mxCell>')
    return i


def text(value, x, y, w=20, h=2.4, size=15, color=INK2, bold=False, italic=False, align="center"):
    style = (f"text;html=1;align={align};verticalAlign=middle;whiteSpace=wrap;{FONT}fontSize={size};"
             f"fontColor={color};fontStyle={(1 if bold else 0) + (2 if italic else 0)};")
    return vertex(value, style, x - w / 2 if align == "center" else x, y - h / 2, w, h, "t")


def box(x, y, w, h, title, lines=(), kind="eval", tsize=18, lsize=15):
    ec, fc, dashed = KIND[kind]
    tcolor = AMBER if kind == "chain" else INK
    body = "<br>".join(escape(l) for l in lines)
    label = (f'<b><font style="font-size:{tsize}px" color="{tcolor}">{escape(title).replace("&lt;br&gt;", "<br>")}</font></b>' if title else "") + \
            (f'<br><font style="font-size:{lsize}px" color="{INK2}">{body}</font>' if lines else "")
    style = (f"rounded=1;arcSize=6;whiteSpace=wrap;html=1;{FONT}fillColor={fc};strokeColor={ec};strokeWidth=1.5;"
             f"dashed={dashed};verticalAlign=top;align=center;spacingTop=6;spacingLeft=4;spacingRight=4;")
    return vertex(label, style, x, y, w, h, "b")


def band(x, y, w, h, fill, stroke="none", dashed=0, opacity=100):
    style = (f"rounded=1;arcSize=3;html=1;fillColor={fill};strokeColor={stroke};dashed={dashed};"
             f"opacity={opacity};strokeWidth=1.2;")
    return vertex("", style, x, y, w, h, "z")


def arrow(p, q, color=INK2, dashed=0, dotted=False, label=None, waypoints=()):
    i = nid("e")
    pattern = "dashPattern=1 3;" if dotted else ""
    style = (f"endArrow=block;endFill=1;endSize=6;html=1;rounded=0;strokeColor={color};strokeWidth=1.5;"
             f"dashed={1 if (dashed or dotted) else 0};{pattern}{FONT}fontSize=14;fontStyle=2;fontColor={color};"
             f"labelBackgroundColor=none;")
    sx, sy = p[0] * S, (Y_TOP - p[1]) * S
    tx, ty = q[0] * S, (Y_TOP - q[1]) * S
    pts = "".join(f'<mxPoint x="{x * S:.1f}" y="{(Y_TOP - y) * S:.1f}"/>' for x, y in waypoints)
    pts = f'<Array as="points">{pts}</Array>' if waypoints else ""
    cells.append(f'<mxCell id="{i}" value="{escape(label or "")}" style="{style}" edge="1" parent="1">'
                 f'<mxGeometry relative="1" as="geometry"><mxPoint x="{sx:.1f}" y="{sy:.1f}" as="sourcePoint"/>'
                 f'<mxPoint x="{tx:.1f}" y="{ty:.1f}" as="targetPoint"/>{pts}</mxGeometry></mxCell>')


def build():
    # zone bands
    band(0.3, 3.2, 39.4, 54.8, GRAY_BG)
    band(40.3, 3.2, 39.4, 54.8, AMBER_BG, AMBER, 1, 60)
    band(80.3, 3.2, 19.4, 54.8, BLUE_BG)
    text("OFF-CHAIN", 20, 56.4, 30, size=16, bold=True)
    text("ON-CHAIN  (blockchain: interface reserved)", 60, 56.4, 38, size=16, color=AMBER, bold=True)
    text("DECISION", 90, 56.4, 18, size=16, bold=True)
    for x, t in [(1, "Multimodal Data"), (21, "Multimodal Analysis"), (41, "Smart Contracts"),
                 (61, "Records &amp; Metrics"), (81, "Sustainable Development")]:
        vertex(f"<b>{t}</b>", f"text;html=1;align=center;verticalAlign=middle;{FONT}fontSize=18;fontColor={INK};",
               x + 9.5 - 10, 59.2, 20, 2.4, "h")
    # column 1: data
    box(1.5, 31.5, 17, 22.5, "Multimodal inputs", ["Clinicopathologic", "stage, histology, smoking", "H&E whole-slide image",
        "TITAN slide embedding", "RNA-seq", "bulk transcriptome", "source ID + collection time"])
    box(1.5, 5, 17, 23.5, "Evidence repository", ["off-chain storage (medlake)", "raw data + full reports",
        "provenance + license", "evidence URI", "hash = SHA-256(report)", "inspectable source evidence"])
    # column 2: analysis
    box(21.5, 46.5, 17, 7.5, "Preprocessing", ["clean, align, fold-local PCA"])
    box(21.5, 35.5, 17, 8.5, "Multimodal model", ["Cox ladder fC, fCW, fCWR", "fusion + 3-year risk"])
    box(21.5, 24.5, 17, 8.5, "Acquisition policy", ["VoI / random / static", "budgets bW, bR"])
    box(21.5, 5, 17, 17, "Structured conclusion", ["finding / decision", "evidence references",
        "confidence (bootstrap CI)", "model version + time"])
    # column 3: smart contracts (bottom-up)
    box(41.5, 5, 17, 9.5, "Submission payload", ["conclusion + evidence", "hash + URI"], "chain")
    box(41.5, 17, 17, 5, "Authorized signer", [], "chain")
    box(41.5, 24.5, 17, 12, "Smart contract", ["check submitter + schema", "store conclusion + hash", "emit event"], "chain")
    box(41.5, 39, 17, 15, "Blockchain", ["confirmed transaction", "compact record linked", "to off-chain evidence"], "chain")
    # column 4: records & metrics
    box(61.5, 31, 17, 23, "On-chain records", ["conclusion / evidence hash", "model version", "evidence URI / record ID",
        "tx hash / block / status", "submitter / contract"], "chain")
    box(61.5, 5, 17, 23.5, "Performance monitoring", ["gas fee: cost per tx", "TPS: successful tx/s",
        "latency: confirmation delay", "gas used / success rate", "receipts + timing logs", "fixed measurement window"], "chain")
    # column 5: decision support
    box(81.5, 5, 17, 49, "Sustainability<br>decision support", [], "plain")
    box(82.5, 37, 15, 9.5, "Traceable decisions", ["accountable record", "of each conclusion"], "chain", tsize=15, lsize=14)
    box(82.5, 24.5, 15, 9.5, "Cost-aware allocation", ["Pareto frontier", "US$ per patient"], "eval", tsize=15, lsize=14)
    box(82.5, 12, 15, 9.5, "Environmental impact", ["kg CO2e per modality", "(RNA wet lab missing)"], "part", tsize=15, lsize=14)
    text("vs. baseline: stage-inclusive<br>clinical model at US$0", 90, 7.8, 16, 4, size=14, italic=True)
    # flows
    arrow((18.5, 50), (21.5, 50))
    arrow((10, 31.5), (10, 28.5), label="archive")
    for y0, y1 in [(46.5, 44), (35.5, 33), (24.5, 22)]:
        arrow((30, y0), (30, y1))
    arrow((18.5, 9.5), (21.5, 9.5), dotted=True, label="evidence")
    arrow((38.5, 9.5), (41.5, 9.5), color=AMBER, dashed=1, label="submit")
    for y0, y1 in [(14.5, 17), (22, 24.5), (36.5, 39)]:
        arrow((50, y0), (50, y1), color=AMBER)
    arrow((58.5, 44), (61.5, 44), color=AMBER, label="store")
    arrow((58.5, 26), (61.5, 15), color=AMBER, label="receipts")
    arrow((78.5, 42), (82.5, 42), color=AMBER, label="read")
    arrow((78.5, 20), (82.5, 27), color=AMBER, dashed=1)
    arrow((90, 5), (6, 5), waypoints=[(90, 0.2), (6, 0.2)])
    text("outcome feedback for the next assessment", 48, -1.6, 40, size=15, italic=True)
    # legend
    lx = 4
    for kind, lab in [("eval", "evaluated in this study"),
                      ("chain", "blockchain component: interface reserved, not evaluated"),
                      ("part", "partially quantified")]:
        ec, fc, dashed = KIND[kind]
        vertex("", f"rounded=1;arcSize=20;html=1;fillColor={fc};strokeColor={ec};strokeWidth=1.5;dashed={dashed};",
               lx, -7.2, 3.0, 2.2, "l")
        text(lab, lx + 3.8, -6.1, len(lab) * 0.82 + 2, size=15, align="left")
        lx += 6 + len(lab) * 0.82


def main():
    build()
    xml = (f'<?xml version="1.0" encoding="UTF-8"?>\n<mxfile host="app.diagrams.net" type="device">\n'
           f'  <diagram id="b1-architecture" name="Architecture">\n'
           f'    <mxGraphModel dx="{W}" dy="{H}" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" '
           f'fold="1" page="1" pageScale="1" pageWidth="{W}" pageHeight="{H}" math="0" shadow="0" background="#ffffff">\n'
           f'      <root>\n        <mxCell id="0"/>\n        <mxCell id="1" parent="0"/>\n        '
           + "\n        ".join(cells) + "\n      </root>\n    </mxGraphModel>\n  </diagram>\n</mxfile>\n")
    OUT.write_text(xml, "utf-8")
    print(f"{len(cells)} cells -> {OUT}")


if __name__ == "__main__":
    main()
