"""Build the external-facing report deck: docs/report/ORAgent_report_2026-11-03.pptx

Content source of truth: docs/paper/experiment_log_v0.1.md (+ novelty_audit_v0.1.md).
All numbers are copied from those docs; this script introduces none.
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
OUT = ROOT / "docs" / "report" / "ORAgent_report_2026-11-03.pptx"

DARK = RGBColor(0x1F, 0x4E, 0x79)
ACC = RGBColor(0x2E, 0x75, 0xB6)
GRAY = RGBColor(0x59, 0x59, 0x59)
LIGHT = RGBColor(0xF2, 0xF2, 0xF2)
RED = RGBColor(0xC0, 0x00, 0x00)
GREEN = RGBColor(0x2E, 0x7D, 0x32)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
BLACK = RGBColor(0x26, 0x26, 0x26)

EA_FONT = "Microsoft YaHei"
LATIN_FONT = "Segoe UI"
MONO_FONT = "Consolas"

prs = Presentation()
prs.slide_width = Inches(13.333)
prs.slide_height = Inches(7.5)
BLANK = prs.slide_layouts[6]
PAGE = [0]


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
    para(ft2, "ORAgent harness · RetailOpt-190 × Qwen3.8-27B · 2026-11-03",
         size=9, color=GRAY, first=True)


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


# ---------------------------------------------------------------- S1 封面
s = prs.slides.add_slide(BLANK)
bg = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, prs.slide_height)
bg.fill.solid(); bg.fill.fore_color.rgb = DARK; bg.line.fill.background()
tf = textbox(s, 1.0, 2.0, 11.3, 3.4)
para(tf, '从"算得出"到"算得对"', size=44, bold=True, color=WHITE, first=True, space_after=10)
para(tf, "LLM 运筹建模的语义校验、多链仲裁与自进化 harness", size=24,
     color=RGBColor(0xBD, 0xD7, 0xEE), space_after=18)
para(tf, "RetailOpt-190 × 内网 Qwen3.8-27B · 实验全记录(19 个实验,逐数字可追溯)",
     size=15, color=RGBColor(0x9D, 0xC3, 0xE6), space_after=6)
para(tf, "2026-11-03 · github.com/Goldfish908/ora(round2 分支)· 文档 docs/paper/ · 原始记录 runs/",
     size=12, color=RGBColor(0x8A, 0xAA, 0xC8))

# ---------------------------------------------------------------- S2 导览
s = prs.slides.add_slide(BLANK); chrome(s, "报告导览")
bullets(s, [
    (0, "背景与调研:自然语言 → 运筹优化建模 的任务设定,现有四类方法的结构性盲区", True),
    (0, "Motivation 实验(4 个):假成功普遍存在、誊抄错误、先验覆盖翻转对、注入探针", True),
    (0, "系统:三层校验 harness —— 预求解闸门 / SCIP 求解 / witness 语义重判 / 修复环", True),
    (0, "工程主线(8 个实验):memory 三代递进 → crash guard → 合体臂 → 三链集成仲裁 80.5%", True),
    (0, "对照与预算:ReLoop 同模型严格对照、预算重分配、负结果(如实报告)", True),
    (0, "自进化与科研命题:三层切片隔离、预注册生死判据、创新点逐条裁决", True),
], y=1.6, size=17)

# ---------------------------------------------------------------- S3 任务设定
s = prs.slides.add_slide(BLANK); chrome(s, "任务设定:一句话生成可执行的优化模型", "PART 1 · 背景")
bullets(s, [
    (0, "数据集 RetailOpt-190:ReLoop 团队公开基准(非自建);38 个原型 × 5 个数值变体,8 个问题族 F1–F8", False),
    (1, "ReLoop 论文报道该基准 SOTA 为 Claude Opus 4.6 的 31.1%", False),
    (0, "模型:内网 Qwen3.8-27B,thinking 开启,temperature 0.6;求解器 SCIP / PySCIPOpt(全开源栈)", False),
    (0, ("主指标 · 真实成功 = 代码可执行 ∧ witness 判语义可行 ∧ 目标值与参照解一致(容差 1e-2)", RED), True),
    (0, ("幻影(spurious success):代码跑通、目标值看似一致,但 witness 重判语义违例 —— 看似对实则错", RED), False),
], y=1.35, h=2.2)
flow(s, [("题面 NL + 数据", "零售库存优化题"),
         ("LLM 生成代码", "PySCIPOpt 建模"),
         ("SCIP 求解", "导出 solution.json"),
         ("独立校验", "witness 语义重判")])

# ---------------------------------------------------------------- S4 调研格局
s = prs.slides.add_slide(BLANK); chrome(s, "调研:四类现有方法与结构性盲区", "PART 1 · 背景")
table(s, [
    ["方法", "核心思路", "关键局限(我们的突破口)"],
    ["ReLoop(2025)", "执行反馈驱动的诊断-修复-回滚环", "只看求解行为;feasible-but-wrong 是其自认的 silent failure"],
    ["SAC-Opt", "建模回译 + 自动语义对齐", "不执行求解;发现错误 ≠ 能修复,尤难修结构性错误"],
    ["Opt-Verifier(2026)", "双侧验证:结构回译 + 解的 LLM 判读", "LLM 判官 false-clear 率校准研究达 90%;数据丰富实例用 toy 绕过"],
    ["OptArgus(2026)", "幻觉检测与分类(31.1% 幻觉率)", "只检测不修复;无执行级语义审计"],
    ["**本工作**", "**确定性 witness + 预求解闸门 + 多链仲裁 + prompt 进化**", "**witness 规则按族定制,迁移性靠自进化线解决**"],
], 0.55, 1.5, 12.25, 3.4, col_w=[2.2, 4.4, 5.65], size=12.5)
bullets(s, [
    (0, "两轮文献扫描 + 逐条新颖性裁决见 docs/paper/related_work_scan_v0.1.md 与 novelty_audit_v0.1.md", False),
    (0, ("结论:\"确定性、零 LLM、误报实测可控的语义审计\" 与 judge 路线互补,且在其不可靠处接管", GREEN), True),
], y=5.35)

# ---------------------------------------------------------------- S5 核心问题
s = prs.slides.add_slide(BLANK); chrome(s, "核心问题:幻影 —— 执行信号看不见的假成功", "PART 2 · MOTIVATION")
bullets(s, [
    (0, "实测(RetailOpt-190 全量,thinking 开):69 题出解,其中 46 题是幻影,真成功仅 13 题", True),
    (1, ("目标值比对协议会报 32.1%(61/190),真实仅 6.8% —— 高估 4.7 倍;off 臂更极端:报 23%、实际 0%", RED), False),
    (0, "幻影不是随机失误:全部幻影共享同一机制(幻影初始库存),目标值系统性虚低 7%–45%", False),
    (0, "根因:题面欠规约(未声明\"期初库存为零\"),模型系统性占据规约留下的自由度", False),
    (1, "即 specification gaming under underspecification —— 是被诱导的系统性行为,不是噪声", False),
    (0, ("推论:任何只看执行信号的框架(ReLoop 式修复环、结果奖励 RL)结构性看不见这类错误", RED), True),
    (0, "→ 必须有一个与求解行为无关的独立语义审计器(witness),这是全工作的基石", True),
], y=1.5, size=15)

# ---------------------------------------------------------------- S6 E1
s = prs.slides.add_slide(BLANK); chrome(s, "Motivation E1:先剥离\"誊抄错误\"这一测量噪声", "PART 2 · MOTIVATION")
bullets(s, [
    (0, "动机:测裸模型底力,定位大头失败模式(4 个 F1 实例 × thinking 开/关)", False),
    (0, "发现:数据内嵌题面(prompt_full)下 4/4 全部死于数据誊抄 —— 把内嵌 JSON 抄成非法 Python", True),
    (0, "对策:prompt_schema 模式 —— 数据预加载为变量,物理上不可能誊抄;崩溃率 7/8 → 3/8", False),
    (0, ("测量纪律:此后全部实验固定 prompt_schema —— 先把测量噪声清掉,才谈语义错误", GREEN), True),
    (0, "启示:LLM 建模的失败是分层的(誊抄层 / 代码层 / 语义层),测量与修复都必须分层", False),
], y=1.6, size=15)

# ---------------------------------------------------------------- S7 E2 主表
s = prs.slides.add_slide(BLANK); chrome(s, "Motivation E2:witness 重判主表 —— 假成功普遍存在", "PART 2 · MOTIVATION")
table(s, [
    ["模式", "代码可执行", "witness 可行", "目标值一致", "幻影", "真实成功"],
    ["thinking 关", "48 / 190", "0", "0", "43", "**0(0%)**"],
    ["thinking 开", "69 / 190", "15", "15", "46", "**13(6.8%)**"],
], 1.2, 1.6, 10.9, 1.5, col_w=[2.0, 1.9, 1.7, 1.7, 1.5, 2.1], size=13)
bullets(s, [
    (0, "做法:事后用 witness 对全部 190 题的产物重判(与生成时的执行信号无关)", False),
    (0, ("thinking 关:43 个\"看似成功\"全部是幻影,真实成功为 0 —— 执行指标完全失真", RED), True),
    (0, "幻影机制高度一致:全部含\"幻影初始库存\"(规则 C-INIT)—— 见下一页案例走查", False),
    (0, "结论:独立语义审计不是锦上添花,是让测量本身成立的必要仪器", True),
], y=3.5, size=14.5)

# ---------------------------------------------------------------- S8 案例走查
s = prs.slides.add_slide(BLANK); chrome(s, "案例走查:一个幻影是如何产生并被抓到的", "PART 2 · MOTIVATION")
bullets(s, [
    (0, "题目:零售库存,多保质期桶(fresh → aging 逐期老化),题面未声明期初库存", False),
    (0, ("模型犯的错:给第 1 期的非新鲜桶凭空填库存 I[p,l,1,r>0] > 0 —— 免费现货替代采购", RED), True),
    (0, "后果:求解器愉快地给出更低成本(虚低 7%–45%);代码跑通、目标值\"对得上\",执行信号一切正常", False),
    (0, "witness 的 C-INIT 规则:逐 (p,l,r) 核对 I[p,l,1,r]=0,违例即报 → 幻影被抓", True),
    (0, "关键:这一步不需要标准答案,只需要题面语义(\"库存从哪来\"必须守恒)—— 因此可上线、可审计", False),
], x=0.55, y=1.45, w=12.25, h=2.6, size=14)
codeblock(s, [
    "# m1_witness/retailopt.py —— witness 语义审计(零 LLM 的确定性检查)",
    "# 机制由实例数据自动激活,而非按题面名称硬编码:",
    "#   constraints.moq > 0    -> C-MOQ: Q ∈ {0} ∪ [moq, ∞)",
    "#   costs.fixed_order > 0  -> C-FIXED 计入目标;lead_time > 0 -> C-INFLOW ...",
    "for p in P:                      # C-INIT: 期初(第1期)非新鲜桶库存必须为 0",
    "    for r in range(1, sl):",
    "        iv = _get(I, p, l, 1, r)",
    "        if abs(iv) > TOL:",
    '            _violations_append(v, "C-INIT", f"I[{p},{l},1,{r}]={iv} != 0", cap)',
], 0.55, 4.15, 12.25, 2.7, size=12)

# ---------------------------------------------------------------- S9 E3
s = prs.slides.add_slide(BLANK); chrome(s, "Motivation E3:翻转对 —— \"先验覆盖\"真实存在", "PART 2 · MOTIVATION")
bullets(s, [
    (0, "科研命题:模块之间的\"连接\"语义(如库龄、提前期)会被模型固有先验覆盖吗?thinking 会加剧吗?", False),
    (0, "方法:自建受控集翻转对 —— 同一结构两种语义,正确答案必须跟随题面翻转;扩量到每格 48 样本", False),
    (0, ("结果 ① 先验覆盖真实存在,且被先验强度调制:几乎只发生在 storage_time(关 35% / 开 21%),其余连接 ≤ 6%", GREEN), True),
    (0, ("结果 ② \"thinking 加剧先验覆盖\"不成立:on 的题面跟随率全面 ≥ off", GREEN), True),
    (0, "结果 ③ 早期小样本的反向信号(v4)扩量后消失 —— 确认是噪声", False),
    (0, ("意义:现象保住、错误归因拿掉 —— 预注册 + 扩量纪律防止了一个错误结论进入论文", RED), True),
], y=1.55, size=15)

# ---------------------------------------------------------------- S10 E4
s = prs.slides.add_slide(BLANK); chrome(s, "Motivation E4:注入探针 —— 检查器的检出下限", "PART 2 · MOTIVATION")
bullets(s, [
    (0, "做法:往正确建模里注入人为错误(变量 / 约束 / 符号类),看检查器能否发现", False),
    (0, "合成错误 100% 可检出 —— 下限达标;但真实错误显著更隐蔽,且检出依赖 thinking", True),
    (0, "受控缺陷集(13 个 artifact、61 次 LLM 调用):盲审检出 6/7 变异,修复成功 6/7,干净件误报 2/6", False),
    (0, ("结论:注入探针只证明下限;真实分布才是战场 —— 主线全部使用真实 agent 轨迹做评估", RED), True),
], y=1.45, h=2.2, size=14)
picture(s, "docs/figs/controlled_eval.png", 1.2, 3.75, 10.9, 2.9,
        "受控缺陷集:审计 worker 盲审(full-info 对照)与修复 worker 表现")

# ---------------------------------------------------------------- S11 系统总览
s = prs.slides.add_slide(BLANK); chrome(s, "系统总览:三层校验 harness(全程确定性、零额外 LLM)", "PART 3 · 系统")
flow(s, [("① 生成", "LLM + memory 条款\n(P3 语义惯例)"),
         ("② 预求解闸门", "AST 静态探针\nfail-open 放行"),
         ("③ 求解", "SCIP →\nsolution.json"),
         ("④ witness 重判", "18 条语义规则\n逐条核对"),
         ("⑤ 修复环", "≤3 轮\nplain 文本反馈")],
     y=1.7, h=1.9)
bullets(s, [
    (0, "设计原则:所有校验层都是确定性 Python,不调 LLM —— 误报率可实测、可复现、可审计", True),
    (0, "闸门 fail-open:拿不准就放行,对成功样本通过率 84.6%,幻影误报 1.9%、成功样本误报 0%", False),
    (0, "witness 代表出题人意图的语义一侧,与求解行为无关 —— 这是它与 ReLoop 式执行反馈的本质区别", False),
    (0, "并行扩展:三条多样化生成链独立跑,最后确定性仲裁(见 E12,80.5%)", False),
], y=4.05, size=14)

# ---------------------------------------------------------------- S12 witness 代码
s = prs.slides.add_slide(BLANK); chrome(s, "witness 核心代码:机制从实例数据自动激活", "PART 3 · 系统")
codeblock(s, [
    '"""Generalized RetailOpt witness checker (all 190 instances, 38 archetypes).',
    'Mechanisms activate from the instance data (not from the scenario name):',
    '  costs.fixed_order > 0          -> C-FIXED in objective (per (p,l,t) with Q>0)',
    '  constraints.moq > 0            -> C-MOQ: Q in {0} u [moq, inf)',
    '  constraints.pack_size > 1      -> C-PACK: Q multiple of pack_size',
    '  constraints.budget_per_period  -> C-BUDGET: per-period spend cap',
    '  constraints.waste_limit_pct    -> C-WASTELIMIT: sum W <= pct * sum demand',
    '  network.trans_edges non-empty  -> C-XEDGE/C-XNET, transshipment cost in obj',
    '  labor_usage any > 0 ...        -> C-LABOR: usage * handled <= cap',
    '  lead_time[p] > 0 / return_rate[p] > 0 -> folded into C-INFLOW',
    '"""',
    "",
    "for t in range(1, T + 1):",
    "    inflow = fresh_inflow(p, l, t)          # C-INFLOW: 入库恒等式",
    "    lhs = _get(I, p, l, t, sl)",
    "    if abs(lhs - inflow) > TOL * max(1.0, abs(inflow)):",
    '        _violations_append(v, "C-INFLOW", f"I[{p},{l},{t},{sl}]={lhs} != {inflow}")',
], 0.55, 1.45, 12.25, 4.4, size=11.5)
bullets(s, [
    (0, "18 条规则按族定制(当前局限:跨数据集迁移需重建,由自进化线的 checker-authoring 解决)", False),
], y=6.05, size=12.5)

# ---------------------------------------------------------------- S13 闸门
s = prs.slides.add_slide(BLANK); chrome(s, "预求解闸门:求解之前拦截\"注定判死\"的代码", "PART 3 · 系统")
codeblock(s, [
    '"""Deterministic AST probes over generated modeling code (Phase A).',
    'Extracts, from a gen.py source string:',
    '- data_keys: dataset keys the code actually reads',
    '- var_names: solver variable name prefixes from addVar(name=...) calls',
    '- init_signals: heuristic evidence that first-period inventory is pinned',
    "",
    'Each probe maps a witness rule family to required data keys.',
    'A probe FAILS (=> early BLOCK evidence) when a required key is never',
    'referenced anywhere in the source.                            """',
], 0.55, 1.4, 7.2, 3.0, size=11)
bullets(s, [
    (0, "动机:省掉\"注定被 witness 判死\"的无效求解预算", True),
    (0, "规则来自 263 条历史崩溃台账蒸馏,纯 Python,零 LLM", False),
    (0, "离线检出率迭代:73.8% → 91.6% → 93.9% → 97.0%(255/263)", True),
    (0, "误报实测:幻影 1.9%、成功样本 0%(fail-open)", False),
    (0, ("在线对照(190 题):真成功 44.2% → 45.8%;求解调用 −26.1%,墙钟 −16.3%", GREEN), True),
    (0, "残余结构:witness 不可行 75→50(−33%),崩溃 18→37 —— 瓶颈从语义层转移到代码健壮性层(设计预期)", False),
], x=8.0, y=1.4, w=4.9, h=5.4, size=12.5)

# ---------------------------------------------------------------- S14 F14 图
s = prs.slides.add_slide(BLANK); chrome(s, "闸门在线对照:6.8% → 44.2% → 45.8%", "PART 4 · 工程实验")
picture(s, "docs/paper/figs/f14_headline.png", 1.4, 1.5, 10.5, 4.7,
        "F14:零样本 / 事后反馈环(A 臂)/ +预求解闸门(B 臂),RetailOpt-190 × Qwen3.8-27B(on 模式)")

# ---------------------------------------------------------------- S15 分层消融
s = prs.slides.add_slide(BLANK); chrome(s, "分层消融:witness 环 → +闸门 → +crash guard", "PART 4 · 工程实验")
picture(s, "docs/paper/figs/layered_ablation_v0.1.png", 0.5, 1.55, 12.4, 4.6,
        "A(仅 witness 环)44.2% → B(+闸门)45.8% → B'(+guard)47.4%;残余失败结构随层迁移;闸门省 26% 求解调用")

# ---------------------------------------------------------------- S16 memory 递进
s = prs.slides.add_slide(BLANK); chrome(s, "memory 三代递进:P1 → P2 → P3", "PART 4 · 工程实验")
table(s, [
    ["阶段", "机制", "单发 pass@1", "关键观察"],
    ["裸模型(thinking 开)", "—", "6.8%", "基线"],
    ["P1 先验注入", "G0–G8 条款(防崩溃)", "8.4%", "崩溃 64%→7%,但错误转化为幻影(出解题中 90% 幻影)"],
    ["P2 生成端升级", "+建模程序脚手架", "11.1%", "对齐 ReLoop 生成端,成本几乎不变"],
    ["**P3 语义 memory**", "**+7 条语义惯例,族留出**", "**21.6%**", "**近乎翻倍;幻影 −12.6pp;F5 族 5%→40%;全环 57.9%**"],
], 0.55, 1.5, 12.25, 3.1, col_w=[2.5, 3.0, 1.8, 4.95], size=12)
bullets(s, [
    (0, ("缺陷洗白(创新点 D):P1 只修崩溃不修语义,把可见失败洗成不可见幻影 —— 修复越深,测量越不能只看执行信号", RED), True),
    (0, "P3 的 7 条语义惯例(需求恒等、库存平衡、初始库存置零、紧 Big-M 等)蒸馏自反馈轨迹,冻结后注入;留出族不参与蒸馏", False),
], y=4.85, size=13.5)

# ---------------------------------------------------------------- S17 guard
s = prs.slides.add_slide(BLANK); chrome(s, "Crash Guard 在线:环内实时拦截,崩溃残余再减半", "PART 4 · 工程实验")
bullets(s, [
    (0, "动机:把崩溃规则做成环内实时拦截器(guard),修复环里即时命中即时改", False),
    (0, "B' 臂(guard v0.1 + 闸门):47.4%;崩溃残余 37 → 19(−49%);guard 在 43.5% 的细胞中触发", True),
    (0, ("B'' 臂(guard v0.3 + 闸门):54.2%(103/190),配对净翻转 +13;逐轮累计 34.7% → 54.2%", GREEN), True),
    (0, "合体臂(P2 生成端 + guard v0.4 + 闸门 + witness 环):r3 终态 50.5% —— 第三轮被 B'' 反超", False),
    (0, ("关键发现:B'' 与合体臂成功集交集仅 67 题、并集 132 题(69.5%)—— 两条链高度互补", RED), True),
    (0, "→ 直接催生集成仲裁实验(下一页)", False),
], y=1.55, size=15)

# ---------------------------------------------------------------- S18 仲裁图
s = prs.slides.add_slide(BLANK); chrome(s, "三链集成仲裁:80.5%,距 Oracle 上界 1.1pp", "PART 4 · 工程实验")
picture(s, "docs/paper/figs/ensemble_trichain_v0.1.png", 0.55, 1.45, 8.3, 5.2,
        "三条单链(54.2 / 50.5 / 57.9%)→ 双链 68.4% → 三链仲裁 80.5%;虚线为 ReLoop 同模型最佳 28.4%")
codeblock(s, [
    "# scripts/ensemble_arb.py —— 确定性仲裁",
    "# 决策时刻零真值、零 LLM:",
    "cand = [r for r in all_rounds",
    '        if r["witness"] == "feasible"]',
    "# 最小化问题:可行候选中取目标值最小",
    "best = min(cand, key=lambda c: c.obj)",
    "",
    "# 并集上界(Oracle,需真值)= 81.6%",
    "# 仲裁规则 80.5%,差距仅 1.1pp",
], 9.0, 1.7, 3.9, 3.6, size=11)
bullets(s, [(0, "部署视角:80.5% vs 单链 57.9% 的差值,通常远大于 3× 求解成本", False)],
         x=9.0, y=5.5, w=3.9, h=1.2, size=12)

# ---------------------------------------------------------------- S19 预算+负结果
s = prs.slides.add_slide(BLANK); chrome(s, "预算重分配与负结果(如实报告)", "PART 5 · 对照与预算")
bullets(s, [
    (0, "E13 预算重分配(纯离线重放,零新 LLM 调用):", True),
    (1, "假设\"砍掉修复环第 3 轮\"不成立 —— 链 A 第 3 轮边际修复率 29.8% 与第 2 轮 29.9% 持平", False),
    (1, ("结论:预算优化方向是\"先铺满多样性(链数),再加深轮数\",以及用自进化抬高单链起点", GREEN), False),
    (0, "E14 witness 修复反馈增强消融 —— 干净的负结果:", True),
    (1, "enriched 反馈(附规则明细)20.3% vs plain 22.0%,McNemar 检验 9v8,无显著差异", False),
    (1, "决策:主线保持 plain 反馈,不并入增强;负结果同样落盘、推送、进实验清单", False),
    (0, "E15 旁证 —— 成功预测器校准(53 个影子对):预测概率与实际成功率单调一致,用于预算与调度决策", False),
], y=1.55, size=14.5)

# ---------------------------------------------------------------- S20 ReLoop 对照
s = prs.slides.add_slide(BLANK); chrome(s, "外部对照:ReLoop 完整管线移植到同一模型", "PART 5 · 对照与预算")
table(s, [
    ["口径", "ReLoop(同模型移植)", "本工作"],
    ["单发", "R1t(CoT 单次)20.5%", "P3 单发 21.6%"],
    ["≤3 轮修复环", "R2t(CoT + L1 环)28.4%", "**P3 臂全环 57.9%**"],
    ["多链集成", "—", "**三链仲裁 80.5%**"],
], 1.0, 1.5, 11.3, 2.4, col_w=[2.6, 4.3, 4.4], size=13.5)
bullets(s, [
    (0, "严格性:同模型(Qwen3.8-27B)、同数据集(RetailOpt-190)、同求解器(SCIP);ReLoop 从其公开仓库完整移植", True),
    (0, "附带发现:thinking 是准确率的决定性变量 —— 关 3.7% vs 开 28.4%(×7.7)", False),
    (0, "公平性注记:ReLoop 的环含诊断-回滚;我们的比较按轮次对齐口径,全部数字留台账可追溯", False),
], y=4.2, size=13.5)

# ---------------------------------------------------------------- S21 自进化设计
s = prs.slides.add_slide(BLANK); chrome(s, "自进化最小可行版:隔离协议 + 预注册生死判据", "PART 6 · 自进化")
bullets(s, [
    (0, "进化对象:prompt 基因组(memory 条款文本);选择压力:dev40 单发适应度", False),
    (0, "三层切片物理隔离(sha256 落盘):", True),
    (1, "dev40(F1–F4 的 v0+v4 变体,进化可见)/ gapcheck60(v1–v3 变体,过拟合闸门)/ F5–F8 留出族(90 题,只用于最终评测)", False),
    (0, "每代 6 个后代:2 个 LLM 条款草稿(从精英失败记录起草)+ 1 语义块改写 + 2 交叉 + 1 最长条款删除", False),
    (0, ("预注册生死判据(结果出来前写死):", RED), True),
    (1, "(a) 第 3 代冠军 dev40 > 45.0%(同批种子 35.0% + 10pp)→ 显著性门槛", False),
    (1, "(c) 冠军全量 190 中 F5–F8 留出族 ≥ 15.0%(P3 的 20.0% − 5pp)→ 留出族不衰减", False),
    (1, "(b) dev40 vs gapcheck60 落差仅作诊断量;(a)∧(c)→继续,¬(a)→回退手工+集成,(a)∧¬(c)→判过拟合回退", False),
], y=1.45, size=13.5)

# ---------------------------------------------------------------- S22 进化结果
s = prs.slides.add_slide(BLANK); chrome(s, "进化进行中:gen0–gen1 已落账,过拟合警报触发", "PART 6 · 自进化")
picture(s, "docs/figs/evo_gen0123_v0.1.png", 0.55, 1.4, 9.2, 4.6,
        "左:各基因组 dev40 适应度(圈=该代冠军);右:冠军的 dev40 vs gapcheck60 泛化落差")
bullets(s, [
    (0, "gen0:种子 35.0% 夺冠;删任一条款全掉点 → 条款内容本身有贡献", True),
    (0, "噪声标定:同配置两次测量差 10pp(1σ≈7.5pp)→ 判据参照系用同批种子", False),
    (0, ("落差 gen0 +15.0pp → gen1 +21.7pp(恶化)→ gen2 +4.2pp → gen3 +7.5pp", RED), True),
    (1, "选择压力一度加剧 dev 过拟合(gen1),gen2/3 回落但非 dev40 突破", False),
    (0, ("判据 (a) 结果:gen3 冠军 32.5% < 45% 门槛 —— 不成立", RED), True),
    (1, "三代冠军 35.0→35.0→32.5→32.5%,LLM 变异无噪声外增益", False),
    (0, "按预注册规则回退:手工 P3 + 三链仲裁(80.5%)为部署主线", True),
    (1, "冠军全量 190 评测(判据 c 留出族检查)进行中,结果落档后更新", False),
], x=9.9, y=1.5, w=3.1, h=5.2, size=11.5)

# ---------------------------------------------------------------- S23 创新点裁决
s = prs.slides.add_slide(BLANK); chrome(s, "创新点逐条裁决(两轮文献扫描后)", "PART 6 · 科研命题")
table(s, [
    ["候选贡献", "裁决", "一句话依据"],
    ["A 幻影现象普遍存在", "仅动机", "OptArgus 31.1%、Falsification 27.6%、ReLoop 已命名 silent failure"],
    ["B 机制归因(specification gaming)", "偏弱", "通用层面已有;我们是 OR 域首个逐实例机制量化"],
    ["C witness 确定性语义审计", "拥挤·有差异化", "vs Opt-Verifier 的 LLM 判官:false-clear 90%;我们误报 1.9%/0% 实测可控"],
    ["**D 缺陷洗白的纵向量化**", "**空位 ★**", "**修复把可见失败洗成幻影;自然轨迹上未见度量者**"],
    ["**E 选择压力放大不可见缺陷**", "**空位 ★**", "**进化落差 15→21.7pp 是域内首个实证**"],
    ["F 双层留出 + 预注册判据", "空位", "成套测量纪律,与 D/E 咬合成故事闭环"],
    ["G 多样性仲裁 80.5%(距 Oracle 1.1pp)", "工程亮点", "best-of-n + verifier 在通用层面拥挤"],
    ["H/I 连接泛化 + 反例监督训练", "空位 · 主战场", "预注册 RQ1/RQ2,科研线下一阶段"],
], 0.55, 1.45, 12.25, 4.9, col_w=[4.1, 2.1, 6.05], size=11)

# ---------------------------------------------------------------- S24 总览+下一步
s = prs.slides.add_slide(BLANK); chrome(s, "数字总览与下一步")
table(s, [
    ["配置", "口径", "真实成功"],
    ["裸模型(thinking 开)", "单发", "6.8%"],
    ["P3 语义 memory", "单发", "**21.6%**"],
    ["ReLoop 同模型 R1t / R2t", "单发 / ≤3 轮", "20.5% / 28.4%"],
    ["B''(guard v0.3 + 闸门)", "全环 ≤3 轮", "54.2%"],
    ["P3 臂", "全环 ≤3 轮", "57.9%"],
    ["**三链仲裁**", "**离线重放**", "**80.5%(Oracle 81.6%)**"],
], 0.55, 1.45, 6.4, 4.2, col_w=[2.9, 1.8, 1.7], size=12)
bullets(s, [
    (0, "权属:RetailOpt-190 为 ReLoop 团队公开基准;全部对比同模型同数据集同求解器", True),
    (0, "下一步:", True),
    (1, "自进化判据已裁决:回退手工 P3 + 三链仲裁(见进化结果页);教训沉淀为论文证据(选择压力放大不可见缺陷)", False),
    (1, "checker-authoring agent:让 witness 规则自动蒸馏,解决跨数据集迁移", False),
    (1, "IndustryOR 零适配迁移预实验(检验非参数进化的可迁移性)", False),
    (1, "反例监督训练(预注册 RQ2):把 witness 判出的执行反例灌进训练", False),
    (0, "全部材料:docs/paper/(24 份专项文档)+ runs/ 原始台账,逐数字可追溯", False),
], x=7.3, y=1.45, w=5.6, h=5.6, size=12.5)

OUT.parent.mkdir(parents=True, exist_ok=True)
prs.save(OUT)
print(f"wrote {OUT} ({PAGE[0]} content slides)")
