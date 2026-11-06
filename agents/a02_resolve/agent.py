"""A02 최신값 판정·DB 갱신 Agent  (Agent정의서_2_최신값판정_DB갱신)

시작 조건  A01이 항목 후보 표를 넘겼을 때(화면: "DB에 저장하고 판정" / "샘플 불러오기")
입력      A01 항목 후보 표 + 기존 DB(지금까지의 값·이력) + 판정 규칙(resolver.py)
출력      갱신된 DB(output/didimdol.db): 항목별 최신값, 변경 이력, 출처, 사람 선택 기록, 미확정 표시 → A03이 읽는다
사람 개입  같은 단계·같은 일자인데 값이 달라 규칙으로 못 정한 충돌만 담당자가 고른다(choose).
          고르기 전까지는 "미확정(충돌)"로 두고 보고서·자료표에 "확인 필요"로 나온다.

판정 규칙(resolver.py, 기준 구현 원본 그대로 · LLM 안 씀 · 같은 입력이면 항상 같은 결과)
  문서 단계 확정·승인본 > 협의결과 > 보고 > 초안 → 같은 단계면 최근 일자 → 같은 일자면 최종 > 변경안 > 원안
  비공식(개인 메모 등)은 값을 바꾸지 않고 '참고'로만 남긴다.

수행 단계
 ① 후보를 DB의 같은 지구·시설·항목과 연결한다      store.save_document
 ② DB에 없으면 새 항목으로 등록한다
 ③ 값이 같으면 출처만 더한다
 ④⑤ 값이 다르면 규칙으로 최신값을 정하고 이전 값은 이력에 남긴다   store.recompute → resolver.resolve
 ⑥ 규칙으로 못 정하면 충돌 목록을 담당자에게 보여 준다            conflicts
 ⑦ 선택 결과를 반영하고 선택 기록을 이력에 저장한다               choose
"""
from agents.a02_resolve import store

NAME = 'A02 최신값 판정·DB 갱신'
CONFLICT = '미확정(충돌)'


def connect(path=None):
    """DB 연결(없으면 만든다). 기본 위치: output/didimdol.db"""
    return store.connect(path) if path else store.connect()


def _snapshot(con):
    return {(f['district'], f['facility'], f['item']): (f['value'], f['status']) for f in store.facts(con)}


def run(con, results, default_district='', reset=False):
    """①~⑥ A01 결과를 DB에 넣고 전체를 다시 판정한다.
    results: [(문서, 후보 목록)] 또는 A01.run()의 [(문서, 후보 목록, 오류)]
    반환: {'docs': 문서 수, 'candidates': 후보 수, 'changed': [(지구, 시설, 항목, 이전, 이후)], 'conflicts': 충돌 항목}"""
    if reset:
        store.reset(con)
    before = _snapshot(con)
    n = 0
    for r in results:
        doc, cands = r[0], r[1]
        store.save_document(con, doc, cands)
        n += len(cands)
    store.recompute(con, default_district)
    return _report(con, before, len(results), n)


def rejudge(con, default_district=''):
    """문서 정보(지구·단계·일자·버전)를 고치거나 문서를 뺀 뒤 전체를 다시 판정한다."""
    before = _snapshot(con)
    store.recompute(con, default_district)
    return _report(con, before, 0, 0)


def _report(con, before, docs, n):
    after = _snapshot(con)
    changed = [(*k, before.get(k), after.get(k)) for k in sorted(set(before) | set(after)) if before.get(k) != after.get(k)]
    return {'docs': docs, 'candidates': n, 'changed': changed, 'conflicts': conflicts(con)}


def conflicts(con, district=None):
    """⑥ 규칙으로 못 정해 담당자 선택을 기다리는 항목."""
    return [f for f in store.facts(con, district=district) if f['status'] == CONFLICT]


def choose(con, district, facility, item, value, chooser='담당자'):
    """⑦ 사람 개입: 충돌 항목의 값을 담당자가 고른다. 선택 기록이 이력에 남고 다시 판정된다."""
    store.save_choice(con, district, facility, item, value, chooser)
