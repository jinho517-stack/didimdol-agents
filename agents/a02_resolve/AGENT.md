# A02 최신값 판정·DB 갱신 Agent

> 근거: `Agent정의서_2_최신값판정_DB갱신.docx` · 앞 Agent: A01 문서 내용 추출 · 뒤 Agent: A03 목적별 자료 추출

| 구분 | 내용 |
|---|---|
| 목적 | A01 항목 후보 표를 기존 DB와 비교해 항목별 최신값을 정하고, DB를 갱신하면서 변경 이력과 출처를 남긴다. 규칙으로 못 정한 충돌만 사람에게 묻는다 |
| 시작 조건 | A01이 항목 후보 표를 넘겼을 때 ("DB에 저장하고 판정", "샘플 불러오기") |
| 입력 | ① A01 항목 후보 표 ② 기존 DB(값·이력) ③ 판정 규칙(`resolver.py`) |
| 출력 | 갱신된 DB(`output/didimdol.db`): 항목별 최신값, 변경 이력, 출처, 사람 선택 기록, 미확정 표시 → A03이 읽음 |
| 사람 개입 | 같은 단계·같은 일자인데 값이 다른 충돌만 담당자가 고른다(📊 대시보드 위쪽 ⚠ 상자). 고르기 전까지 "미확정(충돌)" 유지 → 자료표·보고서에 "확인 필요"로 나옴 |
| 도구 | DB 조회·저장(SQLite), 판정 규칙(LLM 안 씀) |

## 판정 규칙 (`resolver.py`, 기준 구현 원본 그대로 · 수정 금지)
1. 문서 단계: 확정·승인본 > 협의결과 > 보고 > 초안
2. 같은 단계면 최근 일자
3. 같은 일자면 최종 > 변경안 > 원안
4. 모두 같은데 값이 다르면 → 사람 선택 필요
5. 비공식(개인 메모 등)은 값을 바꾸지 않고 '참고'로만 표시
- 같은 입력이면 문서 순서와 관계없이 항상 같은 결과(`test_resolver.py`로 확인).

## 수행 단계와 코드
| 단계 | 하는 일 | 코드 |
|---|---|---|
| ① | 후보를 DB의 같은 지구·시설·항목과 연결 | `agent.run` → `store.save_document` |
| ② | DB에 없으면 새 항목으로 등록 | `store.recompute` |
| ③ | 값이 같으면 출처만 더함 | `store.recompute` (history) |
| ④⑤ | 값이 다르면 규칙으로 최신값, 이전 값은 이력에 | `store.recompute` → `resolver.resolve` |
| ⑥ | 못 정하면 충돌 목록을 담당자에게 | `agent.conflicts` |
| ⑦ | 선택 결과 반영, 선택 기록을 이력에 | `agent.choose` → `store.save_choice` |
| (+) | 문서 정보 수정·문서 빼기 후 다시 판정 | `agent.rejudge` |

## 입구 함수 (`agent.py`)
```python
from agents.a02_resolve import agent as A02
con = A02.connect()                                  # output/didimdol.db
rep = A02.run(con, a01_results, default_district)    # {'changed': [...], 'conflicts': [...]}
A02.conflicts(con)                                   # 사람 선택을 기다리는 항목
A02.choose(con, '누리마루지구', '누리마루선(광역철도)', '개통목표', '2031.12', '담당자')
```

## 정의서와 다른 점 (현재 구현)
- 정의서의 도구에는 "AI 언어모델 + 판정 규칙"이 있지만, 결과가 매번 같아야 하므로 **규칙만** 씁니다.
- 반려·보류는 "고르지 않음"으로 처리합니다. 기존 값은 미확정으로 남고 이력은 그대로입니다.
- 사람이 고른 뒤 더 높은 단계 문서가 들어오면 그 문서가 이깁니다. 이때 선택 기록은 '선택 보관'으로 이력에 남습니다.

## 파일
- `agent.py` 입구 · `store.py` DB(facts·history·sources·choices·candidates) · `resolver.py` 판정 규칙(원본) · `test_resolver.py` 기준 시험(원본)
