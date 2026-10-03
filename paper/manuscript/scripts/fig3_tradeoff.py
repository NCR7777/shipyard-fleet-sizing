from common import *
from style import *
import matplotlib as mpl
from matplotlib.lines import Line2D
setup()
f=fleets(); f['ms'],f['h'],f['due']=zip(*f.cell.map(split))
tiers=[200,250,270,300,325,380,425,500,550]
fig,axs=plt.subplots(2,3,figsize=(W,4.1),sharex=True,layout='constrained')
sty={'short':dict(color=BLUE,ls='-',marker='o',lw=1.5,zorder=3),'massdep':dict(color=GREY,ls='--',marker='s',lw=1.1,zorder=2),
     'long':dict(color=MGREY,ls=':',marker='^',lw=1.1,zorder=2)}
for ax,ms in zip(axs.flat,PROFILES):
    g=f[(f.ms==ms)&(f.due=='baseline')&f.family.isin([str(t) for t in tiers])]
    for h in ['short','massdep','long']:
        x=g[g.h==h].copy(); x['q']=x.family.astype(int); x=x.sort_values('q')
        ax.plot(x.q,x.K_final,ms=3.2,mfc='white' if h!='short' else sty[h]['color'],mew=0.8,label=HANDLING[h],**sty[h])
    if COVER[ms]:
        ax.axvline(COVER[ms],color=INK2,lw=0.7,ls=(0,(3,2)))
    else:
        t=pd.read_csv(RES/'runs_compact'/'tasks_main.csv'); t=t[t.cell==g.cell.iloc[0]]
        share=(t.mass_t>550).mean()
        ax.text(0.97,0.04,'no tier carries every block:\n%.1f%% of blocks > 550 t'%(100*share),transform=ax.transAxes,
                ha='right',va='bottom',fontsize=7,color=INK2,bbox=BOX)
        print('heavy-tail profile: share of blocks above 550 t %.4f'%share)
    ax.set_title('%s (%s)'%(PROFILE[ms],RANGE[ms]))
    ax.set_ylim(0,None); ax.yaxis.set_major_locator(mpl.ticker.MaxNLocator(nbins=4,integer=True)); ax.grid(axis='x',visible=False)
    ax.set_xticks(tiers); ax.tick_params(axis='x',labelrotation=90)
for ax in axs[1]: ax.set_xlabel('Transporter capacity tier (t)')
for ax in axs[:,0]: ax.set_ylabel('Transporters needed, $K$*')
h,l=axs[0,0].get_legend_handles_labels()
h.append(Line2D([],[],color=INK2,lw=0.7,ls=(0,(3,2)))); l.append('smallest tier carrying every block')
fig.legend(h,l,loc='outside upper center',ncol=4,handlelength=2.6)
save(fig,'fig3_tradeoff')
