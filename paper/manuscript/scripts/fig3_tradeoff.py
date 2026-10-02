from common import *
from style import *
import matplotlib as mpl
setup()
f=fleets(); f['ms']=f.cell.str.split('_').str[0]; f['h']=f.cell.str.split('_').str[1]; f['due']=f.cell.str.split('_').str[2]
tiers=[200,250,270,300,325,380,425,500,550]
names={'jiang':'jiang  Jiang empirical (max 450 t)','lightskew':'lightskew  light-skewed (max 500 t)','uniform':'uniform  uniform 100–500 t',
       'extraheavy':'extraheavy  extra-heavy tail (to 800 t)','rohcha':'rohcha  Roh–Cha sample (max 544 t)','liu':'liu  Liu sample (max 399 t)'}
cover={'jiang':500,'lightskew':500,'uniform':500,'extraheavy':None,'rohcha':550,'liu':425}
fig,axs=plt.subplots(2,3,figsize=(7.48,4.3),sharex=True)
hc={'short':BLUE,'massdep':GREY,'long':LGREY}; hl={'short':'short short handling','massdep':'massdep mass-dependent','long':'long long loading'}
for ax,ms in zip(axs.flat,['jiang','lightskew','uniform','extraheavy','rohcha','liu']):
    g=f[(f.ms==ms)&(f.due=='baseline')&f.family.isin([str(t) for t in tiers])]
    for h in ['long','massdep','short']:
        x=g[g.h==h].copy(); x['q']=x.family.astype(int); x=x.sort_values('q')
        ax.plot(x.q,x.K_final,'-o',color=hc[h],lw=1.6 if h=='short' else 1.2,ms=3.2,label=hl[h],zorder=3 if h=='short' else 2)
    if cover[ms]:
        ax.axvline(cover[ms],color=INK2,lw=0.7,ls=(0,(3,2)))
        ax.text(cover[ms]-5,0.6,'single-carry\ntier',ha='right',va='bottom',fontsize=6.2,color=INK2)
    else:
        ax.text(545,0.6,'no single-carry tier:\n9% of blocks > 550 t',ha='right',va='bottom',fontsize=6.2,color=INK2)
    ax.set_title(names[ms],fontsize=7.6)
    ax.set_ylim(0,None); ax.yaxis.set_major_locator(mpl.ticker.MaxNLocator(integer=True))
    ax.set_xticks([200,270,325,380,425,500,550]); 
for ax in axs[1]: ax.set_xlabel('Transporter capacity tier (t)')
for ax in axs[:,0]: ax.set_ylabel('Transporters needed, K*')
h,l=axs[0,0].get_legend_handles_labels()
fig.legend(h[::-1],l[::-1],loc='upper center',ncol=3,bbox_to_anchor=(0.5,1.03))
fig.tight_layout(rect=(0,0,1,0.96))
save(fig,'fig3_tradeoff')
