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
from agents.a04_draft import skill as SK

DIR = Path(__file__).resolve().parents[2] / 'templates' / 'company'
FILES = {  # 양식 이름 → 파일 이름 앞부분
    '짧은 보고서(푸른색)': '3-1.', '짧은 보고서(붉은색)': '3-2.', '표지 있는 보고서(푸른색)': '4-1.',
    '표지 있는 보고서(붉은색)': '4-2.', '1쪽 보고서': '5.', '보도자료': '7.',
}
S = re.S


def template_path(form, path=None):
    """양식 파일: 화면에서 올린 파일(path, 그 접속 동안만) → 없으면 templates/company/ 의 파일"""
    if path and Path(path).exists():
        return Path(path)
    pre = FILES.get(form)
    if not pre or not DIR.exists():
        return None
    return next((p for p in sorted(DIR.glob('*.hwpx')) if p.name.startswith(pre)), None)


def available(form, path=None):
    return template_path(form, path) is not None


def guess_form(filename):
    """올린 양식 파일 이름 → 양식 이름(모르면 None). 예: '3-1. (권장양식) 표지가 없는 짧은 보고서(푸른색).hwpx'"""
    n = Path(filename).name
    for form, pre in FILES.items():
        if n.startswith(pre):
            return form
    red = '붉은' in n or '빨간' in n
    if re.search(r'1\s*p|1쪽|한\s*장', n, re.I):
        return '1쪽 보고서'
    if '보도' in n:
        return '보도자료'
    if '표지가 있는' in n or ('표지' in n and '없는' not in n):
        return '표지 있는 보고서(붉은색)' if red else '표지 있는 보고서(푸른색)'
    if '짧은' in n or '표지가 없는' in n:
        return '짧은 보고서(붉은색)' if red else '짧은 보고서(푸른색)'
    return None


def is_hwpx(path):
    """올린 파일이 한글(hwpx) 문서인지(본문 section0.xml이 있는지)"""
    try:
        with zipfile.ZipFile(path) as z:
            return 'Contents/section0.xml' in z.namelist()
    except Exception:
        return False


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

    def align_right(self, para_id):
        """표를 담은 문단을 오른쪽 정렬로(표 본체를 오른쪽 끝에 맞춤, 담당자 원칙)."""
        def right(x):
            return re.sub(r'(<hh:align [^>]*?horizontal=")\w+', r'\g<1>RIGHT', x, count=1)
        return self._clone('paraPr', 'paraProperties', para_id, right)

    def tight_char(self, char_id, height=None, spacing=None):
        """표 글자: 자간·장평은 보고서 작성 스킬 값(기본 0%, 100%). height를 주면 글자 크기도(1300 = 13pt),
        spacing을 주면 그 자간으로(넘치는 칸만 -6%)."""
        sp, ra = SK.get('table', 'char_spacing') if spacing is None else spacing, SK.get('table', 'char_ratio')
        langs = ('hangul', 'latin', 'hanja', 'japanese', 'other', 'symbol', 'user')

        def tight(x):
            if height:
                x = re.sub(r'(<hh:charPr [^>]*?height=")\d+', rf'\g<1>{height}', x, count=1)
            x = re.sub(r'<hh:spacing [^/]*/>', '<hh:spacing ' + ' '.join(f'{k}="{sp}"' for k in langs) + '/>', x)
            return re.sub(r'<hh:ratio [^/]*/>', '<hh:ratio ' + ' '.join(f'{k}="{ra}"' for k in langs) + '/>', x)
        return self._clone('charPr', 'charProperties', char_id, tight, f'{height or ""}/{sp}/{ra}')

    def border(self, fill_id, sides):
        """표 칸 테두리: sides = {'left': ('SOLID', '0.12 mm'), ...}. 선 색은 스킬 값(기본 검은색), 바탕색은 그대로."""
        col = str(SK.get('table', 'line_color')).lstrip('#')

        def lines(x):
            for s, (kind, width) in sides.items():
                x = re.sub(rf'<hh:{s}Border [^/]*/>', f'<hh:{s}Border type="{kind}" width="{width}" color="#{col}"/>', x)
            return re.sub(r'(<hh:diagonal [^/]*color=")#\w+', rf'\g<1>#{col}', x)
        variant = col + ':' + ','.join(f'{s}={k}/{w}' for s, (k, w) in sorted(sides.items()))
        return self._clone('borderFill', 'borderFills', fill_id, lines, variant)

    def font_id(self, lang, face):
        m = re.search(rf'<hh:fontface lang="{lang}" fontCnt="\d+">(.*?)</hh:fontface>', self.header, S)
        f = re.search(rf'<hh:font id="(\d+)" face="{re.escape(face)}"', m.group(1)) if m else None
        return f.group(1) if f else None

    def char(self, src_id, height=None, color=None, face=None, bold=None):
        """글자 모양 복제: 크기(1300 = 13pt)·색·글꼴·굵게"""
        def ed(x):
            if height:
                x = re.sub(r'(<hh:charPr [^>]*?height=")\d+', rf'\g<1>{height}', x, count=1)
            if color:
                x = re.sub(r'(<hh:charPr [^>]*?textColor=")#\w+', rf'\g<1>{color}', x, count=1)
            if face:
                for lang, attr in (('HANGUL', 'hangul'), ('LATIN', 'latin'), ('HANJA', 'hanja'), ('JAPANESE', 'japanese'),
                                   ('OTHER', 'other'), ('SYMBOL', 'symbol'), ('USER', 'user')):
                    fid = self.font_id(lang, face)
                    if fid is not None:
                        x = re.sub(rf'(<hh:fontRef [^>]*?\b{attr}=")\d+', rf'\g<1>{fid}', x, count=1)
            if bold and '<hh:bold/>' not in x:
                x = x.replace('<hh:underline', '<hh:bold/><hh:underline', 1)
            if bold is False:
                x = x.replace('<hh:bold/>', '')
            return x
        return self._clone('charPr', 'charProperties', src_id, ed, f'{height}/{color}/{face}/{bold}')

    def boxfill(self, fill_id, sides, face=None):
        """칸 테두리 + 바탕색(face=None이면 바탕 없음)"""
        def ed(x):
            for s_, (kind, width) in sides.items():
                x = re.sub(rf'<hh:{s_}Border [^/]*/>', f'<hh:{s_}Border type="{kind}" width="{width}" color="#000000"/>', x)
            x = re.sub(r'<hc:fillBrush>.*?</hc:fillBrush>', '', x, flags=S)
            if face:
                x = x.replace('</hh:borderFill>', f'<hc:fillBrush><hc:winBrush faceColor="{face}" hatchColor="#FF000000" '
                                                  'alpha="0"/></hc:fillBrush></hh:borderFill>')
            return x
        return self._clone('borderFill', 'borderFills', fill_id, ed, f'box:{sorted(sides.items())}/{face}')

    def align(self, para_id, how='LEFT'):
        def ed(x):
            return re.sub(r'(<hh:align [^>]*?horizontal=")\w+', rf'\g<1>{how}', x, count=1)
        return self._clone('paraPr', 'paraProperties', para_id, ed, how)

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
        # 어절 단위 줄바꿈(담당자 원칙: 단어 중간에서 줄이 바뀌지 않게)
        files['Contents/header.xml'] = keep_word(self.header).encode('utf-8')
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
TIGHT = 1.0      # 장평 100% × 자간 0% (보고서 작성 스킬 v2: 표 자간 줄이지 않음)
TIGHT_LO = 0.94  # 넘치는 칸만 자간 -6%
OVER_SP = -6
ALIGN_RIGHT = True
PAD = 1020 + 400  # 칸 안 여백(양식: 좌우 각 510) + 여유
SLACK = 150      # 칸마다 남겨 둘 여유(글자 폭 어림 오차)
RIGHT_GAP = 300  # 숫자 칸 오른쪽 여백(양식 3,500 → 300)
FONT_STEPS = (1300, 1250, 1200, 1150, 1100)  # 본문 줄이 한 줄에 안 들어가면 표 글자를 0.5pt씩(11pt까지) 줄인다
SLIM_MARGIN = 283  # 그래도 넘치면 칸 안 좌우 여백을 1mm로


def apply_skill():
    """보고서 작성 스킬(SKILL.md settings.table) 값으로 표 글자·여백 기준을 맞춘다. 한글 파일을 만들 때마다 다시 읽는다."""
    global FONT, TIGHT, TIGHT_LO, OVER_SP, FONT_STEPS, SLIM_MARGIN, ALIGN_RIGHT
    t = SK.load()['settings']['table']
    FONT = SK.hwp(t['font_pt'])
    TIGHT = round(t['char_ratio'] / 100 * (1 + t['char_spacing'] / 100), 3)  # 장평 100% × 자간 0% = 1.0
    OVER_SP = max(int(t.get('overflow_spacing', -6)), -6)  # 넘치는 칸만 쓰는 자간(-6을 넘기지 않음)
    TIGHT_LO = round(t['char_ratio'] / 100 * (1 + OVER_SP / 100), 3)
    ALIGN_RIGHT = t.get('align') == 'right'
    FONT_STEPS = SK.font_steps()
    SLIM_MARGIN = int(round(t['slim_margin_mm'] * 283.46))  # 1mm ≈ 283 HWPUNIT


def _glyphs(s, font=None):
    """글자 폭 어림(HWPUNIT, 자간 줄인 표 글자 기준): 한글·한자 1em, 숫자·영문 0.6em, 기호·공백 0.4em."""
    font = font or FONT
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
    """제목줄 칸: 두 줄로 나눴을 때 긴 쪽 폭. 낱말 중간에서는 나누지 않는다(띄어쓰기 자리만, 없으면 한 줄 폭)."""
    if not s:
        return 0
    cuts = [k for k, ch in enumerate(s) if ch == ' ']
    return min([_glyphs(s, font)] + [max(_glyphs(s[:k], font), _glyphs(s[k + 1:], font)) for k in cuts])


def _word_need(v, font=None):
    """칸에서 가장 긴 낱말 폭(어절 단위 줄바꿈이라 이보다 좁으면 낱말이 잘림)"""
    return max((_glyphs(w, font) for w in re.split(r'\s+', v or '') if w), default=0)


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


def _squeeze_widths(data, n, total, pad, font):
    """③ 넘치는 칸만 자간 -6%: 필요한 폭이 큰 열부터 하나씩 좁은 자간으로 바꿔 표 폭에 맞춘다.
    반환: (열 너비, 좁힌 열 번호 집합) 또는 (None, set())"""
    global TIGHT
    body = data[1:] or data

    def need(j, tight):
        global TIGHT
        keep, TIGHT = TIGHT, (TIGHT_LO if tight else TIGHT)
        w = max(max(_glyphs(r[j], font) + pad + (RIGHT_GAP if _is_num(r[j]) else 0) for r in body if j < len(r)),
                _two_lines(data[0][j], font) + pad)
        TIGHT = keep
        return w
    normal = [need(j, False) for j in range(n)]
    tight = [need(j, True) for j in range(n)]
    want, cols = normal[:], set()
    for j in sorted(range(n), key=lambda j: -normal[j]):  # 가장 넓은 열부터
        if sum(want) <= total:
            break
        want[j], _ = tight[j], cols.add(j)
    if sum(want) > total:
        return None, set()
    extra = total - sum(want)
    widths = [w + extra * w // sum(want) for w in want]
    widths[-1] += total - sum(widths)
    return widths, cols


def _col_widths(data, n, total, pad=PAD):
    """(글자를 최대한 줄여도 한 줄이 안 될 때만 쓰는 예비 계산) 긴 글자 칸이 두 줄이 되도록 나눈다."""
    """숫자·짧은 칸은 한 줄에 들어갈 만큼 먼저 주고, 남는 폭을 긴 글자 칸(사업명·추진상태 등)이 나눈다."""
    def cell_need(v):
        return _glyphs(v) + pad + (RIGHT_GAP if re.fullmatch(r'[\d,.]+', v) else 0)
    need = [max(cell_need(r[j]) if j < len(r) else 0 for r in data) for j in range(n)]
    floor_w = [max(_word_need(r[j]) if j < len(r) else 0 for r in data) + pad for j in range(n)]  # 가장 긴 낱말
    body = data[1:] or data
    # 고정 칸: 숫자·날짜·짧은 말만 있는 칸(줄바꿈 금지). 나머지는 긴 글자 칸(필요하면 두 줄)
    fixed = [all(re.fullmatch(r'[\d,.\-–]*', r[j] if j < len(r) else '') for r in body) or need[j] <= FONT * 5.5 * TIGHT + pad
             for j in range(n)]
    widths = need[:]
    if sum(need) > total:
        flex = [j for j in range(n) if not fixed[j]]
        room = total - sum(need[j] for j in range(n) if fixed[j])
        floor = FONT * 3 * TIGHT + pad  # 긴 글자 칸도 한글 3자는 한 줄에
        floor = max([floor] + [floor_w[j] for j in flex])  # 가장 긴 낱말은 한 줄에(낱말 중간 줄바꿈 방지)
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
    t = SK.load()['settings']['table']  # 선 굵기: 보고서 작성 스킬 값
    thin, thick = ('SOLID', f"{t['inner_line_mm']:g} mm"), ('SOLID', f"{t['outer_line_mm']:g} mm")
    double = ('DOUBLE_SLIM', f"{t['head_double_mm']:g} mm")
    return {'left': ('NONE', thin[1]) if j == 0 else thin,
            'right': ('NONE', thin[1]) if j == ncols - 1 else thin,
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
    over = set()  # 자간 -6%로 좁힌 열
    if not widths:  # ③ 11pt·여백 1mm로도 넘치면: 넘치는 열만 자간 -6%로 다시 맞춰 본다
        widths, over = _squeeze_widths(data, n, total, 2 * min(side, SLIM_MARGIN) + SLACK, FONT_STEPS[-1])
        if widths:
            font, margin = FONT_STEPS[-1], min(side, SLIM_MARGIN)
    if not widths:  # ④ 마지막 수단: 긴 글자 칸만 줄바꿈
        margin = side
        widths = _col_widths(data, n, total, 2 * side + SLACK)
    if ALIGN_RIGHT:  # 표 본체 오른쪽 정렬
        head = re.sub(r'(<hp:p [^>]*?paraPrIDRef=")(\d+)', lambda m: m.group(1) + F.align_right(m.group(2)), head, count=1)
    if margin != side:
        head = re.sub(r'(<hp:inMargin left=")\d+(" right=")\d+', rf'\g<1>{margin}\g<2>{margin}', head, count=1)
    size = font if font and font != FONT else None
    text_para = re.search(r'paraPrIDRef="(\d+)"', cells[1][1]).group(1)   # 가운데 정렬(글자 칸)
    num_para = F.small_right(re.search(r'paraPrIDRef="(\d+)"', cells[1][-1]).group(1))  # 오른쪽 정렬(숫자 칸)
    out_rows, heights = [], []
    num_col = [n > 2 and all(_is_num(r[j]) or r[j] in ('-', '–', '') for r in data[1:] if j < len(r)) for j in range(n)]
    lines_est = 0
    for row in data:
        lines_est += max((max(1, -(-(_glyphs(row[j], font) + 2 * margin + SLACK) // max(1, widths[j]))) for j in range(min(n, len(row)))),
                         default=1)
    if lines_est * 5.2 + len(data) * 1.6 > 200:  # 한 쪽보다 긴 표: 글자처럼 취급을 끄고 쪽에서 나뉘게(빈 쪽 방지)
        head = head.replace('treatAsChar="1"', 'treatAsChar="0"', 1)
    for ri, row in enumerate(data):
        src = cells[0] if ri == 0 else (cells[-1] if ri == len(data) - 1 else cells[1])
        tcs = []
        for j in range(n):
            v = row[j] if j < len(row) else ''
            numeric = ri > 0 and num_col[j] and bool(re.fullmatch(r'[\d,.]+', v))
            c = src[0] if j == 0 else (src[-1] if j == n - 1 else (src[2] if numeric and len(src) > 2 else src[1]))
            if ri > 0 and j > 0:
                c = re.sub(r'(<hp:p [^>]*?)paraPrIDRef="\d+"', lambda m: m.group(1) + f'paraPrIDRef="{num_para if numeric else text_para}"',
                           c, count=1)
            c = _fill(c, [v])
            pad = 2 * margin + SLACK + (RIGHT_GAP if numeric else 0)
            squeeze = j in over and (_two_lines(v, font) if ri == 0 else _glyphs(v, font)) + pad > widths[j]  # 이 칸만 넘침
            c = re.sub(r'charPrIDRef="(\d+)"',
                       lambda m: f'charPrIDRef="{F.tight_char(m.group(1), size, OVER_SP if squeeze else None)}"', c)
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
        # 표 뒤 띄움: 견본 표 다음 문단이 빈 줄일 때만 쓴다. 견본의 작성 안내("* 숫자는 우측정렬 …")가 보고서에 들어가지 않게
        nxt = tbl + 1
        gaps['table'] = F.segs[nxt] if nxt < len(F.segs) and not F.texts[nxt].strip() else gaps.get('sq', '')
    return roles, gaps


def keep_word(header):
    """문단 모양 전부: 한글 줄 나눔을 글자 단위(BREAK_WORD) → 어절 단위(KEEP_WORD)로"""
    return header.replace('breakNonLatinWord="BREAK_WORD"', 'breakNonLatinWord="KEEP_WORD"')


def _figure(proto, height_mm, F):
    """도면 넣을 자리: 견본 표의 본문 칸 하나로 빈 상자(네 변 가는 선, 바탕 없음)를 만든다."""
    trs = re.findall(r'<hp:tr>.*?</hp:tr>', proto, S)
    cell = re.findall(r'<hp:tc .*?</hp:tc>', trs[min(1, len(trs) - 1)], S)[0]
    head = proto[:proto.index('<hp:tr>')]
    tail = proto[proto.rindex('</hp:tr>') + len('</hp:tr>'):]
    total = int(re.search(r'<hp:sz width="(\d+)"', head).group(1))
    h = int(height_mm * 283.465)
    thin = ('SOLID', f"{SK.load()['settings']['table']['inner_line_mm']:g} mm")
    c = re.sub(r'<hp:t>.*?</hp:t>', '<hp:t></hp:t>', cell, flags=S)
    c = re.sub(r'(<hp:tc [^>]*?borderFillIDRef=")(\d+)',
               lambda m: m.group(1) + F.border(m.group(2), {'left': thin, 'right': thin, 'top': thin, 'bottom': thin}), c, count=1)
    c = re.sub(r'<hp:cellAddr colAddr="\d+" rowAddr="\d+"/>', '<hp:cellAddr colAddr="0" rowAddr="0"/>', c)
    c = re.sub(r'<hp:cellSpan colSpan="\d+" rowSpan="\d+"/>', '<hp:cellSpan colSpan="1" rowSpan="1"/>', c)
    c = re.sub(r'<hp:cellSz width="\d+" height="\d+"', f'<hp:cellSz width="{total}" height="{h}"', c)
    head = re.sub(r'rowCnt="\d+" colCnt="\d+"', 'rowCnt="1" colCnt="1"', head, count=1)
    head = re.sub(r'(<hp:sz width="\d+" widthRelTo="\w+" height=")\d+', lambda m: m.group(1) + str(h), head, count=1)
    return head + '<hp:tr>' + c + '</hp:tr>' + tail


def _body_para(seg, text, F, lead):
    """본문 꼭지 문단: lead(' ㅇ ', '   - ') + (핵심어) 굵게 + 본문, 괄호 안은 작은 글자(스킬 body.paren_pt)"""
    m = re.search(r'<hp:run charPrIDRef="(\d+)">\s*<hp:t>.*?</hp:t>\s*</hp:run>', seg, S)
    if not m or F is None:
        return _fill(seg, [lead + text])
    cid = m.group(1)
    small = F.char(cid, height=SK.hwp(SK.load()['settings']['body']['paren_pt']))
    runs = [(cid, lead)]
    key = re.match(r'(\((?![\d’\'])[^()]{1,14}\))\s*', text)
    if key:
        runs.append((F.char(cid, bold=True), key.group(1) + ' '))
        text = text[key.end():]
    for part in re.split(r'(\([^()]*\))', text):
        if part:
            runs.append((small if part.startswith('(') and part.endswith(')') else cid, part))
    xml = ''.join(f'<hp:run charPrIDRef="{c}"><hp:t>{escape(t)}</hp:t></hp:run>' for c, t in runs)
    return seg[:m.start()] + xml + seg[m.end():]


ATT_FILL = '#364878'  # 붙임 번호 상자 바탕(담당자 수정본)


def _att_heading(proto, num, label, F, ref_char):
    """붙임 제목: [붙임 N](남색·흰 글자) | 간격 | [제목](흰 바탕) — 수정본 모양, HY헤드라인M 16pt, 선 0.3mm"""
    trs = re.findall(r'<hp:tr>.*?</hp:tr>', proto, S)
    cell = re.findall(r'<hp:tc .*?</hp:tc>', trs[min(1, len(trs) - 1)], S)[0]
    head = proto[:proto.index('<hp:tr>')]
    tail = proto[proto.rindex('</hp:tr>') + len('</hp:tr>'):]
    total = int(re.search(r'<hp:sz width="(\d+)"', head).group(1))
    widths = [5969, 592, total - 5969 - 592]
    h = 2731
    thick, none = ('SOLID', '0.3 mm'), ('NONE', '0.12 mm')
    fill_src = re.search(r'borderFillIDRef="(\d+)"', cell).group(1)
    para = re.search(r'paraPrIDRef="(\d+)"', cell).group(1)
    face = 'HY헤드라인M'
    specs = [(num, F.char(ref_char, height=1600, color='#FFFFFF', face=face, bold=False),
              F.boxfill(fill_src, {'left': thick, 'right': thick, 'top': thick, 'bottom': thick}, ATT_FILL), para),
             ('', ref_char, F.boxfill(fill_src, {'left': thick, 'right': thick, 'top': none, 'bottom': none}), para),
             (' ' + label, F.char(ref_char, height=1600, color='#000000', face=face, bold=False),
              F.boxfill(fill_src, {'left': thick, 'right': thick, 'top': thick, 'bottom': thick}, '#FFFFFF'), F.align(para, 'LEFT'))]
    tcs = []
    for j, (txt, ch, bf, pp) in enumerate(specs):
        c = re.sub(r'<hp:p [^>]*>.*</hp:p>', f'<hp:p id="2147483648" paraPrIDRef="{pp}" styleIDRef="0" pageBreak="0" columnBreak="0" '
                   f'merged="0"><hp:run charPrIDRef="{ch}"><hp:t>{escape(txt)}</hp:t></hp:run></hp:p>', cell, count=1, flags=S)
        c = re.sub(r'(<hp:tc [^>]*?borderFillIDRef=")\d+', rf'\g<1>{bf}', c, count=1)
        c = re.sub(r'(<hp:subList [^>]*?vertAlign=")\w+', r'\g<1>CENTER', c, count=1)
        c = re.sub(r'<hp:cellAddr colAddr="\d+" rowAddr="\d+"/>', f'<hp:cellAddr colAddr="{j}" rowAddr="0"/>', c)
        c = re.sub(r'<hp:cellSpan colSpan="\d+" rowSpan="\d+"/>', '<hp:cellSpan colSpan="1" rowSpan="1"/>', c)
        c = re.sub(r'<hp:cellSz width="\d+" height="\d+"', f'<hp:cellSz width="{widths[j]}" height="{h}"', c)
        c = re.sub(r'<hp:cellMargin left="\d+" right="\d+" top="\d+" bottom="\d+"/>',
                   '<hp:cellMargin left="141" right="141" top="141" bottom="141"/>', c)
        tcs.append(c)
    head = re.sub(r'rowCnt="\d+" colCnt="\d+"', 'rowCnt="1" colCnt="3"', head, count=1)
    head = re.sub(r'(<hp:sz width="\d+" widthRelTo="\w+" height=")\d+', lambda m: m.group(1) + str(h), head, count=1)
    return _page_break(head + '<hp:tr>' + ''.join(tcs) + '</hp:tr>' + tail, True)


def _balance(seg, title, limit=13):
    """머리 제목이 길면 가운데에 가까운 띄어쓰기에서 두 줄로(예: 해오름지구 광역교통 / 현안사항 보고)"""
    if len(title) <= limit or ' ' not in title:
        return seg
    spaces = [i for i, ch in enumerate(title) if ch == ' ']
    k = min(spaces, key=lambda i: abs(i - len(title) / 2))
    return seg.replace(escape(title), escape(title[:k]) + '<hp:lineBreak/>' + escape(title[k + 1:]), 1)


def _emit(b, roles, gaps, kind, F=None):
    """양식 블록 하나 → 문단들(앞 띄움 포함)."""
    k = b[0]
    gap = gaps.get(k, '')
    if k == 'figure' and 'table' in roles:  # 쪽 빈 곳: 도면 넣을 자리
        return [gaps.get('sq', ''), _fill(roles['cap'], [b[1]]), _figure(roles['table'], b[2], F)]
    if k == 'att' and 'table' in roles and F is not None:  # 붙임 N 제목 상자(새 쪽)
        ref = re.search(r'charPrIDRef="(\d+)"', roles['sq']).group(1)
        return [_att_heading(roles['table'], b[1], b[2], F, ref), gaps.get('sq', '')]
    if k == 'att' and 'sq' in roles:  # 붙임 N 제목: □ 문단 서식을 빌려 새 쪽에서 시작
        return [_page_break(_fill(roles['sq'], ['', f'{b[1]}  ', b[2]]), True)]
    if k == 'sq' and 'sq' in roles:
        if kind == 'press':
            return [gap, _fill(roles['sq'], ['□ ', '', b[2] or b[1] or '', '', '', ''])]
        return [gap, _fill(roles['sq'], ['□ ', f'({b[1]}) ' if b[1] and b[2] else (b[1] or ''), b[2] or ''])]
    if k == 'o' and 'o' in roles:
        if kind == 'press':
            return [gap, _fill(roles['o'], [' ㅇ ', '', b[1]])]
        return [gap, _body_para(roles['o'], b[1], F, ' ㅇ ')]
    if k == 'dash':
        src = roles.get('dash') or roles.get('o')
        if 'dash' in roles and kind != 'press':
            return [gaps.get('dash', gap), _body_para(src, b[1], F, '   - ')]
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


def render(styled, form, form_path=None):
    path = template_path(form, form_path)
    if not path:
        raise FileNotFoundError(f'{form} 한글 서식 파일이 없습니다(templates/company/ 또는 화면에서 올리기).')
    apply_skill()
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
        out.append(_balance(_fill(F.segs[0], [' ', h[1], '', '담', '당', '처장', '팀장', h[3], h[2]]), h[1]))
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
