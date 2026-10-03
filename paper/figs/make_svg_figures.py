"""Export the introduction and framework SVG sources to vector PDF and 300 dpi PNG.

Run: python paper/figs/make_svg_figures.py [intro_b framework]
Inputs and outputs are in paper/latex/figs/. Set CHROME to a Chrome/Chromium executable,
or use a browser on PATH or the default Windows installation.
"""
import os, re, shutil, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIGS = HERE.parent / 'latex' / 'figs'
TEXTWIDTH = 468.3324          # \textwidth of cas-sc on A4, in pt
CHROME = (os.environ.get('CHROME') or shutil.which('google-chrome') or shutil.which('chromium')
          or shutil.which('chrome') or str(Path(os.environ.get('PROGRAMFILES', ''))
                                         / 'Google' / 'Chrome' / 'Application' / 'chrome.exe'))


def export(name):
    svg = re.sub(r'^<\?xml[^>]*>\s*', '', (FIGS / f'fig_{name}.svg').read_text(encoding='utf-8'))
    vw, vh = map(float, re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', svg).groups())
    w, h = TEXTWIDTH, TEXTWIDTH * vh / vw
    svg = re.sub(r'\swidth="[\d.]+"', f' width="{w:.3f}pt"', svg, count=1)
    svg = re.sub(r'\sheight="[\d.]+"', f' height="{h:.3f}pt"', svg, count=1)
    html = f"""<!doctype html><html><head><meta charset="utf-8"><style>
@page {{ size: {w:.3f}pt {h:.3f}pt; margin: 0 }}
html, body {{ margin: 0; padding: 0; width: {w:.3f}pt; height: {h:.3f}pt; overflow: hidden; background: #fff }}
svg {{ display: block }}
</style></head><body>{svg}</body></html>"""
    with tempfile.TemporaryDirectory() as tmp:
        page = Path(tmp) / f'{name}.html'
        page.write_text(html, encoding='utf-8')
        base = [CHROME, '--headless=new', '--disable-gpu', '--hide-scrollbars', f'--user-data-dir={Path(tmp) / "profile"}']
        subprocess.run(base + ['--no-pdf-header-footer', f'--print-to-pdf={FIGS / f"fig_{name}.pdf"}', page.as_uri()],
                       check=True, capture_output=True, timeout=120)
        # 300 dpi preview, as for the other figures (CSS px = 4/3 pt)
        subprocess.run(base + [f'--window-size={round(w * 4 / 3)},{round(h * 4 / 3)}', f'--force-device-scale-factor={300 / 96:.4f}',
                               f'--screenshot={FIGS / f"fig_{name}.png"}', page.as_uri()], check=True, capture_output=True, timeout=120)
    print(name, 'exported', f'{w:.1f} x {h:.1f} pt')


if __name__ == '__main__':
    for name in sys.argv[1:] or ['intro_b', 'framework']:
        export(name)
