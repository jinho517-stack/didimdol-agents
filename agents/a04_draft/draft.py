"""A04: 보고서 초안 자동 작성.
공공기관 보고서 개조식 양식(제목 상자 → <날짜, 부서> → □ 대제목 → ㅇ (핵심어) 본문 → - 세부 → ⇒ 조치 → < 표 > → 주))을 따른다.
숫자는 모두 DB 최신값에서 가져오고(LLM이 숫자를 만들지 않음), LLM은 키가 있을 때 '종합 의견' 문장만 쓴다.
출력: 화면 미리보기(HTML), 한글(hwpx, templates/report_template.hwpx 서식 사용), 워드(docx)."""
import html
import json
import re
import zipfile
from collections import OrderedDict
from datetime import datetime
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from agents.a02_resolve.resolver import INFORMAL, norm
from agents.a02_resolve.resolver import key as rkey
from common import llm
from common.fmt import fmt_value, short_date  # noqa: F401  (draft.fmt_value로도 씀)

TEMPLATE = Path(__file__).resolve().parents[2] / 'templates' / 'report_template.hwpx'


# ---------- 보고서 목차(섹션)와 양식 ----------
# 블록: ('title', 제목, 부제) ('date', 문구) ('h', 대제목) ('b', 핵심어|None, 본문) ('s', 세부) ('act', 조치)
#       ('table', 표 제목, 열 이름, 행 목록) ('note', 주석)
# 화면에서 고르는 목차(담당자가 고친 현안 보고서 구조, 2026-11-08): 본문 □ 3개 + 붙임 3개
UI_SECTIONS = ['추진 현황 및 문제점', '대응 방향', '향후 계획', '붙임: 사업 개요', '붙임: 관계기관 쟁점', '붙임: 추진 경위·일정']
SECTIONS = UI_SECTIONS + ['개요', '사업개요', '추진경위', '추진현황', '주요 변경사항', '주요 현안', '참고(비공식)', '종합 의견(AI)']
SECTION_HELP = {
    '추진 현황 및 문제점': '사업 현황 한 줄 + 사업별 현안·지연사유·바뀐 값(사업비·연장 등) + 문서 간 값이 다른 항목(확인 필요)',
    '대응 방향': '사업별 대응방안·만회대책(없으면 현안이 있는 사업의 계획)',
    '붙임: 사업 개요': '사업지구 개요 표(사업명·사업시행자·사업기간·총사업비)와 사업별 총괄표',
    '붙임: 관계기관 쟁점': '쟁점별 관계기관 의견 표(문서에 쟁점이 있을 때)',
    '붙임: 추진 경위·일정': '날짜별 추진 경위와 앞으로의 일정 표',
    '개요': '대상 사업·항목 수, 판정 기준 문서, 확정·확인 필요 건수',
    '사업개요': '사업별 주요 제원 표(연장·차로·규모·사업비·시기)와 사업비 합계',
    '추진경위': '문서 날짜순으로 각 문서가 새로 제시하거나 바꾼 값',
    '추진현황': '사업별 최신값 한 줄 요약과 근거 문서',
    '주요 변경사항': '처음 문서 값과 현재 값이 다른 항목',
    '주요 현안': '문서 간 충돌(확인 필요)·담당자 선택 항목 + 직접 입력',
    '향후 계획': '확인 필요 항목 조치, 완료·개통 예정 시기 + 직접 입력',
    '참고(비공식)': '개인 메모 등 비공식 자료의 다른 값(반영 안 함)',
    '종합 의견(AI)': 'AI가 초안을 읽고 쓰는 의견 2~3줄(키 필요, 숫자는 만들지 않음)',
}
PRESETS = {  # 보고서 종류: (기본 제목 꼬리, 기본 목차) — 지금은 현안 보고자료 하나만 만든다(2026-11-08)
    '현안사항 보고': ('광역교통 현안사항 보고', list(UI_SECTIONS)),
}
REPORT = '현안사항 보고'
HEADINGS = {'주요 현안': '□ 주요 현안 및 대응방안', '참고(비공식)': '□ 참고(비공식 자료, 반영 안 함)',
            '종합 의견(AI)': '□ 종합 의견(AI 작성, 검토 필요)'}


def _user_lines(text):
    """직접 입력: 한 줄에 하나. '-'로 시작하면 세부, '⇒'로 시작하면 조치, '(핵심어) 본문'이면 핵심어."""
    out = []
    for ln in (text or '').splitlines():
        ln = ln.strip()
        if not ln:
            continue
        if ln.startswith('-'):
            out.append(('s', ln.lstrip('- ').strip()))
        elif ln.startswith('⇒') or ln.startswith('=>'):
            out.append(('act', ln.lstrip('⇒=> ').strip()))
        else:
            ln = ln.lstrip('ㅇo· ').strip()
            m = re.fullmatch(r'\(([^)]+)\)\s*(.+)', ln)
            out.append(('b', m.group(1), m.group(2)) if m else ('b', None, ln))
    return out


def _nd(v):
    """'30.12 · ’30. 12. → 2030.12 (날짜 값만, 나머지는 그대로)"""
    if v is None:
        return v
    m = re.fullmatch(r"[’'‘`]\s?(\d{2})\.\s?(\d{1,2})\.?", str(v).strip())
    return f'20{m.group(1)}.{int(m.group(2))}' if m else v


def _ym(v):
    """2032.6 → ’32.6월 (문장 안 날짜 표기)"""
    m = re.fullmatch(r'20(\d{2})\.(\d{1,2})', str(v))
    return f'’{m.group(1)}.{int(m.group(2))}월' if m else str(v)


_ENDINGS = [  # 서술형 끝맺음 → 개조식(보고서 작성 스킬 문장 규칙 5): 긴 것부터 바꾼다
    (r'할 예정이다$', '할 예정'), (r'예정이다$', '예정'), (r'필요하다$', '필요'), (r'입장이다$', '입장'),
    (r'중이다$', '중'), (r'([가-힣])하였다$', r'\1함'), (r'했다$', '함'), (r'되었다$', '됨'), (r'됐다$', '됨'),
    (r'였다$', '임'), (r'이었다$', '임'), (r'있었다$', '있었음'), (r'있다$', '있음'), (r'없다$', '없음'),
    (r'된다$', '됨'), (r'한다$', '함'), (r'이다$', '임'), (r'합니다$', '함'), (r'됩니다$', '됨'), (r'입니다$', '임'),
    (r'습니다$', '음'), (r'하겠음$', '할 예정'), (r'겠음$', ' 예정'), (r'([가-힣])ㄴ다$', r'\1함')]
SPACING = [('시행방식', '시행 방식'), ('시행주체', '시행 주체')]  # 스킬 문장 규칙 11: 띄어 쓰는 말(문장 안에서만)


def gaejo(s):
    """한 문장을 개조식으로: 끝의 마침표를 떼고 '~한다/~이다/~예정이다/~하겠음'을 '~함/~임/~예정'으로."""
    s = (s or '').strip().rstrip('.。').strip()
    s = re.sub(r"(?<![\w’])['‘`](\d{2})(?=[.\s년])", r'’\1', s)  # '26.6월 → ’26.6월 (스킬 문장 규칙 10)
    for a, b in SPACING:
        s = s.replace(a, b)
    for pat, rep in _ENDINGS:
        if re.search(pat, s):
            return re.sub(pat, rep, s)
    return s


def _split(text, limit=80):
    """문장 → (앞 문장, [나머지 문장]). 문장(마침표) 단위로만 나누고 각각 개조식으로 끝맺는다.
    한 항목 2줄 이내·한 가지 내용(보고서 작성 스킬 문장 규칙 4)."""
    text = (text or '').strip()
    parts = [gaejo(p) for p in re.split(r'(?<=[다음함됨임요])\.\s+|;\s*', text) if p.strip()]
    if not parts:
        return '', []
    if len(parts) == 1 or len(text) <= limit and len(parts) <= 2 and sum(map(len, parts)) <= limit:
        return ', '.join(parts), []
    return parts[0], parts[1:]


SPEC_LABEL = {'완료시기': '완료', '개통목표': '개통', '착공시기': '착공', '예상완료': '예상 완료',
              '시행자부담': '시행자 부담'}  # 추진현황 제원 한 줄에서 쓰는 이름
DISTRICT_FAC = '지구 공통'  # common.catalog.DISTRICT_FAC와 같음: 지구 전체 값(사업 줄에서는 뺀다)
TABLE_ITEMS = ['연장', '차로', '규모', '사업비', '완료시기', '예상완료', '시행주체']  # 사업개요 표 열(A4 한 장 폭)
INFO_ITEMS = ('담당시행자', '관리상태', '추진단계')  # 추진현황에서 한 줄로 쓰는 짧은 속성


def _ev_date(d):
    """2026.9 → ’26.9월, 2026.9.17 → ’26. 9. 17., 2026 하반기 → ’26. 下, 상반기 → ’26. 上 (스킬 문장 규칙 10)
    기간 2027.6~2028.6 → ’27.6월~’28.6월"""
    if d and '~' in d:
        a, _, z = d.partition('~')
        return f'{_ev_date(a.strip())}~{_ev_date(z.strip())}'
    m = re.fullmatch(r'20(\d\d)\.(\d{1,2})\.(\d{1,2})', d or '')
    if m:
        return f'’{m.group(1)}. {int(m.group(2))}. {int(m.group(3))}.'
    m = re.fullmatch(r'20(\d\d)\.(\d{1,2})', d or '')
    if m:
        return f'’{m.group(1)}.{int(m.group(2))}월'
    m = re.fullmatch(r'20(\d\d)\s*(상반기|하반기)', d or '')
    if m:
        return f"’{m.group(1)}. {'下' if m.group(2) == '하반기' else '上'}"
    m = re.fullmatch(r'20(\d\d)\s*(.*)', d or '')
    return f'’{m.group(1)}년 {m.group(2)}'.strip() if m else (d or '')


def _tdate(v):
    """표 안 날짜: 2030.12 → ’30.12 (담당자 수정본 표 표기)"""
    m = re.fullmatch(r'20(\d\d)\.(\d{1,2})', str(v))
    return f'’{m.group(1)}.{int(m.group(2))}' if m else v


def _ev_key(d):
    m = re.match(r'(\d{4})(?:\.(\d{1,2}))?(?:\.(\d{1,2}))?\s*(상반기|하반기)?', d or '')
    if not m:
        return (9999, 99, 99)
    mon = int(m.group(2)) if m.group(2) else {'상반기': 6, '하반기': 12}.get(m.group(4), 0)
    return (int(m.group(1)), mon, int(m.group(3) or 0))


def _jong(w):
    """마지막 글자 받침: 0 없음, 8 ㄹ, 그 밖은 받침 있음(한글이 아니면 0)"""
    c = (w or ' ')[-1]
    return (ord(c) - 0xAC00) % 28 if '가' <= c <= '힣' else 0


def _ro(w):  # 으로/로
    return w + ('으로' if _jong(w) not in (0, 8) else '로')


def _eun(w):  # 은/는
    return w + ('은' if _jong(w) else '는')


def _dv(v, unit):
    """변경 줄의 값 표기: 2030.12 → ’30.12월, 나머지는 단위를 붙여서"""
    return _ym(v) if re.fullmatch(r'20\d{2}\.\d{1,2}', str(v)) else fmt_value(v, unit)


def build(facts, cands, sources, choices, title='', district='', dept='', sections=None, extra=None,
          use_llm=False, cfg=None, order=None, kinds=None, show_basis=False, events=None, report_date=None):
    """sections: 넣을 목차 이름 목록(SECTIONS 순서로 배치). extra: {목차 이름: 직접 입력 텍스트}.
    order: [(시설, 항목), ...] 보고서에 쓸 순서(config.yaml items 순서). 없으면 이름순.
    kinds: {항목 이름: 'status'|'issue'|'plan'} 문장형 항목 구분(config.yaml items의 kind). 나머지는 값 항목.
    show_basis: True면 검토용으로 근거 문서·문서ID·판정 설명을 붙인다. 기본은 보고서 내용만.
    events: DB의 추진경위·향후 일정 목록(store.events). 있으면 추진경위·향후 계획에 날짜순으로 쓴다."""
    kinds = kinds or {}
    NARR = ('issue', 'plan', 'delay', 'remedy')  # 현안·향후계획·지연사유·만회대책: 해당 목차에서 문장으로 씀
    # 지구 공통(사업시행자·대책 수립일·최초 입주·총사업비)은 사업 줄과 따로 쓴다
    dist = {f['item']: f for f in facts if f['facility'] == DISTRICT_FAC and f['value'] is not None}
    facts = [f for f in facts if f['facility'] != DISTRICT_FAC]
    events = [e for e in (events or []) if e['facility'] == DISTRICT_FAC or any(f['facility'] == e['facility'] for f in facts)]
    sections = [s for s in SECTIONS if s in (sections if sections is not None else PRESETS[REPORT][1])]
    extra = extra or {}
    today = report_date or datetime.now()  # 보고 날짜(화면에서 고름, 없으면 오늘)
    # 날짜 값 표기 통일: '30.12, ’30.12 → 2030.12 (같은 날짜가 표기만 달라 '변경'으로 잡히지 않게)
    facts = [dict(f, value=_nd(f['value'])) for f in facts]
    cands = [dict(c, value=_nd(c['value'])) for c in cands]
    rank = {k: i for i, k in enumerate(order or [])}
    fac_rank, item_rank = {}, {}
    for fac, it in order or []:
        fac_rank.setdefault(fac, len(fac_rank))
        item_rank.setdefault(it, len(item_rank))
    facts = sorted(facts, key=lambda f: (fac_rank.get(f['facility'], 999), f['facility'],
                                         rank.get((f['facility'], f['item']), 999), f['item']))
    keys = {(f['facility'], f['item']) for f in facts}
    cands = [c for c in cands if (c['facility'], c['item']) in keys]
    docs = {s['doc_id']: s for s in sources}
    by_key = {}
    for c in cands:
        by_key.setdefault((c['facility'], c['item']), []).append(c)
    by_fac = OrderedDict()
    for f in facts:
        by_fac.setdefault(f['facility'], []).append(f)
    unit_of = {(f['facility'], f['item']): f['unit'] for f in facts}
    informal = [(f, c) for f in facts for c in by_key.get((f['facility'], f['item']), [])
                if c['stage'] in INFORMAL and (f['value'] is None or norm(c['value']) != norm(f['value']))]
    pending = [f for f in facts if f['status'] == '미확정(충돌)']

    def stem(doc_id):
        return docs.get(doc_id, {}).get('file', doc_id).rsplit('.', 1)[0]

    def val(f):
        if f['status'] == '미확정(충돌)':
            return '확인 필요'
        return year(f['value']) or fmt_value(f['value'], f['unit'])

    def year(v):  # 연도만 있는 시기 값: 2029 → 2029년 (천 단위 쉼표가 붙지 않게)
        return f'{v}년' if re.fullmatch(r'20\d\d', str(v or '')) else ''

    def narr(item):
        return kinds.get(item) in NARR

    def of_kind(kind):
        return {f['facility']: f for f in facts if kinds.get(f['item']) == kind and f['value'] is not None}

    def basis(f):
        d = docs.get(f['source_doc'])
        return f"{stem(d['doc_id'])}({d['stage']}, {short_date(d['date'])})" if d else ''

    B = [('title', title.strip() or f"{district} {PRESETS[REPORT][0]}",
          '디딤돌 자동 작성 초안(검토 전)' if show_basis else ''),
         ('date', f"<{short_date(today.strftime('%Y-%m-%d'))} {dept or '담당부서'}>")]

    att, used_plan = 0, set()
    issues_k, delays_k, remedies_k, plans_k = of_kind('issue'), of_kind('delay'), of_kind('remedy'), of_kind('plan')
    for sec in sections:
        body = []
        if sec == '추진 현황 및 문제점':
            costs = [float(f['value']) for f in facts if f['item'] == '사업비' and f['value'] is not None
                     and re.fullmatch(r'\d+(\.\d+)?', str(f['value']))]
            total = fmt_value(dist['총사업비']['value'], '억원') if '총사업비' in dist else \
                (fmt_value(str(int(sum(costs))), '억원') if costs else '')
            line_ = f"{dist['지구명칭']['value'] if '지구명칭' in dist else district} 광역교통개선대책 {len(by_fac)}개 사업" \
                + (f', 총사업비 {total}' if total else '') + (f", 최초 입주 {_ym(dist['최초입주']['value'])} 예정" if '최초입주' in dist else '')
            body.append(('b', '사업 현황', line_))
            for fac in by_fac:
                chg = []
                for f in by_fac[fac]:  # 바뀐 값(주요 변경사항을 여기에 녹임): 처음 공식 문서 값 → 지금 값
                    if narr(f['item']) or kinds.get(f['item']) in ('attr', 'status') or f['value'] is None:
                        continue
                    off = sorted((c for c in by_key.get((f['facility'], f['item']), []) if c['stage'] not in INFORMAL),
                                 key=lambda c: (c['date'], c['doc_id']))
                    o0 = norm(off[0]['value']) if off else ''
                    if off and o0 != norm(f['value']) and not (o0 and o0 in norm(f['value'])) and f['status'] != '미확정(충돌)':
                        chg.append(f"{SPEC_LABEL.get(f['item'], f['item'])} {_dv(off[0]['value'], f['unit'])} → "
                                   f"{_dv(f['value'], f['unit'])}")
                if fac not in issues_k and fac not in delays_k and not chg:
                    continue
                if fac in issues_k:
                    head, rest = _split(issues_k[fac]['value'])
                    body.append(('b', fac, head))
                    body += [('s', r) for r in rest]
                elif fac in delays_k:
                    body.append(('b', fac, gaejo(delays_k[fac]['value'])))
                else:
                    body.append(('b', fac, _ro(', '.join(chg[:3])) + ' 변경'))
                    chg = []
                if fac in delays_k and fac in issues_k:
                    body.append(('s', f"(지연사유) {gaejo(delays_k[fac]['value'])}"))
                if chg:
                    body.append(('s', _ro(', '.join(chg[:3])) + ' 변경'))
            for f in pending:
                tops = json.loads(f['conflict_candidates'] or '[]')
                cand = ' / '.join(OrderedDict.fromkeys(fmt_value(c['value'], f['unit']) for c in tops))
                body.append(('b', f"{f['facility']} {f['item']}", f'관계기관 문서 간 값 상이({cand}), 확인 필요'))

        elif sec == '대응 방향':
            for fac in by_fac:
                if fac in remedies_k:
                    head, rest = _split(remedies_k[fac]['value'])
                    body.append(('b', fac, head))
                    body += [('s', r) for r in rest]
                elif (fac in issues_k or fac in delays_k) and fac in plans_k:  # 대응방안이 따로 없으면 현안 사업의 계획
                    head, rest = _split(plans_k[fac]['value'])
                    body.append(('b', fac, head))
                    body += [('s', r) for r in rest]
                    used_plan.add(fac)
            if pending:  # 문서 간 값이 다른 항목: 한 줄로(항목마다 되풀이하지 않음)
                names = [f"{f['facility']} {f['item']}" for f in pending]
                more = f' 등 {len(names)}건' if len(names) > 3 else ''
                body.append(('b', '확인 필요', _eun(', '.join(names[:3]) + more) + ' 원문 대조 후 확정'))
            body = body or [('b', None, '문서에서 대응방안·만회대책을 찾지 못함')]

        elif sec == '붙임: 관계기관 쟁점':
            # 쟁점마다 관계기관 의견 줄 + LH 의견(대응방안) 칸(담당자가 고친 보고서 붙임 표 모양)
            groups = OrderedDict()
            for e in [e for e in events if e['kind'] == '쟁점']:
                m = re.match(r'\[(.+?)\]\s*([^:：]+)[:：]\s*(.+)$', e['content'])
                if m:
                    fac = e['facility'] if e['facility'] != DISTRICT_FAC else '지구 공통'
                    g = groups.setdefault((fac, m.group(1).strip()), {'org': [], 'lh': []})
                    who, say = m.group(2).strip(), m.group(3).strip()
                    is_lh = re.search(r'LH|토지주택|사업본부', who) or (dept and who == dept)
                    g['lh' if is_lh else 'org'].append((who, say))
            rows = []
            for (fac, issue), g in groups.items():
                lh = ' / '.join(x[1] for x in g['lh']) or '-'
                for i, (who, say) in enumerate(g['org'] or [('-', '-')]):
                    rows.append([fac, issue if i == 0 else '', who, say, lh if i == 0 else ''])
            rows = rows[:10]  # 한 쪽 안으로
            one = len({r[0] for r in rows}) <= 1
            body = [('table', '주요 쟁점별 관계기관 의견', ([] if one else ['사업']) + ['쟁점', '관계기관', '의견', 'LH 의견(대응방안)'],
                     [r[1:] if one else r for r in rows])] if rows else []

        elif sec == '붙임: 추진 경위·일정':
            # 한 쪽 안으로: 같은 내용은 한 번만, 지난 경위는 최근 4건, 앞으로 일정은 10건(담당자 원칙 7)
            seen, evs = set(), []
            for e in sorted([e for e in events if e['kind'] in ('경위', '계획')], key=lambda e: _ev_key(e['date'])):
                k_ = re.sub(r'[\s()·,]|예정|완료|추진', '', e['content'])[:14]
                if k_ not in seen:
                    seen.add(k_)
                    evs.append(e)
            now = (today.year, today.month, today.day)
            past = [e for e in evs if _ev_key(e['date']) < now][-4:]
            evs = past + [e for e in evs if _ev_key(e['date']) >= now][:10]
            rows = [[_ev_date(e['date']), '실적' if e['kind'] == '경위' else '계획',
                     '지구 공통' if e['facility'] == DISTRICT_FAC else e['facility'], e['content']] for e in evs]
            body = [('table', '추진 경위 및 일정', ['시기', '구분', '사업', '내용'], rows)] if rows else []

        elif sec == '개요':
            dates = sorted(s['date'] for s in sources if s['date'])
            body = [('b', '대상', f'{district} 광역교통개선대책 {len(by_fac)}개 사업')]
            if show_basis:
                body += [('b', '기준', f'관련 문서 {len(sources)}건 종합'
                                     + (f'({short_date(dates[0])} ~ {short_date(dates[-1])})' if dates else '')
                                     + ', 문서 단계 > 같은 단계 최근 일자 > 버전 순으로 최신값 판정'),
                         ('b', '현황', f"확정 {sum(f['status'] == '확정' for f in facts)}건, 확인 필요 {len(pending)}건, "
                                     f"비공식 참고 {len(informal)}건")]
            else:
                status = of_kind('status')
                if status:
                    body.append(('b', '추진상태', ', '.join(f"{fac} {f['value']}" for fac, f in status.items())))
                if pending:
                    body.append(('b', '확인 필요', ', '.join(f"{f['facility']} {f['item']}" for f in pending)))

        elif sec in ('사업개요', '붙임: 사업 개요'):
            # 열 합치기(A4 한 장 폭): 개통목표 → 완료(개통), 지원액 → 사업비. 수치 열 다음에 시행주체·추진상태
            merge = {'개통목표': '완료시기', '지원액': '사업비'}
            label = {'완료시기': '완료(개통)', '사업비': '사업비(억원)'}
            # 추진상태(긴 문장)는 표에 넣지 않고 추진현황에 쓴다. 모든 사업이 '-'인 열은 뺀다
            label['예상완료'] = '예상 완료'
            present = {merge.get(f['item'], f['item']) for f in facts
                       if f['value'] is not None or f['status'] == '미확정(충돌)'}
            items = [i for i in TABLE_ITEMS if i in present]
            units = {f['item']: f['unit'] for f in facts if f['unit'] and f['unit'] != f['item']}
            sym = {f['facility']: f['value'] for f in facts if f['item'] == '사업기호' and f['value']}
            cols = (['기호'] if sym else []) + ['사업명'] + \
                [label.get(i) or (f"{i}({units[i]})" if i in units else i) for i in items] + (['근거'] if show_basis else [])
            rows = []
            for fac, fs in by_fac.items():
                m = {}
                for f in fs:
                    m.setdefault(merge.get(f['item'], f['item']), f)
                srcs = list(OrderedDict.fromkeys(f['source_doc'] for f in fs if f['source_doc']))
                rows.append(([sym.get(fac, '-')] if sym else []) + [fac]
                            + [('확인 필요' if m[i]['status'] == '미확정(충돌)' else year(m[i]['value']) or _tdate(fmt_value(m[i]['value'])))
                               if i in m and m[i]['value'] is not None or i in m and m[i]['status'] == '미확정(충돌)' else '-'
                               for i in items] + ([', '.join(srcs)] if show_basis else []))
            costs = [float(f['value']) for f in facts if f['item'] == '사업비' and f['value'] is not None
                     and re.fullmatch(r'\d+(\.\d+)?', str(f['value']))]
            body = []
            info = [f"사업시행자 {dist['사업시행자']['value']}" if '사업시행자' in dist else '',
                    f"개선대책 수립 {_ym(dist['대책수립일']['value'])}" if '대책수립일' in dist else '',
                    f"대책상 시행시기 {_ym(dist['대책시행시기']['value'])}" if '대책시행시기' in dist else '',
                    f"최초 입주 {_ym(dist['최초입주']['value'])} 예정" if '최초입주' in dist else '']
            if any(info):
                body.append(('b', '지구 개요', ', '.join(x for x in info if x)))
            total = f", 개선대책 총사업비 {fmt_value(dist['총사업비']['value'], '억원')}" if '총사업비' in dist else ''
            body += [('b', '사업 구성', f"{district} 광역교통개선대책 {len(by_fac)}개 사업" + total
                      + (f", 사업비 합계 {fmt_value(str(int(sum(costs))) if sum(costs).is_integer() else str(sum(costs)), '억원')}"
                         f"({len(costs)}개 사업 기준)" if costs and not total else '')),
                     ('table', '사업개요', cols, rows)]
            if sec == '붙임: 사업 개요':  # 붙임: 사업지구 개요 표 + 사업별 총괄표(문장 줄 없이)
                info_rows = [[k, fmt_value(dist[i]['value'], '억원') if i == '총사업비' else
                              (_ym(dist[i]['value']) if i in ('대책수립일', '대책시행시기', '최초입주') else dist[i]['value'])]
                             for k, i in (('사 업 명', '지구명칭'), ('사업시행자', '사업시행자'), ('개선대책 수립', '대책수립일'),
                                          ('시행시기', '대책시행시기'), ('최초 입주', '최초입주'), ('총사업비', '총사업비')) if i in dist]
                body = ([('table', f"{dist['지구명칭']['value'] if '지구명칭' in dist else district} 사업개요", ['구 분', '내 용'], info_rows)]
                        if info_rows else []) + ([('table', '광역교통개선대책 총괄', cols, rows)] if items else [])  # 값 열이 없으면 표를 뺌

        elif sec == '추진경위' and any(e['kind'] == '경위' for e in events) and not show_basis:
            # DB의 추진경위 목록(문서에 날짜와 함께 적힌 실적): 지구 전체 → 사업별, 날짜순, 사업마다 최근 6건
            for fac in [DISTRICT_FAC] + list(by_fac):
                evs = [e for e in events if e['kind'] == '경위' and e['facility'] == fac]
                if not evs:
                    continue
                body.append(('b', '지구 전체' if fac == DISTRICT_FAC else fac, ''))
                body += [('s', f"({_ev_date(e['date'])}) {e['content']}") for e in evs[-6:]]

        elif sec == '추진경위':
            # 날짜순으로 문서를 하나씩 더하며, 그때까지의 문서로 판정 규칙을 적용한 '유효값'이 어떻게 바뀌었는지 기록
            def clip(xs):
                return ', '.join(xs[:4]) + (f' 외 {len(xs) - 4}건' if len(xs) > 4 else '')

            eff, pool = {}, []
            off = sorted((c for c in cands if c['stage'] not in INFORMAL and not narr(c['item'])),
                         key=lambda c: (c['date'], c['doc_id']))
            for n_doc, doc_id in enumerate(OrderedDict.fromkeys(c['doc_id'] for c in off)):
                cs = [c for c in off if c['doc_id'] == doc_id]
                pool += cs
                d = docs.get(doc_id, cs[0])
                new, chg, conf, low, chg_r = [], [], [], 0, []  # chg_r: 보고서용(수치·날짜 항목 변경만)
                for c in cs:
                    k = (c['facility'], c['item'])
                    u = unit_of.get(k, c['unit'])
                    ps = [p for p in pool if (p['facility'], p['item']) == k]
                    top = max(rkey(p) for p in ps)
                    vals = list(OrderedDict((norm(p['value']), p['value']) for p in ps if rkey(p) == top).values())
                    now = vals[0] if len(vals) == 1 else None  # None = 같은 순위 문서끼리 값이 달라 충돌
                    name = f"{c['facility']} {c['item']}"
                    if k not in eff:
                        new.append(f'{name} {fmt_value(c["value"], u)}')
                    elif now is None and eff[k] is not None:
                        conf.append(f"{name} {' / '.join(fmt_value(v, u) for v in vals)}")
                    elif now is not None and (eff[k] is None or norm(eff[k]) != norm(now)):
                        chg.append(f"{name} {'확인 필요' if eff[k] is None else fmt_value(eff[k], u)}→{fmt_value(now, u)}")
                        if eff[k] is not None and kinds.get(c['item']) not in ('attr', 'status'):
                            chg_r.append(f"{name} {fmt_value(eff[k], u)} → {fmt_value(now, u)}")
                    elif now is not None and norm(c['value']) != norm(now) or now is None and eff[k] is None and rkey(c) < top:
                        low += 1
                    eff[k] = now
                ver = f" {d.get('version_kind')}" if d.get('version_kind') else ''
                if show_basis:
                    head = f"{stem(doc_id)}({d['stage']}{ver}, {doc_id})"
                    if n_doc == 0:
                        body.append(('b', short_date(d['date']), f'{head} — {len(new)}개 항목 최초 제시'))
                        continue
                    parts = [p for p in (chg and f'값 변경 {len(chg)}건', conf and f'문서 간 값 충돌 {len(conf)}건',
                                         new and f'신규 {len(new)}건',
                                         low and f'상위 문서보다 우선순위가 낮아 {low}건 미반영') if p]
                    body.append(('b', short_date(d['date']), f"{head} — {', '.join(parts) or f'기존 값 확인({len(cs)}개 항목)'}"))
                    body += [('s', clip(x)) for x in (chg, conf, new) if x]
                    continue
                # 보고서용: 문서(사건) 한 줄 + 수치·날짜가 바뀐 항목만. 문장 항목(추진상태 등) 변경·문서 간 상이는 쓰지 않음
                # (상이 항목은 '주요 현안'에 확인 필요로 나온다)
                head = re.sub(r'^\d{6}\s*', '', stem(doc_id))
                head = re.sub(r'^\[[^\]]*\]\s*', '', head)
                body.append(('b', short_date(d['date']), head))
                body += [('s', x) for x in chg_r[:4]]
            if show_basis and informal:
                body.append(('s', f"비공식 자료 {len({c['doc_id'] for _, c in informal})}건은 경위에서 제외(참고로만 표시)"))

        elif sec == '추진현황':
            for fac, fs in by_fac.items():
                main = [f for f in fs if not narr(f['item'])]
                if show_basis:
                    if main:
                        body.append(('b', fac, ', '.join(f"{f['item']} {val(f)}" for f in main)))
                else:  # □ (사업) 제원 한 줄 → ㅇ (추진상태) → ㅇ (현안)  ※ '주요 현안' 목차가 있으면 현안은 거기서만
                    spec = []
                    for f in main:
                        if kinds.get(f['item']) in ('attr', 'status') or f['value'] is None and f['status'] != '미확정(충돌)':
                            continue
                        v = val(f)
                        spec.append(v if f['item'] == '차로' else f"{SPEC_LABEL.get(f['item'], f['item'])} {v}")
                    attr = [f for f in main if f['item'] == '시행주체' and f['value'] is not None]
                    spec += [f"{f['item']} {val(f)}" for f in attr]
                    if spec:
                        body.append(('b', fac, ', '.join(spec)))
                    info = [f"{ {'담당시행자': '담당', '관리상태': '관리', '추진단계': '단계'}[f['item']] } {val(f)}"
                            for f in main if f['item'] in INFO_ITEMS and f['value'] is not None]
                    if info:
                        body.append(('s', ' · '.join(info)))
                    for f in main:
                        if kinds.get(f['item']) == 'status' and f['value'] is not None:
                            body.append(('s', f"({f['item']}) {val(f)}"))
                for f in fs:
                    if kinds.get(f['item']) == 'issue' and f['value'] is not None and '주요 현안' not in sections:
                        body.append(('s', f"(현안) {f['value']}"))
                srcs = OrderedDict()
                for f in main:
                    if f['source_doc'] in docs:
                        d = docs[f['source_doc']]
                        srcs[d['doc_id']] = f"{stem(d['doc_id'])}({d['stage']}, {short_date(d['date'])})"
                if srcs and show_basis:
                    body.append(('s', '근거: ' + '; '.join(srcs.values())))

        elif sec == '주요 변경사항':
            for f in facts:
                if narr(f['item']):
                    continue
                off = sorted((c for c in by_key.get((f['facility'], f['item']), []) if c['stage'] not in INFORMAL),
                             key=lambda c: (c['date'], c['doc_id']))
                if off and f['value'] is not None and norm(off[0]['value']) != norm(f['value']):
                    first = off[0]
                    body.append(('b', f"{f['facility']} {f['item']}",
                                 f"{fmt_value(first['value'], f['unit'])} → {fmt_value(f['value'], f['unit'])}"))
                    if show_basis:
                        body.append(('s', f"최초 {first['doc_id']}({first['stage']}, {short_date(first['date'])}) → "
                                          f"현재 {f['source_doc']}({f['doc_stage']}, {short_date(f['doc_date'])})"))
            body = body or [('b', None, '문서 간 값이 바뀐 항목 없음')]

        elif sec == '주요 현안':
            chosen = {(c['facility'], c['item']): c for c in choices if c['active']}
            plans, delays, remedies = of_kind('plan'), of_kind('delay'), of_kind('remedy')
            issues = of_kind('issue')
            for fac in [x for x in by_fac if x in issues or x in delays]:  # □ (사업) 현안 → ㅇ 쟁점·지연사유 → ⇒ 만회대책
                if fac in issues:
                    head, rest = _split(issues[fac]['value'])
                    body.append(('b', fac, head))
                    body += [('s', r) for r in rest]
                else:
                    body.append(('b', fac, gaejo(delays[fac]['value'])))
                for e in [e for e in events if e['kind'] == '쟁점' and e['facility'] == fac][:4]:  # 쟁점·기관별 입장
                    body.append(('s', e['content']))
                if fac in delays and fac in issues:
                    body.append(('s', f"(지연사유) {gaejo(delays[fac]['value'])}"))
                if fac in remedies:
                    body.append(('act', f"(만회대책) {gaejo(remedies[fac]['value'])}"))
                elif fac in plans and '향후 계획' not in sections:  # 향후 계획 목차가 따로 있으면 거기서만 씀(중복 방지)
                    body.append(('act', f"(대응방안) {plans[fac]['value']}"))
                f = issues.get(fac) or delays[fac]
                if show_basis:
                    body.append(('s', f"근거: {basis(f)}"))
            for f in pending:
                tops = json.loads(f['conflict_candidates'] or '[]')
                if show_basis:
                    cand = ' / '.join(f"{fmt_value(c['value'], f['unit'])}({c['doc_id']}, {c['stage']} {short_date(c['date'])})"
                                      for c in tops)
                    body += [('b', f"{f['facility']} {f['item']}", f'같은 단계·같은 일자 문서 간 값 상이: {cand}'),
                             ('act', '(대응방안) 원문 대조 후 담당자 확정(디딤돌 DB 화면 "값 충돌")')]
                else:
                    cand = ' / '.join(OrderedDict.fromkeys(fmt_value(c['value'], f['unit']) for c in tops))
                    body += [('b', f"{f['facility']} {f['item']}", f'관계기관 문서 간 상이({cand})'),
                             ('act', '(대응방안) 원문 확인 후 확정')]
            # 담당자가 고른 값(문서 간 상이 → 확정)은 내부 판정 기록이라 검토용에서만 보인다
            numeric_pick = []
            for f in facts:
                c = chosen.get((f['facility'], f['item']))
                if c and f['method'] == '사람 선택':
                    if show_basis:
                        body.append(('b', f"{f['facility']} {f['item']}",
                                     f"문서 간 값 상이 → 담당자 선택으로 {val(f)} 확정({c['chooser']}, {c['chosen_at'][:10]})"))
                    elif kinds.get(f['item']) not in ('attr', 'status') + NARR:
                        numeric_pick.append(f"{f['facility']} {f['item']} {val(f)}")
            if numeric_pick:  # 수치가 문서마다 달랐던 항목은 한 줄 주석으로만
                body.append(('note', f"문서 간 수치가 달랐던 {len(numeric_pick)}건은 원문 확인 후 정리"
                                     f"({', '.join(numeric_pick[:3])}{' 등' if len(numeric_pick) > 3 else ''})"))
            body += _user_lines(extra.get(sec))
            body = body or [('b', None, '문서 간 충돌 항목 없음')]

        elif sec == '향후 계획':
            plans = of_kind('plan')
            sched = [e for e in events if e['kind'] == '계획']
            for fac in [x for x in by_fac if (x in plans and x not in used_plan) or any(e['facility'] == x for e in sched)]:
                f = plans.get(fac) if fac not in used_plan else None
                evs = [e for e in sched if e['facility'] == fac]
                if f:
                    head, rest = _split(f['value'])
                    body.append(('b', fac, head))
                    body += [('s', r) for r in rest]
                elif evs:  # 계획 문장이 없으면 첫 일정을 사업 줄에 바로 씀: ㅇ (사업) ’28. 下 ○○ 완료
                    body.append(('b', fac, f"{_ev_date(evs[0]['date'])} {gaejo(evs[0]['content'])}"))
                    evs = evs[1:]
                body += [('s', f"({_ev_date(e['date'])}) {gaejo(e['content'])}") for e in evs[:4]
                         if not f or re.sub(r'\s', '', e['content'])[:12] not in re.sub(r'\s', '', f['value'])]
                if f and show_basis:
                    body.append(('s', f"근거: {basis(f)}"))
            for f in (pending if '대응 방향' not in sections else []):
                body.append(('b', '확인', f"{f['facility']} {f['item']} 원문 확인 후 확정 예정"))
            if not plans and not sched:  # 문서에 향후계획·일정이 없을 때만 완료·개통 예정 시기로 대신함
                timing = [f for f in facts if f['value'] is not None and re.fullmatch(r'\d{4}\.\d{1,2}', str(f['value']))
                          and f['status'] == '확정']
                for v in sorted({str(f['value']) for f in timing}, key=lambda s: tuple(int(x) for x in s.split('.'))):
                    names = [f"{f['facility']} {SPEC_LABEL.get(f['item'], f['item'])}" for f in timing if str(f['value']) == v]
                    body.append(('b', _ym(v), ', '.join(names) + ' 예정'))
            body += _user_lines(extra.get(sec))
            body = body or [('b', None, '문서에서 향후 계획·일정을 찾지 못함')]

        elif sec == '참고(비공식)':
            for f, c in informal:
                v = fmt_value(c['value'], f['unit'] or c['unit'])
                body.append(('b', f"{f['facility']} {f['item']}",
                             f"{stem(c['doc_id'])}({c['doc_id']})에 {v} 기재 → "
                             f"공식 문서 값({val(f) if f['value'] is not None else '미확정'})과 달라 참고로만 표시"
                             if show_basis else f"비공식 의견: {v} (공식 확인 전)"))
            body = body or [('b', None, '비공식 자료 중 공식 값과 다른 내용 없음')]

        elif sec == '종합 의견(AI)':
            body = llm_opinion(B, cfg) if use_llm else [('b', None, 'AI 미사용(API 키가 있을 때 작성)')]

        if sec.startswith('붙임:'):
            if not body:  # 문서에 내용이 없는 붙임은 뺀다(빈 붙임을 보고서에 남기지 않음)
                continue
            att += 1
            B += [('h', f"붙임 {att} {sec.split(':', 1)[1].strip()}")] + body
        else:
            B += [('h', HEADINGS.get(sec, f'□ {sec}'))] + body
    if show_basis:
        B.append(('note', '주) 근거는 출처 문서(문서ID). 판정 근거·변경 이력은 디딤돌 DB 화면에서 확인. '
                          '본 초안은 자동 작성본으로 담당자 검토 후 사용'))
    # 핵심요약(◈): 무엇을 보고하는지 한 문장, 세부 수치 없음 — "(지구명) (보고 주제) 내용을 보고 드림" (스킬 2장)
    head = B[0][1]
    topic = re.sub(r'\s*보고(\s*\(.*\))?$', '', head).strip()
    topic = topic if topic.startswith(district) or not district else f'{district} {topic}'
    if '지구명칭' in dist and district and topic.startswith(district):  # 공식 명칭으로(예: 해오름 공공주택지구)
        topic = dist['지구명칭']['value'] + topic[len(district):]
    if topic.endswith('결과'):
        summary = f'{topic}를 보고 드림'
    else:
        summary = f"{topic} {'결과를' if re.search(r'회의|면담|협의체', head) else '내용을'} 보고 드림"
    B[2:2] = [('summary', summary), ('meta', {'district': district, 'dept': dept, 'date': today.strftime('%Y-%m-%d')})]
    return B


def llm_opinion(blocks, cfg=None):
    text = to_text(blocks)
    try:
        data = llm.ask_json(
            f'[보고서 초안]\n{text}\n\n위 초안을 읽고 "종합 의견" 2~3개를 공공기관 개조식 한 문장씩 써라. '
            '초안에 없는 숫자·사실은 쓰지 않는다. 회사 보고서 작성 원칙을 따른다: 한 항목은 2줄 이내·한 가지 내용, '
            '명사·동사 위주의 능동형, 시제를 명확히(~함, ~중, ~예정), 미사여구·과장 표현 금지, 날짜는 ’26. 11. 4. 형식. '
            '출력 형식: {"opinions": ["...", "..."]}',
            system='너는 공공기관 보고서 검토를 돕는 도구다.', cfg=cfg)
        ops = [o for o in data.get('opinions', []) if isinstance(o, str) and o.strip()][:3]
        return [('b', None, o.strip()) for o in ops] or [('b', None, 'AI 의견 없음')]
    except Exception as e:
        return [('b', None, f'AI 의견 작성 실패: {e}')]


# ---------- 텍스트 / 화면 미리보기 ----------
def line(b):
    k = b[0]
    if k == 'title':
        return b[1]
    if k in ('date', 'h', 'note'):
        return b[1]
    if k == 'summary':
        return f'◈ {b[1]}'
    if k == 'b':
        return f" ㅇ ({b[1]}) {b[2]}" if b[1] else f" ㅇ {b[2]}"
    if k == 's':
        return f"   - {b[1]}"
    if k == 'act':
        return f"   ⇒ {b[1]}"
    return ''


def to_text(blocks):
    out = []
    for b in blocks:
        if b[0] == 'table':
            out.append(f'< {b[1]} >')
            out.append(' | '.join(b[2]))
            out += [' | '.join(r) for r in b[3]]
        elif b[0] != 'meta':
            out.append(line(b))
    return '\n'.join(out)


def to_html(blocks):
    e = html.escape
    out = []
    for b in blocks:
        k = b[0]
        if k == 'title':
            sub = f'<small>{e(b[2])}</small>' if b[2] else ''
            out.append(f'<div class="rp-title"><div>{e(b[1])}</div>{sub}</div>')
        elif k == 'date':
            out.append(f'<div class="rp-date">{e(b[1])}</div>')
        elif k == 'summary':
            out.append(f'<div class="rp-b" style="background:#fffbe6;padding:6px 10px;margin:4px 0 8px">◈ {e(b[1])}</div>')
        elif k == 'h':
            out.append(f'<div class="rp-h">{e(b[1])}</div>')
        elif k == 'b':
            key = f'<b>({e(b[1])})</b> ' if b[1] else ''
            out.append(f'<div class="rp-b">ㅇ {key}{e(b[2])}</div>')
        elif k == 's':
            out.append(f'<div class="rp-s">- {e(b[1])}</div>')
        elif k == 'act':
            out.append(f'<div class="rp-s rp-act">⇒ {e(b[1])}</div>')
        elif k == 'note':
            out.append(f'<div class="rp-note">{e(b[1])}</div>')
        elif k == 'table':
            head = ''.join(f'<th>{e(c)}</th>' for c in b[2])
            body = ''.join('<tr>' + ''.join(f'<td>{e(c)}</td>' for c in r) + '</tr>' for r in b[3])
            out.append(f'<div class="rp-cap">&lt; {e(b[1])} &gt;</div>'
                       f'<div class="rp-tw"><table class="rp-t"><tr>{head}</tr>{body}</table></div>')
    return '<div class="rp-paper">' + ''.join(out) + '</div>'


# ---------- 워드(docx) ----------
def to_docx(blocks):
    import docx
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt, RGBColor

    d = docx.Document()
    st = d.styles['Normal']
    st.font.name, st.font.size = '맑은 고딕', Pt(11)
    st.element.rPr.rFonts.set(qn('w:eastAsia'), '맑은 고딕')
    for s in d.sections:
        s.left_margin = s.right_margin = Cm(2)

    def shade(cell, color):
        tcPr = cell._tc.get_or_add_tcPr()
        sh = OxmlElement('w:shd')
        sh.set(qn('w:val'), 'clear'), sh.set(qn('w:color'), 'auto'), sh.set(qn('w:fill'), color)
        tcPr.append(sh)

    def para(text='', bold=False, size=11, indent=0.0, align=None, after=2):
        p = d.add_paragraph()
        p.paragraph_format.left_indent = Cm(indent)
        p.paragraph_format.space_after = Pt(after)
        if align:
            p.alignment = align
        if text:
            r = p.add_run(text)
            r.bold, r.font.size = bold, Pt(size)
        return p

    for b in blocks:
        k = b[0]
        if k == 'title':
            t = d.add_table(rows=1, cols=1)
            t.style = 'Table Grid'
            t.alignment = WD_TABLE_ALIGNMENT.CENTER
            c = t.cell(0, 0)
            shade(c, 'DDE7F3')
            p = c.paragraphs[0]
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            r = p.add_run(b[1])
            r.bold, r.font.size = True, Pt(17)
            if b[2]:
                p2 = c.add_paragraph()
                p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
                r2 = p2.add_run(b[2])
                r2.font.size, r2.font.color.rgb = Pt(9), RGBColor(0x52, 0x51, 0x4E)
        elif k == 'date':
            para(b[1], size=10, align=WD_ALIGN_PARAGRAPH.RIGHT, after=8)
        elif k == 'summary':
            para('◈ ' + b[1], size=11, after=6)
        elif k == 'h':
            para(b[1], bold=True, size=13, after=4).paragraph_format.space_before = Pt(10)
        elif k == 'b':
            p = para(indent=0.4)
            p.add_run('ㅇ ')
            if b[1]:
                p.add_run(f'({b[1]}) ').bold = True
            p.add_run(b[2])
        elif k == 's':
            para(f'- {b[1]}', size=10, indent=1.0)
        elif k == 'act':
            para(f'⇒ {b[1]}', bold=True, size=10, indent=1.0)
        elif k == 'note':
            para(b[1], size=9, after=0).paragraph_format.space_before = Pt(10)
        elif k == 'table':
            para(f'< {b[1]} >', bold=True, size=10, align=WD_ALIGN_PARAGRAPH.CENTER)
            t = d.add_table(rows=1, cols=len(b[2]))
            t.style = 'Table Grid'
            t.alignment = WD_TABLE_ALIGNMENT.CENTER
            for i, c in enumerate(b[2]):
                cell = t.rows[0].cells[i]
                shade(cell, 'EFEFEC')
                cell.paragraphs[0].add_run(c).bold = True
            for r in b[3]:
                cells = t.add_row().cells
                for i, v in enumerate(r):
                    cells[i].paragraphs[0].add_run(v)
            for row in t.rows:
                for cell in row.cells:
                    for p in cell.paragraphs:
                        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                        for r in p.runs:
                            r.font.size = Pt(9)
            para(after=4)
    buf = BytesIO()
    d.save(buf)
    return buf.getvalue()


# ---------- 한글(hwpx) ----------
def _top_level_paras(sec):
    """section0.xml에서 최상위 <hp:p> 구간(표 안 문단 제외) 위치 목록."""
    spans, depth, start = [], 0, None
    for m in re.finditer(r'<hp:p [^>]*>|</hp:p>', sec):
        if m.group().startswith('</'):
            depth -= 1
            if depth == 0:
                spans.append((start, m.end()))
        else:
            if depth == 0:
                start = m.start()
            depth += 1
    return spans


def _fill(seg, texts):
    """구간 안 <hp:t> 텍스트를 순서대로 바꾼다(남는 칸은 비움). 줄 배치 캐시는 지워 한글이 다시 계산하게 한다."""
    seg = re.sub(r'<hp:linesegarray>.*?</hp:linesegarray>', '', seg, flags=re.S)
    it = iter(texts)
    return re.sub(r'<hp:t>.*?</hp:t>|<hp:t/>', lambda m: f'<hp:t>{escape(next(it, ""))}</hp:t>', seg, flags=re.S)


def to_hwpx(blocks, template=TEMPLATE):
    with zipfile.ZipFile(template) as z:
        infos = z.infolist()
        files = {i.filename: z.read(i.filename) for i in infos}
    sec = files['Contents/section0.xml'].decode('utf-8')
    spans = _top_level_paras(sec)
    segs = [sec[a:b] for a, b in spans]
    head, tail = sec[:spans[0][0]], sec[spans[-1][1]:]
    proto_title, proto_date, proto_blank = segs[0], segs[1], segs[2]
    proto_h = next(s for s in segs if '□' in s)
    proto_hblank = segs[segs.index(proto_h) + 1]
    proto_kb = next(s for s in segs if 'paraPrIDRef="24"' in s)
    proto_plain = next(s for s in segs if 'paraPrIDRef="26"' in s)

    out = []
    for b in blocks:
        k = b[0]
        if k == 'title':
            out.append(_fill(proto_title, [b[1], b[2]]))
        elif k == 'date':
            out += [_fill(proto_date, [b[1]]), _fill(proto_blank, [])]
        elif k == 'h':
            if len(out) > 2:
                out.append(_fill(proto_blank, []))
            out += [_fill(proto_h, [b[1]]), _fill(proto_hblank, [])]
        elif k == 'b':
            out.append(_fill(proto_kb, [' ㅇ ', f'({b[1]})', f' {b[2]}']) if b[1] else _fill(proto_plain, [f' ㅇ {b[2]}']))
        elif k in ('s', 'act', 'note', 'summary'):
            out.append(_fill(proto_plain, [line(b) if k != 'note' else b[1]]))
        elif k == 'table':  # 한글본은 표 대신 '< 표 제목 >' + 행마다 '- 사업명: 열 값, ...'으로 쓴다
            out.append(_fill(proto_plain, [f' < {b[1]} >']))
            for r in b[3]:
                cells = [f'{c} {v}' for c, v in zip(b[2][1:], r[1:]) if v not in ('-', '')]
                out.append(_fill(proto_plain, [f'   - {r[0]}: ' + ', '.join(cells)]))
    # 문단 id를 겹치지 않게 다시 매김
    n = iter(range(3121190098, 3121190098 + 100000))
    body = ''.join(re.sub(r'^<hp:p id="\d+"', lambda m: f'<hp:p id="{next(n)}"', s) for s in out)
    files['Contents/section0.xml'] = (head + body + tail).encode('utf-8')
    files['Contents/header.xml'] = files['Contents/header.xml'].decode('utf-8').replace(
        'breakNonLatinWord="BREAK_WORD"', 'breakNonLatinWord="KEEP_WORD"').encode('utf-8')  # 어절 단위 줄바꿈
    title = next((b[1] for b in blocks if b[0] == 'title'), '보고서')
    files['Preview/PrvText.txt'] = to_text(blocks)[:1000].encode('utf-8')
    hpf = files['Contents/content.hpf'].decode('utf-8')
    files['Contents/content.hpf'] = re.sub(r'<opf:title>.*?</opf:title>', f'<opf:title>{escape(title)}</opf:title>',
                                           hpf).encode('utf-8')
    buf = BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        for i in infos:  # mimetype은 처음·무압축 그대로
            z.writestr(i, files[i.filename], compress_type=i.compress_type)
    return buf.getvalue()
