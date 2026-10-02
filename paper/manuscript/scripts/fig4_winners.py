from common import *
from style import *
setup()
d=pd.read_csv(RES/'main_decisions.csv'); f=fleets()
co={(c,fa):x for c,fa,x in zip(f.cell,f.family,f.coop_share)}
d['coop']=[co[(c,w)] for c,w in zip(d.cell,d.winner)]
def cls(w,c):
    if c>0.10+1e-12: return 'coupling-reliant'
    return 'mixed' if w.startswith('MX') else 'single-carry tier'
d['cls']=[cls(w,c) for w,c in zip(d.winner,d.coop)]
order=['single-carry tier','mixed','coupling-reliant']; col={'single-carry tier':BLUE,'mixed':AQUA,'coupling-reliant':ORANGE}
lab={'single-carry tier':'homogeneous, ≤10% coupled','mixed':'1–2 heavy + light units, ≤10% coupled','coupling-reliant':'any fleet with >10% coupled'}
ct=pd.crosstab(d.cell,d.cls).reindex(columns=order,fill_value=0)
cells=sorted(ct.index,key=lambda c:(c.split('_')[0],c.split('_')[1],c.split('_')[2]))
fig,ax=plt.subplots(figsize=(7.48,5.2))
y=[];yl=[];pos=0;grp=[]
for ms in ['jiang','lightskew','uniform','extraheavy','rohcha','liu']:
    cs=[c for c in cells if c.startswith(ms)]
    start=pos
    for c in cs:
        y.append(pos); yl.append(c.split('_',1)[1].replace('_',' · ').replace('baseline','emp').replace('tight','tight')); pos+=1
    grp.append((ms,start,pos-1)); pos+=0.8
cs=[c for ms in ['jiang','lightskew','uniform','extraheavy','rohcha','liu'] for c in cells if c.startswith(ms)]
left=np.zeros(len(cs))
for k in order:
    v=ct.loc[cs,k].values/180*100
    ax.barh(y,v,left=left,height=0.78,color=col[k],label=lab[k],edgecolor='white',linewidth=0.6)
    left+=v
ax.set_yticks(y,yl,fontsize=6.3); ax.invert_yaxis()
for ms,a,b in grp:
    ax.text(-15,(a+b)/2,ms,ha='right',va='center',fontsize=8,fontweight='bold')
ax.set_xlim(0,100); ax.set_xlabel('Share of the 180 cost settings per condition (%)')
ax.grid(axis='y',visible=False)
ax.legend(loc='upper center',ncol=3,bbox_to_anchor=(0.45,1.06))
fig.tight_layout()
save(fig,'fig4_winners')
print(d.cls.value_counts(normalize=True)); print(d.groupby(d.cell.str.split('_').str[0]).cls.value_counts(normalize=True).unstack().round(3))
