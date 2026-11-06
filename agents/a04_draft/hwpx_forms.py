"""회사 권장양식 한글(hwpx) 서식에 보고서 내용을 채운다.
양식 파일 속 견본 문단(제목 표, 날짜줄, ◈ 요약 상자, 중제목·대제목, □·ㅇ·-·*, 사이 띄움 문단, 표, 목차, 보도자료 머리·담당 표)을
서식째 복제해 글자만 바꾸므로, 글꼴·크기·색 띠·들여쓰기·간격이 양식 그대로 나온다.
양식 안의 작성 안내 상자와 견본 문구, 보도자료 양식의 실제 담당자 이름·연락처는 넣지 않는다.
서식 파일은 프로젝트 맨 위 templates/company/ 에 둔다(회사 양식이므로 공개 저장소에는 올리지 않음)."""
import re
import zipfile
from io import BytesIO
from itertools import count
from pathlib import Path
from xml.sax.saxutils import escape

from agents.a04_draft import lh_style

DIR = Path(__file__).resolve().parents[2] / 'templates' / 'company'
FILES = {  # 양식 이름 → 파일 이름 앞부분
    '짧은 보고서(푸른색)': '3-1.', '짧은 보고서(붉은색)': '3-2.', '표지 있는 보고서(푸른색)': '4-1.',
    '표지 있는 보고서(붉은색)': '4-2.', '1쪽 보고서': '5.', '보도자료': '7.',
}
S = re.S


def template_path(form):
    pre = FILES.get(form)
    if not pre or not DIR.exists():
        return None
    return next((p for p in sorted(DIR.glob('*.hwpx')) if p.name.startswith(pre)), None)


def available(form):
    return template_path(form) is not None


# ---------- 문단 다루기 ----------
def _spans(sec):
    out, depth, start = [], 0, None
    for m in re.finditer(r'<hp:p [^>]*>|</hp:p>', sec):
        if m.group().startswith('</'):
            depth -= 1
            if depth == 0:
                out.append((start, m.end()))
        else:
            if depth == 0:
                start = m.start()
            depth += 1
    return out


def _text(seg):
    return ''.join(re.sub(r'<[^>]+>', '', t) for t in re.findall(r'<hp:t>(.*?)</hp:t>', seg, S))


BLANK = '\x00'  # 비운 칸 표시(정리 후 지움)


def _fill(seg, texts):
    """글자 칸(<hp:t>…</hp:t>)을 순서대로 바꾼다. 남는 칸은 비운다(빈 <hp:t/>는 그대로).
    표 칸 안에서 안내 문구만 있던 줄이 통째로 비면 그 줄(문단)을 지운다(칸에 다른 줄이 남을 때만)."""
    it = iter(texts)

    def rep(m):
        v = next(it, '')
        return f'<hp:t>{escape(v) if v else BLANK}</hp:t>'
    seg = re.sub(r'<hp:t>.*?</hp:t>', rep, seg, flags=S)

    def tidy(m):
        body = m.group(2)
        ps = re.findall(r'<hp:p [^>]*>(?:(?!<hp:p ).)*?</hp:p>', body, S)
        blank = [p for p in ps if '<hp:t>' in p and not re.sub(BLANK, '', ''.join(re.findall(r'<hp:t>(.*?)</hp:t>', p, S))).strip()
                 and BLANK in p]
        if blank and len(blank) < len(ps):
            for p in blank:
                body = body.replace(p, '', 1)
        return m.group(1) + body + m.group(3)
    seg = re.sub(r'(<hp:subList [^>]*>)(.*?)(</hp:subList>)', tidy, seg, flags=S)
    return seg.replace(BLANK, '')


def _clean(seg):
    return re.sub(r'<hp:linesegarray>.*?</hp:linesegarray>', '', seg, flags=S)  # 줄배치는 한글이 다시 계산


def _page_break(seg, on):
    return re.sub(r'^(<hp:p [^>]*?)pageBreak="[01]"', lambda m: m.group(1) + f'pageBreak="{1 if on else 0}"', seg, count=1)


class Form:
    def __init__(self, path):
        with zipfile.ZipFile(path) as z:
            self.infos = z.infolist()
            self.files = {i.filename: z.read(i.filename) for i in self.infos}
        self.sec = self.files['Contents/section0.xml'].decode('utf-8')
        sp = _spans(self.sec)
        self.head, self.tail = self.sec[:sp[0][0]], self.sec[sp[-1][1]:]
        self.segs = [_clean(self.sec[a:b]) for a, b in sp]
        self.texts = [_text(s) for s in self.segs]
        self.header = self.files['Contents/header.xml'].decode('utf-8')
        self._clones = {}

    def find(self, pred, start=0):
        return next((i for i in range(start, len(self.segs)) if pred(self.texts[i].strip())), None)

    def _clone(self, tag, group, src_id, edit, variant=''):
        """header.xml의 글자·문단 모양(src_id)을 복제·수정해 새 번호로 추가하고 그 번호를 돌려준다."""
        key = (tag, src_id, edit.__name__, variant)
        if key in self._clones:
            return self._clones[key]
        m = re.search(rf'<hh:{tag} id="{src_id}"[^>]*?(?:/>|>.*?</hh:{tag}>)', self.header, S)
        if not m:
            return src_id
        cnt = re.search(rf'<hh:{group} itemCnt="(\d+)"', self.header)
        # 글자·문단 모양은 0번부터, 테두리는 1번부터 매긴다 → 있는 번호 중 가장 큰 것 + 1
        new_id = max(int(i) for i in re.findall(rf'<hh:{tag} id="(\d+)"', self.header)) + 1
        xml = edit(re.sub(r'id="\d+"', f'id="{new_id}"', m.group(), count=1))
        self.header = self.header.replace(f'</hh:{group}>', xml + f'</hh:{group}>', 1)
        self.header = self.header.replace(cnt.group(), f'<hh:{group} itemCnt="{int(cnt.group(1)) + 1}"', 1)
        self._clones[key] = str(new_id)
        return str(new_id)

    def tight_char(self, char_id, height=None):
        """표 글자: 자간 -8%, 장평 98%(가이드라인 허용 범위). height를 주면 글자 크기도 바꾼다(1300 = 13pt)."""
        def tight(x):
            if height:
                x = re.sub(r'(<hh:charPr [^>]*?height=")\d+', rf'\g<1>{height}', x, count=1)
            x = re.sub(r'(<hh:spacing )[^/]*/>', r'\1hangul="-8" latin="-8" hanja="-8" japanese="-8" other="-8" symbol="-8" user="-8"/>', x)
            return re.sub(r'(<hh:ratio )[^/]*/>', r'\1hangul="98" latin="98" hanja="98" japanese="98" other="98" symbol="98" user="98"/>', x)
        return self._clone('charPr', 'charProperties', char_id, tight, height or '')

    def border(self, fill_id, sides):
        """표 칸 테두리: sides = {'left': ('SOLID', '0.12 mm'), ...}. 선 색은 모두 검은색, 바탕색은 그대로."""
        def lines(x):
            for s, (kind, width) in sides.items():
                x = re.sub(rf'<hh:{s}Border [^/]*/>', f'<hh:{s}Border type="{kind}" width="{width}" color="#000000"/>', x)
            return re.sub(r'(<hh:diagonal [^/]*color=")#\w+', r'\1#000000', x)
        variant = ','.join(f'{s}={k}/{w}' for s, (k, w) in sorted(sides.items()))
        return self._clone('borderFill', 'borderFills', fill_id, lines, variant)

    def small_right(self, para_id):
        """숫자 칸 문단: 오른쪽 정렬은 두고 오른쪽 여백만 작게(양식은 넓은 칸 기준 3,500 안팎)."""
        def small(x):
            vals = [int(v) for v in re.findall(r'<hc:right value="(-?\d+)"', x)]
            base = min(vals) if vals else 0
            return re.sub(r'<hc:right value="(-?\d+)"',
                          lambda m: f'<hc:right value="{int(int(m.group(1)) * RIGHT_GAP / base) if base else 0}"', x)
        return self._clone('paraPr', 'paraProperties', para_id, small)

    def save(self, body_segs, title, preview):
        ids = count(1000000)
        body = ''.join(re.sub(r'<hp:tbl id="\d+"', lambda m: f'<hp:tbl id="{next(ids)}"', s) for s in body_segs)
        files = dict(self.files)
        files['Contents/section0.xml'] = (self.head + body + self.tail).encode('utf-8')
        files['Contents/header.xml'] = self.header.encode('utf-8')
        if 'Preview/PrvText.txt' in files:
            files['Preview/PrvText.txt'] = preview[:1000].encode('utf-8')
        if 'Contents/content.hpf' in files:
            hpf = files['Contents/content.hpf'].decode('utf-8')
            files['Contents/content.hpf'] = re.sub(r'<opf:title>.*?</opf:title>|<opf:title/>',
                                                   f'<opf:title>{escape(title)}</opf:title>', hpf, count=1).encode('utf-8')
        buf = BytesIO()
        with zipfile.ZipFile(buf, 'w') as z:
            for i in self.infos:  # mimetype은 처음·무압축 그대로
                z.writestr(i, files[i.filename], compress_type=i.compress_type)
        return buf.getvalue()


# ---------- 표 ----------
FONT = 1300      # 표 글자 13pt = 1300 HWPUNIT(한글 한 글자 폭에 가깝다)
TIGHT = 0.90     # 장평 98% + 자간 -8% → 글자 폭 약 90%
PAD = 1020 + 400  # 칸 안 여백(양식: 좌우 각 510) + 여유
SLACK = 150      # 칸마다 남겨 둘 여유(글자 폭 어림 오차)
RIGHT_GAP = 300  # 숫자 칸 오른쪽 여백(양식 3,500 → 300)
FONT_STEPS = (1300, 1250, 1200, 1150, 1100)  # 본문 줄이 한 줄에 안 들어가면 표 글자를 0.5pt씩(11pt까지) 줄인다
SLIM_MARGIN = 283  # 그래도 넘치면 칸 안 좌우 여백을 1mm로


def _glyphs(s, font=FONT):
    """글자 폭 어림(HWPUNIT, 자간 줄인 표 글자 기준): 한글·한자 1em, 숫자·영문 0.6em, 기호·공백 0.4em."""
    w = 0
    for ch in s:
        if '가' <= ch <= '힣' or 'ㄱ' <= ch <= 'ㆎ' or '一' <= ch <= '鿿' or ch in '㎡※□ㅇ◈':
            w += font
        elif ch.isalnum():
            w += font * 0.6
        else:
            w += font * 0.4
    return int(w * TIGHT)


def _is_num(v):
    return bool(re.fullmatch(r'[\d,.]+', v))


def _two_lines(s, font):
    """제목줄 칸: 두 줄로 나눴을 때 긴 쪽 폭(가장 고르게 나눈 자리 기준)."""
    return min(max(_glyphs(s[:k], font), _glyphs(s[k:], font)) for k in range(1, len(s) + 1)) if s else 0


def _one_line_widths(data, n, total, pad, font):
    """본문 줄은 모든 칸이 한 줄, 제목줄은 두 줄까지 들어가는 열 너비. 표 폭 안에 안 들어가면 None."""
    body = data[1:] or data
    want = [max(max(_glyphs(r[j], font) + pad + (RIGHT_GAP if _is_num(r[j]) else 0) for r in body if j < len(r)),
                _two_lines(data[0][j], font) + pad) for j in range(n)]
    if sum(want) > total:
        return None
    extra = total - sum(want)  # 남는 폭은 필요한 폭 비율대로 나눈다
    widths = [w + extra * w // sum(want) for w in want]
    widths[-1] += total - sum(widths)
    return widths


def _col_widths(data, n, total, pad=PAD):
    """(글자를 최대한 줄여도 한 줄이 안 될 때만 쓰는 예비 계산) 긴 글자 칸이 두 줄이 되도록 나눈다."""
    """숫자·짧은 칸은 한 줄에 들어갈 만큼 먼저 주고, 남는 폭을 긴 글자 칸(사업명·추진상태 등)이 나눈다."""
    def cell_need(v):
        return _glyphs(v) + pad + (RIGHT_GAP if re.fullmatch(r'[\d,.]+', v) else 0)
    need = [max(cell_need(r[j]) if j < len(r) else 0 for r in data) for j in range(n)]
    body = data[1:] or data
    # 고정 칸: 숫자·날짜·짧은 말만 있는 칸(줄바꿈 금지). 나머지는 긴 글자 칸(필요하면 두 줄)
    fixed = [all(re.fullmatch(r'[\d,.\-–]*', r[j] if j < len(r) else '') for r in body) or need[j] <= FONT * 5.5 * TIGHT + pad
             for j in range(n)]
    widths = need[:]
    if sum(need) > total:
        flex = [j for j in range(n) if not fixed[j]]
        room = total - sum(need[j] for j in range(n) if fixed[j])
        floor = FONT * 3 * TIGHT + pad  # 긴 글자 칸도 한글 3자는 한 줄에
        if flex and room >= floor * len(flex):
            want = sum(need[j] for j in flex)
            alloc = {j: room * need[j] / want for j in flex}
            for _ in range(len(flex)):  # 바닥보다 작은 칸은 바닥으로 올리고 나머지에서 덜어낸다
                low = [j for j in flex if alloc[j] < floor]
                if not low:
                    break
                for j in low:
                    alloc[j] = floor
                rest = [j for j in flex if alloc[j] > floor]
                excess = sum(alloc.values()) - room
                spare = sum(alloc[j] - floor for j in rest)
                for j in rest:
                    alloc[j] -= excess * (alloc[j] - floor) / spare if spare else 0
            for j in flex:
                widths[j] = int(alloc[j])
        else:  # 고정 칸만으로도 넘치면 전체를 같은 비율로 줄임
            widths = [int(w * total / sum(need)) for w in need]
    else:  # 남는 폭은 긴 글자 칸 쪽에 더 준다
        extra = total - sum(need)
        grow = [j for j in range(n) if not fixed[j]] or list(range(n))
        for j in grow:
            widths[j] += extra // len(grow)
    widths[-1] += total - sum(widths)
    return widths

def _cell_lines(ri, j, nrows, ncols):
    """양식 표 테두리(가이드라인 견본 기준): 양옆 바깥선 없음, 위·아래 바깥선 0.25mm,
    제목줄 아래만 이중선, 나머지 안쪽 선 0.12mm. 견본의 빨간 굵은 선(설명용 표시)은 따르지 않는다."""
    thin, thick, double = ('SOLID', '0.12 mm'), ('SOLID', '0.25 mm'), ('DOUBLE_SLIM', '0.5 mm')
    return {'left': ('NONE', '0.12 mm') if j == 0 else thin,
            'right': ('NONE', '0.12 mm') if j == ncols - 1 else thin,
            'top': thick if ri == 0 else (double if ri == 1 else thin),
            'bottom': double if ri == 0 else (thick if ri == nrows - 1 else thin)}


def _table(proto, cols, rows, F):
    """견본 표(머리줄·본문·마지막 줄, 첫·가운데·끝 칸의 테두리 서식)를 복제해 열·행 수에 맞춘 표를 만든다.
    표 글자는 자간을 줄인 글자 모양으로, 숫자 칸은 오른쪽 여백을 줄인 문단 모양으로 바꾼다(숫자가 끊기지 않게)."""
    trs = re.findall(r'<hp:tr>.*?</hp:tr>', proto, S)
    cells = [re.findall(r'<hp:tc .*?</hp:tc>', tr, S) for tr in trs]
    head = proto[:proto.index('<hp:tr>')]
    tail = proto[proto.rindex('</hp:tr>') + len('</hp:tr>'):]
    total = int(re.search(r'<hp:sz width="(\d+)"', head).group(1))
    data = [list(map(str, cols))] + [list(map(str, r)) for r in rows]
    n = len(cols)
    mg = re.search(r'<hp:inMargin left="(\d+)" right="(\d+)"', head) or \
        re.search(r'<hp:cellMargin left="(\d+)" right="(\d+)"', cells[1][0])
    side = (int(mg.group(1)) + int(mg.group(2))) // 2 if mg else 510
    # 본문 줄 한 줄 맞추기: 양식 그대로 → 글자 0.5pt씩 줄이기 → 칸 안 여백 1mm. 그래도 안 되면 긴 글자 칸만 두 줄
    widths, font = None, None
    for margin in dict.fromkeys((side, min(side, SLIM_MARGIN))):
        for f in FONT_STEPS:
            widths = _one_line_widths(data, n, total, 2 * margin + SLACK, f)
            if widths:
                font = f
                break
        if widths:
            break
    if not widths:
        margin = side
        widths = _col_widths(data, n, total, 2 * side + SLACK)
    if margin != side:
        head = re.sub(r'(<hp:inMargin left=")\d+(" right=")\d+', rf'\g<1>{margin}\g<2>{margin}', head, count=1)
    size = font if font and font != FONT else None
    text_para = re.search(r'paraPrIDRef="(\d+)"', cells[1][1]).group(1)   # 가운데 정렬(글자 칸)
    num_para = F.small_right(re.search(r'paraPrIDRef="(\d+)"', cells[1][-1]).group(1))  # 오른쪽 정렬(숫자 칸)
    out_rows, heights = [], []
    for ri, row in enumerate(data):
        src = cells[0] if ri == 0 else (cells[-1] if ri == len(data) - 1 else cells[1])
        tcs = []
        for j in range(n):
            v = row[j] if j < len(row) else ''
            numeric = ri > 0 and bool(re.fullmatch(r'[\d,.]+', v))
            c = src[0] if j == 0 else (src[-1] if j == n - 1 else (src[2] if numeric and len(src) > 2 else src[1]))
            if ri > 0 and j > 0:
                c = re.sub(r'(<hp:p [^>]*?)paraPrIDRef="\d+"', lambda m: m.group(1) + f'paraPrIDRef="{num_para if numeric else text_para}"',
                           c, count=1)
            c = _fill(c, [v])
            c = re.sub(r'charPrIDRef="(\d+)"', lambda m: f'charPrIDRef="{F.tight_char(m.group(1), size)}"', c)
            c = re.sub(r'(<hp:tc [^>]*?borderFillIDRef=")(\d+)',
                       lambda m: m.group(1) + F.border(m.group(2), _cell_lines(ri, j, len(data), n)), c, count=1)
            if margin != side:  # 칸마다 따로 여백을 쓰는 경우까지 맞춘다
                c = re.sub(r'(<hp:cellMargin left=")\d+(" right=")\d+', rf'\g<1>{margin}\g<2>{margin}', c, count=1)
            c = re.sub(r'<hp:cellAddr colAddr="\d+" rowAddr="\d+"/>', f'<hp:cellAddr colAddr="{j}" rowAddr="{ri}"/>', c)
            c = re.sub(r'<hp:cellSz width="\d+"', f'<hp:cellSz width="{widths[j]}"', c)
            tcs.append(c)
        heights.append(int(re.search(r'<hp:cellSz width="\d+" height="(\d+)"', src[0]).group(1)))
        out_rows.append('<hp:tr>' + ''.join(tcs) + '</hp:tr>')
    head = re.sub(r'rowCnt="\d+" colCnt="\d+"', f'rowCnt="{len(data)}" colCnt="{n}"', head, count=1)
    head = re.sub(r'(<hp:sz width="\d+" widthRelTo="\w+" height=")\d+', lambda m: m.group(1) + str(sum(heights)), head, count=1)
    return head + ''.join(out_rows) + tail


# ---------- 양식별 채우기 ----------
def _body_roles(F, start=0):
    """본문 견본: 기호별 문단과 그 앞의 띄움 문단."""
    r = {}
    r['sq'] = F.find(lambda t: t.startswith('□ (') or t.startswith('□ ('), start)
    r['o'] = F.find(lambda t: t.startswith('ㅇ ') and '들여쓰기' in t, start)
    r['dash'] = F.find(lambda t: t.startswith('- ') and '들여쓰기' in t, start)
    r['note'] = F.find(lambda t: t.startswith('* ') and '들여쓰기' in t, start)
    roles = {k: F.segs[i] for k, i in r.items() if i is not None}
    gaps = {k: F.segs[i - 1] for k, i in r.items() if i is not None and not F.texts[i - 1].strip()}
    cap = F.find(lambda t: t.startswith('< 표제목') or t.startswith('&lt; 표제목'), start)
    unit = F.find(lambda t: t.startswith('(단위'), start)
    tbl = F.find(lambda t: t.startswith('구분내용수량금액'), start)
    if None not in (cap, unit, tbl):
        roles.update(cap=F.segs[cap], unit=F.segs[unit], table=F.segs[tbl])
        gaps['table'] = F.segs[tbl + 1] if tbl + 1 < len(F.segs) else ''
    return roles, gaps


def _emit(b, roles, gaps, kind, F=None):
    """양식 블록 하나 → 문단들(앞 띄움 포함)."""
    k = b[0]
    gap = gaps.get(k, '')
    if k == 'sq' and 'sq' in roles:
        if kind == 'press':
            return [gap, _fill(roles['sq'], ['□ ', '', b[2] or b[1] or '', '', '', ''])]
        return [gap, _fill(roles['sq'], ['□ ', f'({b[1]}) ' if b[1] and b[2] else (b[1] or ''), b[2] or ''])]
    if k == 'o' and 'o' in roles:
        return [gap, _fill(roles['o'], [' ㅇ ', '', b[1]] if kind == 'press' else [f' ㅇ {b[1]}'])]
    if k == 'dash':
        src = roles.get('dash') or roles.get('o')
        return [gaps.get('dash', gap), _fill(src, [f'   - {b[1]}', '', ''] if 'dash' not in roles else [f'   - {b[1]}'])]
    if k == 'note' and 'note' in roles:
        return [gap, _fill(roles['note'], [f'    * {b[1]}'] if kind != 'press' else [' ', f'  * {b[1]}', ''])]
    if k == 'table' and 'table' in roles:
        unit_pat = r'\((km|㎡|억원|m|원|천원|백만원|%)\)'  # 열 이름의 (단위)만 단위 줄로 옮긴다
        units = list(dict.fromkeys(u for c in b[2] for u in re.findall(unit_pat, c)))
        return [gaps.get('sq', ''), _fill(roles['cap'], [f'< {b[1]} >']),
                _fill(roles['unit'], [f'(단위 : {", ".join(units)})' if units else '']),
                _table(roles['table'], [re.sub(unit_pat, '', c) for c in b[2]], b[3], F), gaps.get('table', '')]
    return []


def render(styled, form):
    path = template_path(form)
    if not path:
        raise FileNotFoundError(f'{form} 한글 서식 파일이 templates/company/ 에 없습니다.')
    F = Form(path)
    kind = lh_style.FORMS[form][0]
    title = next((b[1] for b in styled if b[0] in ('title', 'cover', 'head1p', 'ptitle')), '보고서')
    out = []
    if kind == 'short':
        i_date = F.find(lambda t: '14pt' in t and '○' in t)
        i_sum = F.find(lambda t: t.startswith('◈'))
        i_mid = F.find(lambda t: t.startswith('1. 중제목'))
        roles, gaps = _body_roles(F, i_mid)
        dl = next(b[1] for b in styled if b[0] == 'dateline')
        out += [_fill(F.segs[0], [title]), _fill(F.segs[i_date], [dl])] + F.segs[i_date + 1:i_sum]
        for b in styled:
            if b[0] == 'summary':
                out.append(_fill(F.segs[i_sum], ['◈ ' + b[1]]))
            elif b[0] == 'mid':
                out += [F.segs[i_mid - 1], _fill(F.segs[i_mid], [f'{b[1]}. {b[2]}'])]
                gaps['sq_after_mid'] = F.segs[i_mid + 1]
            else:
                segs = _emit(b, roles, gaps, kind, F)
                if segs and b[0] == 'sq' and out and out[-1].startswith('<hp:p') and \
                        _text(out[-1]).strip().split('.')[0].isdigit():
                    segs[0] = gaps.get('sq_after_mid', segs[0])
                out += segs
    elif kind == 'cover':
        i_title = F.find(lambda t: t.startswith('제목') or t.startswith('제 목'))
        i_date = F.find(lambda t: t.startswith('0000'), i_title)
        i_dept = F.find(lambda t: t.startswith('○'), i_date)
        i_toc = F.find(lambda t: '대제목1' in t)
        i_big = F.find(lambda t: t.startswith('Ⅰ. 대제목'), i_toc + 1)
        i_sum = F.find(lambda t: t.startswith('◈'), i_big)
        roles, gaps = _body_roles(F, i_big)
        cover = next(b for b in styled if b[0] == 'cover')
        heads = next((b[1] for b in styled if b[0] == 'toc'), [])
        out += F.segs[:i_title] + [_fill(F.segs[i_title], [cover[1]])] + F.segs[i_title + 1:i_date] + \
            [_fill(F.segs[i_date], [cover[2]])] + F.segs[i_date + 1:i_dept] + [_fill(F.segs[i_dept], [cover[3]])] + \
            F.segs[i_dept + 1:i_toc]
        toc = F.segs[i_toc]  # 목차 칸: 첫 항목 문단을 복제해 대제목만 적고(쪽 번호는 비움) 나머지 견본 항목은 지운다
        ps = re.findall(r'<hp:p [^>]*>(?:(?!<hp:p ).)*?</hp:p>', toc, S)
        entry = next(p for p in ps if 'Ⅰ.' in _text(p))
        keep_note = [p for p in ps if _text(p).strip().startswith('※')]
        entries = ''.join(re.sub(r'<hp:t>.*?</hp:t>', f'<hp:t>{escape(f"{lh_style.ROMAN[i]}. {h}")}</hp:t>', entry, count=1, flags=S)
                          for i, h in enumerate(heads))
        first, last = toc.index(ps[0]), toc.rindex(ps[-1]) + len(ps[-1])
        out.append(toc[:first] + entries + ''.join(keep_note) + toc[last:])
        n_big = 0
        for b in styled:
            if b[0] == 'big':
                seg = _fill(F.segs[i_big], [f'{b[1]}. {b[2]}', ''])
                out += ([] if n_big == 0 else [F.segs[i_sum + 1]]) + [_page_break(seg, n_big == 0), F.segs[i_big + 1]]
                n_big += 1
            elif b[0] == 'summary':
                continue
            else:
                out += _emit(b, roles, gaps, kind, F)
            if b[0] == 'big' and n_big == 1:
                sm = next((x for x in styled if x[0] == 'summary'), None)
                if sm:
                    out += [_fill(F.segs[i_sum], ['◈ ' + sm[1]]), F.segs[i_sum + 1]]
    elif kind == 'onepage':
        i_sum = F.find(lambda t: t.startswith('◈'))
        roles, gaps = _body_roles(F, i_sum)
        h = next(b for b in styled if b[0] == 'head1p')
        out.append(_fill(F.segs[0], [' ', h[1], '', '담', '당', '부장', '차장', h[3], h[2]]))
        out += F.segs[1:i_sum]
        for b in styled:
            if b[0] == 'summary':
                out.append(_fill(F.segs[i_sum], ['◈ ' + b[1]]))
            elif b[0] != 'head1p':
                out += _emit(b, roles, gaps, kind, F)
    elif kind == 'press':
        i_head = F.find(lambda t: t == '보도자료')
        i_date = F.find(lambda t: t.startswith('배포'), i_head)
        i_title = F.find(lambda t: 'LH,' in t, i_date)
        i_lead = F.find(lambda t: t.startswith('□') and '한국토지주택공사' in t)
        i_o = F.find(lambda t: t.startswith('ㅇ'), i_lead)
        i_sq = F.find(lambda t: t.startswith('□'), i_lead + 1)
        i_note = F.find(lambda t: t.startswith('*'), i_lead)
        i_contact = F.find(lambda t: t.startswith('담당부서'))
        roles = {'sq': F.segs[i_lead], 'sq2': F.segs[i_sq], 'o': F.segs[i_o], 'note': F.segs[i_note]}
        gaps = {'sq': F.segs[i_sq - 1], 'o': F.segs[i_o - 1], 'note': F.segs[i_note - 1], 'dash': F.segs[i_o - 1]}
        ph = next(b for b in styled if b[0] == 'presshead')
        pt = next(b for b in styled if b[0] == 'ptitle')
        subs = next((b[1] for b in styled if b[0] == 'psub'), []) + ['', '']
        date, _, rest = ph[1].partition(' / ')
        out += [F.segs[i_head], _fill(F.segs[i_date], [' ' * 21, '배포', date + ' ', '/ ', rest]),
                _fill(F.segs[i_title], ['', ' ', pt[1], ' ', ' - ', '', subs[0], '', f' - {subs[1]}'])]
        out += F.segs[i_title + 1:i_lead]
        lead_done = False
        for b in styled:
            k = b[0]
            if k == 'sq' and not lead_done:
                out.append(_fill(roles['sq'], ['□ ', '', b[2], '', '', '']))
                lead_done = True
            elif k == 'sq':
                out += [gaps['sq'], _fill(roles['sq2'], ['□ ' + (b[2] or b[1] or '')])]
            elif k in ('o', 'dash', 'note'):
                out += _emit(b, roles, gaps, kind, F)
            elif k == 'contact':
                out += [F.segs[i_contact - 1],
                        _fill(F.segs[i_contact], ['담당부서', b[1], '책임자', '팀  장 ', '', '', '담당자', '차  장', '', ''])]
    out = [s for s in out if s]
    preview = lh_style.to_text(styled)
    return F.save(out, title, preview)
