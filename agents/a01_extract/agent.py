"""A01 문서 내용 추출 Agent  (Agent정의서_1_문서내용추출)

시작 조건  담당자가 타겟 문서를 올리고(문서 선택) 처리 시작("값 뽑기")을 눌렀을 때
입력      타겟 문서(PDF·한글 hwpx·워드·엑셀·텍스트) + 추출 항목 목록(분류 체계: config.yaml의 지구·사업·항목)
출력      항목 후보 표: 시설·사업, 항목, 값, 단위, 출처(문서명·위치), 문서 단계, 문서 일자, 읽기 실패 표시
          → A02가 읽는다. 파일로도 남긴다(output/a01_항목후보표.csv)
사람 개입  별도 승인 없음. 읽지 못한 문서는 "확인 필요"(읽기 실패)로 표시하고, 화면에서 틀린 값을 빼고 저장한다.

수행 단계
 ① 문서를 읽는다                         reader.read_text
 ② 문서 단계·일자를 찾는다(파일명 추정)     reader.describe / guess_meta
 ③ 분류 체계의 항목마다 값·단위를 뽑는다     AI(LLM): reader.extract_candidates / 키 없으면 규칙: reader.rule_extract
 ④ 값마다 출처(문서ID·파일·위치)를 붙인다   (③의 결과에 포함)
 ⑤ 못 찾은 값은 만들지 않는다(추측 금지), 읽기 실패는 표시
 ⑥ 항목 후보 표로 저장하고 A02에 넘긴다     save_table
"""
import csv
from pathlib import Path

from agents.a01_extract import reader

NAME = 'A01 문서 내용 추출'
TABLE = Path(__file__).resolve().parents[2] / 'output' / 'a01_항목후보표.csv'
COLUMNS = ['doc_id', 'file', 'district', 'stage', 'date', 'version_kind', 'facility', 'item', 'value', 'unit',
           'location', 'error']


def describe(paths, start_num=1, cat=None):
    """② 올린 파일 목록 → 문서 정보(문서ID·단계·일자·버전·형식). 단계·일자는 파일명으로 추정(화면에서 고침)."""
    return reader.describe(paths, start_num, cat)


def run(docs, items, use_llm=False, cfg=None, on_progress=None):
    """①~⑤ 문서마다 항목 후보를 뽑는다.
    docs: describe()의 결과(문서 정보), items: 추출 항목 목록 [{'facility','item','unit'}]
    반환: [(문서, 후보 목록, 오류 문구)]  — 오류 문구가 있으면 '확인 필요(읽기 실패)'"""
    out = []
    for i, d in enumerate(docs, 1):
        if on_progress:
            on_progress(i, len(docs), d)
        try:
            text = reader.read_text(d['path'])
            facs = list(dict.fromkeys(i['facility'] for i in items))
            if use_llm:
                cands, meta = reader.extract_candidates(d, items, cfg, text=text)
                events = meta.get('events') or []
                if not any(e['kind'] in ('경위', '계획') for e in events):  # AI가 경위를 안 줬으면 규칙으로 보탬
                    events += reader.extract_events(text, facs, d.get('date'))
            else:
                cands = reader.rule_extract(d, items, text=text)
                events = reader.extract_events(text, facs, d.get('date'))
            d['events'] = events  # 추진경위·향후 일정(날짜별 여러 줄) → A02가 events 표에 저장
            out.append((d, cands, ''))
        except Exception as e:  # 값을 추측해 채우지 않고 읽기 실패로 넘긴다
            out.append((d, [], f'읽기 실패(확인 필요): {e}'))
    return out


def load_sample(sample_dir, extra=False, other=False, default_district=''):
    """샘플 모드: 모의 문서의 '추출 결과 예시'(sample/*.csv)를 A01 출력으로 쓴다(API 키 없이 전체 흐름 시연용)."""
    return reader.load_sample(sample_dir, extra, other, default_district)


def save_table(results, path=TABLE):
    """⑥ 항목 후보 표를 CSV(UTF-8 BOM)로 남긴다. results: run()의 반환 형식."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, COLUMNS)
        w.writeheader()
        for d, cands, err in results:
            base = {k: d.get(k, '') for k in ('doc_id', 'file', 'district', 'stage', 'date', 'version_kind')}
            if not cands:
                w.writerow({**base, 'error': err or '찾은 값 없음'})
            for c in cands:
                w.writerow({**base, **{k: c.get(k, '') for k in ('facility', 'item', 'value', 'unit', 'location')},
                            'error': err})
    return path
