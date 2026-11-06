"""A02 최신값 판정 규칙 엔진 (기준 구현, LLM 없이 규칙만 사용).
입력: A01이 만든 항목 후보 표(CSV). 출력: 항목별 최신값, 판정 유형, 변경 이력, 사람 선택 필요 목록.
문서를 어떤 순서로 넣어도 같은 결과가 나오도록 전체 후보를 매번 다시 계산한다."""
import csv
from collections import defaultdict

STAGE_RANK = {'확정': 4, '승인': 4, '확정·승인본': 4, '협의결과': 3, '보고': 2, '초안': 1}
VERSION_RANK = {'최종': 3, '변경안': 2, '원안': 1, '': 0}
INFORMAL = {'비공식', '메모'}


def norm(v):
    return str(v).replace(',', '').replace(' ', '').strip()


def key(c):
    return (STAGE_RANK[c['stage']], c['date'], VERSION_RANK.get(c.get('version_kind', ''), 0))


def load(path):
    with open(path, encoding='utf-8') as f:
        return list(csv.DictReader(f))


def resolve(cands, choices=None):
    """choices: {(시설, 항목): 사람이 선택한 값}  → 사람 선택 반영"""
    choices = choices or {}
    groups = defaultdict(list)
    for c in cands:
        groups[(c['facility'], c['item'])].append(c)
    out = []
    for (fac, item), cs in sorted(groups.items()):
        official = [c for c in cs if c['stage'] not in INFORMAL]
        informal = [c for c in cs if c['stage'] in INFORMAL]
        row = dict(facility=fac, item=item, value=None, unit='', status='', method='', source='', note='', history='', candidates=[])
        if not official:
            row.update(status='참고', method='공식 문서 없음', note='비공식 메모만 있음: ' + ', '.join(c['value'] for c in informal))
            out.append(row); continue
        top_key = max(key(c) for c in official)
        tops = [c for c in official if key(c) == top_key]
        top_vals = {norm(c['value']) for c in tops}
        row['unit'] = tops[0]['unit']
        # 이력: 값이 바뀐 지점만 키 순서로 기록
        seq, last = [], None
        for c in sorted(official, key=key):
            if norm(c['value']) != last:
                seq.append(f"{c['value']}{c['unit']}({c['stage']} {c['date']} {c['doc_id']})"); last = norm(c['value'])
        row['history'] = ' → '.join(seq)
        if len(top_vals) > 1:  # 같은 단계·같은 일자·같은 버전인데 값이 다름
            if (fac, item) in choices:
                ch = choices[(fac, item)]
                row.update(value=ch, status='확정', method='사람 선택', source='담당자 선택',
                           note='후보: ' + ' / '.join(f"{c['value']}{c['unit']}({c['doc_id']})" for c in tops))
            else:
                row.update(status='미확정(충돌)', method='사람 선택 필요',
                           note='후보: ' + ' / '.join(f"{c['value']}{c['unit']}({c['doc_id']}, {c['file']})" for c in tops))
            row['candidates'] = [(c['value'], c['doc_id']) for c in tops]
        else:
            win = tops[0]
            lower_diff = [c for c in official if norm(c['value']) != norm(win['value'])]
            if not lower_diff:
                method = '충돌 없음'
            elif all(STAGE_RANK[c['stage']] < STAGE_RANK[win['stage']] for c in lower_diff):
                method = '규칙(단계 우선순위)'
            else:
                method = '규칙(같은 단계에서 최근 일자)'
            row.update(value=win['value'], status='확정', method=method, source=f"{win['doc_id']} {win['file']} ({win['location']})")
        diff_inf = [c for c in informal if row['value'] is not None and norm(c['value']) != norm(row['value'])]
        if diff_inf:
            row['note'] = (row['note'] + ' | ' if row['note'] else '') + '참고(비공식, 반영 안 함): ' + ', '.join(f"{c['value']}{c['unit']}({c['doc_id']})" for c in diff_inf)
        out.append(row)
    return out


if __name__ == '__main__':
    import sys
    rows = resolve(load(sys.argv[1] if len(sys.argv) > 1 else 'candidates_sample.csv'))
    for r in rows:
        print(f"{r['facility']} / {r['item']}: {r['value']}{r['unit'] if r['value'] else ''} [{r['status']}, {r['method']}]  {r['note']}")
