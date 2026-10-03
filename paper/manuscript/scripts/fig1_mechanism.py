from style import *
import matplotlib.patches as mp
setup()
fig,axs=plt.subplots(1,2,figsize=(W,2.2),sharex=True,layout='constrained')
def seg(ax,y,x0,w,kind,label=None):
    st={'approach':dict(fc='#e4e3df',ec='none'),'wait':dict(fc='white',ec=INK2,lw=0.6),
        'align':dict(fc=ORANGE,ec='none'),'A':dict(fc=BLUE,ec='none'),'B':dict(fc=GREY,ec='none')}[kind]
    ax.add_patch(mp.Rectangle((x0,y-0.32),w,0.64,**st))
    if label: ax.text(x0+w/2,y,label,ha='center',va='center',fontsize=7,color='white' if kind in('A','B','align') else INK2)
for ax in axs:
    ax.set_ylim(-0.9,1.45); ax.set_xlim(0,112); ax.grid(False)
    ax.spines['left'].set_visible(False); ax.tick_params(axis='y',length=0)
    ax.set_xlabel('Time (min)')
# illustrative times: approach 10 min (8 and 12 when coupled), service 33 min, alignment delta 10 min per member
a=axs[0]
a.set_yticks([1,0],['425 t unit','270 t unit'])
seg(a,1,0,10,'approach'); seg(a,1,10,33,'A','block A (420 t)')
seg(a,0,0,10,'approach'); seg(a,0,10,33,'B','block B (250 t)')
a.set_title('(a) Single carry: both blocks done at 43 min')
a.text(1,-0.45,'transporter-time: A 43 min, B 43 min',fontsize=7,color=INK2,va='top')
b=axs[1]
b.set_yticks([1,0],['270 t unit','270 t unit'])
seg(b,1,0,8,'approach'); seg(b,1,8,4,'wait'); seg(b,1,12,10,'align','δ'); seg(b,1,22,33,'A','block A, coupled')
seg(b,0,0,12,'approach'); seg(b,0,12,10,'align','δ'); seg(b,0,22,33,'A','block A, coupled')
seg(b,1,55,10,'approach'); seg(b,1,65,33,'B','block B')
b.set_title('(b) Coupled lift: block B waits, done at 98 min')
b.text(1,-0.45,'extra transporter-time for A: 43 + 2 × 10 (δ) + 4 (waiting) = 67 min',fontsize=7,color=INK2,va='top')
handles=[mp.Patch(fc='#e4e3df',label='empty approach'),mp.Patch(fc='white',ec=INK2,lw=0.6,label='waiting for partner'),
         mp.Patch(fc=ORANGE,label='alignment δ'),mp.Patch(fc=BLUE,label='service of heavy block A'),mp.Patch(fc=GREY,label='service of light block B')]
fig.legend(handles=handles,loc='outside lower center',ncol=5,handlelength=1.4,columnspacing=1.0)
save(fig,'fig1_mechanism')
