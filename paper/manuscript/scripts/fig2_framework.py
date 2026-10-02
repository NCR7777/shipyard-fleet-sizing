from style import *
import matplotlib.patches as mp
setup()
fig,ax=plt.subplots(figsize=(7.48,2.2)); ax.set_xlim(-0.6,101.6); ax.set_ylim(4,35); ax.axis('off')
boxes=[
 ('1 Daily instances','Shipyard road network\n97 block moves in 16 h\n6 mass × 3 handling\n× 2 due-date scenarios\n30 days per condition'),
 ('2 Schedule','ALNS: global order +\none team per block\n(single carrier or a\nminimal team of ≤3\ncoupled transporters)'),
 ('3 Size','smallest K that meets\n≥95% on time over\n30 days and no block\n>120 min late → K*'),
 ('4 Price','C = r·P + L\nP: 33 tender awards\n5 price curves, 9 r\n4 labour measures'),
 ('5 Decide, audit','cheapest fleet in each\nof 6,480 settings;\nsearch, sampling,\nnoise, parameter and\nsecond-yard checks'),
]
w=18.6; gap=1.75; x0=0.3
for i,(t,b) in enumerate(boxes):
    x=x0+i*(w+gap)
    fc='#e8f0fb' if i in (2,4) else '#f4f3f0'
    ax.add_patch(mp.FancyBboxPatch((x,12.5),w,20.5,boxstyle='round,pad=0.3,rounding_size=1.2',fc=fc,ec=BLUE if i in (2,4) else LGREY,lw=0.8))
    ax.text(x+0.9,31.3,t,fontsize=7.4,fontweight='bold',va='top',color=INK)
    ax.text(x+0.9,27.0,b,fontsize=6.2,va='top',color=INK2,linespacing=1.35)
    if i<4:
        ax.annotate('',xy=(x+w+gap-0.05,23),xytext=(x+w+0.35,23),arrowprops=dict(arrowstyle='-|>',color=INK2,lw=0.8,mutation_scale=8))
ax.annotate('',xy=(x0+2*(w+gap)+w/2,12.1),xytext=(x0+2*(w+gap)+w/2,7.6),arrowprops=dict(arrowstyle='-',color=BLUE,lw=0.7,ls=(0,(2,2))))
ax.text(x0+2*(w+gap)+w/2+1,7.8,'main study: 384 fleet series, 51,480 ALNS runs; all studies: 189,330 runs',fontsize=6.3,color=BLUE,va='bottom')
save(fig,'fig2_framework')
