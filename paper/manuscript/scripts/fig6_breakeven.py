from common import *
from style import *
setup()
f=fleets(); f=f[f.K_final.notna()]
co={(c,fa):x for c,fa,x in zip(f.cell,f.family,f.coop_share)}
rs=np.exp(np.linspace(np.log(0.5),np.log(5000),300))
recs=[]
for cell,g in f.groupby('cell'):
    gi=g.set_index('family')
    for m in RC.MAIN_MODELS:
        P=RC.proxy(m); cap={fa:P(RC.caps(cell,fa,int(k))) for fa,k in zip(g.family,g.K_final)}
        for lab in RC.LAB4:
            L={fa:RC.labour(v,lab,int(v.K_final)) for fa,v in gi.iterrows()}
            fams=list(cap); C=np.array([[r*cap[fa]+L[fa] for fa in fams] for r in rs])
            w=C.argmin(1); sc=np.array([co[(cell,fams[i])]<=0.1+1e-12 for i in w])
            recs.append((cell,RC.mname(m),lab,sc))
arr=np.array([x[3] for x in recs]); m4=np.array([x[0].startswith('extraheavy') for x in recs])
allshare=arr.mean(0)*100; ex=arr[~m4].mean(0)*100
fig,ax=plt.subplots(figsize=(3.54*1.25,2.7))
ax.axvspan(5.1,30,color='#e8f0fb',lw=0)
ax.text(np.sqrt(5.1*30),3,'calibrated\nrange',ha='center',va='bottom',fontsize=6.3,color=BLUE)
ax.plot(rs,ex,color=BLUE,lw=1.8,label='excluding blocks heavier than every tier (extraheavy)')
ax.plot(rs,allshare,color=GREY,lw=1.4,label='all 36 conditions')
ax.axvline(64,color=INK2,lw=0.6,ls=(0,(3,2))); ax.text(70,8,'one crew-shift\n(64 labour-h)',fontsize=6.2,color=INK2)
ax.set_xscale('log'); ax.set_xlim(0.5,5000); ax.set_ylim(0,102)
ax.set_xticks([1,10,100,1000],['1','10','100','1,000'])
ax.set_xlabel('Daily capital cost of a 270 t transporter, r (labour-hours)')
ax.set_ylabel('Settings won by a fleet\nthat couples ≤10% of blocks (%)')
ax.legend(loc='lower left',bbox_to_anchor=(0,0.13),fontsize=6.4)
fig.tight_layout(); save(fig,'fig6_breakeven')
i5=np.argmin(abs(rs-5.1)); i30=np.argmin(abs(rs-30))
print('ex extraheavy at r=5.1,30, max r:',ex[i5],ex[i30],ex[-1],' all:',allshare[i5],allshare[i30],allshare[-1], 'min ex',ex.min())
