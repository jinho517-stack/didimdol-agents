"""A01 ⑤ 문서 분류: 올린 자료(문서관리대장 행·고시문·내부보고·도면)를 '어느 교통대책(사업)'과 '어떤 내용'으로 나눈다.
- 규칙: 제목·본문에 나온 사업 이름(띄어쓰기 무시, 괄호 앞 이름 포함)과 내용 낱말(공사·인허가·설계 …)로 1차 분류
- 사람 확인이 필요한 경우: 사업이 0개(대책 무관?)·2개 이상 나옴, 날짜를 못 찾음 → '확인 필요' + 멈춘 이유
- AI(키가 있을 때): 확인 필요 문서만 한 번에 보내 추천 답(사업·내용·이유)을 받는다. 담당자가 정한 예시를 함께 보낸다.
담당자가 정한 결과는 output/intake_examples.json에 쌓여 다음 분류의 예시가 된다."""
import json
import re
from pathlib import Path

from agents.a01_extract.reader import _aliases, _ns
from common import llm

KINDS = ['광역교통개선대책 보고서', '문서관리대장', '도면', '고시문', '내부 보고자료']
KIND_SHORT = {'광역교통개선대책 보고서': '대책보고서', '문서관리대장': '문서대장', '도면': '도면', '고시문': '고시문',
              '내부 보고자료': '내부보고'}
KIND_HELP = {'광역교통개선대책 보고서': '사업 개요와 대책 목록(기준정보)을 뽑습니다',
             '문서관리대장': '공문 목록(엑셀·CSV) · 행마다 문서 1건, 대책이 섞여 있음',
             '도면': '표제란·파일명으로 대책에 연결', '고시문': '고시일을 공식 날짜로 사용',
             '내부 보고자료': '주간·월간·현안 보고 등 내부 보고 문서'}
CONTENTS = ['설계', '인허가', '보상', '공사', '협의·민원', '사업비 집행', '공통']
STAGE4 = ['설계', '인허가', '보상', '공사']  # 사업 진행 단계(왼쪽 목록의 막대)
COMMON = '공통 · 대책 무관'
STATUS = ['확인 필요', '자동 확정', '사람 결정', '적재 완료']
# 내용 낱말: 위에서부터 먼저 맞는 것
CONTENT_KW = [('사업비 집행', ('분담금', '정산', '집행', '예산', '지급')),
              ('인허가', ('승인', '인가', '고시', '허가', '도로구역', '실시계획', '지정')),
              ('보상', ('보상', '편입', '감정평가', '수용', '토지')),
              ('공사', ('공사', '착공', '준공', '공정', '시공', '안전점검', '하부공', '상부공')),
              ('설계', ('설계', '평면도', '배치도', '종단', '횡단', '선형', '기본계획', '노선도', '도면')),
              ('협의·민원', ('협의', '민원', '의견', '요청', '회신', '주민', '설명회', '회의'))]
EXAMPLES = Path(__file__).resolve().parents[2] / 'output' / 'intake_examples.json'


def content_hit(text):
    """(내용 구분, 맞은 낱말). 없으면 ('공통', '')"""
    for name, kws in CONTENT_KW:
        for k in kws:
            if k in (text or ''):
                return name, k
    return '공통', ''


def content_of(text):
    return content_hit(text)[0]


def clues(doc, limit=4):
    """사람이 읽을 단서 줄: [(어디서, 문장)]. 제목 + 본문 중 대책 이름·내용 낱말이 나온 줄(긴 줄은 앞부분만)."""
    out = [('제목', doc['title'])]
    kws = [k for name, ks in CONTENT_KW if name == doc.get('content') for k in ks]
    ments = [_ns(m) for m in doc.get('mentions') or []]
    for ln in (doc.get('text') or '').splitlines():
        ln = ln.strip()
        if not ln or _ns(ln) == _ns(doc['title']) or len(out) >= limit:
            continue
        if any(m in _ns(ln) for m in ments) or any(k in ln for k in kws):
            out.append(('본문', ln if len(ln) <= 110 else ln[:110] + '…'))
    return out


def why(doc):
    """분류 근거를 쉬운 문장으로: [교통대책 근거, 내용 근거]"""
    m = doc.get('mentions') or []
    fac = (f"제목·본문에 대책 이름 {len(m)}개: {', '.join(m)}" if m else '제목·본문에 대책 이름이 없음')
    name, kw = content_hit(doc['title'])
    if not kw:
        name, kw = content_hit((doc.get('text') or '')[:1500])
    con = f"'{kw}' 낱말 → {name}" if kw else '내용 낱말 없음 → 공통'
    return [fac, con]


def mentions(text, facilities):
    """본문·제목에 나온 사업들(이름이 긴 것부터, 짧은 이름이 긴 이름 안에 있으면 하나로)."""
    t = _ns(text)
    al = _aliases(facilities)
    found = [f for f in facilities if any(a in t for a in al[f])]
    return [f for f in found if not any(f != g and _ns(f) in _ns(g) for g in found)]


def guess_kind(filename):
    n = Path(filename).name
    if re.search(r'대장|목록', n) and Path(n).suffix.lower() in ('.xlsx', '.csv'):
        return '문서관리대장'
    if re.search(r'평면도|배치도|도면|노선도|종단|횡단', n):
        return '도면'
    if '고시' in n:
        return '고시문'
    if re.search(r'개선대책\(안\)|개선대책 수립|대책\(안\) 요약', n):
        return '광역교통개선대책 보고서'
    return '내부 보고자료'


# ---------- 문서관리대장(엑셀·CSV) → 행마다 문서 ----------
def read_ledger(path):
    """열 이름으로 일자·문서번호·제목을 찾는다. 반환: [{'date','docno','title'}]"""
    import pandas as pd
    p = Path(path)
    df = pd.read_csv(p, dtype=str, encoding='utf-8-sig') if p.suffix.lower() == '.csv' else pd.read_excel(p, dtype=str)
    df = df.fillna('')
    cols = {c: str(c) for c in df.columns}
    pick = lambda pat: next((c for c, s in cols.items() if re.search(pat, s)), None)  # noqa: E731
    c_date, c_no, c_title = pick(r'일자|날짜|시행일|접수일'), pick(r'문서\s*번호|번호'), pick(r'제목|건명|문서명')
    rows = []
    for _, r in df.iterrows():
        title = str(r[c_title]).strip() if c_title else ''
        if not title:
            continue
        rows.append({'row': int(_) + 2, 'date': _date(str(r[c_date])) if c_date else '', 'docno': str(r[c_no]).strip() if c_no else '',
                     'title': title})
    return rows


def _date(s):
    s = (s or '').strip()
    m = re.search(r'(20\d{2})[-./년\s]+(\d{1,2})[-./월\s]+(\d{1,2})', s)
    if m:
        return f'{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}'
    m = re.match(r'(\d{2})(\d{2})(\d{2})(?!\d)', s)
    return f'20{m.group(1)}-{m.group(2)}-{m.group(3)}' if m else ''


def date_in_text(text, kind):
    """본문에서 날짜 찾기. 고시문은 '고시일'·'고시' 근처 날짜를 공식 날짜로 쓴다."""
    if kind == '고시문':
        m = re.search(r'고시[^\n]{0,30}?(20\d{2}[.\-년\s]+\d{1,2}[.\-월\s]+\d{1,2})', text or '')
        if m:
            return _date(m.group(1))
    m = re.search(r'(문서일자|시행일자|작성일|일자)\s*[:：]?\s*(20\d{2}[.\-년\s]+\d{1,2}[.\-월\s]+\d{1,2})', text or '')
    return _date(m.group(2)) if m else ''


# ---------- 분류 ----------
def rule(doc, facilities):
    """규칙 분류 한 건. doc: {'title','text','date','kind'} → doc에 facility·content·status·reason·options를 채워 돌려준다."""
    head = doc['title']
    found = mentions(head, facilities) or mentions(doc.get('text', '')[:3000], facilities)
    content = content_of(head) if content_of(head) != '공통' else content_of(doc.get('text', '')[:1500])
    reasons = []
    if len(found) == 1:
        fac = found[0]
    elif not found:
        fac = COMMON
        reasons.append('제목·본문에서 교통대책 이름을 찾지 못했습니다. 공통 자료인지, 어느 대책인지 정해 주세요.')
    else:
        fac = COMMON if content in ('사업비 집행', '공통') else found[0]
        reasons.append(f'한 문서에 대책 {len(found)}개가 함께 나옵니다. 하나로 정할지, 공통으로 둘지 정해 주세요.')
    if not doc.get('date'):
        reasons.append('날짜를 파일명·본문에서 찾지 못했습니다. 날짜를 확인해 주세요.')
    doc.update(facility=fac, content=content, mentions=found, options=list(dict.fromkeys([fac] + found + [COMMON])),
               status='확인 필요' if reasons else '자동 확정', reason=' '.join(reasons), how='규칙')
    return doc


def load_examples():
    try:
        return json.loads(EXAMPLES.read_text(encoding='utf-8'))
    except Exception:
        return []


def save_example(doc, district):
    """담당자가 정한 분류를 예시로 쌓는다(다음 AI 분류 때 보여 줌)."""
    ex = [e for e in load_examples() if e.get('title') != doc['title']]
    ex.append({'district': district, 'title': doc['title'], 'facility': doc['facility'], 'content': doc['content']})
    EXAMPLES.parent.mkdir(parents=True, exist_ok=True)
    EXAMPLES.write_text(json.dumps(ex[-200:], ensure_ascii=False, indent=1), encoding='utf-8')


def ai_suggest(docs, facilities, district, cfg=None):
    """확인 필요 문서만 AI에게 보내 추천(사업·내용·이유)을 받는다. 상태는 그대로 '확인 필요'(사람이 정함)."""
    need = [d for d in docs if d['status'] == '확인 필요']
    if not need:
        return 0
    ex = [e for e in load_examples() if e.get('district') == district][-20:]
    items = [{'id': i, '종류': d['kind'], '제목': d['title'], '본문 앞부분': d.get('text', '')[:400]} for i, d in enumerate(need)]
    prompt = (f'[사업지구] {district}\n[교통대책 목록] {json.dumps(facilities, ensure_ascii=False)}\n'
              f'[내용 구분] {json.dumps(CONTENTS, ensure_ascii=False)}\n'
              + (f'[담당자가 정한 예시] {json.dumps(ex, ensure_ascii=False)}\n' if ex else '')
              + f'[분류할 문서] {json.dumps(items, ensure_ascii=False)}\n\n'
              f'문서마다 가장 맞는 교통대책 하나(목록 이름 그대로, 특정 대책이 아니면 "{COMMON}")와 내용 구분 하나를 고르고, '
              '고른 이유를 25자 이내로 써라. 출력: {"items": [{"id": 0, "facility": "...", "content": "...", "why": "..."}]}')
    try:
        data = llm.ask_json(prompt, system='너는 LH 광역교통 담당자의 문서 분류를 돕는 도구다. 목록에 없는 이름은 쓰지 않는다.', cfg=cfg)
    except Exception:
        return 0
    n = 0
    for x in data.get('items') or []:
        try:
            d = need[int(x['id'])]
        except (KeyError, ValueError, IndexError, TypeError):
            continue
        fac, con = x.get('facility'), x.get('content')
        if fac in facilities or fac == COMMON:
            d['facility'] = fac
            d['options'] = list(dict.fromkeys([fac] + d['options']))
        if con in CONTENTS:
            d['content'] = con
        if x.get('why'):
            d['ai_why'] = str(x['why'])[:60]
        d['how'] = 'AI 추천'
        n += 1
    return n


def classify(docs, facilities, district='', use_llm=False, cfg=None):
    for d in docs:
        rule(d, facilities)
    n_ai = ai_suggest(docs, facilities, district, cfg) if use_llm and llm.available(cfg) else 0
    return n_ai


def stage_bar(docs, facility):
    """대책별 진행 막대: 설계 → 인허가 → 보상 → 공사 중 자료가 있는 가장 뒤 단계(누적 막대).
    반환: (현재 단계 번호 0~3, 없으면 -1), 단계 이름('자료 없음'·'단계 미상' 포함)"""
    fs = [d for d in docs if d['facility'] == facility]
    idx = max((STAGE4.index(d['content']) for d in fs if d['content'] in STAGE4), default=-1)
    return idx, (STAGE4[idx] if idx >= 0 else ('자료 없음' if not fs else '단계 미상'))
