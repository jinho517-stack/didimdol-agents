"""A03: 목적별 자료 조회. 확정·선택된 DB 값만 골라 자료표를 만들고, 값마다 출처를 붙인다.
LLM은 '어떤 시설·항목이 목적에 맞는지' 고르는 데만 쓰고 값은 바꾸지 않는다. 키가 없으면 키워드 규칙으로 고른다."""
from datetime import datetime
from io import BytesIO

from common import llm

KEYWORDS = {  # 목적 문구의 낱말 → 시설·항목 이름에 들어 있는 낱말
    '철도': '철도', '광역철도': '철도', '도로': '도로', '연결도로': '연결도로', '환승': '환승', '버스': '버스',
    '대중교통': '버스', '사업비': '사업비', '비용': '사업비', '예산': '사업비', '연장': '연장', '길이': '연장',
    '차로': '차로', '규모': '규모', '면적': '규모', '지원': '지원', '일정': ('시기', '목표'), '시기': ('시기', '목표'),
    '개통': '개통', '완료': '완료', '준공': '완료',
}


def _match(names, purpose):
    hits = set()
    for word, needle in KEYWORDS.items():
        if word in purpose:
            for n in names:
                if any(x in n for x in (needle if isinstance(needle, tuple) else (needle,))):
                    hits.add(n)
    hits |= {n for n in names if n in purpose}
    return hits


def select_rule(facts, purpose):
    facs = sorted({f['facility'] for f in facts})
    items = sorted({f['item'] for f in facts})
    hf, hi = _match(facs, purpose), _match(items, purpose)
    sel = [f for f in facts if (not hf or f['facility'] in hf) and (not hi or f['item'] in hi)]
    basis = '규칙(키워드): ' + ('시설 ' + ', '.join(sorted(hf)) if hf else '시설 전체') + ' / ' + \
            ('항목 ' + ', '.join(sorted(hi)) if hi else '항목 전체')
    return sel, basis


def select_llm(facts, purpose, cfg=None):
    pairs = '\n'.join(f"- {f['facility']} / {f['item']}" for f in facts)
    data = llm.ask_json(
        f'[목적] {purpose}\n\n[DB에 있는 시설 / 항목]\n{pairs}\n\n'
        '목적에 필요한 시설·항목 쌍만 위 목록에서 그대로 골라라. 목록에 없는 것은 만들지 않는다.\n'
        '출력 형식: {"pairs": [{"facility": "...", "item": "..."}], "reason": "고른 이유 한 문장"}',
        system='너는 행정 자료표 구성을 돕는 도구다.', cfg=cfg)
    want = {(p.get('facility'), p.get('item')) for p in data.get('pairs', [])}
    sel = [f for f in facts if (f['facility'], f['item']) in want]
    if not sel:
        raise ValueError('LLM이 고른 항목이 없음')
    return sel, f"LLM 선택: {data.get('reason', '')}"


def select(facts, purpose, use_llm=False, cfg=None):
    """목적에 맞는 DB 항목(facts) 고르기. 반환: (항목 목록, 선택 근거 설명)"""
    usable = [f for f in facts if f['status'] != '참고']
    if use_llm:
        try:
            return select_llm(usable, purpose, cfg)
        except Exception as e:  # LLM 실패 시 규칙으로 대신
            sel, basis = select_rule(usable, purpose)
            return sel, basis + f' (LLM 선택 실패로 규칙 사용: {e})'
    return select_rule(usable, purpose)


def build(facts, purpose, use_llm=False, cfg=None):
    """반환: (자료표 행 목록, 선택 근거 설명)"""
    sel, basis = select(facts, purpose, use_llm, cfg)
    return [to_row(f) for f in sel], basis


def to_row(f):
    if f['value'] is None:
        val = '미확정(담당자 선택 필요)'
    else:
        val = f"{f['value']}{f['unit'] or ''}" + (' (미확정)' if f['status'] == '미확정(충돌)' else '')
    src = f"{f['source_doc']} {f['source_file']} ({f['source_loc']})" if f['source_doc'] else ''
    note = f['note'] or ''
    ref = note.split('참고(비공식, 반영 안 함): ', 1)[1] if '참고(비공식' in note else ''
    return {'지구': f['district'], '시설': f['facility'], '항목': f['item'], '값': val,
            '비공식 참고(반영 안 함)': ref, '상태': f['status'], '판정 유형': f['method'],
            '문서 단계': f['doc_stage'], '문서 일자': f['doc_date'], '출처': src}


def to_excel(table, purpose, basis, sources):
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = '자료표'
    ws.append([f'목적: {purpose}'])
    ws.append([f"작성: {datetime.now():%Y-%m-%d %H:%M} / 디딤돌 / {basis}"])
    ws.append([])
    cols = list(table[0].keys()) if table else ['지구', '시설', '항목', '값']
    ws.append(cols)
    head = PatternFill('solid', fgColor='DDE7F3')
    for c in ws[4]:
        c.font, c.fill = Font(bold=True), head
    for r in table:
        ws.append([r[c] for c in cols])
    ws['A1'].font = Font(bold=True, size=13)
    ws.freeze_panes = 'A5'
    widths = {'지구': 12, '시설': 22, '항목': 10, '값': 22, '상태': 12, '판정 유형': 26, '출처': 60,
              '문서 단계': 10, '문서 일자': 12, '비공식 참고(반영 안 함)': 28}
    for i, c in enumerate(cols, 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = widths.get(c, 14)
    for row in ws.iter_rows(min_row=5):
        for c in row:
            c.alignment = Alignment(vertical='top', wrap_text=True)
    s = wb.create_sheet('출처 문서')
    s.append(['문서ID', '파일명', '문서일자', '문서 단계', '버전 종류', '형식'])
    for c in s[1]:
        c.font, c.fill = Font(bold=True), head
    for d in sources:
        s.append([d['doc_id'], d['file'], d['date'], d['stage'], d['version_kind'], d['format']])
    s.column_dimensions['B'].width = 60
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
