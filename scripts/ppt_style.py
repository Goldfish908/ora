"""Shared PPT style helpers (extracted from make_report_ppt.py).

Usage:
    from ppt_style import *          # prs, BLANK, helpers
    ... build slides ...
    save(ROOT / "docs" / "report" / "xxx.pptx")
"""
from pathlib import Path

from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

ROOT = Path(__file__).resolve().parent.parent

DARK = RGBColor(0x1F, 0x4E, 0x79)
ACC = RGBColor(0x2E, 0x75, 0xB6)
GRAY = RGBColor(0x59, 0x59, 0x59)
LIGHT = RGBColor(0xF2, 0xF2, 0xF2)
RED = RGBColor(0xC0, 0x00, 0x00)
GREEN = RGBColor(0x2E, 0x7D, 0x32)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
BLACK = RGBColor(0x26, 0x26, 0x26)
ORANGE = RGBColor(0xC5, 0x5A, 0x11)

EA_FONT = "Microsoft YaHei"
LATIN_FONT = "Segoe UI"
MONO_FONT = "Consolas"

prs = Presentation()
prs.slide_width = Inches(13.333)
prs.slide_height = Inches(7.5)
BLANK = prs.slide_layouts[6]
PAGE = [0]
FOOTER = "ORAgent harness · RetailOpt-190 / IndustryOR · Qwen3.8-27B · 2026-11-04"


def save(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(path))
    print(f"saved {path} ({PAGE[0]} slides)")


def _ea(run, name):
    rPr = run._r.get_or_add_rPr()
    for tag in ("a:ea", "a:cs"):
        for el in rPr.findall(qn(tag)):
            rPr.remove(el)
        el = rPr.makeelement(qn(tag), {"typeface": name})
        rPr.append(el)


def style(run, size=14, bold=False, color=BLACK, mono=False, italic=False):
    f = run.font
    f.size = Pt(size)
    f.bold = bold
    f.italic = italic
    f.color.rgb = color
    f.name = MONO_FONT if mono else LATIN_FONT
    _ea(run, MONO_FONT if mono else EA_FONT)


def textbox(slide, x, y, w, h):
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    return tf


def para(tf, text, size=14, bold=False, color=BLACK, level=0, mono=False,
         align=PP_ALIGN.LEFT, space_after=4, first=False, bullet=None):
    p = tf.paragraphs[0] if first else tf.add_paragraph()
    p.alignment = align
    p.space_after = Pt(space_after)
    p.line_spacing = 1.12
    prefix = ""
    if bullet == 1:
        prefix = "• " if level == 0 else "  – "
    r = p.add_run()
    r.text = prefix + text
    style(r, size=size, bold=bold, color=color, mono=mono)
    return p


def chrome(slide, title, kicker=""):
    bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, Inches(0.16))
    bar.fill.solid(); bar.fill.fore_color.rgb = DARK; bar.line.fill.background()
    tf = textbox(slide, 0.55, 0.28, 12.2, 0.9)
    if kicker:
        para(tf, kicker, size=11, bold=True, color=ACC, first=True, space_after=0)
        para(tf, title, size=24, bold=True, color=DARK)
    else:
        para(tf, title, size=26, bold=True, color=DARK, first=True)
    PAGE[0] += 1
    ft = textbox(slide, 11.8, 7.08, 1.3, 0.35)
    para(ft, f"{PAGE[0]}", size=10, color=GRAY, align=PP_ALIGN.RIGHT, first=True)
    ft2 = textbox(slide, 0.55, 7.08, 8.0, 0.35)
    para(ft2, FOOTER, size=9, color=GRAY, first=True)


def bullets(slide, items, x=0.55, y=1.35, w=12.25, h=5.6, size=14):
    tf = textbox(slide, x, y, w, h)
    first = True
    for it in items:
        lvl, txt, bold = it if len(it) == 3 else (it[0], it[1], False)
        color = BLACK
        if isinstance(txt, tuple):
            txt, color = txt
        para(tf, txt, size=size - (1 if lvl else 0), bold=bold, color=color,
             level=lvl, first=first, bullet=1, space_after=6 if lvl == 0 else 3)
        first = False
    return tf


def table(slide, rows, x, y, w, h, col_w=None, header=True, size=12):
    nr, nc = len(rows), len(rows[0])
    gf = slide.shapes.add_table(nr, nc, Inches(x), Inches(y), Inches(w), Inches(h))
    tbl = gf.table
    if col_w:
        for i, cw in enumerate(col_w):
            tbl.columns[i].width = Emu(int(Inches(cw)))
    for ri, row in enumerate(rows):
        for ci, val in enumerate(row):
            cell = tbl.cell(ri, ci)
            cell.margin_top = cell.margin_bottom = Emu(18000)
            cell.margin_left = cell.margin_right = Emu(45000)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            tfc = cell.text_frame
            tfc.word_wrap = True
            p = tfc.paragraphs[0]
            r = p.add_run(); r.text = str(val)
            if header and ri == 0:
                cell.fill.solid(); cell.fill.fore_color.rgb = DARK
                style(r, size=size, bold=True, color=WHITE)
            else:
                cell.fill.solid()
                cell.fill.fore_color.rgb = LIGHT if ri % 2 == 0 else WHITE
                bold = isinstance(val, str) and val.startswith("**")
                if bold:
                    r.text = val.strip("*")
                style(r, size=size, bold=bold, color=BLACK)
    return gf


def picture(slide, path, x, y, w, h, caption=None):
    path = ROOT / path
    with Image.open(path) as im:
        iw, ih = im.size
    box_ar, img_ar = w / h, iw / ih
    if img_ar >= box_ar:
        nw, nh = w, w / img_ar
    else:
        nh, nw = h, h * img_ar
    nx, ny = x + (w - nw) / 2, y + (h - nh) / 2
    slide.shapes.add_picture(str(path), Inches(nx), Inches(ny), Inches(nw), Inches(nh))
    if caption:
        tf = textbox(slide, x, min(ny + nh + 0.03, 7.0), w, 0.4)
        para(tf, caption, size=10, color=GRAY, align=PP_ALIGN.CENTER, first=True)


def codeblock(slide, lines, x, y, w, h, size=11):
    box = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y),
                                 Inches(w), Inches(h))
    box.fill.solid(); box.fill.fore_color.rgb = RGBColor(0x2D, 0x2D, 0x2D)
    box.line.fill.background()
    box.adjustments[0] = 0.04
    tf = box.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Inches(0.15)
    tf.margin_top = tf.margin_bottom = Inches(0.1)
    first = True
    for ln in lines:
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        p.line_spacing = 1.0
        r = p.add_run(); r.text = ln
        col = RGBColor(0xCE, 0xCE, 0xCE)
        st = ln.lstrip()
        if st.startswith("#"):
            col = RGBColor(0x8E, 0xC9, 0x8A)
        style(r, size=size, color=col, mono=True)
    return box


def flow(slide, steps, x=0.55, y=2.9, w=12.25, h=1.5):
    n = len(steps)
    bw = (w - 0.35 * (n - 1)) / n
    for i, (t, d) in enumerate(steps):
        bx = x + i * (bw + 0.35)
        box = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(bx), Inches(y),
                                     Inches(bw), Inches(h))
        box.fill.solid(); box.fill.fore_color.rgb = ACC if i % 2 == 0 else DARK
        box.line.fill.background()
        tf = box.text_frame; tf.word_wrap = True
        tf.margin_left = tf.margin_right = Inches(0.08)
        p = tf.paragraphs[0]; p.alignment = PP_ALIGN.CENTER
        r = p.add_run(); r.text = t; style(r, size=13, bold=True, color=WHITE)
        p2 = tf.add_paragraph(); p2.alignment = PP_ALIGN.CENTER
        r2 = p2.add_run(); r2.text = d; style(r2, size=10, color=RGBColor(0xDD, 0xE6, 0xF0))
        if i < n - 1:
            ar = slide.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, Inches(bx + bw + 0.02),
                                        Inches(y + h / 2 - 0.12), Inches(0.31), Inches(0.24))
            ar.fill.solid(); ar.fill.fore_color.rgb = GRAY; ar.line.fill.background()


def cover(title, subtitle, line3, line4):
    s = prs.slides.add_slide(BLANK)
    bg = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, prs.slide_height)
    bg.fill.solid(); bg.fill.fore_color.rgb = DARK; bg.line.fill.background()
    tf = textbox(s, 1.0, 2.0, 11.3, 3.4)
    para(tf, title, size=44, bold=True, color=WHITE, first=True, space_after=10)
    para(tf, subtitle, size=24, color=RGBColor(0xBD, 0xD7, 0xEE), space_after=18)
    para(tf, line3, size=15, color=RGBColor(0x9D, 0xC3, 0xE6), space_after=6)
    para(tf, line4, size=12, color=RGBColor(0x8A, 0xAA, 0xC8))
    return s
