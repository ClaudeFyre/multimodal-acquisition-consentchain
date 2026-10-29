#!/usr/bin/env python3
"""Export the implemented model-evidence route as an editable vector schematic."""
from pathlib import Path
import sys
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch,FancyArrowPatch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(Path(__file__).resolve().parent/'figure_qa'))
from audit_panel_alignment import require_matplotlib_panel_alignment

mpl.rcParams.update({'font.family':'sans-serif','font.sans-serif':['Arial','Helvetica','DejaVu Sans'],
    'font.size':7.5,'pdf.fonttype':42,'svg.fonttype':'none','axes.linewidth':.7})

def main():
    target=ROOT.parents[2]/'papers/b1_jbhi/figures/fig0_architecture'
    fig=plt.figure(figsize=(183/25.4,54/25.4))
    ax=fig.add_axes([.015,.04,.97,.91]);ax.set_xlim(0,5.4);ax.set_ylim(0,1.9);ax.axis('off')
    blocks=[
        ('Model experiments','C / CW / CWR\nAcquisition policies\nFrozen B1 results','#edf3fa','#42668e'),
        ('Off-chain evidence','Protocol + result files\nSHA-256 manifest\nOriginal files retained','#edf3fa','#42668e'),
        ('Ledger adapter','ANALYSIS_RECORD\nConclusion + version\nEvidence URI + hash','#edf3fa','#42668e'),
        ('EVM smart contract','Immutable analysis\nAuthorized submitters\nVersioned display labels','#fff1db','#9a6c25'),
        ('Audit and metrics','Recompute file hashes\nRead contract events\nGas / receipt latency','#f0f2f4','#5e6772')]
    width=.94;gap=.14;left=.03;y=.65;height=.95
    for i,(title,body,fill,edge) in enumerate(blocks):
        x=left+i*(width+gap)
        ax.add_patch(FancyBboxPatch((x,y),width,height,boxstyle='round,pad=0.015,rounding_size=0.025',
            linewidth=.8,edgecolor=edge,facecolor=fill))
        ax.text(x+width/2,y+height-.20,title,ha='center',va='center',fontsize=8,fontweight='bold',color='#202833')
        ax.text(x+width/2,y+.38,body,ha='center',va='center',fontsize=7.25,linespacing=1.48,color='#354052')
        if i<4:
            ax.add_patch(FancyArrowPatch((x+width+.025,y+height/2),(x+width+gap-.025,y+height/2),
                arrowstyle='-|>',mutation_scale=7,linewidth=.85,color='#6b7686'))
    ax.text(.03,1.78,'MODEL OUTPUTS AND EVIDENCE',fontsize=7.3,fontweight='bold',color='#42668e')
    ax.text(3.27,1.78,'REGISTRATION AND VERIFICATION',fontsize=7.3,fontweight='bold',color='#9a6c25')
    ax.text(2.70,.32,'Evidence, model specification and analysis digests remain fixed.',ha='center',fontsize=7.5,color='#29313c')
    ax.text(2.70,.10,'Data name and description can be revised; each revision emits a versioned event.',ha='center',fontsize=7.5,color='#29313c')
    require_matplotlib_panel_alignment(fig,json_out=str(target)+'.alignment.json',
        overlay_svg=str(target)+'.alignment.svg',tolerance_pt=1.5,gutter_tolerance_pt=1.5,strict=True)
    fig.savefig(str(target)+'.pdf')
    fig.savefig(str(target)+'.svg')
    fig.savefig(str(target)+'.png',dpi=600)
    plt.close(fig)
    print(target)

if __name__=='__main__':main()
