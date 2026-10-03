from common import *
from style import *
from collections import Counter
setup()
lb=pd.read_csv(RES/'delay_cap_late_blocks.csv'); gr=pd.read_csv(RES/'delay_cap_grid.csv')
lb['ms']=[split(c)[0] for c in lb.cell]
# fleets that qualify with one transporter fewer without a cap than with the 120-min cap; MX1/MX2 with substituted heavy
# members are the same fleet as the two-tier mix of equal composition
comp={(c,tuple(sorted(Counter(RC.caps(c,fa,int(k))).items()))) for c,fa,k in zip(lb.cell,lb.family,lb.K_uncapped)}
assert (lb.K_120==lb.K_uncapped+1).all()
print('fleet-condition pairs %d, distinct fleets %d, largest delay %.1f-%.1f h'%(len(lb),len(comp),lb.max_delay_h.min(),lb.max_delay_h.max()))
levels=['inf','480','240','120','60','30']; xl=['None','480','240','120','60','30']
gr['level']=gr.level.map(lambda v: 'inf' if str(v)=='inf' else str(int(float(v))))
gr['ms']=[split(c)[0] for c in gr.cell]
fig,(a,b,c)=plt.subplots(1,3,figsize=(W,2.35),layout='none')     # fixed equal gutters; (a) has no y axis
fig.subplots_adjust(left=0.012,right=0.995,bottom=0.215,top=0.875,wspace=0.42)

# (a) blocks deferred more than 4 h in the best uncapped schedules of the homogeneous light fleets
h=lb[lb.family.isin(['300','325'])].sort_values(['ms','family'])
y=np.arange(len(h)); cp=h.late_over_4h_coupled.values; al=(h.late_over_4h-h.late_over_4h_coupled).values
a.barh(y,cp,height=0.6,color=ORANGE,label='coupled')
a.barh(y,al,left=cp,height=0.6,color=LGREY,label='carried alone')
for yi,(n,mx,fam,ms) in enumerate(zip(h.late_over_4h,h.max_delay_h,h.family,h.ms)):
    a.text(1,yi-0.36,'%s t, %s'%(fam,PROFILE[ms]),fontsize=7,va='bottom')
    a.text(n+1.5,yi,'max %.1f h'%mx,fontsize=7,va='center',color=INK2)
    print('(a) %s t %s: %d of %d blocks deferred > 4 h are coupled; largest delay %.1f h'%(fam,PROFILE[ms],n-al[yi],n,mx))
a.set_yticks([]); a.spines['left'].set_visible(False); a.set_ylim(len(h)-0.4,-0.9); a.set_xlim(0,118)
a.set_xticks([0,20,40,60,80,100])
a.set_xlabel('Blocks deferred > 4 h, no cap (30 days)'); a.set_title('(a) Without a cap, coupled lifts slip')
a.legend(loc='lower right',handlelength=1.0)

# (b) share of decisions (180 per condition and cap) whose winner couples at most 10% of blocks
sty={'jiang':dict(color=BLUE,marker='o',ls='-'),'uniform':dict(color=GREY,marker='s',ls='--'),'liu':dict(color=AQUA,marker='^',ls=':')}
for k,ms in enumerate(['jiang','uniform','liu']):
    s=gr[gr.ms==ms].groupby('level').coop.agg(lambda v: 100*(v<=0.10+1e-12).mean()).reindex(levels)
    assert (gr[gr.ms==ms].groupby('level').size()==180).all()
    b.plot(np.arange(6)+(k-1)*0.12,s.values,ms=3.5,lw=1.1,mfc='white' if k else sty[ms]['color'],label=PROFILE[ms],**sty[ms])
    print('(b) %s: %s'%(PROFILE[ms],dict(zip(xl,s.round(1).tolist()))))
b.set_xticks(range(6),xl); b.set_ylim(60,104); b.set_xlabel('Lateness cap $T_{\\max}$ (min)')
b.set_ylabel('Decisions won by fleets\ncoupling ≤10% (%)'); b.set_title('(b) Tested caps favour low-coupling fleets')
b.legend(loc='lower right')

# (c) least-cost increase over the uncapped decision, shift labour (45 cost scenarios per condition)
sh=gr[gr.labour=='shift_h']
for k,ms in enumerate(['jiang','uniform','liu']):
    s=sh[sh.ms==ms].groupby('level').cost_vs_inf.agg(['min','median','max','size']).reindex(levels)*[100,100,100,1]
    assert (s['size']==45).all()
    xx=np.arange(6)+(k-1)*0.22
    c.vlines(xx,s['min'],s['max'],color=sty[ms]['color'],lw=1.0)
    c.plot(xx,s['median'],ls='none',marker=sty[ms]['marker'],ms=3.5,color=sty[ms]['color'],mfc='white' if k else sty[ms]['color'],
           label=PROFILE[ms])
    print('(c) %s: min-median-max (%%) %s'%(PROFILE[ms],dict(zip(xl,s[['min','median','max']].round(2).values.tolist()))))
r=sh.groupby('level').cost_vs_inf.agg(['min','max']).reindex(levels)*100
print('(c) all three conditions, shift labour: %s'%dict(zip(xl,r.round(2).values.tolist())))
print('(c) all labour measures, lowest difference: %.2f%%'%(100*gr.cost_vs_inf.min()))
c.axhline(0,color=INK2,lw=0.6)
c.set_xticks(range(6),xl); c.set_xlabel('Lateness cap $T_{\\max}$ (min)'); c.set_ylim(-0.3,5.2)
c.set_ylabel('Least-cost increase vs. no cap,\nshift labour (%)'); c.set_title('(c) The cap costs little')
c.legend(loc='upper left')
save(fig,'fig7_service')
