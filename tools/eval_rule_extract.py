"""간이 추출(규칙) 정확도 점검: 모의 문서를 규칙으로 읽어, 정답 역할의 추출 예시 CSV와 비교한다.
실행: python tools/eval_rule_extract.py   (문장형 항목 현안·향후계획은 표 칸에 있을 때만 뽑으므로 따로 집계)"""
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from agents.a01_extract import reader as extract  # noqa: E402
from agents.a02_resolve.resolver import norm  # noqa: E402
from common import catalog  # noqa: E402

TEXT = {'현안', '향후계획', '추진상태', '시행주체'}


def main(verbose=False):
    cat = catalog.load()
    docs, cands = extract.load_sample(BASE / 'sample', True, True, cat['default'])
    tot = {'수치': [0, 0, 0], '문장': [0, 0, 0]}  # 맞음, 정답 수, 뽑은 수
    for d in docs:
        want = {(c['facility'], c['item'], norm(c['value'])) for c in cands if c['doc_id'] == d['doc_id']}
        got = {(c['facility'], c['item'], norm(c['value']))
               for c in extract.rule_extract(d, catalog.items_for(cat, d['district']))}
        # 문장형은 표현이 조금씩 달라도 되므로 (사업, 항목)이 맞으면 찾은 것으로 본다
        want = {x if x[1] not in TEXT else (x[0], x[1], '') for x in want}
        got = {x if x[1] not in TEXT else (x[0], x[1], '') for x in got}
        for kind, pick in (('수치', lambda x: x[1] not in TEXT), ('문장', lambda x: x[1] in TEXT)):
            w, g = {x for x in want if pick(x)}, {x for x in got if pick(x)}
            tot[kind][0] += len(w & g)
            tot[kind][1] += len(w)
            tot[kind][2] += len(g)
        if verbose and want != got:
            print(f"== {d['doc_id']} {d['file']}")
            for x in sorted(want - got):
                print('   못 뽑음:', x)
            for x in sorted(got - want):
                print('   잘못/추가:', x)
    for kind, (ok, w, g) in tot.items():
        print(f'{kind}: 정답 {w}개 중 {ok}개 찾음({ok / w:.0%}), 뽑은 {g}개 중 {ok}개 맞음({ok / g if g else 0:.0%})')
    return tot


if __name__ == '__main__':
    main('-v' in sys.argv)
