# A01 문서 내용 추출 Agent

> 근거: `Agent정의서_1_문서내용추출.docx` · 뒤 Agent: A02 최신값 판정·DB 갱신

| 구분 | 내용 |
|---|---|
| 목적 | 담당자가 올린 문서에서 미리 정한 항목의 값을 뽑아, 값마다 출처와 문서 단계·일자를 붙인 **항목 후보 표**로 만든다 |
| 시작 조건 | 담당자가 문서를 올리고 "값 뽑기"를 눌렀을 때 (샘플 모드: "샘플 불러오기") |
| 입력 | ① 타겟 문서(PDF·한글 hwpx·워드 docx·엑셀 xlsx·텍스트) ② 추출 항목 목록(분류 체계: `config.yaml`의 지구·사업·항목) |
| 출력 | 항목 후보 표: 문서ID·파일·지구·단계·일자·버전, 시설·사업, 항목, 값, 단위, 위치, 읽기 실패 표시 → `output/a01_항목후보표.csv` (UTF-8 BOM), A02로 넘김 |
| 사람 개입 | 별도 승인 없음. 화면에서 뽑힌 값을 보고 틀린 값은 빼고 저장. 읽지 못한 문서는 "읽기 실패(확인 필요)"로 표시 |
| 도구 | 문서 읽기(pdfplumber·python-docx·openpyxl·hwpx XML), AI 언어모델(키 있을 때) 또는 규칙 추출(키 없을 때) |

## 수행 단계와 코드
| 단계 | 하는 일 | 코드 |
|---|---|---|
| ① | 문서를 읽는다 | `reader.read_text` (형식별 `read_pdf`·`read_docx`·`read_xlsx`·`read_hwpx`·`read_txt`) |
| ② | 문서 단계·일자를 찾는다 | `agent.describe` → `reader.guess_meta` (파일명으로 추정, 화면에서 고침) |
| ③ | 항목마다 값·단위를 뽑는다 | `agent.run` → AI: `reader.extract_candidates` / 규칙: `reader.rule_extract` |
| ④ | 값마다 출처를 붙인다 | ③의 결과에 문서ID·위치 포함 |
| ⑤ | 못 찾은 값은 만들지 않는다 | AI 프롬프트에 "문서에 없는 값은 만들지 않음", 규칙은 찾은 값만 |
| ⑥ | 항목 후보 표로 저장, A02에 넘긴다 | `agent.save_table` → A02 `agent.run` |

## 입구 함수 (`agent.py`)
```python
from agents.a01_extract import agent as A01
docs = A01.describe(paths, start_num=1, cat=CAT)        # 올린 파일 → 문서 정보
results = A01.run(docs, items, use_llm=False)            # [(문서, 후보 목록, 오류)]
A01.save_table(results)                                  # output/a01_항목후보표.csv
docs, cands = A01.load_sample('sample', extra=True, other=True)   # 샘플 모드(추출 결과 예시)
```

## 정의서와 다른 점 (현재 구현)
- 도면 이미지에서 글자 읽기(OCR)는 하지 않습니다(요구사항상 범위 밖). 스캔 PDF도 읽지 못합니다.
- 문서 단계·일자는 파일명으로 추정하고 담당자가 💾 DB 화면에서 고칩니다.
- 출처는 문서ID와 문서 안 위치(문단·표 칸)로 남깁니다. PDF는 쪽 번호까지 남깁니다.
- 규칙 추출 정확도(모의 문서 기준, `python tools/eval_rule_extract.py`): 수치 97%, 문장 항목 85%.

## 파일
- `agent.py` 입구 · `reader.py` 문서 읽기와 추출(규칙·AI)
