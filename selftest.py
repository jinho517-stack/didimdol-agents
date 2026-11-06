"""인수 시험(화면 없이). 실행: python selftest.py
1) resolver 기준 시험(test_resolver.py) 그대로 통과
2) 샘플 모드 흐름: 문서 11개 → DB 판정 결과가 정답표 11개 항목과 일치
3) 철도 개통 목표 미확정(충돌) → 2031.12 선택 시 확정 + 선택 기록
4) 환승센터 규모 12000㎡ 확정, 개인 메모 8000㎡는 참고로만 표시
5) 선택 이후 더 높은 단계 문서가 들어오면 그 문서가 이기고 선택 기록은 이력으로 보관
6) 입력 순서 무관, 모든 값에 출처, 자료표 엑셀·초안 생성, 문서 11개 읽기
10) agent 4개 연결: A01 → A02 → A03 → A04(자동 점검 포함), 각 agent의 입구(agent.py)로 실행"""
import random
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from agents.a01_extract import agent as A01
from agents.a01_extract import reader as extract
from agents.a02_resolve import agent as A02
from agents.a02_resolve import store as db
from agents.a02_resolve.resolver import norm
from agents.a03_query import agent as A03
from agents.a03_query import compare, query
from agents.a04_draft import agent as A04
from agents.a04_draft import draft
from common import catalog, llm

BASE = Path(__file__).parent
SAMPLE = BASE / 'sample'
EXPECT = {  # test_resolver.py의 정답표와 같음
    ('가온방면 연결도로', '연장'): ('2.1', '충돌 없음'),
    ('가온방면 연결도로', '사업비'): ('520', '규칙(같은 단계에서 최근 일자)'),
    ('가온방면 연결도로', '완료시기'): ('2031.6', '규칙(같은 단계에서 최근 일자)'),
    ('다온방면 도로확장', '연장'): ('0.8', '규칙(단계 우선순위)'),
    ('다온방면 도로확장', '차로'): ('4', '규칙(단계 우선순위)'),
    ('다온방면 도로확장', '사업비'): ('190', '규칙(같은 단계에서 최근 일자)'),
    ('누리마루선(광역철도)', '사업비'): ('4650', '규칙(같은 단계에서 최근 일자)'),
    ('누리마루선(광역철도)', '개통목표'): (None, '사람 선택 필요'),
    ('환승센터', '규모'): ('12000', '충돌 없음'),
    ('환승센터', '사업비'): ('230', '충돌 없음'),
    ('입주 초기 버스 지원', '지원액'): ('105', '규칙(같은 단계에서 최근 일자)'),
}
RAIL = ('누리마루선(광역철도)', '개통목표')
CAT = catalog.load()


def ok(msg):
    print('  통과:', msg)


def load_sample(con, shuffle_seed=None, extra=False, other=False):
    docs, cands = extract.load_sample(SAMPLE, extra, other)
    if shuffle_seed is not None:
        random.Random(shuffle_seed).shuffle(docs)
    db.reset(con)
    for d in docs:
        db.save_document(con, d, [c for c in cands if c['doc_id'] == d['doc_id']])
    db.recompute(con, '누리마루지구')


def fact_map(con):
    return {(f['facility'], f['item']): f for f in db.facts(con)}


def main():
    print('1) resolver 기준 시험')
    r = subprocess.run([sys.executable, str(BASE / 'agents' / 'a02_resolve' / 'test_resolver.py')], cwd=SAMPLE, capture_output=True,
                       text=True, encoding='utf-8')
    assert r.returncode == 0, r.stdout + r.stderr
    ok(r.stdout.strip())

    tmp = Path(tempfile.mkdtemp()) / 'selftest.db'
    con = db.connect(tmp)

    print('2) 샘플 모드 → DB 판정')
    load_sample(con)
    fm = fact_map(con)
    for k, (v, m) in EXPECT.items():
        f = fm[k]
        assert (norm(f['value']) if f['value'] is not None else None) == v, (k, f['value'], v)
        assert f['method'] == m, (k, f['method'], m)
    ok('정답표 11개 항목 값·판정 유형 일치')
    for seed in range(5):
        load_sample(con, seed)
        assert {k: (f['value'], f['method'], f['source_doc']) for k, f in fact_map(con).items()} == \
               {k: (f['value'], f['method'], f['source_doc']) for k, f in fm.items()}
    ok('문서 등록 순서를 5번 섞어도 같은 결과(값·판정·출처)')
    missing = [k for k, f in fm.items() if f['value'] is not None and not (f['source_doc'] and f['source_loc'])]
    assert not missing, missing
    ok('값이 있는 모든 항목에 출처 문서·위치 있음')

    print('3) 철도 개통 목표 충돌 선택')
    assert fm[RAIL]['status'] == '미확정(충돌)'
    db.save_choice(con, '누리마루지구', *RAIL, '2031.12', '시험 담당자')
    f = fact_map(con)[RAIL]
    assert (f['value'], f['status'], f['method']) == ('2031.12', '확정', '사람 선택'), f
    assert f['source_doc'] == 'D06', f['source_doc']
    ch = db.choices(con)
    assert len(ch) == 1 and ch[0]['value'] == '2031.12' and ch[0]['chooser'] == '시험 담당자' and ch[0]['active']
    assert any(h['kind'] == '사람 선택' for h in db.history(con, f['id']))
    ok('2031.12 선택 → 확정, 선택 기록(후보·선택값·선택자·선택일)과 이력 저장')

    print('4) 비공식 메모')
    f = fact_map(con)[('환승센터', '규모')]
    assert f['value'] == '12000' and f['status'] == '확정' and '8000' in f['note'] and '참고(비공식' in f['note']
    ok('환승센터 규모 12000㎡ 확정, 개인 메모 8000㎡는 참고(비공식, 반영 안 함)')

    print('5) 선택 이후 상위 문서 투입')
    db.save_document(con, {'doc_id': 'D99', 'file': '261030 가상 확정본.txt', 'date': '2026-10-30',
                           'stage': '확정·승인본', 'version_kind': '', 'format': '텍스트'},
                     [{'facility': RAIL[0], 'item': RAIL[1], 'value': '2032.6', 'unit': '', 'location': '1행'}])
    db.recompute(con, '누리마루지구')
    f = fact_map(con)[RAIL]
    assert (f['value'], f['status'], f['source_doc']) == ('2032.6', '확정', 'D99'), f
    assert not db.choices(con)[0]['active']
    assert any(h['kind'] == '선택 보관' for h in db.history(con, f['id']))
    ok('상위 단계 문서가 이기고, 담당자 선택은 이력으로 보관')

    print('6) 자료표·초안')
    load_sample(con)
    table, basis = query.build(db.facts(con), '유사 지구 비교용 협의 자료')
    assert len(table) == 15 and all(r['출처'] for r in table if r['상태'] == '확정'), basis
    x = query.to_excel(table, '유사 지구 비교용 협의 자료', basis, db.sources(con))
    assert x[:2] == b'PK'
    t2, _ = query.build(db.facts(con), '철도 사업비 현황')
    assert [(r['시설'], r['항목']) for r in t2] == [('누리마루선(광역철도)', '사업비')], t2
    order = catalog.order(CAT, '누리마루지구')
    blocks = draft.build(db.facts(con), db.load_candidates(con), db.sources(con), db.choices(con),
                         '', '누리마루지구', '광역교통팀', order=order, show_basis=True)
    text = draft.to_text(blocks)
    for must in ('□ 개요', '□ 사업개요', '□ 추진현황', '□ 주요 변경사항', '□ 주요 현안 및 대응방안', '⇒ (대응방안)',
                 '12,000㎡', '4,650억원', '0.6km → 0.8km', '2031.12(D06', '2032.6(D06b', '8,000㎡'):
        assert must in text, must
    tail, secs = draft.PRESETS['현안사항 보고']
    t2 = draft.to_text(draft.build(db.facts(con), db.load_candidates(con), db.sources(con), db.choices(con),
                                   '누리마루지구 ' + tail, '누리마루지구', '', secs,
                                   {'향후 계획': '(협의) 제21차 실무협의체 개최\n- 11월 예정'}, order=order,
                                   show_basis=True))
    for must in ('□ 사업개요', '□ 추진경위', '□ 주요 현안 및 대응방안', '□ 향후 계획', '우선순위가 낮아 8건 미반영',
                 '문서 간 값 충돌 1건', ' ㅇ (협의) 제21차 실무협의체 개최', '   - 11월 예정'):
        assert must in t2, must
    assert '□ 개요' not in t2 and '□ 참고' not in t2  # 체크하지 않은 목차는 빠짐
    clean = draft.to_text(draft.build(db.facts(con), db.load_candidates(con), db.sources(con), db.choices(con),
                                      '', '누리마루지구', '', list(draft.SECTIONS[:-1]), order=order))
    assert not re.search(r'\bD\d{2}b?\b|근거|문서ID|판정|우선순위|미반영|비공식 자료 \d', clean), \
        re.search(r'.*(\bD\d{2}b?\b|근거|문서ID|판정|우선순위|미반영).*', clean).group()
    for must in ('0.6km → 0.8km', '관계기관 문서 간 상이(2031.12 / 2032.6)', '비공식 의견: 8,000㎡ (공식 확인 전)'):
        assert must in clean, must
    assert draft.to_docx(blocks)[:2] == b'PK'
    hw = draft.to_hwpx(blocks)
    import io, zipfile, xml.etree.ElementTree as ET
    with zipfile.ZipFile(io.BytesIO(hw)) as z:
        assert z.namelist()[0] == 'mimetype' and z.getinfo('mimetype').compress_type == zipfile.ZIP_STORED
        ET.fromstring(z.read('Contents/section0.xml'))
    tmp_h = Path(tempfile.mkdtemp()) / 'r.hwpx'
    tmp_h.write_bytes(hw)
    back = extract.read_hwpx(tmp_h)
    assert '□ 주요 현안 및 대응방안' in back and '누리마루지구 광역교통개선대책 추진현황 보고' in back
    ok(f'자료표 {len(table)}행(출처 포함)·엑셀, 키워드 선택, 보고서 초안(양식·목차 선택, 한글 hwpx·워드 docx) 생성')

    print('7) 현안 문서 7개 추가 (sample/extra)')
    load_sample(con, extra=True)
    fm = fact_map(con)
    for k, (v, m) in EXPECT.items():  # 기존 정답표 11개 항목은 그대로
        f = fm[k]
        assert ((norm(f['value']) if f['value'] is not None else None), f['method']) == (v, m), (k, f['value'], f['method'])
    want = {  # (시설, 항목): (최신값, 근거 문서)
        ('가온방면 연결도로', '추진상태'): ('대안노선 조건부 합의', 'E04'),  # 협의결과끼리 최근 일자
        ('다온방면 도로확장', '추진상태'): ('실시설계 착수', 'E03'),  # 협의결과가 보고를 이김
        ('환승센터', '추진상태'): ('교육청 협의 중', 'E07'),  # 보고끼리 최근 일자, 초안(E05)은 미반영
        ('누리마루선(광역철도)', '현안'): (None, 'E04'),
    }
    for k, (v, d) in want.items():
        assert fm[k]['source_doc'] == d and (v is None or fm[k]['value'] == v), (k, fm[k]['value'], fm[k]['source_doc'])
    assert '교육청 담당자 구두 의견' in fm[('환승센터', '현안')]['note']  # 비공식 메모는 참고로만
    kinds = CAT['kinds']
    tail, secs = draft.PRESETS['현안사항 보고']
    t3 = draft.to_text(draft.build(db.facts(con), db.load_candidates(con), db.sources(con), db.choices(con),
                                   tail, '누리마루지구', '', secs, order=order, kinds=kinds))
    for must in (' ㅇ (가온방면 연결도로) 가온시가 우회 대안노선을 조건부로 수용함', '추진상태: 대안노선 조건부 합의',
                 ' ㅇ (다온방면 도로확장) 11월 실시설계 용역 발주', '가온방면 연결도로 추진상태 협의 지연(가온시 노선 반대)→대안노선 조건부 합의'):
        assert must in t3, must
    assert '사업비 분담 협의 필요 |' not in t3  # 현안 문장은 사업개요 표에 들어가지 않음
    ok('기존 정답 11개 유지, 추진상태·현안·향후계획 판정(단계·일자 규칙), 비공식 메모 참고, 현안 보고서 반영')

    print('8) 문서 읽기 (기본 11개 + 현안 7개 + 다른 지구 8개)')
    for p in extract.list_folder(SAMPLE) + extract.list_folder(SAMPLE / 'extra') + extract.list_folder(SAMPLE / 'other'):
        text = extract.read_text(p)
        assert len(text.strip()) > 20, p.name
        g = extract.guess_meta(p.name)
        print(f'     {p.name}: {len(text)}자, 추정 단계 {g["stage"]} {g["version_kind"]}'.rstrip())
    docs, _ = extract.load_sample(SAMPLE, extra=True, other=True)
    wrong = [(d['file'], d['stage'], extract.guess_meta(d['file'])) for d in docs
             if (d['stage'], d['version_kind']) != (extract.guess_meta(d['file'])['stage'],
                                                     extract.guess_meta(d['file'])['version_kind'])]
    assert not wrong, wrong
    bad = [(d['file'], d['district']) for d in docs if d['district'] not in ('', '누리마루지구')
           and catalog.guess_district(CAT, d['file']) != d['district']]
    assert not bad, bad
    ok(f'{len(docs)}개 형식별 읽기 성공, 파일명 기반 단계·버전·지구 추정이 예시와 일치')

    print('9) 여러 사업지구 통합 (누리마루 + 한빛 + 솔내)')
    load_sample(con, extra=True, other=True)
    assert set(db.districts(con)) == {'누리마루지구', '한빛지구', '솔내지구'}
    fm = {(f['facility'], f['item']): f for f in db.facts(con, district='누리마루지구')}
    for k, (v, m) in EXPECT.items():  # 지구별 판정이라 다른 지구 문서가 누리마루 결과를 바꾸지 않음
        f = fm[k]
        assert ((norm(f['value']) if f['value'] is not None else None), f['method']) == (v, m), (k, f['value'], f['method'])
    hb = {(f['facility'], f['item']): f for f in db.facts(con, district='한빛지구')}
    assert hb[('새솔로 확장', '사업비')]['value'] == '1250' and hb[('새솔로 확장', '사업비')]['source_doc'] == 'H02'
    assert hb[('한빛IC 연결도로', '추진상태')]['value'] == '보상 착수'  # 협의결과(H04)가 보고(H03)를 이김
    q1 = compare.answer('지자체에서 1천억 미만의 유사 도로사업들을 검토해보라고 하는데 다른 사업지구에 이런 사례가 있을까?',
                        db.facts(con), CAT, '누리마루지구')
    assert sorted(r['사업명'] for r in q1['rows']) == ['솔내 연결도로', '한빛IC 연결도로'], q1['conditions']
    assert 'entities' not in q1['filter']  # "지자체에서 검토하라고"는 시행주체 조건이 아님
    q2 = compare.answer('개별 광역시설 사업 중에 시행주체(공사주체)가 지자체인 사업의 사례가 있을까?', db.facts(con), CAT)
    assert {'가온방면 연결도로', '한빛IC 연결도로', '솔내 연결도로', '한빛 환승주차장'} <= {r['사업명'] for r in q2['rows']}
    assert all(r['주체 구분'].startswith('지자체') for r in q2['rows'])
    q3 = compare.answer('사업비 5천억 이상 철도사업', db.facts(con), CAT)
    assert [r['사업명'] for r in q3['rows']] == ['한빛선 연장(광역철도)']
    q4 = compare.answer('주민 반대로 지연되는 사업', db.facts(con), CAT)
    assert '새솔로 확장' in {r['사업명'] for r in q4['rows']}
    ok(f"지구별 판정(누리마루 정답 유지), 통합 검색: 1천억 미만 도로 {len(q1['rows'])}건 · 지자체 시행 {len(q2['rows'])}건 · "
       f"5천억 이상 철도 {len(q3['rows'])}건 · 주민 반대 {len(q4['rows'])}건")

    print('10) agent 4개 연결 (A01 → A02 → A03 → A04)')
    con2 = A02.connect(Path(tempfile.mkdtemp()) / 'agents.db')
    docs = []
    for folder in (SAMPLE, SAMPLE / 'extra', SAMPLE / 'other'):  # A01이 모의 문서를 직접 읽음(규칙 추출)
        docs += A01.describe(extract.list_folder(folder), len(docs) + 1, CAT)
    r1 = []
    for dist in sorted({d['district'] or CAT['default'] for d in docs}):
        r1 += A01.run([d for d in docs if (d['district'] or CAT['default']) == dist], catalog.items_for(CAT, dist))
    assert not [d['file'] for d, _, e in r1 if e] and sum(len(c) for _, c, _ in r1) > 100
    csv_path = A01.save_table(r1, Path(tempfile.mkdtemp()) / 'a01.csv')
    r2 = A02.run(con2, r1, CAT['default'], reset=True)  # A02: 판정, 규칙으로 못 정한 충돌은 사람에게
    assert [(f['facility'], f['item']) for f in r2['conflicts']] == [RAIL], r2['conflicts']
    A02.choose(con2, '누리마루지구', *RAIL, '2031.12', '시험 담당자')
    assert not A02.conflicts(con2)
    facts = db.facts(con2, district='누리마루지구')
    r3 = A03.run(facts, '현안사항 보고', facilities=sorted({f['facility'] for f in facts}))
    assert r3['table'] and not r3['lacking'] and all(row['출처'] for row in r3['table'] if row['상태'] != '참고')
    r3p = A03.run(facts, '철도 사업비 현황')  # 목적 문장만 줬을 때: 키워드 규칙으로 항목 선택
    assert {f['item'] for f in r3p['facts']} == {'사업비'} and all('철도' in f['facility'] for f in r3p['facts'])
    tail, secs = A04.PRESETS['현안사항 보고']
    cands = db.load_candidates(con2, '누리마루지구')
    b4 = A04.run(r3, cands, db.sources(con2, '누리마루지구'), db.choices(con2, '누리마루지구'), '시험', '누리마루지구',
                 '', secs, order=catalog.order(CAT, '누리마루지구'), kinds=CAT['kinds'])
    chk = A04.check(b4, r3, cands, secs)
    assert all(c['결과'] == '통과' for c in chk), chk
    bad = b4 + [('b', None, '사업비 9,999억원')]  # 자료표에 없는 수치를 넣으면 점검이 잡아야 함
    assert A04.check(bad, r3, cands, secs)[0]['결과'] == '확인 필요'
    assert A04.check(b4, r3, cands, secs + ['참고(비공식)'])[2]['결과'] == '확인 필요'  # 빠진 목차
    lay = A04.Layout(b4, '짧은 보고서(푸른색)', r3['facts'], '누리마루지구', '', CAT['kinds'])
    assert lay.docx()[:2] == b'PK' and lay.hwpx()[:2] == b'PK'
    con2.close()
    ok(f"A01 규칙 추출 {sum(len(c) for _, c, _ in r1)}건({csv_path.name}) → A02 충돌 1건 사람 선택 → "
       f"A03 자료표 {len(r3['table'])}행 → A04 초안·자동 점검 {len(chk)}개 통과(틀린 수치·빠진 목차는 잡아냄)")

    print(f"\n모든 시험 통과. (LLM 연결: {'사용 가능' if llm.available() else '키 없음 → 샘플 모드'})")
    con.close()


if __name__ == '__main__':
    main()
