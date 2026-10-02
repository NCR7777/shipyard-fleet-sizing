import matplotlib as mpl
import matplotlib.pyplot as plt
BLUE='#2a78d6'; ORANGE='#eb6834'; AQUA='#1baf7a'; GREY='#8a8986'; LGREY='#c9c8c4'; INK='#0b0b0b'; INK2='#52514e'; GRID='#e6e5e1'
CLS = {'heavy tier':BLUE, 'mixed fleet':AQUA, 'light tier':ORANGE}
def setup():
    mpl.rcParams.update({
        'font.family':'DejaVu Sans','font.size':8,'axes.titlesize':8.5,'axes.labelsize':8,
        'xtick.labelsize':7,'ytick.labelsize':7,'legend.fontsize':7,
        'axes.edgecolor':INK2,'axes.linewidth':0.6,'xtick.color':INK2,'ytick.color':INK2,
        'axes.labelcolor':INK,'text.color':INK,'axes.spines.top':False,'axes.spines.right':False,
        'xtick.major.width':0.6,'ytick.major.width':0.6,'xtick.major.size':2.5,'ytick.major.size':2.5,
        'axes.grid':True,'grid.color':GRID,'grid.linewidth':0.5,'axes.axisbelow':True,
        'savefig.dpi':300,'savefig.bbox':'tight','savefig.pad_inches':0.03,'legend.frameon':False,
        'axes.titleweight':'bold','axes.titlelocation':'left'})
import os
from pathlib import Path
OUT = Path(os.environ.get('OE_FIG_OUT', Path(__file__).resolve().parents[1] / 'figures'))   # paper/manuscript/figures
OUT.mkdir(parents=True, exist_ok=True)
def save(fig,name):
    fig.savefig(OUT / f'{name}.png'); fig.savefig(OUT / f'{name}.pdf')
