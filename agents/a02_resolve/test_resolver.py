"""정답표(모의데이터_정답표.xlsx '항목정답표')와 같은 결과가 나오는지, 입력 순서가 달라도 같은지 확인."""
import random
from resolver import load, resolve, norm
EXPECT = {  # (시설, 항목): (값, 판정 유형)
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
def check(rows):
    got = {(r['facility'], r['item']): r for r in rows}
    for k, (v, m) in EXPECT.items():
        r = got[k]
        assert (norm(r['value']) if r['value'] else None) == v, (k, r['value'], v)
        assert r['method'] == m, (k, r['method'], m)
    return got
cands = load('candidates_sample.csv')
got = check(resolve(cands))
assert '8000' in got[('환승센터', '규모')]['note'], '비공식 메모는 참고로 표시되어야 함'
for seed in range(20):  # 입력 순서가 달라도 결과 동일
    c2 = cands[:]; random.Random(seed).shuffle(c2); check(resolve(c2))
r = resolve(cands, choices={('누리마루선(광역철도)', '개통목표'): '2031.12'})
assert {(x['facility'], x['item']): x for x in r}[('누리마루선(광역철도)', '개통목표')]['status'] == '확정'
print('통과: 정답표 11개 항목 일치, 입력 순서 무관(20회), 사람 선택 반영, 비공식 메모는 참고로만 표시')
