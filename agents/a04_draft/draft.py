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
SECTIONS = ['개요', '사업개요', '추진경위', '추진현황', '주요 변경사항', '주요 현안', '향후 계획', '참고(비공식)', '종합 의견(AI)']
SECTION_HELP = {
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
PRESETS = {  # 양식 이름: (기본 제목 꼬리, 기본 목차)
    '추진현황 보고': ('광역교통개선대책 추진현황 보고', ['개요', '사업개요', '추진현황', '주요 변경사항', '주요 현안', '참고(비공식)']),
    '현안사항 보고': ('광역교통 현안사항 보고', ['사업개요', '추진경위', '주요 현안', '향후 계획']),
    '총괄 현황표': ('광역교통개선대책 총괄 현황', ['사업개요', '추진현황']),
    '직접 구성': ('광역교통 보고', []),
}
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


def build(facts, cands, sources, choices, title='', district='', dept='', sections=None, extra=None,
          use_llm=False, cfg=None, order=None, kinds=None, show_basis=False):
    """sections: 넣을 목차 이름 목록(SECTIONS 순서로 배치). extra: {목차 이름: 직접 입력 텍스트}.
    order: [(시설, 항목), ...] 보고서에 쓸 순서(config.yaml items 순서). 없으면 이름순.
    kinds: {항목 이름: 'status'|'issue'|'plan'} 문장형 항목 구분(config.yaml items의 kind). 나머지는 값 항목.
    show_basis: True면 검토용으로 근거 문서·문서ID·판정 설명을 붙인다. 기본은 보고서 내용만."""
    kinds = kinds or {}
    NARR = ('issue', 'plan')  # 현안·향후계획: 표·변경 목록에 넣지 않고 해당 목차에서 문장으로 씀
    sections = [s for s in SECTIONS if s in (sections if sections is not None else PRESETS['추진현황 보고'][1])]
    extra = extra or {}
    today = datetime.now()
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
        return '확인 필요' if f['status'] == '미확정(충돌)' else fmt_value(f['value'], f['unit'])

    def narr(item):
        return kinds.get(item) in NARR

    def of_kind(kind):
        return {f['facility']: f for f in facts if kinds.get(f['item']) == kind and f['value'] is not None}

    def basis(f):
        d = docs.get(f['source_doc'])
        return f"{stem(d['doc_id'])}({d['stage']}, {short_date(d['date'])})" if d else ''

    B = [('title', title.strip() or f"{district} {PRESETS['추진현황 보고'][0]}",
          '디딤돌 자동 작성 초안(검토 전)' if show_basis else ''),
         ('date', f"<{short_date(today.strftime('%Y-%m-%d'))} {dept or '담당부서'}>")]

    for sec in sections:
        body = []
        if sec == '개요':
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

        elif sec == '사업개요':
            # 열 합치기(A4 한 장 폭): 개통목표 → 완료(개통), 지원액 → 사업비. 수치 열 다음에 시행주체·추진상태
            merge = {'개통목표': '완료시기', '지원액': '사업비'}
            label = {'완료시기': '완료(개통)', '사업비': '사업비(억원)'}
            present = OrderedDict.fromkeys(merge.get(f['item'], f['item']) for f in facts if not narr(f['item']))
            items = sorted(present, key=lambda i: (kinds.get(i) in ('attr', 'status'), item_rank.get(i, 999), i))
            units = {f['item']: f['unit'] for f in facts if f['unit'] and f['unit'] != f['item']}
            cols = ['사업명'] + [label.get(i) or (f"{i}({units[i]})" if i in units else i) for i in items] + \
                (['근거'] if show_basis else [])
            rows = []
            for fac, fs in by_fac.items():
                m = {}
                for f in fs:
                    m.setdefault(merge.get(f['item'], f['item']), f)
                srcs = list(OrderedDict.fromkeys(f['source_doc'] for f in fs if f['source_doc']))
                rows.append([fac] + [('확인 필요' if m[i]['status'] == '미확정(충돌)' else fmt_value(m[i]['value']))
                                     if i in m else '-' for i in items] + ([', '.join(srcs)] if show_basis else []))
            costs = [float(f['value']) for f in facts if f['item'] == '사업비' and f['value'] is not None
                     and re.fullmatch(r'\d+(\.\d+)?', str(f['value']))]
            body = [('b', '사업 구성', f"{district} 광역교통개선대책 {len(by_fac)}개 사업"
                                    + (f", 사업비 합계 {fmt_value(str(int(sum(costs))) if sum(costs).is_integer() else str(sum(costs)), '억원')}"
                                       f"({len(costs)}개 사업 기준)" if costs else '')),
                    ('table', '사업개요', cols, rows)]

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
                new, chg, conf, low = [], [], [], 0
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
                # 보고서용: 무엇이 바뀌었는지만. 반영되지 않은 문서(하위 단계·값 그대로)는 쓰지 않음
                head = re.sub(r'^\d{6}\s*', '', stem(doc_id))
                if n_doc == 0:
                    body.append(('b', short_date(d['date']), head))
                elif chg or conf or new:
                    body.append(('b', short_date(d['date']), head))
                    body += [('s', x) for x in chg[:4] + [f'{x} (문서 간 상이)' for x in conf] + new[:3]]
            if show_basis and informal:
                body.append(('s', f"비공식 자료 {len({c['doc_id'] for _, c in informal})}건은 경위에서 제외(참고로만 표시)"))

        elif sec == '추진현황':
            for fac, fs in by_fac.items():
                main = [f for f in fs if not narr(f['item'])]
                if main:
                    body.append(('b', fac, ', '.join(f"{f['item']} {val(f)}" for f in main)))
                for f in fs:
                    if kinds.get(f['item']) == 'issue' and f['value'] is not None:
                        body.append(('s', f"현안: {f['value']}"))
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
            status = of_kind('status')
            for fac, f in of_kind('issue').items():  # 문서에서 뽑은 사업별 현안
                body.append(('b', fac, f['value']))
                st = status.get(fac)
                sub = [f"추진상태: {st['value']}"] if st else []
                if show_basis:
                    sub.append(f"근거: {basis(f)}")
                if sub:
                    body.append(('s', ' · '.join(sub)))
            for f in pending:
                tops = json.loads(f['conflict_candidates'] or '[]')
                if show_basis:
                    cand = ' / '.join(f"{fmt_value(c['value'], f['unit'])}({c['doc_id']}, {c['stage']} {short_date(c['date'])})"
                                      for c in tops)
                    body += [('b', f"{f['facility']} {f['item']}", f'같은 단계·같은 일자 문서 간 값 상이: {cand}'),
                             ('act', '(대응방안) 원문 대조 후 담당자 확정(디딤돌 대시보드 "확인 필요")')]
                else:
                    cand = ' / '.join(OrderedDict.fromkeys(fmt_value(c['value'], f['unit']) for c in tops))
                    body += [('b', f"{f['facility']} {f['item']}", f'관계기관 문서 간 상이({cand})'),
                             ('act', '(대응방안) 원문 확인 후 확정')]
            for f in facts:
                c = chosen.get((f['facility'], f['item']))
                if c and f['method'] == '사람 선택':
                    body.append(('b', f"{f['facility']} {f['item']}",
                                 f"문서 간 값 상이 → 담당자 선택으로 {val(f)} 확정({c['chooser']}, {c['chosen_at'][:10]})"
                                 if show_basis else f"관계기관 문서 간 상이하였으나 확인 결과 {val(f)}로 정리"))
            body += _user_lines(extra.get(sec))
            body = body or [('b', None, '문서 간 충돌 항목 없음')]

        elif sec == '향후 계획':
            for fac, f in of_kind('plan').items():  # 문서에서 뽑은 사업별 향후계획
                body.append(('b', fac, f['value']))
                if show_basis:
                    body.append(('s', f"근거: {basis(f)}"))
            for f in pending:
                body.append(('b', '확인', f"{f['facility']} {f['item']} 원문 확인 후 확정"))
            timing = [f for f in facts if f['value'] is not None and re.fullmatch(r'\d{4}\.\d{1,2}', str(f['value']))
                      and f['status'] == '확정']
            for v in sorted({str(f['value']) for f in timing}, key=lambda s: tuple(int(x) for x in s.split('.'))):
                names = [f"{f['facility']}({f['item']})" for f in timing if str(f['value']) == v]
                body.append(('b', f'{v} 예정', ', '.join(names)))
            body += _user_lines(extra.get(sec))
            body = body or [('b', None, '(직접 입력)')]

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

        B += [('h', HEADINGS.get(sec, f'□ {sec}'))] + body
    if show_basis:
        B.append(('note', '주) 근거는 출처 문서(문서ID). 판정 근거·변경 이력은 디딤돌 대시보드에서 확인. '
                          '본 초안은 자동 작성본으로 담당자 검토 후 사용'))
    # 핵심요약(◈, 회사 양식의 요약 상자): 사업 수·확인 필요·현안 사업 / 양식 적용에 쓰는 정보(meta)
    issue_facs = list(of_kind('issue'))
    summary = f'{district} 광역교통개선대책 {len(by_fac)}개 사업 추진현황' + \
        (f', 현안 {len(issue_facs)}건({", ".join(issue_facs[:2])}{" 등" if len(issue_facs) > 2 else ""})' if issue_facs else '') + \
        (f', 확인 필요 {len(pending)}건' if pending else '') + ' 정리'
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
