"""보고서 작성 스킬(skills/lh_report_style/SKILL.md) 읽기.
SKILL.md 위쪽(---로 둘러싼 부분)의 settings는 서식 숫자로, 아래 '## 문장 규칙'은 AI 문장 다듬기 지침으로 쓴다.
파일이 없거나 값이 빠지면 DEFAULTS(지금까지 확정한 값)를 쓴다."""
import copy
import re
from pathlib import Path

import yaml

PATH = Path(__file__).resolve().parents[2] / 'skills' / 'lh_report_style' / 'SKILL.md'
DEFAULTS = {
    'table': {'font_pt': 13, 'min_font_pt': 11, 'font_step_pt': 0.5, 'char_spacing': 0, 'char_ratio': 100,
              'overflow_spacing': -6, 'slim_margin_mm': 1, 'align': 'right', 'line_color': '000000',
              'outer_line_mm': 0.25, 'inner_line_mm': 0.12, 'head_double_mm': 0.4, 'header_fill': 'E5E5E5'},
    'body': {'font_pt': 15, 'paren_pt': 13, 'note_pt': 13, 'line_spacing': 160,
             'before_sq_pt': 8, 'before_o_pt': 6, 'before_dash_pt': 4, 'before_note_pt': 3},
    'writing': {'max_chars': 80, 'min_chars': 45, 'line_em': 30, 'max_em': 58, 'min_em': 47},
}
_cache = {}


def load(path=PATH):
    """반환: {'name','title','version','description','settings','rules','text','path','found'} (파일이 바뀌면 다시 읽음)"""
    path = Path(path)
    stamp = path.stat().st_mtime if path.exists() else None
    if _cache.get('key') == (str(path), stamp):
        return _cache['skill']
    meta, body = {}, ''
    if stamp is not None:
        text = path.read_text(encoding='utf-8')
        m = re.match(r'^---\s*\n(.*?)\n---\s*\n(.*)$', text, re.S)
        meta, body = (yaml.safe_load(m.group(1)) or {}, m.group(2)) if m else ({}, text)
    settings = copy.deepcopy(DEFAULTS)
    for grp, vals in (meta.get('settings') or {}).items():
        if isinstance(vals, dict):
            settings.setdefault(grp, {}).update({k: v for k, v in vals.items() if v is not None})
    # AI에게 주는 지침: '담당자 원칙'(우선) + '문장 규칙'
    rules = '\n\n'.join(m.group(0).strip() for m in re.finditer(
        r'^## (?:\d+\.\s*)?(?:담당자 원칙|문장 규칙).*?(?=^## |\Z)', body, re.S | re.M))
    sk = {'name': meta.get('name', 'lh-report-style'), 'title': meta.get('title', 'LH 보고서 작성 스킬'),
          'version': meta.get('version', 0), 'description': meta.get('description', ''),
          'settings': settings, 'rules': rules, 'text': body.strip(),
          'path': path, 'found': stamp is not None}
    _cache.update(key=(str(path), stamp), skill=sk)
    return sk


def get(group, key, path=PATH):
    return load(path)['settings'][group][key]


def hwp(pt):
    """pt → 한글 글자 크기 단위(13pt = 1300)"""
    return int(round(pt * 100))


def font_steps(path=PATH):
    """표 글자 크기 후보(큰 것부터): 13pt → 12.5 → … → 11pt (한글 단위)"""
    t = load(path)['settings']['table']
    out, f = [], float(t['font_pt'])
    while f >= float(t['min_font_pt']) - 1e-9:
        out.append(hwp(f))
        f -= float(t['font_step_pt']) or 0.5
    return tuple(out) or (hwp(t['font_pt']),)


def summary(path=PATH):
    """화면에 보여 줄 한 줄 요약들"""
    s = load(path)['settings']
    t, b = s['table'], s['body']
    return [f"표 글자 {t['font_pt']:g}pt(넘치면 {t['min_font_pt']:g}pt까지 {t['font_step_pt']:g}pt씩 줄임) · "
            f"자간 {t['char_spacing']}%(넘치는 칸만 {t['overflow_spacing']}%까지) · 장평 {t['char_ratio']}% · 본문 칸 한 줄",
            f"표 {'오른쪽' if t.get('align') == 'right' else '왼쪽'} 정렬 · 선 #{t['line_color']} · 제목줄 아래 이중선 "
            f"{t['head_double_mm']:g}mm · 바깥 {t['outer_line_mm']:g}mm · 안쪽 {t['inner_line_mm']:g}mm · 제목줄 배경 #{t['header_fill']}",
            f"본문 {b['font_pt']:g}pt(괄호 안 수치 {b['paren_pt']:g}pt) · 참고 {b['note_pt']:g}pt · 줄간격 {b['line_spacing']}% · "
            f"문단 위 간격 □{b['before_sq_pt']:g} ㅇ{b['before_o_pt']:g} -{b['before_dash_pt']:g} *{b['before_note_pt']:g}pt"]
