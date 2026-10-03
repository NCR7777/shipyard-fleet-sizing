from common import *
from style import *
setup()
d=pd.read_csv(RES/'main_decisions.csv'); f=fleets()
co={(c,fa):x for c,fa,x in zip(f.cell,f.family,f.coop_share)}
d['coop']=[co[(c,w)] for c,w in zip(d.cell,d.winner)]
order=['homogeneous','mix','heavy coupling','light coupling']
lab={'homogeneous':'Homogeneous, couples ≤10%','mix':'Light units + 1–2 heavy units, couples ≤10%',
     'heavy coupling':'Heavy tier (≥425 t) or mix, couples >10%','light coupling':'Light tier (≤380 t), couples >10%'}
col={'homogeneous':BLUE,'mix':AQUA,'heavy coupling':LORANGE,'light coupling':ORANGE}
def cls(w,c):
    if c<=0.10+1e-12: return 'mix' if w.startswith('MX') else 'homogeneous'
    return 'heavy coupling' if w.startswith('MX') or int(w)>=425 else 'light coupling'
d['cls']=[cls(w,c) for w,c in zip(d.winner,d.coop)]
d['ms'],d['h'],d['due']=zip(*d.cell.map(split))
rows=[(h,due) for h in ['short','massdep','long'] for due in ['baseline','tight']]
short={'short':'Short','massdep':'Mass-dep.','long':'Long loading'}
fig,axs=plt.subplots(2,3,figsize=(W,3.6),sharex=True,sharey=True,layout='constrained')
for ax,ms in zip(axs.flat,PROFILES):
    g=d[d.ms==ms]; ct=pd.crosstab([g.h,g.due],g.cls).reindex(index=rows,columns=order,fill_value=0)
    assert (ct.sum(1)==180).all()
    left=np.zeros(len(rows)); y=np.arange(len(rows))
    for k in order:
        v=ct[k].values/180*100
        ax.barh(y,v,left=left,height=0.74,color=col[k],label=lab[k],edgecolor='white',linewidth=0.5); left+=v
    ax.set_yticks(y,['%s, %s'%(short[h],DUE[due]) for h,due in rows]); ax.set_ylim(len(rows)-0.5,-0.5)
    ax.set_xlim(0,100); ax.set_xticks([0,25,50,75,100]); ax.grid(axis='y',visible=False); ax.tick_params(axis='y',length=0)
    ax.set_title('%s (%s)'%(PROFILE[ms],RANGE[ms]))
fig.supxlabel('Share of the 180 cost scenarios (%)',fontsize=8); fig.get_layout_engine().set(wspace=0.05)
h,l=axs[0,0].get_legend_handles_labels()
fig.legend(h,l,loc='outside upper center',ncol=2,handlelength=1.2,columnspacing=1.5)
save(fig,'fig4_winners')
tot=d.cls.value_counts().reindex(order)
print('decisions %d; class shares (%%): %s; couples <=10%% in total %.1f%%'%(len(d),
      ', '.join('%s %.1f'%(k,100*v/len(d)) for k,v in tot.items()),100*(d.coop<=0.10+1e-12).mean()))
