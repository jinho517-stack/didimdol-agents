"""여러 사업지구의 사업(광역교통시설)을 한 표로 모아 비교·검색한다. 통합 비교 화면과 질문하기(챗봇)가 같이 쓴다.
검색은 항상 DB 최신값(facts)에서 한다. 질문은 규칙(키 없을 때) 또는 LLM(키 있을 때)으로 '검색 조건'으로 바꾸고,
조건 실행과 숫자는 코드가 맡는다(LLM이 숫자를 만들지 않음)."""
import json
import re

from common import catalog, llm
from common.fmt import fmt_value

TYPES = ['도로', '철도', '환승', '대중교통']
ENTITY = ['지자체(기초)', '지자체(광역)', 'LH(사업시행자)', '국가·공공기관', '기타', '미정']
KEYWORDS = ['반대', '지연', '증액', '보상', '예타', '재조사', '소음', '민원', '이견', '중재', '설계', '착공', '부지',
            '교육청', '학교용지', '분담', '대안노선', '조건부', '주민']


def _num(v):
    try:
        return float(str(v).replace(',', ''))
    except (TypeError, ValueError):
        return None


# ---------- 사업 목록 ----------
def projects(facts, cat):
    """facts(항목 단위) → 사업 단위 행 목록."""
    by = {}
    for f in facts:
        by.setdefault((f['district'], f['facility']), {})[f['item']] = f
    out = []
    for (district, fac), m in by.items():
        def v(item):
            f = m.get(item)
            return None if f is None or f['status'] == '참고' else f['value']
        cost_item = '사업비' if v('사업비') is not None else ('지원액' if v('지원액') is not None else None)
        cost = _num(v(cost_item)) if cost_item else None
        timing_item = '개통목표' if v('개통목표') is not None else '완료시기'
        entity = v('시행주체') or ''
        out.append({
            '지구': district, '사업명': fac, '유형': catalog.facility_type(cat, district, fac),
            '사업비(억원)': cost, '비용 구분': cost_item or '', '연장(km)': _num(v('연장')), '차로': v('차로') or '',
            '규모(㎡)': _num(v('규모')), '시기': v(timing_item) or '', '시기 구분': timing_item if v(timing_item) else '',
            '시행주체': entity, '주체 구분': catalog.entity_class(entity), '추진상태': v('추진상태') or '',
            '현안': v('현안') or '', '향후계획': v('향후계획') or '',
            '확인 필요': ', '.join(i for i, f in m.items() if f['status'] == '미확정(충돌)'),
            '근거 문서': ', '.join(sorted({f['source_doc'] for f in m.values() if f['source_doc']})),
        })
    return sorted(out, key=lambda r: (r['지구'], TYPES.index(r['유형']) if r['유형'] in TYPES else 9, r['사업명']))


def run(rows, flt):
    """검색 조건 실행. flt 키: districts, exclude_districts, types, cost_min, cost_max, cost_min_incl, cost_max_incl,
    entities, keywords, pending"""
    out = []
    for r in rows:
        if flt.get('districts') and r['지구'] not in flt['districts']:
            continue
        if r['지구'] in (flt.get('exclude_districts') or []):
            continue
        if flt.get('types') and r['유형'] not in flt['types']:
            continue
        c = r['사업비(억원)']
        if flt.get('cost_min') is not None and (c is None or c < flt['cost_min'] or
                                               (c == flt['cost_min'] and not flt.get('cost_min_incl', True))):
            continue
        if flt.get('cost_max') is not None and (c is None or c > flt['cost_max'] or
                                               (c == flt['cost_max'] and not flt.get('cost_max_incl', True))):
            continue
        if flt.get('entities') and r['주체 구분'] not in flt['entities']:
            continue
        text = ' '.join(r[k] for k in ('사업명', '추진상태', '현안', '향후계획'))
        if flt.get('keywords') and not any(k in text for k in flt['keywords']):
            continue
        if flt.get('pending') and not r['확인 필요']:
            continue
        out.append(r)
    return out


def describe(flt):
    """검색 조건을 사람이 읽는 문장으로."""
    parts = []
    if flt.get('districts'):
        parts.append('지구 ' + '·'.join(flt['districts']))
    if flt.get('exclude_districts'):
        parts.append('·'.join(flt['exclude_districts']) + ' 제외')
    if flt.get('types'):
        parts.append('유형 ' + '·'.join(flt['types']))
    lo, hi = flt.get('cost_min'), flt.get('cost_max')
    if lo is not None or hi is not None:
        lo_s = f"{fmt_value(_fmt(lo), '억원')} {'이상' if flt.get('cost_min_incl', True) else '초과'}" if lo is not None else ''
        hi_s = f"{fmt_value(_fmt(hi), '억원')} {'이하' if flt.get('cost_max_incl', True) else '미만'}" if hi is not None else ''
        parts.append('사업비(지원액) ' + ' ~ '.join(p for p in (lo_s, hi_s) if p))
    if flt.get('entities'):
        parts.append('시행주체 ' + '·'.join(flt['entities']))
    if flt.get('keywords'):
        parts.append('현안·상태에 "' + '" 또는 "'.join(flt['keywords']) + '" 포함')
    if flt.get('pending'):
        parts.append('확인 필요 항목 있음')
    return ' · '.join(parts) or '조건 없음(전체)'


def _fmt(x):
    return str(int(x)) if float(x).is_integer() else str(x)


# ---------- 질문 → 검색 조건 (규칙) ----------
UNIT = {'조': 10000, '천억': 1000, '백억': 100, '십억': 10, '억': 1}
AMOUNT = re.compile(r'(\d+(?:[.,]\d+)?)?\s*(조|천억|백억|십억|억)\s*원?\s*(미만|이하|초과|이상|넘는|넘은|넘게|까지|보다\s*(?:작|적|낮)|보다\s*(?:크|많|높)|~|에서)?')


def parse(question, cat, current=None):
    q = question.strip()
    flt, notes = {}, []
    types = [t for t, pat in (('철도', r'철도|전철|[가-힣]선\b'), ('도로', r'도로|IC|교차로|확장|연결로'),
                              ('환승', r'환승'), ('대중교통', r'BRT|버스|대중교통')) if re.search(pat, q)]
    if types:
        flt['types'] = types
    for m in AMOUNT.finditer(q):
        if not m.group(1) and m.group(2) == '억':
            continue
        amt = float((m.group(1) or '1').replace(',', '')) * UNIT[m.group(2)]
        op = re.sub(r'\s', '', m.group(3) or '')
        if op in ('미만',) or op.startswith('보다작') or op.startswith('보다적') or op.startswith('보다낮'):
            flt['cost_max'], flt['cost_max_incl'] = amt, False
        elif op in ('이하', '까지'):
            flt['cost_max'], flt['cost_max_incl'] = amt, True
        elif op in ('초과', '넘는', '넘은', '넘게') or op.startswith('보다크') or op.startswith('보다많') or op.startswith('보다높'):
            flt['cost_min'], flt['cost_min_incl'] = amt, False
        elif op in ('이상', '~', '에서'):
            flt['cost_min'], flt['cost_min_incl'] = amt, True
        elif 'cost_min' in flt and 'cost_max' not in flt:  # "500억~1천억"의 뒤쪽
            flt['cost_max'], flt['cost_max_incl'] = amt, True
        else:
            flt['cost_max'], flt['cost_max_incl'] = amt, True
            notes.append(f'"{m.group(0).strip()}"은(는) 이하로 해석')
    if re.search(r'시행주체|공사주체|사업주체|시행하는|시행 중인|직접 시행|주체가|시행을 맡', q):
        ents = []
        if re.search(r'기초', q):
            ents.append('지자체(기초)')
        if re.search(r'광역지자체|광역 지자체|도청|도가|도에서', q):
            ents.append('지자체(광역)')
        if not ents and re.search(r'지자체|시청|시가|군|구청', q):
            ents = ['지자체(기초)', '지자체(광역)']
        if re.search(r'LH|사업시행자|공사가', q):
            ents.append('LH(사업시행자)')
        if re.search(r'국가|공단|국토부', q):
            ents.append('국가·공공기관')
        if ents:
            flt['entities'] = ents
    named = [d for d in cat['districts'] if d in q or cat['keys'].get(d, d) in q]
    if named:
        flt['districts'] = named
    if current and re.search(r'다른\s*(사업)?\s*(지구|단지|사업지)|타\s*(사업)?\s*지구|다른 곳', q) and current not in named:
        flt['exclude_districts'] = [current]
    kws = [k for k in KEYWORDS if k in q]
    if kws:
        flt['keywords'] = kws
    if re.search(r'확인 필요|충돌|미확정', q):
        flt['pending'] = True
    return flt, notes


# ---------- 질문 → 검색 조건 (LLM) ----------
LLM_SCHEMA = """{"types": ["도로"|"철도"|"환승"|"대중교통"], "districts": [지구 이름], "exclude_districts": [지구 이름],
 "cost_min": 숫자(억원) 또는 null, "cost_min_incl": true|false, "cost_max": 숫자(억원) 또는 null, "cost_max_incl": true|false,
 "entities": ["지자체(기초)"|"지자체(광역)"|"LH(사업시행자)"|"국가·공공기관"], "keywords": [현안·추진상태에서 찾을 낱말], "pending": true|false}"""


def parse_llm(question, cat, current=None, cfg=None):
    data = llm.ask_json(
        f'[질문] {question}\n[현재 보고 있는 지구] {current or "없음"}\n[지구 목록] {", ".join(cat["districts"])}\n\n'
        '질문을 광역교통 사업 DB 검색 조건으로 바꿔라. 질문에 없는 조건은 넣지 않는다(빈 목록 또는 null).\n'
        '- "1천억 미만" → cost_max 1000, cost_max_incl false. 금액 단위는 억원.\n'
        '- "다른 지구/사업지구" → exclude_districts에 현재 지구.\n'
        '- 시행주체(공사주체)를 묻는 경우에만 entities를 쓴다. "지자체가 검토하라고 한다"처럼 요청 주체일 뿐이면 쓰지 않는다.\n'
        f'출력 형식(JSON): {LLM_SCHEMA}',
        system='너는 질문을 DB 검색 조건으로 바꾸는 도구다.', cfg=cfg)
    flt = {}
    if isinstance(data.get('types'), list):
        flt['types'] = [t for t in data['types'] if t in TYPES]
    for k in ('districts', 'exclude_districts'):
        if isinstance(data.get(k), list):
            flt[k] = [d for d in data[k] if d in cat['districts']]
    for k in ('cost_min', 'cost_max'):
        if _num(data.get(k)) is not None:
            flt[k] = _num(data[k])
            flt[k + '_incl'] = bool(data.get(k + '_incl', True))
    if isinstance(data.get('entities'), list):
        flt['entities'] = [e for e in data['entities'] if e in ENTITY]
    if isinstance(data.get('keywords'), list):
        flt['keywords'] = [str(k) for k in data['keywords'] if str(k).strip()][:5]
    if data.get('pending') is True:
        flt['pending'] = True
    return {k: v for k, v in flt.items() if v not in ([], None)}


# ---------- 답변 ----------
def line(r):
    bits = [r['유형']]
    if r['사업비(억원)'] is not None:
        bits.append(f"{r['비용 구분']} {fmt_value(_fmt(r['사업비(억원)']), '억원')}")
    if r['연장(km)'] is not None:
        bits.append(f"연장 {_fmt(r['연장(km)'])}km")
    if r['시기']:
        bits.append(f"{r['시기 구분']} {r['시기']}")
    if r['시행주체']:
        bits.append(f"시행주체 {r['시행주체']}")
    if r['추진상태']:
        bits.append(f"추진상태 {r['추진상태']}")
    return f"({r['지구']}) {r['사업명']} — " + ' · '.join(bits)


def template_answer(rows, flt):
    if not rows:
        return '조건에 맞는 사업이 DB에 없습니다. 조건을 넓혀 보세요(예: 금액 기준 상향, 유형 제외).'
    out = [f'조건에 맞는 사업이 {len(rows)}건 있습니다.']
    for r in rows:
        out.append(f'- {line(r)}')
        if r['현안']:
            out.append(f'  - 현안: {r["현안"]}')
    return '\n'.join(out)


def llm_answer(question, rows, flt, cfg=None):
    data = [{k: r[k] for k in ('지구', '사업명', '유형', '사업비(억원)', '비용 구분', '연장(km)', '시기', '시기 구분',
                               '시행주체', '주체 구분', '추진상태', '현안', '향후계획')} for r in rows]
    res = llm.ask_json(
        f'[질문] {question}\n[검색 조건] {describe(flt)}\n[DB 검색 결과 {len(rows)}건]\n{json.dumps(data, ensure_ascii=False)}\n\n'
        '검색 결과만 근거로 질문에 답하라. 결과에 없는 사업·숫자는 쓰지 않는다. 사례가 있으면 지구·사업명·핵심 수치·시사점을 '
        '개조식 3~6줄로, 없으면 없다고 짧게 답한다. 출력 형식: {"answer": "..."}',
        system='너는 LH 광역교통 담당자를 돕는 검색 도우미다.', cfg=cfg)
    return res['answer']


def answer(question, facts, cat, current=None, use_llm=False, cfg=None):
    """반환: {'filter', 'conditions', 'rows', 'text', 'mode', 'notes'}"""
    rows_all = projects(facts, cat)
    mode, notes = '규칙', []
    if use_llm:
        try:
            flt = parse_llm(question, cat, current, cfg)
            mode = 'AI'
        except Exception as e:
            flt, notes = parse(question, cat, current)
            notes.append(f'AI 해석 실패로 규칙 사용: {e}')
    else:
        flt, notes = parse(question, cat, current)
    rows = run(rows_all, flt)
    text = None
    if mode == 'AI':
        try:
            text = llm_answer(question, rows, flt, cfg)
        except Exception as e:
            notes.append(f'AI 답변 실패로 정해진 틀 사용: {e}')
    return {'filter': flt, 'conditions': describe(flt), 'rows': rows, 'mode': mode, 'notes': notes,
            'text': text or template_answer(rows, flt)}
