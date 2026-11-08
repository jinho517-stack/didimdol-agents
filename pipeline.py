"""agent 4개를 화면 없이 차례로 돌린다: A01 → A02 → A03 → A04.  각 agent의 입력·출력이 그대로 보인다.

  python pipeline.py                         샘플 모드(A01 = 모의 문서의 추출 결과 예시, 키 없이)
  python pipeline.py --read                  A01이 sample/ 모의 문서를 직접 읽는다(키 있으면 AI, 없으면 규칙)
  python pipeline.py --district 한빛지구 --preset "현안사항 보고"

결과 파일(output/pipeline/): a01_항목후보표.csv, didimdol.db, 자료표.xlsx, 보고서 초안 .hwpx/.docx
담당자 선택이 필요한 충돌(A02 ⑥)은 화면(streamlit run app.py)에서 고른다. 여기서는 '미확정'으로 둔 채 진행한다."""
import argparse
from pathlib import Path

from agents.a01_extract import agent as A01
from agents.a02_resolve import agent as A02
from agents.a03_query import agent as A03
from agents.a04_draft import agent as A04
from common import catalog, llm

BASE = Path(__file__).parent
OUT = BASE / 'output' / 'pipeline'


def main(argv=None):
    ap = argparse.ArgumentParser(description='디딤돌 agent 4개 연결 실행')
    ap.add_argument('--read', action='store_true', help='A01이 모의 문서를 직접 읽음(기본: 추출 결과 예시 사용)')
    ap.add_argument('--district', default=None, help='보고서를 만들 사업지구(기본: config.yaml의 기본 지구)')
    ap.add_argument('--preset', default='현안사항 보고', choices=list(A04.PRESETS), help='보고 유형')
    ap.add_argument('--form', default='디딤돌 기본', choices=list(A04.FORMS), help='회사 양식(모양)')
    a = ap.parse_args(argv)

    cfg = llm.load_config()
    cat = catalog.load(cfg)
    use_llm = llm.available(cfg)
    district = a.district or cat['default']
    OUT.mkdir(parents=True, exist_ok=True)

    # ---- A01 문서 내용 추출 → 항목 후보 표
    print(f'[{A01.NAME}]')
    if a.read:
        docs = []
        for folder in (BASE / 'sample', BASE / 'sample' / 'extra', BASE / 'sample' / 'other'):
            docs += A01.describe(A01.reader.list_folder(folder), len(docs) + 1, cat)
        results = []
        for dist in {d['district'] or cat['default'] for d in docs}:
            group = [d for d in docs if (d['district'] or cat['default']) == dist]
            results += A01.run(group, catalog.items_for(cat, dist), use_llm, cfg)
        how = 'AI 추출' if use_llm else '규칙 추출(키 없음)'
    else:
        docs, cands = A01.load_sample(BASE / 'sample', extra=True, other=True, default_district=cat['default'])
        results = [(d, [c for c in cands if c['doc_id'] == d['doc_id']], '') for d in docs]
        how = '샘플 모드(추출 결과 예시)'
    table = A01.save_table(results, OUT / 'a01_항목후보표.csv')
    fails = [d['file'] for d, _, e in results if e]
    print(f'  {how}: 문서 {len(results)}건 → 후보 {sum(len(c) for _, c, _ in results)}건 · 읽기 실패 {len(fails)}건')
    print(f'  출력: {table.relative_to(BASE)}')

    # ---- A02 최신값 판정·DB 갱신 → DB
    print(f'[{A02.NAME}]')
    con = A02.connect(OUT / 'didimdol.db')
    rep = A02.run(con, results, cat['default'], reset=True)
    print(f"  판정 항목 {len(rep['changed'])}건 갱신 · 담당자 선택 필요 {len(rep['conflicts'])}건"
          + ''.join(f"\n   - 확인 필요: {f['district']} {f['facility']} / {f['item']}" for f in rep['conflicts']))
    print('  출력: output/pipeline/didimdol.db')

    # ---- A03 목적별 자료 추출 → 자료표
    print(f'[{A03.NAME}]')
    facts = A02.store.facts(con, district=district)
    facs = list(dict.fromkeys(f['facility'] for f in facts))
    res3 = A03.run(facts, a.preset, facilities=facs, use_llm=use_llm, cfg=cfg)
    sources = A02.store.sources(con, district)
    xlsx = OUT / f'자료표_{district}.xlsx'
    xlsx.write_bytes(A03.to_excel(res3, f'{district} {a.preset}', sources))
    print(f"  목적 '{a.preset}' · {district}: 자료표 {len(res3['table'])}행 · 부족·미확정 {len(res3['lacking'])}건")
    print(f'  출력: {xlsx.relative_to(BASE)}')

    # ---- A04 보고서 초안 작성 → 초안 + 자동 점검
    print(f'[{A04.NAME}]')
    tail, sections = A04.PRESETS[a.preset]
    title = f'{district} {tail}'
    blocks = A04.run(res3, A02.store.load_candidates(con, district), sources, A02.store.choices(con, district),
                     title, district, cfg.get('report', {}).get('dept', ''), sections, {}, use_llm, cfg,
                     order=catalog.order(cat, district), kinds=cat['kinds'])
    for r in A04.check(blocks, res3, A02.store.load_candidates(con, district), sections):
        print(f"  자동 점검 · {r['점검']}: {r['결과']} — {r['설명']}")
    lay = A04.Layout(blocks, a.form, res3['facts'], district, '', cat['kinds'])
    for ext, make in (('hwpx', lay.hwpx), ('docx', lay.docx)):
        p = OUT / f'{title}.{ext}'
        p.write_bytes(make())
        print(f'  출력: {p.relative_to(BASE)}')
    print('  → 담당자 최종 검토 필요(Agent정의서_4: 사람 개입 지점)')


if __name__ == '__main__':
    main()
