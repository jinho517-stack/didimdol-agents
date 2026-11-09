"""A04 ③ AI 본문 작성: 담당자가 고친 보고서(수정본)를 예시로 주고, DB 값·경위·쟁점으로 본문(□ 3개)을 새로 쓰게 한다.

규칙 초안은 DB 값을 항목별로 옮겨 적기만 해서 '수치를 띡 가져다 쓴' 글이 된다. 담당자 수정본은
  ㅇ (사업 현황) 해오름선(9.8km, 7,600억원)은 ’32.6월 개통을 목표로 추진 중이나 종점·시행 방식 이견 지속
처럼 여러 값과 쟁점을 한 줄에 엮고, 핵심어도 사업명이 아니라 쟁점(종점·시행방식·사업비·협의·일정)으로 잡는다.
그래서 본문은 AI가 예시 문체로 쓰고, 붙임 표는 규칙 초안(DB 값 그대로)을 쓴다.

안전장치(숫자는 DB 값 그대로)
 - 본문의 숫자는 하나하나 넘겨준 자료에 있는 숫자인지 검사한다(연도 두 자리·월 표기는 같은 숫자로 봄). 없는 숫자가 든 줄은 버린다.
 - 문서 간 값이 다른 항목은 숫자 대신 '확인 필요'로 쓰게 하고, 그 후보 숫자를 확정값처럼 쓰면 버린다.
 - 한 목차에서 버린 줄이 절반을 넘거나 AI가 실패하면 그 목차는 규칙 초안을 그대로 쓴다.
"""
import json
import re
import time
from pathlib import Path

from agents.a04_draft import draft
from agents.a04_draft import skill as SK
from common import llm
from common.fmt import fmt_value

EXAMPLES = Path(__file__).resolve().parents[2] / 'skills' / 'lh_report_style' / 'examples'
BODY = ['추진 현황 및 문제점', '대응 방향', '향후 계획']
NUM = re.compile(r'\d[\d,]*(?:\.\d+)?')
NARR = {'issue': '현안', 'delay': '지연사유', 'remedy': '만회대책', 'plan': '향후계획', 'status': '추진상태'}


def examples():
    return '\n\n'.join(p.read_text(encoding='utf-8').strip() for p in sorted(EXAMPLES.glob('*.txt')))


def _num_forms(tok):
    """숫자 하나 → 같은 숫자로 보는 표기들(2032.6 → 32.6, 2032 → 32, 7,600 → 7600)"""
    t = tok.replace(',', '').rstrip('.')
    out = {t}
    m = re.fullmatch(r'20(\d\d)(\.\d{1,2})?(\.\d{1,2})?', t)
    if m:
        out |= {m.group(1), m.group(1) + (m.group(2) or ''), m.group(1) + (m.group(2) or '') + (m.group(3) or '')}
    for part in t.split('.'):  # 2026.6.17 → 2026, 6, 17
        out.add(part.lstrip('0') or '0')
    return out


def allowed_numbers(text):
    ok = set()
    for tok in NUM.findall(text):
        ok |= _num_forms(tok)
    return ok


def bad_numbers(line, ok):
    """줄에 있는 숫자 중 자료에 없는 것(12 이하 작은 정수는 월·개수라 허용)"""
    bad = []
    for tok in NUM.findall(line):
        t = tok.replace(',', '').rstrip('.')
        if re.fullmatch(r'\d{1,2}', t) and int(t) <= 12 or t in ok:
            continue
        bad.append(tok)
    return bad


def payload(res3, events, cands, district, kinds):
    """AI에 넘길 자료(사업지구·사업별 값·문장 항목·변경·확인 필요·경위·계획·쟁점)."""
    facts = res3['facts']
    dist = {f['item']: f for f in facts if f['facility'] == draft.DISTRICT_FAC and f['value'] is not None}
    out = {'사업지구': {k: fmt_value(f['value'], f['unit']) for k, f in dist.items()} | {'이름': district}, '사업': []}
    by_key = {}
    for c in cands:
        by_key.setdefault((c['facility'], c['item']), []).append(c)
    pending = []
    for fac in dict.fromkeys(f['facility'] for f in facts if f['facility'] != draft.DISTRICT_FAC):
        p = {'사업명': fac, '값': {}, '변경': []}
        for f in [f for f in facts if f['facility'] == fac]:
            k = kinds.get(f['item'])
            if f['status'] == '미확정(충돌)':
                tops = json.loads(f.get('conflict_candidates') or '[]')
                cand = ' / '.join(dict.fromkeys(fmt_value(c['value'], f['unit']) for c in tops))
                p.setdefault('확인필요', []).append(f"{f['item']}: 문서마다 다름({cand}) → 본문에는 숫자 없이 '{f['item']} 확인 필요'로")
                pending.append((fac, f['item'], [str(c['value']) for c in tops]))
                continue
            if f['value'] is None:
                continue
            if k in NARR:
                p[NARR[k]] = f['value']
            else:
                p['값'][f['item']] = fmt_value(f['value'], f['unit'])
                off = sorted((c for c in by_key.get((fac, f['item']), []) if c['stage'] not in draft.INFORMAL),
                             key=lambda c: (c['date'], c['doc_id']))
                if off and draft.norm(off[0]['value']) != draft.norm(f['value']):
                    p['변경'].append(f"{f['item']} {fmt_value(off[0]['value'], f['unit'])} → {fmt_value(f['value'], f['unit'])}"
                                   f"({off[0]['date']} 문서 → {f.get('doc_date') or ''} 문서)")
        if not p['변경']:
            p.pop('변경')
        out['사업'].append(p)
    for kind, name in (('경위', '추진경위'), ('계획', '향후 일정'), ('쟁점', '관계기관 쟁점')):
        rows = [f"[{e['date'] or '날짜 없음'}] {'지구 공통' if e['facility'] == draft.DISTRICT_FAC else e['facility']}: {e['content']}"
                for e in events if e['kind'] == kind]
        if rows:
            out[name] = rows[-30:]
    return out, pending


LONG = 100  # 꼭지가 이보다 길면(두 줄 넘김) 쉼표에서 나눠 뒷부분을 '-' 세부로


def _cut(text):
    """긴 꼭지 → (앞, [뒤]). 앞부분이 LONG 안에 들도록 마지막 쉼표에서 자른다(괄호 안 쉼표는 건너뜀)."""
    if len(text) <= LONG:
        return text, []
    depth, cuts = 0, []
    for i, ch in enumerate(text):
        depth += ch in '(（' and 1 or (-1 if ch in ')）' else 0)
        if ch == ',' and depth == 0 and 25 <= i <= LONG:
            cuts.append(i)
    if not cuts:
        return text, []
    i = cuts[-1]
    return draft.gaejo(text[:i]), [draft.gaejo(text[i + 1:].strip())]


def _past_only(line, report_date):
    """줄에 적힌 날짜(’26.6월, ’26.6~8월, ’26. 下 등)가 모두 보고 날짜(YYYY-MM-DD)보다 앞이면 True"""
    m = re.match(r'20(\d\d)-(\d\d)', report_date or '')
    if not m:
        return False
    now = (int(m.group(1)), int(m.group(2)))
    ends = []
    for yy, mm, mm2, half in re.findall(r"’(\d\d)\.\s*(?:(\d{1,2})(?:\s*~\s*(\d{1,2}))?월|(上|下))", line):
        mon = int(mm2 or mm) if mm else (6 if half == '上' else 12)
        ends.append((int(yy), mon))
    return bool(ends) and all(e < now for e in ends)


def _fix(text):
    """스킬 날짜 표기: ’27 상반기 → ’27. 上, 2027년 하반기 → ’27. 下"""
    text = re.sub(r"(?:’|20)(\d\d)년?\s*(상|하)반기", lambda m: f"’{m.group(1)}. {'上' if m.group(2) == '상' else '下'}", text)
    return draft.gaejo(text)


def _blocks(sec):
    """AI 목차 → 블록"""
    out = []
    for it in sec.get('items') or []:
        key, text = str(it.get('key') or '').strip().strip('()') or None, _fix(str(it.get('text') or ''))
        if not text:
            continue
        text, more = _cut(text)
        out.append(('b', key, text))
        out += [('s', m) for m in more if m]
        out += [('s', _fix(str(s))) for s in (it.get('subs') or []) if str(s).strip()]
    return out


def run(blocks, res3, events, cands, district, cfg=None, kinds=None, sections=BODY, path=SK.PATH):
    """반환: (새 블록 목록, 결과) — 결과 = {'written':[목차], 'kept_rule':[(목차, 이유)], 'dropped':[(줄, 이유)], 'seconds', 'error'}"""
    rep = {'written': [], 'kept_rule': [], 'dropped': [], 'seconds': 0, 'error': None, 'summary': None}
    want = [s for s in BODY if s in sections and ('h', f'□ {s}') in blocks]
    if not want:
        return blocks, rep
    kinds = kinds or {}
    data, pending = payload(res3, events, cands, district, kinds)
    data_text = json.dumps(data, ensure_ascii=False)
    sk = SK.load(path)
    title = next((b[1] for b in blocks if b[0] == 'title'), '')
    meta = next((b[1] for b in blocks if b[0] == 'meta'), {})
    system = ('너는 LH(한국토지주택공사) 광역교통 담당자다. 내부 현안 보고서 본문을 개조식으로 쓴다.\n'
              '아래 [담당자가 고친 보고서]가 정답 문체다. 핵심어 잡는 법, 한 줄에 수치·기관·입장을 엮는 법, 끝맺음, 날짜 표기를 그대로 따른다.\n\n'
              f'[담당자가 고친 보고서 — 모의 예시]\n{examples()}\n\n[스킬: {sk["title"]} v{sk["version"]} 문장 규칙]\n{sk["rules"]}')
    prompt = (
        f'[보고서 제목] {title}\n[보고 날짜] {meta.get("date", "")}\n[사업지구] {district}\n'
        f'[자료(DB 최신값·문서에서 뽑은 경위·계획·쟁점)]\n{data_text}\n\n'
        f'위 자료만 써서 본문 목차 {", ".join(want)}를 써라.\n'
        '쓰는 법\n'
        '1. 각 목차는 ㅇ 꼭지 2~5개. 꼭지마다 (핵심어) + 한 문장. 핵심어는 2~6자의 쟁점·주제(예: 사업 현황, 종점, 시행방식, 사업비, 협의, 일정, 재원). '
        '사업이 여럿이고 사업마다 쓸 때만 사업명을 핵심어로 쓴다.\n'
        '2. 추진 현황 및 문제점: 첫 꼭지는 (사업 현황)으로 지구 전체를 한 줄로 — 사업 수·총사업비·핵심 사업 수치를 괄호로 묶고 '
        '"~을 목표로 추진 중이나 ~ 지속"처럼 문제로 이어지게. 나머지 꼭지는 현안·쟁점·지연을 기관별 입장과 함께. 값이 바뀐 것은 "○○ → ○○"로 문장 안에.\n'
        '3. 대응 방향: 문제점 꼭지와 같은 핵심어 순서로 LH 대응방안·만회대책. 자료에 없는 대응은 지어내지 말고 "~ 검토 필요"처럼 짧게.\n'
        '4. 향후 계획: 날짜가 있는 일정을 (협의)·(일정) 등으로 묶어 ’26.6월, ’26. 下 표기로. 이미 지난 날짜(보고 날짜 이전)는 쓰지 않는다.\n'
        '5. 숫자는 자료에 있는 것만 그대로 쓴다. 더하기·빼기·추정 금지(사업 개수 세기만 허용). 문서마다 다른 값은 숫자 없이 "확인 필요".\n'
        '6. 개조식 명사형 끝맺음(~함·~임·~예정·~필요·~요청·~지속·~검토). 한 꼭지는 두 줄(90자) 이내로 한 가지 내용만 — 넘치면 꼭지를 나누거나 "subs"(- 세부, 꼭지당 2개 이내)로 내린다. '
        '값이 바뀐 사실은 꼭 필요한 것만(사업비·개통·착공 등) 쓴다.\n'
        '7. ◈ 핵심요약: "(무엇) (현안 검토/추진 현황) 결과를 보고 드림" 또는 "~ 내용을 보고 드림" 한 문장, 숫자 없이.\n'
        '출력 형식: {"summary": "...", "sections": [{"title": "추진 현황 및 문제점", "items": [{"key": "사업 현황", "text": "...", "subs": []}]}]}')
    t0 = time.time()
    try:
        c = dict(cfg or llm.load_config())
        c['llm'] = dict(c.get('llm', {}), effort='medium')  # 글쓰기는 조금 더 생각하게
        out = llm.ask_json(prompt, system=system, cfg=c)
    except Exception as e:
        rep['error'], rep['seconds'] = str(e)[:300], round(time.time() - t0, 1)
        return blocks, rep
    rep['seconds'] = round(time.time() - t0, 1)
    ok = allowed_numbers(data_text + ' ' + title + ' ' + str(meta.get('date', '')))
    conflict_vals = {v.replace(',', '') for _, _, vs in pending for v in vs}
    new = list(blocks)
    got = {str(s.get('title', '')).strip('□ ').strip(): s for s in (out.get('sections') or []) if isinstance(s, dict)}
    for name in want:
        sec = got.get(name)
        if not sec:
            rep['kept_rule'].append((name, 'AI가 이 목차를 쓰지 않음'))
            continue
        body, dropped = [], 0
        for b in _blocks(sec):
            line = (b[1] or '') + ' ' + (b[2] if b[0] == 'b' else b[1])
            bad = bad_numbers(line, ok)
            hit = [n for n in NUM.findall(line) if n.replace(',', '') in conflict_vals and '확인 필요' not in line]
            if bad or hit:
                dropped += 1
                rep['dropped'].append((line.strip(), f"자료에 없는 숫자 {', '.join(bad)}" if bad else
                                       f"문서마다 다른 값({', '.join(hit)})을 확정처럼 씀"))
                continue
            if name == '향후 계획' and _past_only(line, meta.get('date', '')):
                rep['dropped'].append((line.strip(), '보고 날짜 이전 일정'))
                continue
            if b[0] == 's' and (not body or body[-1][0] not in ('b', 's')):
                continue
            body.append(b)
        n_b = sum(1 for b in body if b[0] == 'b')
        if name == '향후 계획' and not n_b and not dropped:  # 문서에 보고 날짜 이후 일정이 없음
            body, n_b = [('b', None, '보고 날짜 이후 일정이 문서에 없음(최신 자료 확인 필요)')], 1
        if not n_b or dropped > n_b:
            rep['kept_rule'].append((name, f'버린 줄이 많음({dropped}줄)' if dropped else '쓸 줄이 없음'))
            continue
        i = new.index(('h', f'□ {name}'))
        j = next((k for k in range(i + 1, len(new)) if new[k][0] == 'h'), len(new))
        new[i + 1:j] = body
        rep['written'].append(name)
    summ = str(out.get('summary') or '').strip().lstrip('◈ ').strip()
    if summ and not NUM.search(summ) and summ.endswith('보고 드림'):
        new = [('summary', summ) if b[0] == 'summary' else b for b in new]
        rep['summary'] = summ
    return new, rep
