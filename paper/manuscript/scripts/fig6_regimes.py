from common import *
from style import *
import matplotlib.patches as mp
setup()
d=pd.read_csv(RES/'heavy_share_decisions.csv'); f=pd.read_csv(RES/'heavy_share_fleets.csv')
co={(c,fa):x for c,fa,x in zip(f.cell,f.family,f.coop_share)}
d['cell']=['heavy%.2f_%s_baseline'%(p,h) for p,h in zip(d.p,d.handling)]
d['coop']=[co[(c,w)] for c,w in zip(d.cell,d.winner.astype(str))]
m={'coupling tier':'300 t fleet','mix':'270 t units + 1 or 2 heavy units','single-carry tier':'550 t fleet'}
d['c']=d.winner_class.map(m)
order=list(m.values())
col=dict(zip(order,[LBLUE,AQUA,BLUE]))
ps=sorted(d.p.unique())
fig,axs=plt.subplots(1,2,figsize=(W,2.7),sharey=True,layout='constrained')
for ax,h,tt in zip(axs,['short','massdep'],['(a) Short handling','(b) Mass-dependent handling']):
    g=d[d.handling==h]; x=np.arange(len(ps))
    for lab,sub,y0,hh in [('all',g,0,100),('shift',g[g.labour=='shift_h'],105,7)]:   # bar of 180 scenarios, strip of 45
        ct=pd.crosstab(sub.p,sub.c).reindex(index=ps,columns=order,fill_value=0)
        n=ct.sum(1).values; assert set(n)=={180 if lab=='all' else 45}
        bot=np.zeros(len(ps))
        for k in order:
            v=ct[k].values/n*hh
            ax.bar(x,v,bottom=y0+bot,width=0.72,color=col[k],edgecolor='white',linewidth=0.5,label=k if lab=='all' else None)
            bot+=v
        print(HANDLING[h],lab,'scenarios won (%):'); print((100*ct.div(n,axis=0)).round(1).to_string())
    ax.set_xticks(x,['%g'%(100*p) for p in ps]); ax.set_xlabel('Share of heavy blocks (350–540 t), $\\varphi$ (%)')
    ax.set_title(tt,pad=4); ax.set_ylim(0,113); ax.set_yticks([0,25,50,75,100]); ax.spines['left'].set_bounds(0,100)
    print(HANDLING[h],'mean / max coupled share of the winners by phi:',d[d.handling==h].groupby('p').coop.agg(['mean','max']).round(3).values.tolist())
axs[0].set_ylabel('Cost scenarios won (%)')
axs[0].text(-0.62,108.5,'shift labour',ha='right',va='center',fontsize=7)
h,l=axs[0].get_legend_handles_labels()
fig.legend(h,l,loc='outside lower center',ncol=3)
save(fig,'fig6_regimes')
