# 디딤돌 (행정업무 효율화)

> 화면 메뉴는 **자료 DB · 보고서 작성** 두 개입니다("자료만 올리세요. 보고서는 알아서 쓸게요.").
> - 자료 DB › 📥 자료 적재: 파일 올리기 → 사업지구 자동 인식 → 문서별 교통대책·내용 분류(AI) → 사람 확인 → DB 적재
> - 자료 DB › 🗂 적재 현황·관리: ⚠ 값 충돌 선택, DB 적재 현황, 사업 목록·유형 고치기, 문서 수정·빼기, 🧪 키 없이 시연용 샘플 DB
> - 보고서 작성: 사업지구·종류(현안 보고)·제목·날짜 → 초안 만들기 → 근거 자료 | 미리보기 → 한글(hwpx)·워드·자료표(엑셀) 저장

2026 공공 AI 대전환 챌린지 세션1(자유주제) 출품작 「디딤돌(행정업무 효율화)」.

사업지구 문서(PDF·한글·워드·엑셀·텍스트)를 넣으면 항목별 최신값을 출처와 함께 DB로 만듭니다. 문서끼리 값이 충돌하면 담당자에게 고르게 하고, 확정된 값으로 목적별 자료표와 보고서 초안을 만듭니다.
이 저장소는 그 일을 **Agent 정의서 4개에 맞춰 agent 4개로 나눈 구조**입니다. 앞 agent의 출력이 다음 agent의 입력이 됩니다.

## agent 4개

```
 담당자: 문서 올리기          담당자: 충돌만 고르기       담당자: 목적 입력          담당자: 최종 검토(필수)
        │                          │                         │                           │
 ┌──────▼───────┐  항목 후보 표  ┌──▼────────────┐   DB    ┌──▼───────────┐  자료표   ┌──▼───────────┐
 │ A01 문서 내용 │ ─────────────▶ │ A02 최신값 판정 │ ──────▶ │ A03 목적별    │ ────────▶ │ A04 보고서    │ ──▶ 한글·워드 초안
 │     추출      │  (CSV)         │    ·DB 갱신    │ (SQLite)│   자료 추출   │ (표·엑셀) │   초안 작성   │     + 자동 점검
 └──────────────┘                └───────────────┘         └──────────────┘           └──────────────┘
```

| Agent | 폴더 | 입력 | 출력 | 사람 개입 | AI 사용 |
|---|---|---|---|---|---|
| **A01 문서 내용 추출** | [`agents/a01_extract`](agents/a01_extract/AGENT.md) | 타겟 문서, 추출 항목 목록 | 항목 후보 표(값·단위·출처·단계·일자) | 틀린 값 빼고 저장 | 키 있으면 값 추출(없으면 규칙) |
| **A02 최신값 판정·DB 갱신** | [`agents/a02_resolve`](agents/a02_resolve/AGENT.md) | 항목 후보 표, 기존 DB, 판정 규칙 | 갱신된 DB(최신값·이력·출처·선택 기록) | 규칙으로 못 정한 충돌만 선택 | 안 씀(규칙만, 늘 같은 결과) |
| **A03 목적별 자료 추출** | [`agents/a03_query`](agents/a03_query/AGENT.md) | 보고서 목적, DB | 자료표(출처·기준일·부족·미확정 표시), 엑셀 | 목적 입력 | 키 있으면 목적 → 항목 고르기·질문 해석 |
| **A04 보고서 초안 작성** | [`agents/a04_draft`](agents/a04_draft/AGENT.md) | 자료표, 보고서 양식, 수정 의견 | 보고서 초안(hwpx·docx) + 자동 점검 결과 | 최종 검토(필수) | 키 있으면 '종합 의견' 문장만 |

- 각 폴더의 `agent.py`가 그 agent의 **입구(run)** 이고, `AGENT.md`에 정의서 요약·수행 단계별 코드 위치·정의서와 다른 점이 있습니다.
- 근거 문서: `Agent정의서_1_문서내용추출` · `2_최신값판정_DB갱신` · `3_목적별자료추출` · `4_보고서초안작성` (모듈 Task: 광역교통개선대책 문서 적재 및 보고서 초안 작성)
- 4명이 나눠 맡을 때: 한 사람이 agent 폴더 하나를 맡습니다. agent끼리는 위 표의 입력·출력 형식으로만 주고받으므로, 각자 자기 폴더 안을 고쳐도 다른 agent에 영향이 없습니다(`selftest.py` 10번 시험이 연결을 확인).

### agent를 화면 없이 차례로 돌려 보기
```bash
python pipeline.py                 # 샘플 모드: A01 = 모의 문서의 추출 결과 예시
python pipeline.py --read          # A01이 sample/ 모의 문서 26개를 직접 읽음(키 없으면 규칙 추출)
python pipeline.py --district 한빛지구 --preset "추진현황 보고"
```
agent마다 무엇을 받아 무엇을 넘겼는지 출력하고, 결과 파일을 `output/pipeline/`에 남깁니다(항목 후보 표 CSV, DB, 자료표 엑셀, 보고서 초안 hwpx·docx).

## 화면 (`streamlit run app.py`)

화면은 담당자가 agent를 부르는 곳이고, 계산은 모두 agent가 합니다.

| 화면 | 하는 일 | 쓰는 agent |
|---|---|---|
| 자료 DB › 📥 자료 적재 | 파일 올리기(PDF·한글·워드·엑셀·텍스트) → 사업지구 자동 인식(처음 보는 지구는 그 자리에서 등록) → 문서마다 어느 교통대책의 어떤 내용인지 분류 → "확인 필요" 문서는 원문 단서·AI가 멈춘 이유를 보고 사람이 결정 → "확인된 자료 DB 적재" | **A01 → A02** |
| 자료 DB › 🗂 적재 현황·관리 | ⚠ 값 충돌을 버튼으로 확정, 지구별 적재 항목·추진경위 표, 사업 목록·유형 고치기, 문서의 지구·단계·일자 수정과 빼기, 🧪 키 없이 시연용 샘플 DB 불러오기 | A02 |
| 보고서 작성 | 사업지구·종류·제목·보고 날짜(세부 설정: 작성 부서·대상 사업·목차·회사 한글 양식) → "초안 만들기" → 근거 자료 목록과 미리보기 확인 → 한글(hwpx)·워드(docx)·자료표(xlsx) 저장 | **A03 → A04** |

## 클라우드에서 실행 (Streamlit Community Cloud, 무료)
다른 사람이 설치 없이 웹 주소로 쓰게 하려면:
1. https://share.streamlit.io 에 GitHub 계정으로 로그인 → **Create app** → *Deploy a public app from GitHub*
2. Repository `jinho517-stack/didimdol-agents`, Branch `main`, Main file path `app.py`
3. **Advanced settings** → Python 3.12, **Secrets** 칸에 `.streamlit/secrets.toml.example` 형식으로 값 입력
   - `ANTHROPIC_API_KEY`(없으면 AI 없이 규칙으로 동작), 조직 키면 `ANTHROPIC_WORKSPACE_ID`
   - `APP_PASSWORD`를 넣으면 접속할 때 비밀번호를 물어봅니다(공개 주소에서 AI 사용료 보호)
4. **Deploy** → 몇 분 뒤 `https://<이름>.streamlit.app` 주소가 생깁니다. 이 주소와 접근 비밀번호를 심사위원·팀원에게 전달

**DB는 어디에 쌓이나요?**
- 내 PC: 프로젝트의 `output/didimdol.db`(SQLite 파일 하나). 올린 파일 사본은 `output/uploads/`.
- 클라우드: 앱이 도는 서버의 임시 디스크(`output/`). **모든 접속자가 같은 DB를 함께 씁니다.**
  앱이 다시 시작되면(코드 갱신, 오래 안 쓰면 잠듦 → 깨어날 때) **DB가 비워집니다.** 시연 때는 "📁 모의 자료로 해 보기"로 다시 채웁니다.
  계속 남겨야 하면 외부 DB(예: Supabase PostgreSQL)로 옮기는 작업이 필요합니다.
- 회사 한글 양식(`templates/company/`)은 저장소에 없어서 클라우드의 한글(hwpx)본은 기본 서식으로 나옵니다(워드본은 같은 규칙 적용).

## 실행 방법

Python 3.12가 필요합니다(requirements.txt의 고정 버전을 3.12에서 시험).

Windows PowerShell (가상환경을 켜는 `activate` 없이, 가상환경의 python을 직접 부릅니다):
```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:PYTHONUTF8 = "1"; .venv\Scripts\python.exe selftest.py   # "모든 시험 통과"가 나오면 정상
.venv\Scripts\python.exe -m streamlit run app.py              # 브라우저에서 http://localhost:8501
```
macOS·Linux:
```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python selftest.py
.venv/bin/python -m streamlit run app.py
```
- `.venv\Scriptsctivate`는 PowerShell의 스크립트 실행 제한 때문에 오류가 날 수 있어 쓰지 않습니다. 꼭 쓰려면 그 창에서만 `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`를 먼저 실행하세요.
- `$env:PYTHONUTF8 = "1"`은 Windows에서 시험 결과가 글자 깨짐으로 멈추지 않게 하는 설정입니다.
- `selftest.py`: 판정 규칙 기준 시험, 정답표 11개 항목, 충돌 선택, 비공식 메모, 문서 26개 읽기, 여러 지구 검색, **agent 4개 연결과 자동 점검(10번)**.

### 시연 순서 (키 없이)
1. 자료 DB › 📥 자료 적재 → **"📁 모의 자료로 해 보기"** → 사업지구(누리마루지구) 자동 인식, 문서 5건 분류(자동 확정·확인 필요) → 확인 필요 문서를 오른쪽에서 결정 → "확인된 자료 DB 적재" *(A01 분류 → A02)*
2. 자료 DB › 🗂 적재 현황·관리 → **"🧪 API 키 없이 시연: 샘플 DB 불러오기"** → "샘플 불러오기" *(모의 문서 26개의 A01 추출 예시 → A02 판정)*
3. 같은 화면의 ⚠ 값 충돌에서 누리마루선(광역철도) 개통목표 **2031.12** 선택 → DB에 확정 *(A02 사람 개입)*
4. DB 적재 현황 표에서 환승센터 규모 **12,000㎡** 확인 — 비공식 메모의 8,000㎡는 반영되지 않음 *(A02 규칙)*
5. 보고서 작성 → 누리마루지구 · 현안 보고 → "초안 만들기" → 근거 자료·미리보기 확인 → 한글·워드·자료표 저장 *(A03 → A04)*
6. (선택) 터미널에서 `python pipeline.py` → agent 4개가 차례로 넘겨주는 입력·출력과 자동 점검 결과 확인

키가 없으면 1번의 값 추출과 5번의 본문 문장은 규칙으로 만들어 내용이 얇습니다. 키를 넣으면 AI가 추출·분류하고, 담당자 수정본 문체로 본문을 씁니다(숫자는 DB 값만).

### 실제 추출(LLM) 사용
키 값은 파일에 쓰지 않고 환경변수로만 넣습니다.
```powershell
$env:ANTHROPIC_API_KEY = "<키>"            # 조직 키면 $env:ANTHROPIC_WORKSPACE_ID = "<작업공간 ID>" 도
.venv\Scripts\python.exe -m streamlit run app.py
```
키가 있으면 A01이 AI로 값을 뽑고, A03이 질문·목적을 AI로 해석하며, A04에서 '종합 의견(AI)' 목차를 쓸 수 있습니다.

## DB 적재 항목 (1차, 현안보고 기준)
현안보고 실제 양식(총괄현황·관리카드·추진현황 보고 등)을 기준으로 정했습니다. 목록은 `config.yaml`의 `item_templates`·`common_items`에 있습니다.

| 묶음 | 항목 | 저장 방식 |
|---|---|---|
| 지구 공통 | 사업시행자(지분), 개선대책 수립일, 최초 입주, 개선대책 총사업비 | 값 1개(지구마다 '지구 공통' 행) |
| 사업 기본 | 사업 기호, 분야, 사업명, 연장, 차로(4→6), 규모, 시행주체, 담당 사업시행자, 관리상태(정상추진·지연우려) | 값 1개(최신값 판정) |
| 사업비 | 사업비(최초→변경은 이력으로), 시행자 부담액 | 값 1개 |
| 일정 | 개선대책상 완료(개통), 예상 완료(준공), 착공, 추진단계 | 값 1개 |
| 현안·대응 | 추진상태, 현안, 지연사유, 만회대책, 향후계획 | 값 1개(문장) |
| 추진경위·일정·쟁점 | 날짜별 경위(실적), 향후 일정(계획), 쟁점·관계기관별 입장 | 여러 줄(DB `events` 표) |

- 규칙 추출은 표 머리글(예상·착공·부담 열), 관리카드 머리(사업명 | 정상추진), "2029년 착공", "ㅇ (지연사유) …", "-‘26.09:내용"·"(‘26년 하반기) 내용" 같은 경위 줄을 읽습니다. AI 추출은 같은 항목과 경위·쟁점 목록을 JSON으로 받습니다.
- 확인: 💾 DB › 📂 문서 관리 › "📋 DB 적재 현황". 보고서: 사업개요(지구 개요·기호·예상 완료 열), 추진경위(날짜별), 추진현황(착공·예상 완료·관리상태), 주요 현안(쟁점·지연사유·만회대책), 향후 계획(일정).
- 2차 후보: 비목별·연도별 사업비, 집행액·추진율, 관계기관 협의의견·조치계획, 회의 안건·결과, 위원회 조건부 사항.

## 모델 교체 (`config.yaml`)
모든 LLM 호출은 `common/llm.py`의 `ask(prompt, system=None, json_mode=False)` 한 곳을 거칩니다.
```yaml
llm:
  provider: openai_compatible      # anthropic 또는 openai_compatible
  model: <모델 이름>
  base_url: http://localhost:11434/v1
  api_key_env: OPENAI_API_KEY      # 키가 필요 없는 로컬 서버면 ""
```

## 폴더 구성
```
app.py                화면(Streamlit): 담당자가 agent를 부르는 곳
pipeline.py           agent 4개를 화면 없이 차례로 실행
selftest.py           인수 시험(10번: agent 연결)
config.yaml           모델 설정, 사업지구·사업(유형)·유형별 항목(= A01 분류 체계)
agents/
  a01_extract/        A01 문서 내용 추출   agent.py · reader.py · AGENT.md
  a02_resolve/        A02 최신값 판정·DB 갱신   agent.py · store.py(DB) · resolver.py(판정 규칙 원본) · test_resolver.py · AGENT.md
  a03_query/          A03 목적별 자료 추출   agent.py · query.py(자료표) · compare.py(통합 비교·질문) · AGENT.md
  a04_draft/          A04 보고서 초안 작성   agent.py(자동 점검·양식 적용) · draft.py · lh_style.py · hwpx_forms.py · AGENT.md
common/               여러 agent가 같이 쓰는 것: llm.py(모델 교체 지점) · catalog.py(지구·사업·항목) · fmt.py(값 표기)
templates/            보고서 한글 서식(합성). 회사 양식은 templates/company/ (저장소에 올리지 않음)
sample/               모의 문서 26개(누리마루 18·한빛·솔내 8) + A01 추출 결과 예시 CSV
tools/                개발용: 규칙 추출 정확도 점검, 모의 문서 생성
output/               산출물(DB·항목 후보 표·자료표·초안·업로드 사본). 원본 문서와 분리
```

## 데이터와 보안
- 모든 데이터는 **가상(합성) 데이터**입니다. 가상 지구: 누리마루·한빛·솔내. 실제 사업·기관·문서·개인정보와 무관합니다.
- 원본 문서는 읽기만 하고, 산출물은 `output/`에만 만듭니다.
- 회사 권장양식 서식 파일(`templates/company/`)은 저장소에 없습니다. 없으면 워드에만 회사 양식이 적용되고 한글본은 기본 서식으로 나옵니다.
- API 키는 환경변수로만 넣습니다.

## 알려진 제약사항
- 문서 단계·일자는 파일명으로 추정하고 💾 DB 화면에서 사람이 고칩니다.
- 단위가 다른 값(예: 억원과 백만원)은 정규화하지 않습니다.
- 도면 인식(OCR), 스캔 PDF, 로그인·권한은 범위 밖입니다. 여러 지구 통합 비교·챗봇 코드(`compare.py`)는 남아 있으나, 멘토 의견에 따라 화면에서는 뺐습니다.
- 문장형 항목(추진상태·현안·향후계획)도 수치와 같은 규칙으로 정합니다. 같은 단계·같은 날짜 문서끼리 표현이 조금만 달라도 '확인 필요'가 됩니다.
- 각 agent가 정의서와 다르게 구현된 부분은 그 agent의 `AGENT.md` "정의서와 다른 점"에 적었습니다.
- 오픈소스 라이선스: Streamlit(Apache-2.0), Altair(BSD-3-Clause), pandas(BSD-3-Clause), openpyxl(MIT), python-docx(MIT), pdfplumber(MIT), PyYAML(MIT), fpdf2(LGPL-3.0, 모의 문서 생성 도구에서만).
