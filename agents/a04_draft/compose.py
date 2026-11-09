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

from agents.a04_draft import draft, fit
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


def _cut(key, text):
    """두 줄을 넘는 꼭지 → (앞, [뒤]). 앞부분이 두 줄 폭 안에 드는 마지막 쉼표에서 자르고 뒤는 '-' 세부로(괄호 안 쉼표는 건너뜀)."""
    mx = fit.writing()['max_em']
    if fit.item_em(key, text) <= mx:
        return text, []
    depth, cuts = 0, []
    for i, ch in enumerate(text):
        depth += 1 if ch in '(（' else (-1 if ch in ')）' else 0)
        if ch == ',' and depth == 0 and 20 <= fit.item_em(key, text[:i]) <= mx:
            cuts.append(i)
    if not cuts:
        return text, []
    i = cuts[-1]
    return draft.gaejo(text[:i]), [draft.gaejo(text[i + 1:].strip())]


def _groups(body):
    """본문 블록 → 꼭지 묶음 [(시작 위치, 끝 위치)] — ㅇ 하나와 그 아래 '-' 세부"""
    starts = [i for i, b in enumerate(body) if b[0] == 'b'] + [len(body)]
    return [(starts[k], starts[k + 1]) for k in range(len(starts) - 1)]


def _width_job(bodies):
    """폭이 맞지 않는 꼭지: ㅇ가 두 줄 넘김(60칸 초과)·한 줄 반 남짓(48칸 미만), 또는 '-' 세부가 두 줄 넘김"""
    jobs, w = [], fit.writing()
    for name, body in bodies.items():
        for a, z in _groups(body):
            b = body[a]
            ok_max, ok_min, width = fit.fits(b[1], b[2], 'o')
            subs = [x[1] for x in body[a + 1:z] if x[0] == 's']
            sub_over = [round(fit.em(t), 1) for t in subs if not fit.fits(None, t, 'dash')[0]]
            # 담당자 원칙 2: '-' 세부도 두 줄에 가깝게 — 한 줄 남짓한 세부는 위 꼭지에 합치거나 채우게 한다
            sub_short = [round(fit.em(t), 1) for t in subs if fit.em(t) < w['min_em'] * fit.LINE_EM['dash'] / fit.LINE_EM['o']]
            if ok_max and ok_min and not sub_over and not sub_short:
                continue
            jobs.append({'id': f'{name}|{a}|{z}', 'key': b[1] or '', 'text': b[2], 'width': width, 'subs': subs,
                         'problem': ('두 줄 넘침' if not ok_max else ('짧음' if not ok_min else '')) +
                                    (f' / 세부 두 줄 넘침{sub_over}' if sub_over else '') +
                                    (f' / 세부 짧음{sub_short}(본문에 합치거나 두 줄 가깝게)' if sub_short else ''),
                         'target': f"ㅇ {w['min_em']}~{w['max_em']}칸"})
    return jobs


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


def _dates(text):
    """날짜 표기만: ’27 상반기·2027년 하반기·’27 上 → ’27. 上/下"""
    text = re.sub(r"(?:’|20)(\d\d)년?\s*(상|하)반기", lambda m: f"’{m.group(1)}. {'上' if m.group(2) == '상' else '下'}", text)
    return re.sub(r"’(\d\d)\s*([上下])", r"’\1. \2", text)


def _fix(text):
    """스킬 날짜 표기: ’27 상반기 → ’27. 上, 2027년 하반기 → ’27. 下"""
    text = re.sub(r"(?:’|20)(\d\d)년?\s*(상|하)반기", lambda m: f"’{m.group(1)}. {'上' if m.group(2) == '상' else '下'}", text)
    text = re.sub(r"’(\d\d)\s*([上下])", r"’\1. \2", text)  # ’27 上 → ’27. 上
    return draft.gaejo(text)


def _blocks(sec):
    """AI 목차 → 블록"""
    out = []
    for it in sec.get('items') or []:
        key, text = str(it.get('key') or '').replace('**', '').strip().strip('()') or None, _fix(str(it.get('text') or ''))
        if not text:
            continue
        out.append(('b', key, text))
        out += [('s', _fix(str(s))) for s in (it.get('subs') or []) if str(s).strip()]
    return out


BODY_MM = 250 - 32 - 16  # 1쪽에서 머리(제목·결재란)·◈ 요약을 뺀 높이


def body_mm(bodies):
    """본문(□ 목차들) 높이 어림(mm) — fit.block_mm과 같은 기준"""
    h = 0.0
    for body in bodies.values():
        h += fit.GAP_MM['sq'] + fit.LINE_MM
        for b in body:
            if b[0] == 'b':
                h += fit.GAP_MM['o'] + fit.lines(fit.item_em(b[1], b[2]), 'o') * fit.LINE_MM
            elif b[0] == 's':
                h += fit.GAP_MM['dash'] + fit.lines(fit.em(b[1]), 'dash') * fit.LINE_MM
    return round(h, 1)


def _compress(bodies, ok, conflict_vals, system, cfg, rep, data_text=''):
    """본문이 1쪽을 넘으면 AI에게 꼭지를 합치고 덜 중요한 것을 빼 1쪽(ㅇ 8~9개)에 맞추게 한다. 숫자 검사를 통과해야 바꾼다."""
    h = body_mm(bodies)
    rep['page'] = {'before_mm': h, 'limit_mm': BODY_MM}
    if h <= BODY_MM:
        return
    cur = [{'title': n, 'items': [{'key': b[1], 'text': b[2], 'subs': []} if b[0] == 'b' else None for b in body]}
           for n, body in bodies.items()]
    for sec, (n, body) in zip(cur, bodies.items()):  # 세부를 위 꼭지에 붙여 보여 줌
        items = []
        for b in body:
            if b[0] == 'b':
                items.append({'key': b[1], 'text': b[2], 'subs': []})
            elif b[0] == 's' and items:
                items[-1]['subs'].append(b[1])
        sec['items'] = items
    n_items = sum(len(x['items']) for x in cur)
    prompt = (f'아래 본문이 A4 1쪽을 넘는다(어림 {h:.0f}mm, 한도 {BODY_MM}mm, 지금 ㅇ {n_items}개). '
              '같은 목차 구성으로 ㅇ 꼭지를 모두 합쳐 8개 이하(목차당 2~3개)로 줄여라. 겹치는 꼭지는 합치고, 덜 중요한 내용(붙임 표에 있는 수치 변경 등)은 뺀다. '
              '"-" 세부는 쓰지 않는다. 꼭지마다 (핵심어) 포함 48~60칸(두 줄에 가깝게, 두 줄 넘지 않게; 한글 1칸·띄어쓰기 0.5·숫자 0.55·괄호 안 0.87배). '
              '숫자·날짜·사업명·기관명은 그대로, [자료]에 없는 숫자는 만들지 않는다. 꼭지마다 핵심어구 1~2개는 **어구**로 감싼다.\n'
              f'[자료]\n{data_text}\n[지금 본문]\n{json.dumps(cur, ensure_ascii=False)}\n'
              '출력 형식: {"sections": [{"title": "...", "items": [{"key": "...", "text": "...", "subs": []}]}]}')
    try:
        out = llm.ask_json(prompt, system=system, cfg=cfg)
    except Exception as e:
        rep['page']['error'] = str(e)[:200]
        return
    got = {str(x.get('title', '')).strip('□ ').strip(): x for x in (out.get('sections') or []) if isinstance(x, dict)}
    new = {}
    for n in bodies:
        if n not in got:
            return
        body = _blocks(got[n])
        lines = [(b[1] or '') + ' ' + b[2] if b[0] == 'b' else b[1] for b in body]
        if not body or any(bad_numbers(l, ok) for l in lines) or \
                any(x.replace(',', '') in conflict_vals and '확인 필요' not in l for l in lines for x in NUM.findall(l)):
            return  # 하나라도 어긋나면 줄이기 전 본문을 그대로 씀
        new[n] = body
    if body_mm(new) < h:
        bodies.update(new)
        rep['page']['after_mm'] = body_mm(new)


def _refit(bodies, ok, conflict_vals, system, cfg, rep, data_text='', rounds=2):
    """폭이 안 맞는 꼭지만 AI에게 다시 쓰게 한다(꼭지 단위, 최대 2번). 숫자·폭 검사를 통과한 것만 바꾼다."""
    w = fit.writing()
    mid = (w['max_em'] + w['min_em']) / 2
    dash_max = w['max_em'] * fit.LINE_EM['dash'] / fit.LINE_EM['o']
    rep['refit'] = {'asked': 0, 'fixed': 0}
    for _ in range(rounds):
        jobs = _width_job(bodies)
        if not jobs:
            return
        rep['refit']['asked'] += len(jobs)
        prompt = ('아래 보고서 꼭지들의 길이를 고쳐라. 폭은 "칸"으로 센다: 한글 1칸, 띄어쓰기 0.5칸, 숫자·영문 0.55칸, 괄호 안 글자 0.87배. '
                  '본문 한 줄은 30칸이고 줄은 낱말 단위로 바뀌므로 두 줄 끝에 여유를 둔다.\n'
                  f'- ㅇ 본문(text)은 (핵심어) 포함 {w["min_em"]}~{w["max_em"]}칸: 두 줄을 넘지 않되 두 줄에 최대한 가깝게.\n'
                  f'- - 세부(subs)는 하나에 {int(dash_max)}칸 이내, 꼭지당 0~2개.\n'
                  '- "두 줄 넘침": 군더더기·중복을 빼거나 덜 중요한 내용을 덜어 낸다. subs는 새로 만들지 않는다(원래 있던 subs만 유지·합치기).\n'
                  '- "짧음": subs의 내용을 본문에 합치거나, [자료]에 있는 같은 주제의 사유·기관·조건·일정을 보태 두 줄에 가깝게 채운다.\n'
                  '- 숫자·날짜·사업명·기관명은 그대로 쓰고 [자료]에 없는 숫자를 만들지 않는다. 핵심어(key)는 바꾸지 않는다. 개조식 끝맺음. **강조** 표시는 그대로 두거나 핵심어구 1~2개에 다시 붙인다.\n'
                  f'[자료]\n{data_text}\n[고칠 꼭지]\n{json.dumps(jobs, ensure_ascii=False)}\n'
                  '출력 형식: {"items": [{"id": "...", "text": "...", "subs": ["..."]}]}')
        try:
            out = llm.ask_json(prompt, system=system, cfg=cfg)
        except Exception as e:
            rep['refit']['error'] = str(e)[:200]
            return
        by = {str(x.get('id')): x for x in (out.get('items') or []) if isinstance(x, dict)}
        changes = []
        for j in jobs:
            x = by.get(j['id'])
            if not x:
                continue
            txt = _fix(str(x.get('text') or ''))
            subs = [_fix(str(t)) for t in (x.get('subs') or []) if str(t).strip()][:2]
            if not txt:
                continue
            lines = [(j['key'] or '') + ' ' + txt] + subs
            if any(bad_numbers(l, ok) for l in lines) or \
                    any(n.replace(',', '') in conflict_vals and '확인 필요' not in l for l in lines for n in NUM.findall(l)):
                continue
            ok_max, ok_min, width = fit.fits(j['key'] or None, txt, 'o')
            subs_ok = all(fit.fits(None, t, 'dash')[0] for t in subs)
            if ok_max and subs_ok and (ok_min or abs(width - mid) < abs(j['width'] - mid)):
                name, a, z = j['id'].rsplit('|', 2)
                changes.append((name, int(a), int(z), [('b', j['key'] or None, txt)] + [('s', t) for t in subs]))
        for name, a, z, blk in sorted(changes, key=lambda c: -c[1]):  # 뒤에서부터 바꿔야 위치가 안 어긋남
            bodies[name][a:z] = blk
            rep['refit']['fixed'] += 1


def _attach(new, att, ok, conflict_vals, rep):
    """AI가 간추린 붙임 표로 바꾼다(행마다 숫자 검사, 남은 행이 2개 미만이면 규칙 표 그대로)."""
    def safe(cells):
        line = ' '.join(cells)
        return not bad_numbers(line, ok) and not any(n.replace(',', '') in conflict_vals and '확인 필요' not in line
                                                       for n in NUM.findall(line))
    plans = (('관계기관 쟁점', 'issues', '주요 쟁점별 관계기관 의견', ['쟁점', '관계기관', '의견', 'LH 의견(대응방안)'],
              ('쟁점', '관계기관', '의견', 'LH의견'), 10),
             ('추진 경위·일정', 'schedule', '추진 경위 및 향후 일정', ['시기', '추진 내용', '비고'], ('시기', '내용', '비고'), 12))
    rep['attach'] = {}
    for label, key, cap, cols, fields, mx in plans:
        rows = [[_fix(str(r.get(f) or '').replace('**', '')).strip() if f != '시기' else _dates(str(r.get(f) or '')).strip() for f in fields]
                for r in (att.get(key) or []) if isinstance(r, dict)]
        rows = [r for r in rows if any(r) and safe(r)][:mx]
        i = next((k for k, b in enumerate(new) if b[0] == 'h' and b[1].startswith('붙임') and b[1].endswith(label)), None)
        if i is None or len(rows) < 2:
            continue
        j = next((k for k in range(i + 1, len(new)) if new[k][0] == 'table'), None)
        if j is None or any(new[k][0] == 'h' for k in range(i + 1, j)):
            continue
        new[j] = ('table', cap, cols, rows)
        rep['attach'][label] = len(rows)


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
        '0. 본문(□ 3개)은 A4 1쪽에 들어가게 상급자가 알아야 할 핵심만: ㅇ 꼭지는 모두 합쳐 8~9개, 목차당 2~3개, "-" 세부는 원칙적으로 쓰지 않는다(꼭 필요할 때 본문 전체 2개 이내). '
        '사업마다 꼭지를 만들지 말고 쟁점(현황·종점·시행방식·사업비·일정 등)으로 묶는다. 덜 중요한 사업 내용은 붙임 표에 있으므로 본문에서 뺀다.\n'
        '1. 꼭지마다 (핵심어) + 한 문장. 핵심어는 2~6자의 쟁점·주제(예: 사업 현황, 종점, 시행방식, 사업비, 협의, 일정, 재원). '
        '사업이 여럿이고 사업마다 쓸 때만 사업명을 핵심어로 쓴다.\n'
        '2. 추진 현황 및 문제점: 첫 꼭지는 (사업 현황)으로 지구 전체를 한 줄로 — 사업 수·총사업비·핵심 사업 수치를 괄호로 묶고 '
        '"~을 목표로 추진 중이나 ~ 지속"처럼 문제로 이어지게. 나머지 꼭지는 현안·쟁점·지연을 기관별 입장과 함께. 값이 바뀐 것은 "○○ → ○○"로 문장 안에.\n'
        '3. 대응 방향: 문제점 꼭지와 같은 핵심어 순서로 LH 대응방안·만회대책. 자료에 없는 대응은 지어내지 말고 "~ 검토 필요"처럼 짧게.\n'
        '4. 향후 계획: 날짜가 있는 일정을 (협의)·(일정) 등으로 묶어 ’26.6월, ’26. 下 표기로. 이미 지난 날짜(보고 날짜 이전)는 쓰지 않는다.\n'
        '5. 숫자는 자료에 있는 것만 그대로 쓴다. 더하기·빼기·추정 금지(사업 개수 세기만 허용). 문서마다 다른 값은 숫자 없이 "확인 필요".\n'
        '6. 개조식 명사형 끝맺음(~함·~임·~예정·~필요·~요청·~지속·~검토). 꼭지(ㅇ·-)는 두 줄을 넘지 않되 두 줄에 최대한 가깝게 채운다. '
        '본문 한 줄은 한글 약 30자(띄어쓰기는 반 칸, 숫자·영문·괄호 안 작은 글자는 좁음)이므로 (핵심어) 포함 공백 포함 약 60~72자가 알맞다. '
        '넘치면 꼭지를 나누거나 "subs"(- 세부, 꼭지당 2개 이내)로 내리고, 짧으면 자료에 있는 사유·기관·조건을 보태 채운다. '
        '값이 바뀐 사실은 꼭 필요한 것만(사업비·개통·착공 등) 쓴다.\n'
        '7. ◈ 핵심요약: "(무엇) (현안 검토/추진 현황) 결과를 보고 드림" 또는 "~ 내용을 보고 드림" 한 문장, 숫자 없이.\n'
        '8. 붙임 표(각 표가 A4 한 쪽 안에, 칸마다 짧게 — 13pt 표 한 줄에 들어가게): '
        '"issues"는 관계기관 쟁점 표 행(자료의 관계기관 쟁점만): 쟁점 2~8자, 관계기관 2~6자, 의견 28자 이내, LH의견 24자 이내, '
        '같은 쟁점의 둘째 행부터 쟁점·LH의견은 빈 문자열, 겹치는 의견은 합쳐 최대 10행. LH·사업시행자 입장은 관계기관 행으로 쓰지 말고 LH의견 칸에 쓴다. 각 행의 의견·LH의견은 그 행의 쟁점에 관한 것만 쓴다(다른 쟁점 내용을 끼워 넣지 않음). '
        '"schedule"은 추진 경위·일정 표 행: 시기(’26.6월·’26. 下·’26.6월~’26.8월 표기), 내용 20자 이내, 비고 12자 이내(없으면 빈 문자열), '
        '최근 실적 3~4건 + 보고 날짜 이후 일정, 같은 일은 한 번만, 날짜순 최대 12행.\n'
        '9. 꼭지마다 상급자가 꼭 봐야 할 핵심어구 1~2개(결정·쟁점·핵심 수치, 4~12자)를 **어구**처럼 별표 두 개로 감싼다(수정본의 굵은 글씨). '
        '(핵심어)와 괄호 안은 감싸지 않는다.\n'
        '출력 형식: {"summary": "...", "sections": [{"title": "추진 현황 및 문제점", "items": [{"key": "사업 현황", "text": "...", "subs": []}]}], '
        '"attach": {"issues": [{"쟁점": "", "관계기관": "", "의견": "", "LH의견": ""}], "schedule": [{"시기": "", "내용": "", "비고": ""}]}}')
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
    new, bodies = list(blocks), {}
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
        bodies[name] = body
    _compress(bodies, ok, conflict_vals, system, c, rep, data_text)  # 본문 1쪽 맞추기
    _refit(bodies, ok, conflict_vals, system, c, rep, data_text)  # 두 줄에 맞추기(AI 2차) → 그래도 넘치면 쉼표에서 나눔
    for name, body in bodies.items():
        out_b, skip = [], False
        for b in body:
            line = (b[1] or '') + ' ' + b[2] if b[0] == 'b' else b[1]
            if name == '향후 계획' and _past_only(line, meta.get('date', '')):  # 다시 쓴 뒤에도 지난 일정은 뺀다
                rep['dropped'].append((line.strip(), '보고 날짜 이전 일정'))
                skip = b[0] == 'b'
                continue
            if b[0] == 's' and skip:
                continue
            skip = False
            if b[0] == 'b':
                head, more = _cut(b[1], b[2])
                out_b += [('b', b[1], head)] + [('s', m) for m in more if m]
            else:
                out_b.append(b)
        if name == '향후 계획' and not any(b[0] == 'b' for b in out_b):
            out_b = [('b', None, '보고 날짜 이후 일정이 문서에 없음(최신 자료 확인 필요)')]
        i = new.index(('h', f'□ {name}'))
        j = next((k for k in range(i + 1, len(new)) if new[k][0] == 'h'), len(new))
        new[i + 1:j] = out_b
        rep['written'].append(name)
    _attach(new, out.get('attach') or {}, ok, conflict_vals, rep)  # 붙임 표: 한 쪽 안으로 간추린 표
    summ = str(out.get('summary') or '').replace('**', '').strip().lstrip('◈ ').strip()
    if summ and not NUM.search(summ) and summ.endswith('보고 드림'):
        new = [('summary', summ) if b[0] == 'summary' else b for b in new]
        rep['summary'] = summ
    return new, rep
