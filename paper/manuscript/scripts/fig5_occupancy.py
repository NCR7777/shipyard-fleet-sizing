from common import *
from style import *
setup()
f=fleets(); f['ms']=[split(c)[0] for c in f.cell]
co={(c,fa):x for c,fa,x in zip(f.cell,f.family,f.coop_share)}
fig,axs=plt.subplots(2,2,figsize=(W,5.0),layout='constrained')
(ax1,ax2),(ax3,ax4)=axs

# (a) transporter-hours per day against the coupled share, 330 sized fleets outside the heavy-tail profile
f['veh_h']=f.crew_veh_h/4
ref=f[[fa==str(COVER[split(c)[0]]) for c,fa in zip(f.cell,f.family)]].set_index('cell').veh_h   # covering fleet of each condition
f['excess']=f.veh_h/f.cell.map(ref)-1
g=f[f.ms!='extraheavy']
b,a=np.polyfit(g.coop_share,g.excess,1); r=np.corrcoef(g.coop_share,g.excess)[0,1]
ax1.scatter(g.coop_share*100,g.excess*100,s=9,color=GREY,alpha=0.6,lw=0,label='sized fleets (n = %d)'%len(g))
xx=np.linspace(0,1,50); ax1.plot(xx*100,(a+b*xx)*100,color=BLUE,lw=1.6,label='least-squares fit')
ax1.text(0.97,0.04,'+%.1f%% per pp of blocks coupled (r = %.2f)'%(b,r),transform=ax1.transAxes,ha='right',va='bottom',
         color=BLUE,fontsize=7)
ax1.set_xlabel('Blocks carried by a coupled team (%)'); ax1.set_ylabel('Extra transporter-hours per day\n(% of covering fleet)')
ax1.set_title('(a) Coupling multiplies occupancy'); ax1.legend(loc='upper left',handletextpad=0.3)
print('(a) n %d, slope %.3f %% per pp, r %.4f'%(len(g),b,r))

# (b) main-study decomposition against the covering tier; additional mixes are not plotted
p=pd.read_csv(RES/'vehicle_time_pairs.csv')
main_keys=set(zip(f.cell,f.family))
p=p[[key in main_keys for key in zip(p.cell,p.family)]]
p=p[(p.coup_block_share>0.01)&(p.cell.map(lambda c: split(c)[0])!='extraheavy')&(p.d_work_h>0)]
q=lambda v: (np.median(v),sorted(v)[int(0.1*(len(v)-1))],sorted(v)[int(0.9*(len(v)-1))])
me,se,rr=q(list(p.share_excess)),q(list(p.share_sync)),np.corrcoef(p.h_occ,p.rel_work)[0,1]
top=p.d_work_h.max()*1.04
ax2.plot([0,top],[0,top],color=INK2,lw=0.7,ls=(0,(3,2)),label='1:1')
ax2.scatter(p.d_work_h,p.coup_excess_h,s=9,color=BLUE,alpha=0.7,lw=0,label='coupled occupancy')
ax2.scatter(p.d_work_h,p.d_sync_h,s=9,color=ORANGE,alpha=0.8,lw=0,label='waiting for partners')
ax2.set_xlim(0,top); ax2.set_ylim(0,top)
ax2.text(0.97,0.13,'median %.1f%% occupancy, %.1f%% waiting\n(%d fleet pairs)'%(100*me[0],100*se[0],len(p)),
         transform=ax2.transAxes,ha='right',va='bottom',fontsize=7)
ax2.set_xlabel('Extra transporter-hours per day vs. covering tier'); ax2.set_ylabel('Transporter-hours per day')
ax2.set_title('(b) Waiting is a small part'); ax2.legend(loc='upper left',handletextpad=0.3)
print('(b) pairs %d; occupancy share median %.1f%% (p10-p90 %.1f-%.1f); waiting median %.1f%% (%.1f-%.1f); r %.3f'%(
      len(p),100*me[0],100*me[1],100*me[2],100*se[0],100*se[1],100*se[2],rr))

# (c) transporters beyond the workload rule; 95% intervals from resampling conditions (cells), 2,000 resamples
lr=pd.read_csv(RES/'main_load_rule.csv').merge(f[['series','coop_share']],on='series')
lr['due']=[split(c)[2] for c in lr.cell]; lr['rel']=lr.d/lr.K_star
labs=['0','(0,10]','(10,30]','(30,60]','(60,100]']
lr['bin']=pd.cut(lr.coop_share,[-0.01,0.0001,0.1,0.3,0.6,1.0],labels=labs)
rng=np.random.default_rng(1); x=np.arange(len(labs)); w=0.38
for k,(due,c) in enumerate([('baseline',LGREY),('tight',BLUE)]):
    s=lr[lr.due==due]        # cells in profile and handling order, so the resamples do not depend on the condition codes
    cells=sorted(s.cell.unique(),key=lambda c: (PROFILES.index(split(c)[0]),list(HANDLING).index(split(c)[1])))
    S=s.pivot_table(index='cell',columns='bin',values='rel',aggfunc='sum',observed=False).reindex(index=cells,columns=labs).fillna(0).values
    N=s.pivot_table(index='cell',columns='bin',values='rel',aggfunc='count',observed=False).reindex(index=cells,columns=labs).fillna(0).values
    idx=rng.integers(0,len(cells),(2000,len(cells)))
    with np.errstate(invalid='ignore'):
        boot=S[idx].sum(1)/N[idx].sum(1)
    mean=S.sum(0)/N.sum(0); lo,hi=np.nanpercentile(boot,[2.5,97.5],axis=0)
    ax3.bar(x+(k-0.5)*w,mean*100,w*0.92,color=c,label='%s due dates'%DUE[due],
            yerr=[(mean-lo)*100,(hi-mean)*100],error_kw=dict(lw=0.6,capsize=1.5,ecolor=INK2))
    for j,lb in enumerate(labs):
        print('(c) %s %-9s mean %6.2f%% [%6.2f, %6.2f]  fleets %3d  conditions %2d'%(
              DUE[due],lb,100*mean[j],100*lo[j],100*hi[j],N[:,j].sum(),(N[:,j]>0).sum()))
ax3.axhline(0,color=INK2,lw=0.6)
ax3.set_xticks(x,labs); ax3.set_xlabel('Blocks carried by a coupled team (%)')
ax3.set_ylabel('Transporters beyond workload rule,\n($K$* − $K_\\rho$)/$K$* (%)')
ax3.set_title('(c) Coupling needs timing slack'); ax3.legend(loc='upper left')

# (d) winners as theta varies; every fleet's cost is a line in theta, so the winner is read off the lower envelope
ths=np.exp(np.linspace(np.log(0.5),np.log(5000),4001))
recs=[]
for cell,gc in f.groupby('cell'):
    fams=list(gc.family); le=np.array([co[(cell,fa)]<=0.10+1e-12 for fa in fams])
    for m in RC.MAIN_MODELS:
        P=RC.proxy(m); cap=np.array([P(RC.caps(cell,fa,int(k))) for fa,k in zip(gc.family,gc.K_final)])
        for lab in RC.LAB4:
            L=np.array([RC.labour(v,lab,int(v.K_final)) for _,v in gc.iterrows()])
            win=lambda th: le[np.argmin(np.outer(th,cap)+L,axis=1)]
            cut=[(L[j]-L[i])/(cap[i]-cap[j]) for i in range(len(fams)) for j in range(len(fams)) if cap[i]>cap[j]]
            cut=np.unique([c for c in cut if c>0]+[0.0])                     # envelope breakpoints
            mids=np.append((cut[:-1]+cut[1:])/2,cut[-1]+1)
            first=next((lo for lo,ok in zip(cut,win(mids)) if not ok),np.inf)  # lowest theta won by a coupling fleet
            inf=le[np.lexsort((L,cap))[0]]                                    # theta -> infinity: capital alone
            recs.append(dict(ms=split(cell)[0],lab=lab,curve=win(ths),pts=win(np.array([5.1,30.0])),lim=inf,first_th=first))
R=pd.DataFrame(recs); out=R.ms!='extraheavy'
lines=[(out,'Outside heavy-tail profile, all labour measures',dict(color=BLUE,lw=1.6)),
       (out&(R.lab=='crew_team_h'),'Outside heavy-tail profile, crew-team hours',dict(color=BLUE,lw=1.2,ls='--')),
       (R.ms==R.ms,'All 36 conditions',dict(color=GREY,lw=1.3))]
ax4.axvspan(5.1,30,ymin=0.32,color='#e8f0fb',lw=0)          # the bottom strip is kept free for the legend
ax4.text(np.sqrt(5.1*30),35,'calibrated\nrange',ha='center',va='bottom',fontsize=7,color=BLUE)
ax4.axvline(64,ymin=0.32,color=INK2,lw=0.7,ls=':')
ax4.text(70,35,'one crew-day\n(64 labour-h)',fontsize=7,color=INK2,va='bottom')
for m,lab,st in lines:
    ax4.plot(ths,np.stack(R[m]['curve']).mean(0)*100,label=lab,**st)
    at=np.stack(R[m]['pts']).mean(0)*100
    print('(d) %-48s n=%3d  theta 5.1: %.1f%%  theta 30: %.1f%%  limit: %.1f%%  first below 100%%: %.2f'%(
          lab,m.sum(),at[0],at[1],100*R[m]['lim'].mean(),R[m]['first_th'].min()))
ax4.set_xscale('log'); ax4.set_xlim(0.5,5000); ax4.set_ylim(0,102)
ax4.set_xticks([1,10,100,1000],['1','10','100','1,000'])
ax4.set_xlabel('Daily capital cost of a 270 t transporter, $\\theta$ (labour-hours)')
ax4.set_ylabel('Decisions won by fleets\ncoupling ≤10% (%)')
ax4.set_title('(d) Capital would have to be very dear'); ax4.legend(loc='lower left')
save(fig,'fig5_occupancy')
