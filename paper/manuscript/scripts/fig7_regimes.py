from common import *
from style import *
setup()
d=pd.read_csv(RES/'heavy_share_decisions.csv'); f=pd.read_csv(RES/'heavy_share_fleets.csv')
co={(c,fa):x for c,fa,x in zip(f.cell,f.family,f.coop_share)}
d['cell']=['heavy%.2f_%s_baseline'%(p,h) for p,h in zip(d.p,d.handling)]
d['coop']=[co[(c,w)] for c,w in zip(d.cell,d.winner.astype(str))]
m={'coupling tier':'light tier (300 t)','mix':'light units + 1–2 heavy (MX1/MX2)','single-carry tier':'heavy tier (550 t)'}
d['c']=d.winner_class.map(m)
order=['light tier (300 t)','light units + 1–2 heavy (MX1/MX2)','heavy tier (550 t)']
col=dict(zip(order,['#9ec5f4',AQUA,BLUE]))
ps=sorted(d.p.unique())
fig,axs=plt.subplots(1,2,figsize=(7.48,2.8),sharey=True)
for ax,h,tt in zip(axs,['short','massdep'],['(a) Short handling (short)','(b) Mass-dependent handling (massdep)']):
    g=d[d.handling==h]; ct=pd.crosstab(g.p,g.c).reindex(index=ps,columns=order,fill_value=0)/180*100
    x=np.arange(len(ps)); bot=np.zeros(len(ps))
    for k in order:
        ax.bar(x,ct[k].values,bottom=bot,width=0.72,color=col[k],edgecolor='white',linewidth=0.6,label=k); bot+=ct[k].values
    ax.set_xticks(x,['%g'%(100*p) for p in ps]); ax.set_xlabel('Share of heavy blocks (350–540 t), p (%)')
    ax.set_title(tt); ax.grid(axis='x',visible=False); ax.set_ylim(0,100)
axs[0].set_ylabel('Share of 180 cost settings (%)')
h,l=axs[0].get_legend_handles_labels()
fig.legend(h,l,loc='lower center',ncol=3,bbox_to_anchor=(0.5,-0.04))
fig.tight_layout(rect=(0,0.07,1,1),w_pad=1.5)
save(fig,'fig7_regimes')
print(d.groupby(['handling','p']).coop.agg(['mean','max']).round(3))
