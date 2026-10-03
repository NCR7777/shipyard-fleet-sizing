import matplotlib as mpl
import matplotlib.pyplot as plt
BLUE='#2a78d6'; ORANGE='#eb6834'; AQUA='#1baf7a'; GREY='#8a8986'; LGREY='#c9c8c4'; MGREY='#6f6e6a'; LORANGE='#f4b08f'
LBLUE='#9ec5f4'; INK='#0b0b0b'; INK2='#52514e'; GRID='#e6e5e1'
W = 6.5          # text width of the manuscript (468 pt); figures are drawn at final size, no scaling in LaTeX
BOX = dict(fc='white', ec='none', pad=0.6)   # white backing for annotations that sit near lines
def setup():
    mpl.rcParams.update({
        'font.family':'serif','font.serif':['Times New Roman'],'mathtext.fontset':'stix',
        'font.size':8,'axes.titlesize':8,'axes.labelsize':8,'xtick.labelsize':7,'ytick.labelsize':7,'legend.fontsize':7,
        'pdf.fonttype':42,'svg.fonttype':'none',
        'axes.edgecolor':INK2,'axes.linewidth':0.6,'xtick.color':INK2,'ytick.color':INK2,'xtick.labelcolor':INK,'ytick.labelcolor':INK,
        'axes.labelcolor':INK,'text.color':INK,'axes.spines.top':False,'axes.spines.right':False,
        'xtick.major.width':0.6,'ytick.major.width':0.6,'xtick.major.size':2.5,'ytick.major.size':2.5,
        'axes.grid':False,'grid.color':GRID,'grid.linewidth':0.5,'axes.axisbelow':True,
        'savefig.dpi':300,'savefig.bbox':None,'legend.frameon':False,
        'axes.titleweight':'bold','axes.titlelocation':'left','figure.constrained_layout.use':False,
        'figure.constrained_layout.h_pad':0.03,'figure.constrained_layout.w_pad':0.03})
    try:                         # sub- and superscripts of 8 pt labels print at 7 pt (default factor 0.7 gives 5.6 pt)
        import matplotlib._mathtext as mt; mt.SHRINK_FACTOR = 0.875
    except ImportError:
        pass
import os
from pathlib import Path
OUT = Path(os.environ.get('OE_FIG_OUT', Path(__file__).resolve().parents[1] / 'figures'))   # paper/manuscript/figures
def save(fig,name):
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / f'{name}.png'); fig.savefig(OUT / f'{name}.pdf')
