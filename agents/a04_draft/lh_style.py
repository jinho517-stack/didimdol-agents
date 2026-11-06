"""회사 보고서 양식(권장양식) 적용: 보고서 블록 → 양식별 화면 미리보기(HTML)·워드(docx).
양식 규칙은 회사 권장양식(짧은 보고서·표지 있는 보고서·1쪽 보고서·보도자료)의 글꼴·기호·간격을 옮겼다(양식 파일 자체는 저장소에 없음).
- 글꼴: 제목·제목류 HY헤드라인M, 본문 휴먼명조 15pt, 참고(*) 중고딕 13pt, 표 중고딕 13pt
- 기호 단계: (중제목) → □ → ㅇ(1칸) → -(3칸) → *(4칸), 행간 □ 8pt · ㅇ 6pt · - 4pt · * 3pt, 줄간격 160%
- 편집용지: 위·아래 10mm(+머리말·꼬리말 10mm), 왼쪽·오른쪽 20mm
회사 로고·슬로건 이미지와 실제 담당자 이름·연락처는 넣지 않는다(빈칸으로 둠)."""
import html
import re
from datetime import datetime
from io import BytesIO

from agents.a04_draft import draft

FORMS = {  # 이름: (종류, 색)
    '짧은 보고서(푸른색)': ('short', 'blue'),
    '짧은 보고서(붉은색)': ('short', 'red'),
    '표지 있는 보고서(푸른색)': ('cover', 'blue'),
    '표지 있는 보고서(붉은색)': ('cover', 'red'),
    '1쪽 보고서': ('onepage', 'blue'),
    '보도자료': ('press', 'blue'),
    '디딤돌 기본': ('basic', 'blue'),
}
FORM_HELP = {
    'short': '제목 띠 → (날짜, 부서) → ◈ 핵심요약 → 1. 중제목 → □ → ㅇ → - (권장양식 3)',
    'cover': '표지(제목 32pt·날짜·부서) → 목차 → Ⅰ. 대제목 → □ → ㅇ → - (권장양식 4, 표지·목차는 쪽수 제외)',
    'onepage': '머리 표(부서 | 제목 | 담당 | 날짜) → ◈ 핵심요약 → □ → ㅇ → - (권장양식 5, 1쪽 분량)',
    'press': '보도자료 머리 → 배포 일시 → LH, 기사제목 → 소제목 → 리드문 → 본문 → 담당부서 (보도자료 양식)',
    'basic': '디딤돌 기본 개조식',
}
COLOR = {'blue': ('0B76C0', '27A4E0'), 'red': ('EE8270', 'E2242B')}  # (제목 위 띠, 아래 띠)
HEAD, BODY, NOTE = 'HY헤드라인M', '휴먼명조', '중고딕'
ROMAN = 'ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ'


def josa(word, pair=('은', '는')):
    """마지막 글자 받침에 따라 은/는. 괄호 안 글자는 무시(예: 누리마루선(광역철도) → 선 → 은)."""
    w = re.sub(r'\([^)]*\)$', '', word.strip())
    c = w[-1] if w else ''
    if '가' <= c <= '힣':
        return pair[0] if (ord(c) - 0xAC00) % 28 else pair[1]
    return pair[1] if c.isalpha() and c.upper() not in 'LMNR' else pair[0]


def lh_date(d=None, short=True):
    """가이드라인 날짜 표기: ’26. 11. 4. / 2026. 11. 4."""
    d = d or datetime.now()
    return f"’{d:%y}. {d.month}. {d.day}." if short else f"{d.year}. {d.month}. {d.day}."


# ---------- 블록 → 양식 블록 ----------
# 양식 블록: ('cover', 제목, 날짜, 부서) ('toc', [대제목]) ('title', 제목) ('head1p', 제목, 부서, 날짜) ('dateline', 문구)
# ('summary', 문구) ('mid', 번호, 제목) ('big', 번호, 제목) ('sq', 핵심어, 본문) ('o', 본문) ('dash', 본문)
# ('note', 본문) ('table', 표 제목, 열, 행) ('pagebreak',)
def restyle(blocks, form):
    kind = FORMS[form][0]
    title = next((b[1] for b in blocks if b[0] == 'title'), '보고서')
    meta = next((b[1] for b in blocks if b[0] == 'meta'), {})
    dept = meta.get('dept') or '○○○○처'
    summary = next((b[1] for b in blocks if b[0] == 'summary'), '')
    heads = [re.sub(r'^□\s*', '', b[1]) for b in blocks if b[0] == 'h']
    out = []
    if kind == 'cover':
        out += [('cover', title, lh_date(short=False).rsplit('.', 2)[0] + '.', dept), ('pagebreak',),
                ('toc', heads), ('pagebreak',)]
    elif kind == 'onepage':
        out.append(('head1p', title, dept, lh_date(short=False)))
    else:
        out += [('title', title), ('dateline', f'({lh_date()}, {dept})')]
    if summary:
        out.append(('summary', summary))
    n = 0
    for b in blocks:
        k = b[0]
        if k == 'h':
            n += 1
            name = re.sub(r'^□\s*', '', b[1])
            if kind == 'cover':
                out.append(('big', ROMAN[n - 1] if n <= len(ROMAN) else str(n), name))
            elif kind == 'onepage':
                out.append(('sq', name, ''))
            else:
                out.append(('mid', str(n), name))
        elif k == 'b':
            if kind == 'onepage':
                out.append(('o', f'({b[1]}) {b[2]}' if b[1] else b[2]))
            else:
                out.append(('sq', b[1], b[2]))
        elif k == 's':
            out.append(('dash', b[1]) if kind == 'onepage' else ('o', b[1]))
        elif k == 'act':
            out.append(('dash', '⇒ ' + re.sub(r'^\(대응방안\)\s*', '(대응방안) ', b[1])))
        elif k == 'note':
            out.append(('note', re.sub(r'^주\)\s*', '', b[1])))
        elif k == 'table':
            out.append(b)
    return out


def press_release(blocks, facts, district, dept, kinds):
    """보도자료 블록: 사업 DB 값으로 기사제목·소제목·리드문·본문을 만든다(문체: ~했다/~이다)."""
    by_fac = {}
    for f in facts:
        by_fac.setdefault(f['facility'], {})[f['item']] = f
    n = len(by_fac)
    costs = [float(f['value']) for f in facts if f['item'] == '사업비' and f['value'] is not None
             and re.fullmatch(r'\d+(\.\d+)?', str(f['value']))]
    total = draft.fmt_value(str(int(sum(costs))), '억원') if costs else ''
    issues = [(fac, m['현안']['value']) for fac, m in by_fac.items() if m.get('현안') and m['현안']['value']]
    plans = [(fac, m['향후계획']['value']) for fac, m in by_fac.items() if m.get('향후계획') and m['향후계획']['value']]
    status = {fac: m['추진상태']['value'] for fac, m in by_fac.items() if m.get('추진상태') and m['추진상태']['value']}
    d = datetime.now()
    out = [('presshead', f"{lh_date(short=False)}({'월화수목금토일'[d.weekday()]}) 09:00 / 즉시 보도 가능합니다."),
           ('ptitle', f'LH, {district} 광역교통 개선사업 {n}건 추진상황 점검'),
           ('psub', [f"{district} 광역교통개선대책 {n}개 사업" + (f", 사업비 {total} 규모" if total else ''),
                     '현안 사업은 관계기관과 협의해 대응방안 마련' if issues else '사업별 추진상황과 향후 일정 공유'])]
    out.append(('sq', None, f"한국토지주택공사(LH)는 {district} 광역교통개선대책 {n}개 사업의 추진상황을 점검했다고 "
                            f"{d.day}일 밝혔다."))
    out.append(('o', '이번 점검은 사업별 최신 계획값과 추진상태를 관계기관 협의 결과까지 반영해 정리하고자 마련됐다.'))
    out.append(('sq', None, '사업별 추진 내용'))
    for fac, m in by_fac.items():
        parts = []
        for item, unit in (('연장', 'km'), ('사업비', '억원'), ('지원액', '억원')):
            if m.get(item) and m[item]['value'] is not None and m[item]['status'] != '미확정(충돌)':
                parts.append(f"{item} {draft.fmt_value(m[item]['value'], unit)}")
        s = f"{fac}{josa(fac)} " + (', '.join(parts) + ' 규모로 ' if parts else '') + \
            (f"현재 '{status[fac]}' 단계이다." if fac in status else '추진 중이다.')
        out.append(('o', s))
    if issues or plans:
        out.append(('sq', None, '현안 및 향후 계획'))
        for fac, t in issues[:3]:
            out.append(('o', f"{fac}: {t}"))
        for fac, t in plans[:3]:
            out.append(('dash', f"{fac} {t}"))
    out.append(('contact', dept))
    return out


# ---------- 화면 미리보기(HTML) ----------
CSS = """<style>
.lh{background:#fff;color:#111;border:1px solid #c9c9c9;padding:30px 34px;max-width:860px;line-height:1.6;
    font-family:'휴먼명조','HCR Batang','Batang',serif;font-size:15px}
.lh .hd{font-family:'HY헤드라인M','Malgun Gothic',sans-serif;font-weight:700}
.lh .ttl{text-align:center;font-size:22px;padding:6px 0;margin-bottom:4px}
.lh .dl{text-align:right;font-size:14px;margin-bottom:12px}
.lh .sum{background:#fffbe6;border-top:1px solid #333;border-bottom:1px solid #333;padding:9px 12px;margin:6px 0 14px}
.lh .mid{font-size:16px;margin:16px 0 4px}.lh .big{font-size:19px;margin:18px 0 6px;border-bottom:2px solid #333;padding-bottom:3px}
.lh .sq{margin:9px 0 0}.lh .o{margin:6px 0 0 14px}.lh .dash{margin:4px 0 0 34px}
.lh .note{margin:3px 0 0 44px;font-family:'중고딕','Malgun Gothic',sans-serif;font-size:13px}
.lh table{border-collapse:collapse;width:100%;font-family:'중고딕','Malgun Gothic',sans-serif;font-size:12.5px;margin:4px 0}
.lh th,.lh td{border:1px solid #888;padding:3px 6px;text-align:center}.lh th{background:#d9d9d9;border-bottom:3px double #333}
.lh td.n{text-align:right}.lh .cap{text-align:center;font-family:'중고딕','Malgun Gothic',sans-serif;font-size:14px;margin-top:10px}
.lh .cover{text-align:center;padding:60px 0 40px;border-bottom:1px dashed #aaa;margin-bottom:20px}
.lh .cover .ct{font-size:30px;padding:14px 0}.lh .cover .cd{font-size:20px;margin-top:40px}.lh .cover .cp{font-size:22px;margin-top:40px}
.lh .toc{border-bottom:1px dashed #aaa;padding-bottom:16px;margin-bottom:16px}.lh .toc h4{text-align:center;letter-spacing:12px}
.lh .h1p{display:grid;grid-template-columns:22% 1fr 26%;border:1px solid #333;margin-bottom:12px}
.lh .h1p div{border-right:1px solid #333;padding:6px;font-size:13px;display:flex;align-items:center;justify-content:center}
.lh .h1p .t{font-size:21px}.lh .h1p div:last-child{border-right:0;flex-direction:column}
.lh .ph{display:grid;grid-template-columns:1fr;border:1px solid #333;text-align:center;font-size:18px;padding:6px;margin-bottom:6px}
.lh .pd{text-align:right;font-size:14px;text-decoration:underline;margin-bottom:12px}
.lh .pt{font-size:25px;text-align:center;margin:8px 0}.lh .ps{font-size:15px;margin:2px 0 0 10px}
.lh .pline{border-bottom:1px solid #333;margin:8px 0 12px}
.lh .ct2{width:100%;margin-top:22px}
</style>"""


def bars(color):
    top, bottom = COLOR[color]
    return f'border-top:6px solid #{top};border-bottom:6px solid #{bottom}'


def to_html(blocks, form):
    kind, color = FORMS[form]
    e = html.escape
    o = []
    for b in blocks:
        k = b[0]
        if k == 'cover':
            o.append(f'<div class="cover"><div class="hd ct" style="{bars(color)}">{e(b[1])}</div>'
                     f'<div class="hd cd">{e(b[2])}</div><div class="hd cp">{e(b[3])}</div></div>')
        elif k == 'toc':
            items = ''.join(f'<div class="hd" style="margin:6px 0">{ROMAN[i] if i < len(ROMAN) else i + 1}. {e(t)}</div>'
                            for i, t in enumerate(b[1]))
            o.append(f'<div class="toc"><h4 class="hd">목 차</h4>{items}'
                     f'<div style="font-size:12px">※ 표지와 목차는 페이지 산정에서 제외</div></div>')
        elif k == 'title':
            o.append(f'<div class="hd ttl" style="{bars(color)}">{e(b[1])}</div>')
        elif k == 'head1p':
            o.append(f'<div class="h1p"><div>{e(b[2])}</div><div class="hd t">{e(b[1])}</div>'
                     f'<div><span>담당 &nbsp;부장 ____ / 차장 ____</span><span>{e(b[3])}</span></div></div>')
        elif k == 'dateline':
            o.append(f'<div class="dl">{e(b[1])}</div>')
        elif k == 'summary':
            o.append(f'<div class="sum">◈ {e(b[1])}</div>')
        elif k == 'mid':
            o.append(f'<div class="hd mid">{e(b[1])}. {e(b[2])}</div>')
        elif k == 'big':
            o.append(f'<div class="hd big">{e(b[1])}. {e(b[2])}</div>')
        elif k == 'sq':
            key = f'<b>({e(b[1])})</b> ' if b[1] and b[2] else (f'<b>{e(b[1])}</b>' if b[1] else '')
            o.append(f'<div class="sq">□ {key}{e(b[2])}</div>')
        elif k == 'o':
            o.append(f'<div class="o">ㅇ {e(b[1])}</div>')
        elif k == 'dash':
            o.append(f'<div class="dash">- {e(b[1])}</div>')
        elif k == 'note':
            o.append(f'<div class="note">* {e(b[1])}</div>')
        elif k == 'table':
            head = ''.join(f'<th>{e(c)}</th>' for c in b[2])
            rows = ''.join('<tr>' + ''.join(f'<td class="{"n" if re.fullmatch(r"[\d,.]+", str(c)) else ""}">{e(c)}</td>'
                                            for c in r) + '</tr>' for r in b[3])
            o.append(f'<div class="cap">&lt; {e(b[1])} &gt;</div><table><tr>{head}</tr>{rows}</table>')
        elif k == 'presshead':
            o.append(f'<div class="ph hd">보도자료</div><div class="pd">배포 &nbsp; {e(b[1])}</div><div class="pline"></div>')
        elif k == 'ptitle':
            o.append(f'<div class="hd pt">{e(b[1])}</div>')
        elif k == 'psub':
            o.append(''.join(f'<div class="hd ps">- {e(s)}</div>' for s in b[1]) + '<div class="pline"></div>')
        elif k == 'contact':
            o.append(f'<table class="ct2"><tr><td>담당부서</td><td>{e(b[1])}</td><td>책임자</td><td>팀장 ______ ( - - )</td></tr>'
                     f'<tr><td></td><td></td><td>담당자</td><td>______ ( - - )</td></tr></table>')
    return CSS + '<div class="lh">' + ''.join(o) + '</div>'


# ---------- 워드(docx) ----------
def to_docx(blocks, form):
    import docx
    from docx.enum.section import WD_SECTION
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Mm, Pt
    kind, color = FORMS[form]
    top_c, bottom_c = COLOR[color]
    d = docx.Document()
    sec = d.sections[0]
    sec.page_height, sec.page_width = Mm(297), Mm(210)
    sec.top_margin = sec.bottom_margin = Mm(20)  # 위·아래 10mm + 머리말·꼬리말 10mm
    sec.left_margin = sec.right_margin = Mm(20)
    sec.header_distance = sec.footer_distance = Mm(10)

    def font(run, name, size, bold=False):
        run.font.name, run.font.size, run.bold = name, Pt(size), bold
        rpr = run._element.get_or_add_rPr()
        rf = rpr.find(qn('w:rFonts'))
        if rf is None:
            rf = OxmlElement('w:rFonts')
            rpr.append(rf)
        for a in ('w:ascii', 'w:hAnsi', 'w:eastAsia'):
            rf.set(qn(a), name)

    def para(text='', name=BODY, size=15, bold=False, align=None, before=0, left=0.0, hanging=0.0, line=1.6):
        p = d.add_paragraph()
        f = p.paragraph_format
        f.space_before, f.space_after, f.line_spacing = Pt(before), Pt(0), line
        if left:
            f.left_indent, f.first_line_indent = Mm(left), Mm(-hanging)
        if align:
            p.alignment = align
        if text:
            font(p.add_run(text), name, size, bold)
        return p

    def border(p, side, sz, col, val='single'):
        ppr = p._p.get_or_add_pPr()
        bd = ppr.find(qn('w:pBdr'))
        if bd is None:
            bd = OxmlElement('w:pBdr')
            ppr.append(bd)
        el = OxmlElement(f'w:{side}')
        for a, v in (('w:val', val), ('w:sz', str(sz)), ('w:space', '4'), ('w:color', col)):
            el.set(qn(a), v)
        bd.append(el)

    def shade(el_pr, fill):
        sh = OxmlElement('w:shd')
        for a, v in (('w:val', 'clear'), ('w:color', 'auto'), ('w:fill', fill)):
            sh.set(qn(a), v)
        el_pr.append(sh)

    def cell_text(cell, text, size=13, bold=False, name=NOTE, align=WD_ALIGN_PARAGRAPH.CENTER):
        p = cell.paragraphs[0]
        p.alignment = align
        p.paragraph_format.line_spacing = 1.3
        font(p.add_run(text), name, size, bold)

    for b in blocks:
        k = b[0]
        if k == 'pagebreak':
            d.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
        elif k == 'cover':
            for _ in range(8):
                para(size=15)
            p = para(b[1], HEAD, 32, align=WD_ALIGN_PARAGRAPH.CENTER, line=1.3)
            border(p, 'top', 36, top_c), border(p, 'bottom', 36, bottom_c)
            for _ in range(6):
                para(size=15)
            para(b[2], HEAD, 20, align=WD_ALIGN_PARAGRAPH.CENTER)
            for _ in range(7):
                para(size=15)
            para(b[3], HEAD, 24, align=WD_ALIGN_PARAGRAPH.CENTER)
        elif k == 'toc':
            para('목     차', HEAD, 24, align=WD_ALIGN_PARAGRAPH.CENTER, before=20)
            for i, t in enumerate(b[1]):
                para(f'{ROMAN[i] if i < len(ROMAN) else i + 1}. {t}', HEAD, 20, before=10)
            para('※ 표지와 목차는 페이지 산정에서 제외', NOTE, 12, before=16)
        elif k == 'title':
            p = para(b[1], HEAD, 20, align=WD_ALIGN_PARAGRAPH.CENTER, line=1.3)
            border(p, 'top', 36, top_c), border(p, 'bottom', 36, bottom_c)
        elif k == 'head1p':
            t = d.add_table(rows=1, cols=3)
            t.style = 'Table Grid'
            t.alignment = WD_TABLE_ALIGNMENT.CENTER
            cell_text(t.cell(0, 0), b[2], 13)
            cell_text(t.cell(0, 1), b[1], 20, name=HEAD)
            cell_text(t.cell(0, 2), '담당  부장 ____\n         차장 ____', 11)
            t.cell(0, 2).add_paragraph().add_run(b[3]).font.size = Pt(11)
            for c, w in zip(t.rows[0].cells, (Mm(35), Mm(100), Mm(35))):
                c.width = w
        elif k == 'dateline':
            para(b[1], BODY, 14, align=WD_ALIGN_PARAGRAPH.RIGHT, before=2)
        elif k == 'summary':
            p = para('◈ ' + b[1], BODY, 15, before=8, left=5, hanging=5)
            border(p, 'top', 6, '333333'), border(p, 'bottom', 6, '333333')
            shade(p._p.get_or_add_pPr(), 'FFFBE6')
        elif k == 'mid':
            para(f'{b[1]}. {b[2]}', HEAD, 15, before=14)
        elif k == 'big':
            p = para(f'{b[1]}. {b[2]}', HEAD, 18, before=16)
            border(p, 'bottom', 12, '333333')
        elif k == 'sq':
            p = para(before=8, left=5, hanging=5)
            font(p.add_run('□ '), BODY, 15)
            if b[1]:
                font(p.add_run(f'({b[1]}) ' if b[2] else b[1]), BODY, 15, bold=True)
            if b[2]:
                font(p.add_run(b[2]), BODY, 15)
        elif k == 'o':
            para('ㅇ ' + b[1], BODY, 15, before=6, left=8.5, hanging=5)
        elif k == 'dash':
            para('- ' + b[1], BODY, 15, before=4, left=14, hanging=4)
        elif k == 'note':
            para('* ' + b[1], NOTE, 13, before=3, left=17, hanging=3)
        elif k == 'table':
            para(f'< {b[1]} >', NOTE, 14, align=WD_ALIGN_PARAGRAPH.CENTER, before=8)
            t = d.add_table(rows=1, cols=len(b[2]))
            t.style = 'Table Grid'
            t.alignment = WD_TABLE_ALIGNMENT.CENTER
            for i, c in enumerate(b[2]):
                cell = t.rows[0].cells[i]
                shade(cell._tc.get_or_add_tcPr(), 'D9D9D9')
                cell_text(cell, c, 12, bold=True)
                tcb = OxmlElement('w:tcBorders')  # 제목줄 하단 이중실선
                bt = OxmlElement('w:bottom')
                for a, v in (('w:val', 'double'), ('w:sz', '6'), ('w:color', '333333')):
                    bt.set(qn(a), v)
                tcb.append(bt)
                cell._tc.get_or_add_tcPr().append(tcb)
            for r in b[3]:
                cells = t.add_row().cells
                for i, v in enumerate(r):
                    num = re.fullmatch(r'[\d,.]+', str(v))
                    cell_text(cells[i], str(v), 12, align=WD_ALIGN_PARAGRAPH.RIGHT if num else WD_ALIGN_PARAGRAPH.CENTER)
        elif k == 'presshead':
            t = d.add_table(rows=1, cols=1)
            t.style = 'Table Grid'
            cell_text(t.cell(0, 0), '보도자료', 18, name=HEAD)
            p = para(f'배포   {b[1]}', BODY, 13, align=WD_ALIGN_PARAGRAPH.RIGHT, before=6)
            border(p, 'bottom', 6, '333333')
        elif k == 'ptitle':
            para(b[1], HEAD, 25, align=WD_ALIGN_PARAGRAPH.CENTER, before=10, line=1.3)
        elif k == 'psub':
            for i, s in enumerate(b[1]):
                p = para('- ' + s, HEAD, 14, before=2, left=4, hanging=4)
                if i == len(b[1]) - 1:
                    border(p, 'bottom', 6, '333333')
        elif k == 'contact':
            para(size=10, before=10)
            t = d.add_table(rows=2, cols=4)
            t.style = 'Table Grid'
            for (r, c), v in {(0, 0): '담당부서', (0, 1): b[1], (0, 2): '책임자', (0, 3): '팀  장  ______ (   -    -    )',
                              (1, 2): '담당자', (1, 3): '______ (   -    -    )'}.items():
                cell_text(t.cell(r, c), v, 12, name=BODY)
            t.cell(0, 0).merge(t.cell(1, 0))
            t.cell(0, 1).merge(t.cell(1, 1))
    buf = BytesIO()
    d.save(buf)
    return buf.getvalue()


def to_basic(styled):
    """양식 블록 → 기본 블록(한글 hwpx 기본 서식 출력용)."""
    out = []
    for b in styled:
        k = b[0]
        if k == 'ptitle':
            out.insert(0, ('title', b[1], '보도자료'))
        elif k == 'presshead':
            out.append(('date', '배포 ' + b[1]))
        elif k == 'psub':
            out += [('s', s) for s in b[1]]
        elif k == 'sq':
            out.append(('b', None, b[2]) if b[2] else ('h', '□ ' + (b[1] or '')))
        elif k in ('o', 'dash'):
            out.append(('s', b[1]))
        elif k == 'contact':
            out.append(('note', f'담당부서: {b[1]} / 책임자: / 담당자:'))
    return out


def to_text(blocks):
    sym = {'sq': '□', 'o': ' ㅇ', 'dash': '   -', 'note': '    *'}
    out = []
    for b in blocks:
        k = b[0]
        if k == 'cover':
            out += [b[1], b[2], b[3]]
        elif k == 'toc':
            out += ['목 차'] + [f'{ROMAN[i]}. {t}' for i, t in enumerate(b[1])]
        elif k in ('title', 'dateline', 'ptitle'):
            out.append(b[1])
        elif k == 'head1p':
            out.append(f'[{b[2]}] {b[1]} [{b[3]}]')
        elif k == 'summary':
            out.append('◈ ' + b[1])
        elif k in ('mid', 'big'):
            out.append(f'{b[1]}. {b[2]}')
        elif k == 'sq':
            out.append('□ ' + (f'({b[1]}) {b[2]}' if b[1] and b[2] else (b[1] or b[2])))
        elif k in sym:
            out.append(f'{sym[k]} {b[1]}')
        elif k == 'table':
            out += [f'< {b[1]} >', ' | '.join(b[2])] + [' | '.join(map(str, r)) for r in b[3]]
        elif k == 'presshead':
            out += ['보도자료', '배포 ' + b[1]]
        elif k == 'psub':
            out += ['- ' + s for s in b[1]]
        elif k == 'contact':
            out.append(f'담당부서 {b[1]} / 책임자 / 담당자')
    return '\n'.join(out)
