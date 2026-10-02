from common import *
from style import *
setup()
f=fleets(); cn=json.load(open(RES/'claim_numbers.json'))
f['veh_h']=f.crew_veh_h/4
f['sync']=[cn['per_series'][s]['sync_share'] for s in f.series]
ref=f[f.family=='550'].set_index('cell').veh_h
f['excess']=f.veh_h/f.cell.map(ref)-1
f['ms']=f.cell.str.split('_').str[0]
g=f[f.ms!='extraheavy'].copy()
b,a=np.polyfit(g.coop_share,g.excess,1); r=np.corrcoef(g.coop_share,g.excess)[0,1]
lr=pd.read_csv(RES/'main_load_rule.csv').merge(f[['series','coop_share']],on='series')
lr['due']=lr.cell.str.split('_').str[2]; lr['rel']=lr.d/lr.K_star
bins=[-0.01,0.0001,0.1,0.3,0.6,1.0]; labs=['0','0–10','10–30','30–60','60–100']
lr['bin']=pd.cut(lr.coop_share,bins,labels=labs)
agg=lr.groupby(['due','bin'],observed=True).rel.agg(['mean','count','sem']).reset_index()
fig,(ax1,ax2)=plt.subplots(1,2,figsize=(7.48,2.9),gridspec_kw=dict(width_ratios=[1.15,1]))
ax1.scatter(g.coop_share*100,g.excess*100,s=9,color=GREY,alpha=0.55,lw=0,label='fleet series (n = %d)'%len(g))
xx=np.linspace(0,1,50); ax1.plot(xx*100,(a+b*xx)*100,color=BLUE,lw=1.8,label='least-squares fit')
ax1.text(56,8,'+%.1f%% transporter-hours\nper 1 pp of blocks coupled\n(r = %.2f)'%(b,r),color=BLUE,fontsize=7)
ax1.set_xlabel('Blocks carried by a coupled team (%)'); ax1.set_ylabel('Transporter-hours worked per day,\nvs. single-carry fleet (%)')
ax1.set_title('(a) Coupling multiplies vehicle occupancy')
ax1.legend(loc='upper left',handletextpad=0.3)
x=np.arange(len(labs)); w=0.36
for k,(due,col,lab) in enumerate([('baseline',LGREY,'empirical due dates'),('tight',BLUE,'tight due dates')]):
    s=agg[agg.due==due].set_index('bin').reindex(labs)
    ax2.bar(x+(k-0.5)*w,s['mean']*100,w*0.92,color=col,label=lab,yerr=1.96*s['sem']*100,error_kw=dict(lw=0.6,capsize=1.5,ecolor=INK2))
ax2.axhline(0,color=INK2,lw=0.6)
ax2.set_xticks(x,labs); ax2.set_xlabel('Blocks carried by a coupled team (%)')
ax2.set_ylabel('Transporters beyond the workload\nrule, (K* − K$_\\rho$)/K* (%)')
ax2.set_title('(b) Coupling also needs timing slack')
ax2.legend(loc='upper left')
fig.tight_layout(w_pad=2.0)
save(fig,'fig5_occupancy')
print(b,a,r, agg)
print('sync median %.4f max %.4f'%(f.sync.median(),f.sync.max()))
