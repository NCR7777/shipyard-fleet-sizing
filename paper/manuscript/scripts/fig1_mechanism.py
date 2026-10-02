from style import *
import matplotlib.patches as mp
setup()
fig,axs=plt.subplots(1,2,figsize=(7.48,2.35),sharex=True)
def seg(ax,y,x0,w,kind,label=None):
    st={'approach':dict(fc='#e4e3df',ec='none'),'wait':dict(fc='white',ec=INK2,hatch='////',lw=0.4),
        'align':dict(fc=ORANGE,ec='none'),'A':dict(fc=BLUE,ec='none'),'B':dict(fc=GREY,ec='none')}[kind]
    ax.add_patch(mp.Rectangle((x0,y-0.32),w,0.64,**st))
    if label: ax.text(x0+w/2,y,label,ha='center',va='center',fontsize=6.2,color='white' if kind in('A','B','align') else INK2)
for ax in axs:
    ax.set_ylim(-0.7,1.7); ax.set_xlim(0,112); ax.grid(False)
    ax.spines['left'].set_visible(False); ax.tick_params(axis='y',length=0)
    ax.set_xlabel('Time (min)')
# (a) single carry: heavy unit carries A, light unit carries B in parallel
a=axs[0]
a.set_yticks([1,0],['425 t unit','300 t unit'])
seg(a,1,0,10,'approach'); seg(a,1,10,33,'A','block A (420 t)')
seg(a,0,0,10,'approach'); seg(a,0,10,33,'B','block B (250 t)')
a.set_title('(a) Single carry: both done by 43 min')
a.text(1,-0.62,'transporter-time: A 43 min, B 43 min',fontsize=6.3,color=INK2)
# (b) coupled: two 270 t units lift A together, B waits
b=axs[1]
b.set_yticks([1,0],['270 t unit','270 t unit'])
seg(b,1,0,8,'approach'); seg(b,1,8,4,'wait'); seg(b,1,12,10,'align','δ'); seg(b,1,22,33,'A','block A, coupled')
seg(b,0,0,12,'approach'); seg(b,0,12,10,'align','δ'); seg(b,0,22,33,'A','block A, coupled')
seg(b,1,55,10,'approach'); seg(b,1,65,33,'B','block B')
b.set_title('(b) Coupled lift: B waits, done at 98 min')
b.text(1,-0.62,'transporter-time: A 2 × 55 = 110 min, B 43 min',fontsize=6.3,color=INK2)
handles=[mp.Patch(fc='#e4e3df',label='empty approach'),mp.Patch(fc='white',ec=INK2,hatch='////',lw=0.4,label='waiting for partner'),
         mp.Patch(fc=ORANGE,label='alignment δ'),mp.Patch(fc=BLUE,label='service of heavy block A'),mp.Patch(fc=GREY,label='service of light block B')]
fig.legend(handles=handles,loc='lower center',ncol=5,bbox_to_anchor=(0.5,-0.06),fontsize=6.6,handlelength=1.4,columnspacing=1.0)
fig.tight_layout(rect=(0,0.08,1,1),w_pad=2)
save(fig,'fig1_mechanism')
