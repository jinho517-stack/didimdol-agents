"""꼭지 길이·쪽 채우기 계산 (담당자 수정본 PDF로 맞춘 값, 2026-11-09)

- 폭은 '칸'(본문 15pt 한글 한 글자 = 1칸)으로 센다. 띄어쓰기 0.5칸, 숫자·영문 0.55칸, 문장부호 0.35칸,
  괄호 안 글자는 13pt라 0.87배. 수정본 PDF에서 본문 한 줄은 약 31칸, '-' 세부 한 줄은 약 29칸.
- 쪽 높이는 mm로 어림한다(A4, 수정본 기준 본문을 쓸 수 있는 높이 약 250mm). 정확한 쪽 나눔은 한글이 하므로,
  빈 곳을 채우는 도면 자리는 넉넉히 여유를 두고 넣는다(다음 쪽으로 밀리지 않게).
"""
import math
import re

from agents.a04_draft import skill as SK

LINE_EM = {'o': 30.0, 'sq': 30.0, 'dash': 28.0, 'note': 29.0}  # 11-09 한글 PDF로 다시 맞춤
PAGE_MM = 246.0        # 11-09 한글 PDF: 쪽 위 19mm ~ 아래 265mm
LINE_MM = 8.5          # 본문 한 줄(15pt, 줄간격 160%)
ROW_MM = 6.6           # 표 한 줄(13pt, 칸 여백 포함)
GAP_MM = {'sq': 4.5, 'o': 2.2, 'dash': 1.4, 'note': 1.1}
WRAP_MM = 6.0          # 표 칸 안에서 한 줄 더 늘 때(13pt, 11-10 한글 PDF 붙임 2 쟁점 표로 맞춤)
TABLE_EM = 34.0        # 표 폭(13pt 글자 수)
CELL_PAD_EM = 1.2      # 칸 좌우 여백(글자 수)


def table_lines(cols, rows):
    """표 줄마다 몇 줄로 그려질지 어림. 칸마다 줄바꿈되므로(11-10 빈 쪽 원인: 줄 전체 폭으로만 셈) 열 폭을 먼저 나눈다:
    열마다 가장 긴 글의 폭을 재고, 합이 표 폭을 넘으면 그 비율로 줄여 열 폭을 정한 뒤 칸마다 줄 수를 센다."""
    table = [list(map(str, cols))] + [list(map(str, r)) for r in rows]
    n = max(len(r) for r in table)
    need = [max((em(r[j]) * 0.87 + CELL_PAD_EM for r in table if j < len(r)), default=CELL_PAD_EM) for j in range(n)]
    scale = min(1.0, TABLE_EM / sum(need)) if sum(need) else 1.0
    width = [max(2.0, w * scale) for w in need]
    return [max(1, max((math.ceil((em(c) * 0.87 + CELL_PAD_EM) / width[j] - 0.05) for j, c in enumerate(r) if c), default=1))
            for r in table]


def writing():
    w = SK.load()['settings'].get('writing', {})
    return {'line_em': w.get('line_em', 30), 'max_em': w.get('max_em', 56), 'min_em': w.get('min_em', 49)}


def em(text, paren_scale=13 / 15):
    """글의 폭(칸). 괄호 안은 작은 글자."""
    w, depth = 0.0, 0
    for ch in (text or '').replace('**', ''):
        if ch in '(（':
            depth += 1
        s = paren_scale if depth > 0 else 1.0
        if '가' <= ch <= '힣' or ch in '下上ㅇ□◈「」『』':
            cw = 1.0
        elif ch == ' ':
            cw = 0.5
        elif ch.isdigit() or (ch.isascii() and ch.isalpha()):
            cw = 0.55
        elif ch in "’'.,·()":
            cw = 0.35
        elif ch in '~→':
            cw = 0.9
        else:
            cw = 1.0
        w += cw * s
        if ch in ')）':
            depth = max(0, depth - 1)
    return w


def item_em(key, text):
    """ㅇ 꼭지 한 개의 폭: '(핵심어) 본문' (핵심어 괄호는 본문 크기)"""
    return (em(f'({key}) ', paren_scale=1.0) if key else 0) + em(text)


def lines(width, kind='o'):
    return max(1, math.ceil(width / LINE_EM.get(kind, 31.0) - 0.02))


def block_mm(b):
    """양식 블록(lh_style.restyle 결과) 하나의 높이 어림(mm)"""
    k = b[0]
    if k in ('head1p', 'title'):
        return 32.0
    if k == 'dateline':
        return 8.0
    if k == 'summary':
        return 16.0
    if k in ('mid', 'big'):
        return 14.0
    if k == 'att':
        return 24.0  # 붙임 제목 상자 + 아래 간격
    if k == 'sq':
        txt = f'({b[1]}) {b[2]}' if b[1] and b[2] else (b[1] or b[2] or '')
        return GAP_MM['sq'] + lines(em(txt), 'sq') * LINE_MM
    if k in ('o', 'dash', 'note'):
        return GAP_MM[k] + lines(em(b[1]), k) * LINE_MM
    if k == 'table':
        cols, rows = b[2], b[3]
        unit = any(re.search(r'\((km|㎡|억원|m|원|%)\)', str(c)) for c in cols)
        return 13.0 + (5.0 if unit else 0) + sum(ROW_MM + (n - 1) * WRAP_MM for n in table_lines(cols, rows)) + 2.0
    if k == 'figure':
        return 17.0 + b[2]
    return 0.0


def add_figures(styled, name=''):
    """쪽 끝에 빈 곳이 크게 남으면 그 자리에 '도면 넣을 자리'(빈 상자)를 넣는다(담당자 원칙: 빈 곳 없이 채우기).
    본문 끝(첫 붙임 앞)과 각 붙임 끝에서 마지막 쪽의 남은 높이를 어림해 60mm 넘게 비면 넣는다."""
    out, used = [], 0.0
    if any(b[0] in ('cover', 'press', 'presshead') for b in styled):  # 표지·보도자료는 쪽 구성이 달라 건너뜀
        return list(styled)

    def close(caption):
        if used > PAGE_MM:  # 여러 쪽에 걸친 부분은 높이 어림이 부정확해 빈 쪽이 생길 수 있으므로 넣지 않음
            return
        rest = PAGE_MM - used
        if rest > 75:  # 도면 제목·간격 17mm + 여유 23mm를 빼고 남은 높이만큼 상자(넘치면 상자째 다음 쪽으로 밀려 빈 쪽이 생김)
            out.append(('figure', caption, round(rest - 40, 1)))

    cap = f'< {name} 위치도 >' if name else '< 위치도 >'
    for b in styled:
        if b[0] == 'att' and out:
            close(cap)
            used = 0.0
        if b[0] == 'att':
            cap = f'< {name} 현황도 >' if '개요' in (b[2] or '') and name else '< 관련 도면 >'
        out.append(b)
        used += block_mm(b)
    if out:
        close(cap)
    return out


def fits(key, text, kind='o'):
    """(두 줄 안에 드는지, 두 줄에 가까운지, 폭)"""
    w = writing()
    width = item_em(key, text) if kind == 'o' else em(text)
    mx = w['max_em'] if kind == 'o' else w['max_em'] * LINE_EM['dash'] / LINE_EM['o']
    return width <= mx, width >= w['min_em'] * (1 if kind == 'o' else 0), round(width, 1)
