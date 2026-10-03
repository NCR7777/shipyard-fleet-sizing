from common import *
from style import *
setup()
x=pd.read_csv(RES/'robust_series.csv'); xd=pd.read_csv(RES/'robust_decisions.csv')
cells=['jiang_short_baseline','rohcha_short_baseline','liu_short_baseline','jiang_massdep_baseline','rohcha_massdep_baseline','liu_massdep_baseline']
fig,axs=plt.subplots(2,3,figsize=(W,3.9),sharex=True,sharey=True,layout='constrained')
for ax,c in zip(axs.flat,cells):
    g=x[x.cell==c]
    nomw=xd[(xd.cell==c)&(xd.labour=='shift_h')&(xd.model=='affine')].winner_nominal.mode().iat[0]
    for _,r in g.iterrows():
        ys=[r['pert_K+%d'%d] for d in range(4)]; xs=[d for d in range(4) if not pd.isna(ys[d])]; ys=[y*100 for y in ys if not pd.isna(y)]
        hi=r.family==nomw
        ax.plot(xs,ys,'-o' if hi else '-',color=BLUE if hi else LGREY,lw=1.6 if hi else 0.9,ms=3,zorder=3 if hi else 2)
        if hi: ax.text(0.97,0.04,'blue: nominal cost winner\n(%s)'%fleet_label(nomw),transform=ax.transAxes,fontsize=7,color=BLUE,
                       ha='right',va='bottom')
    ax.axhline(95,color=INK2,lw=0.7,ls=(0,(3,2)))
    ms,h,_=split(c); ax.set_title('%s, %s'%(PROFILE[ms],HANDLING[h].lower().replace('mass-dependent','mass-dep.')))
    ax.set_xticks(range(4),['$K$*','+1','+2','+3'])
axs[0,0].text(3,95.4,'95% target',ha='right',va='bottom',fontsize=7,color=INK2)
for ax in axs[:,0]: ax.set_ylabel('On-time share under\n±50% handling noise (%)')
fig.supxlabel('Transporters added to the nominal count $K$*',fontsize=8)
axs[0,0].set_ylim(78,100)
save(fig,'figS1_robust')
