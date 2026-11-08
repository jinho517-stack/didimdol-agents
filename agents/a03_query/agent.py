"""A03 목적별 자료 추출 Agent  (Agent정의서_3_목적별자료추출)

시작 조건  담당자가 보고서 목적(보고 유형·대상 사업, 또는 목적 문장·질문)을 입력했고 A02의 DB 갱신이 끝났을 때
입력      보고서 목적 + 갱신된 DB(항목별 최신값·출처·기준일·미확정 표시)
출력      자료표: 목적에 필요한 항목의 값·단위·출처·기준일 + 부족·미확정 표시 → A04가 읽는다
          (엑셀로도 내려받음: to_excel)
사람 개입  목적 입력은 담당자. 자료표 자체의 별도 승인은 없고 A04 초안 최종 검토 때 함께 확인한다.

수행 단계
 ① 목적을 읽고 필요한 항목을 정한다    대상 사업을 골랐으면 그 사업의 전체 항목,
                                     목적 문장이면 AI(키 있을 때) 또는 키워드 규칙: query.select
 ② DB에서 해당 지구·시설의 값을 가져온다
 ③ 값이 없거나 충돌이 안 풀린 항목은 "부족·미확정"으로 표시한다
 ④ 값마다 출처와 기준일을 유지한 채 자료표로 만든다   query.to_row
 ⑤ 자료표를 A04에 넘긴다

같은 DB 조회 기능으로 여러 지구 통합 비교(compare)와 챗봇 질문 검색(search)도 이 agent가 맡는다.
"""
from agents.a03_query import compare, query

NAME = 'A03 목적별 자료 추출'
LACK = '부족·미확정'


def run(facts, purpose, facilities=None, use_llm=False, cfg=None):
    """①~⑤ 목적에 맞는 자료표를 만든다.
    facts: A02 DB의 항목(store.facts), purpose: 목적 문구(예: '현안사항 보고'),
    facilities: 대상 사업을 직접 고른 경우 그 목록(없으면 목적 문구로 고름)
    반환: {'purpose', 'basis', 'facts': 고른 DB 항목, 'table': 자료표 행, 'lacking': 부족·미확정 항목}"""
    if facilities:
        sel = [f for f in facts if f['facility'] in facilities]
        basis = '대상 사업 선택: ' + ', '.join(f for f in facilities if f != '지구 공통')
    else:
        sel, basis = query.select(facts, purpose, use_llm, cfg)
    lacking = [f for f in sel if f['status'] != '참고' and (f['value'] is None or f['status'] == '미확정(충돌)')]
    lack_ids = {id(f) for f in lacking}
    table = [{**query.to_row(f), '표시': LACK if id(f) in lack_ids else ''} for f in sel]
    return {'purpose': purpose, 'basis': basis, 'facts': sel, 'table': table, 'lacking': lacking}


def to_excel(result, title, sources):
    """자료표 엑셀(값마다 출처, '출처 문서' 시트 포함)."""
    return query.to_excel(result['table'], title, result['basis'], sources)


def search(question, facts, cat, current=None, use_llm=False, cfg=None):
    """챗봇: 질문 → 검색 조건(지구·유형·사업비·시행주체·현안 낱말) → DB 조회 결과와 답. 숫자는 DB 값만."""
    return compare.answer(question, facts, cat, current, use_llm, cfg)


def projects(facts, cat):
    """사업 단위 요약(대시보드·통합 비교용): 사업비·연장·시기·시행주체·추진상태·현안."""
    return compare.projects(facts, cat)
