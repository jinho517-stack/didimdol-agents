"""사업지구·사업(시설)·항목 목록. config.yaml의 districts × item_templates(+common_items)로 만든다.
통합 비교에 쓰는 사업 유형 추정과 시행주체 구분(지자체/LH/국가)도 여기서 한다."""
import re
from pathlib import Path

from common import llm


LOCAL = Path(__file__).resolve().parents[1] / 'output' / 'local_districts.yaml'  # 화면에서 추가한 사업지구(산출물 폴더)
DISTRICT_FAC = '지구 공통'  # 지구 전체 값(사업시행자·대책 수립일 …)을 담는 행. 사업 목록·보고서 사업 줄에서는 뺀다


def projects_of(cat, district):
    """그 지구의 광역시설(사업) 이름 목록 — '지구 공통' 제외"""
    return [f for (d, f) in cat['types'] if d == district and f != DISTRICT_FAC]


def local_districts():
    import yaml
    if LOCAL.exists():
        return yaml.safe_load(LOCAL.read_text(encoding='utf-8')) or []
    return []


def save_local_district(name, facilities, key=None):
    """화면에서 새 사업지구 등록/수정. facilities: [{'name':…, 'type':…}]. config.yaml은 건드리지 않는다."""
    import yaml
    ds = [d for d in local_districts() if d['name'] != name]
    ds.append({'name': name, 'key': key or re.sub(r'(지구|단지)$', '', name), 'facilities': facilities})
    LOCAL.parent.mkdir(parents=True, exist_ok=True)
    LOCAL.write_text(yaml.safe_dump(ds, allow_unicode=True, sort_keys=False), encoding='utf-8')


RAIL_WORDS = re.compile(r'철도|전철|지하철|경전철|GTX|트램', re.I)


GENERIC = {'철도', '도로', '환승', '환승시설', '대중교통', '접속시설', '연결도로', '도로확장', '확장', '광역철도', '광역도로',
           '버스', '광역교통', '광역교통시설', '사업', '공통', '신설', '개선', '교차로', '철도사업', '도로사업'}


def is_generic(name):
    """사업 이름이 아니라 분야·일반 낱말인지(예: '철도', '연결도로', '도로·대중교통')"""
    n = re.sub(r'\s', '', name or '')
    return len(n) < 3 or n in GENERIC or all(p in GENERIC for p in re.split(r'[·,/및]', n) if p)


def merge_found(district, texts):
    """올린 문서에서 찾은 사업 중 등록 목록에 없는 것을 화면 등록 지구에 더한다(기본 지구는 그대로). 반환: 더한 사업 이름들"""
    local = {d['name']: d for d in local_districts()}
    if district not in local:
        return []
    cur = [f for f in _repair(local[district])['facilities']]
    def same(a, b):
        a, b = re.sub(r'\s|\(.*?\)', '', a), re.sub(r'\s|\(.*?\)', '', b)
        return a == b or a in b or b in a
    add = [s for s in suggest_facilities(texts) if not is_generic(s['name']) and not any(same(s['name'], f['name']) for f in cur)]
    if add or len(cur) != len(local[district].get('facilities', [])):
        save_local_district(district, cur + add, key=local[district].get('key'))
    return [s['name'] for s in add]


def _repair(d):
    """화면에서 등록한 지구: 예전 유형 추정 오류('개선'·'n호선' 등을 철도로 봄)로 저장된 '철도'를 바로잡는다.
    이름에 철도라는 말이 없고 지금 규칙으로는 철도가 아니면 지금 규칙의 유형으로 본다(담당자가 고친 값은 '철도' 외에는 그대로)."""
    facs = []
    for f in d.get('facilities', []):
        if is_generic(f['name']):  # '철도'·'연결도로'처럼 사업 이름이 아닌 낱말은 뺀다
            continue
        t = f.get('type')
        if t == '철도' and not RAIL_WORDS.search(f['name']):
            g = facility_type({'types': {}}, '', f['name'])
            t = g if g != '철도' else t
        facs.append({**f, 'type': t})
    return {**d, 'facilities': facs}


def load(cfg=None):
    cfg = dict(cfg or llm.load_config())
    names = {d['name'] for d in cfg.get('districts', [])}
    cfg['districts'] = list(cfg.get('districts', [])) + [_repair(d) for d in local_districts() if d['name'] not in names]
    tpl, common = cfg.get('item_templates', {}), cfg.get('common_items', [])
    items, types = [], {}
    for d in cfg.get('districts', []):
        facs = list(d.get('facilities', []))
        if '지구' in tpl:  # 지구 전체에 하나인 값(사업시행자·대책 수립일·최초 입주·총사업비)
            facs.append({'name': DISTRICT_FAC, 'type': '지구'})
        for fac in facs:
            types[(d['name'], fac['name'])] = fac['type']
            for it in tpl.get(fac['type'], []) + (common if fac['type'] != '지구' else []):
                items.append({'district': d['name'], 'facility': fac['name'], 'type': fac['type'], 'item': it['item'],
                              'unit': it.get('unit') or '', 'kind': it.get('kind', '')})
    return {
        'default': cfg.get('district') or (cfg.get('districts') or [{'name': ''}])[0]['name'],
        'districts': [d['name'] for d in cfg.get('districts', [])],
        'keys': {d['name']: d.get('key') or d['name'] for d in cfg.get('districts', [])},
        'items': items,
        'types': types,
        'kinds': {it['item']: it['kind'] for it in items if it['kind']},
    }


def items_for(cat, district):
    return [i for i in cat['items'] if i['district'] == district]


def order(cat, district=None):
    """보고서·화면에 쓸 (시설, 항목) 순서."""
    return [(i['facility'], i['item']) for i in cat['items'] if district is None or i['district'] == district]


def guess_district(cat, filename):
    name = Path(filename).name
    hits = [(len(key), d) for d, key in cat['keys'].items() if key and key in name]
    return max(hits)[1] if hits else cat['default']  # 긴 이름 우선('미리내'가 '미리'보다 먼저)


def guess_dept(texts):
    """문서들에 가장 많이 나온 작성 부서(○○사업본부·○○사업단·○○처, 뒤의 ○○팀까지). 없으면 ''"""
    cnt = {}
    for t in texts:
        for m in re.finditer(r'(?<![가-힣])([가-힣]{2,10}(?:사업본부|사업단|처)(?:\s[가-힣]{2,8}팀)?)(?![가-힣])', t or ''):
            w = m.group(1)
            if not re.match(r'(관계|담당|조치|처리|대처|관련)', w):
                cnt[w] = cnt.get(w, 0) + 1
    return max(cnt, key=lambda w: (cnt[w], len(w))) if cnt else ''


# ---------- 새 사업지구 이름 자동 인식 ----------
# 지구 이름이 드러나는 표현: "해오름지구", "해오름 공공주택지구", "해오름 택지개발지구", "해오름신도시", "해오름사업본부·사업단"
_DIST_PAT = re.compile(r'([가-힣]{2,6})\s?(?:공공주택|택지개발|도시개발|보금자리)?\s?(?:지구|신도시|사업본부|사업단)(?![가-힣])')
_NOT_NAME = re.compile(r'도로|철도|확장|개선|대책|반영|교통|주택|개발|사업|협의|검토|계획|담당|보고|결과|현황|회의|광역|시행|관리|'
                       r'공공|택지|도시|변경|요약|설명|통보|회신|의견|조치|노선|현안|점검|자료|카드|메모|부분|대상|해당|인근|전체|신규|기존|각')
_PLACE_END = ('시', '도', '군', '구', '선', '로', '역', '청', '처', '부', '팀', '과')


def _name_ok(w):
    return 2 <= len(w) <= 6 and not _NOT_NAME.search(w) and not w.endswith(_PLACE_END)


def _file_word(filename):
    """파일명의 첫 한글 낱말(날짜·괄호 빼고). 예: '260219 해오름 광역교통…' → '해오름', '미리내지구 …' → '미리내'"""
    stem = re.sub(r'^\s*\d{6,8}\s*', '', Path(filename).stem)
    stem = re.sub(r'\[[^\]]*\]|\([^)]*\)', ' ', stem)
    m = re.match(r'\s*([가-힣]+)', stem)
    return re.sub(r'(지구|신도시)$', '', m.group(1)) if m else ''


def detect_district(cat, files, texts=(), cfg=None, use_llm=False):
    """올린 문서들의 파일명·본문에서 사업지구 이름을 찾는다.
    점수: 파일명 첫 낱말 3점(문서마다) · 본문 첫 200자 안 지구 표현 3점 · 그 밖 본문 지구 표현 1점.
    파일명 낱말은 본문에도 지구 표현으로 나오거나 두 문서 이상에 있을 때만 인정한다(우연한 낱말 제외).
    반환: {'name','key','known'(등록된 지구 이름|None),'source','evidence','others':[다른 후보]} 또는 None"""
    score, src, fword_cnt, in_pat = {}, {}, {}, set()

    def add(w, pts, why):
        score[w] = score.get(w, 0) + pts
        src.setdefault(w, [])
        if why not in src[w]:
            src[w].append(why)
    for i, f in enumerate(files):
        text = texts[i] if i < len(texts) else ''
        for m in _DIST_PAT.finditer(text or ''):
            w = m.group(1)
            if _name_ok(w):
                in_pat.add(w)
                add(w, 3 if m.start() < 200 else 1, f'본문 "{m.group(0).strip()}"')
        for m in _DIST_PAT.finditer(Path(f).stem):
            if _name_ok(m.group(1)):
                in_pat.add(m.group(1))
        w = _file_word(f)
        if _name_ok(w):
            fword_cnt[w] = fword_cnt.get(w, 0) + 1
    for w, n in fword_cnt.items():
        if w in in_pat or n >= 2:
            add(w, 3 * n, f'파일명 {n}건')
    # 등록된 지구는 이름·키로도 찾는다(본문에 "누리마루"만 있어도 인정)
    for d, key in cat['keys'].items():
        k = re.sub(r'(지구|신도시)$', '', key or d)
        if k in score:
            continue
        n = sum(k in Path(f).name for f in files)
        if n:
            add(k, 3 * n, f'파일명 {n}건')
    source = '파일명·본문'
    if not score and use_llm and llm.available(cfg):  # 규칙으로 못 찾으면 AI에게 문서 앞부분을 보여 주고 묻는다
        head = '\n\n'.join(f'[{Path(f).name}]\n{(texts[i] if i < len(texts) else "")[:500]}' for i, f in enumerate(files[:5]))
        try:
            ans = llm.ask_json(f'{head}\n\n위 문서들이 다루는 공공주택·택지 사업지구 이름을 하나만 답하라. '
                               '모르면 빈 문자열. 출력: {"district": "○○지구"}', cfg=cfg)
            w = re.sub(r'\s|(지구|신도시)$', '', str(ans.get('district') or ''))
            if _name_ok(w):
                add(w, 1, 'AI 추정')
                source = 'AI'
        except Exception:
            pass
    if not score:
        return None
    ranked = sorted(score, key=lambda w: (-score[w], -len(w)))
    best = ranked[0]
    known = next((d for d, key in cat['keys'].items()
                  if re.sub(r'(지구|신도시)$', '', key or d) == best or d in (best, best + '지구')), None)
    return {'name': known or best + '지구', 'key': best, 'known': known, 'source': source,
            'evidence': ', '.join(src[best]),
            'others': [w + '지구' for w in ranked[1:] if score[w] >= max(3, score[best] / 3)]}


def facility_type(cat, district, facility):
    t = cat['types'].get((district, facility))
    if t:
        return t
    # 사업명으로 유형 추정(등록된 사업이 아닐 때). 순서가 중요: 접속 → 환승 → 대중교통 → 철도(분명한 말) → 도로 → 철도(○○선)
    if '접속' in facility:
        return '접속시설'
    if re.search(r'환승|교통광장|역광장|주차장', facility):
        return '환승'
    if re.search(r'버스|BRT|대중교통|차고지|DRT', facility, re.I):
        return '대중교통'
    if re.search(r'철도|전철|지하철|경전철|GTX|트램', facility, re.I):
        return '철도'
    if re.search(r'도로|국도|지방도|우회|교량|교차로|IC|램프|확장|개설|지하차도|고가|연결로|육교|자전거', facility, re.I):
        return '도로'
    # '○○선'은 철도 노선(예: 해오름선)이지만 '개선·노선·차선·선형'과 '1호선·315호선'(도로 노선 번호)은 아님
    if re.search(r'(?<![개노차직곡\d])(?<!\d호)[가-힣]{1,}선(\(|\s|$)', facility) and not re.search(r'\d+호선|개선|노선|차선|선형', facility):
        return '철도'
    return '도로'


FAC_SUFFIX = (r'(?:연결도로|도로확장|도로|확장|IC|JC|교차로|교량|지하차도|램프|선(?:\([^)]*\))?|BRT|DRT|트램|환승센터|환승주차장|'
              r'센터|차고지|공영차고지|정류장|주차장|버스\s?지원|지원)')


def _clean_fac(name, district=''):
    """사업명 다듬기: 앞의 지구 이름('다온 ', '다온지구 ')·뒤의 '조성'·'신설'을 뗀다(다온IC처럼 붙은 이름은 그대로)."""
    n = re.sub(r'\s+', ' ', name or '').strip(' ·,')
    stem = re.sub(r'(공공주택)?지구$', '', district or '').strip()
    if stem:
        n = re.sub(rf'^{re.escape(stem)}(\s*공공주택지구|지구)?\s+', '', n)
    return re.sub(r'\s+(조성|신설|설치|사업)$', '', n).strip()


def suggest_facilities(texts, district=''):
    """새 지구 문서에서 사업명 후보 찾기: 표의 '사업명' 칸, "ㅇ (사업 현황) ○○(…)는", "ㅇ (○○도로) …", 표 첫 칸,
    "○○선/○○IC/○○센터/○○차고지" 같은 낱말."""
    pat = r'[가-힣A-Za-z0-9·]+(?:\s[가-힣A-Za-z0-9·]+){0,3}?\s?' + FAC_SUFFIX
    seen = {}

    def add(c, w=1):
        c = _clean_fac(c, district)
        if c and not re.search(r'\d{4}|억|km|㎡|공공주택지구|광역교통개선대책', c) and not is_generic(c):
            seen[c] = seen.get(c, 0) + w
    for t in texts:
        lines = [re.sub(r'^\[[^\]]+\]\s*', '', ln).strip() for ln in t.splitlines()]  # '[3행] ' 같은 위치 표시 뗌
        for i, ln in enumerate(lines):  # 표 '사 업 명' 칸 다음 줄 = 사업 이름(한글 표는 칸마다 한 줄로 읽힘)
            if re.fullmatch(r'사\s*업\s*명', ln):
                nxt = next((x for x in lines[i + 1:i + 3] if x), '')
                if 2 <= len(nxt) <= 30 and not re.search(r'공공주택지구|조성사업 및', nxt):
                    add(re.sub(r'\(.*?\)$', '', nxt), 3)
            m = re.match(r'[ㅇ○◦·\-]?\s*\(사업\s*현황\)\s*([^()]{2,25}?)\s*\(', ln)  # (사업 현황) 광역BRT(11.2km, …)는
            if m and re.fullmatch(pat, _clean_fac(m.group(1), district)):
                add(m.group(1), 2)
        for line in t.splitlines():
            body = re.sub(r'^\[[^\]]+\]\s*', '', line)
            cands = re.findall(r'\(([^()]{2,25}(?:\([^)]*\))?)\)', body)
            if '|' in body:
                cands.append(body.split('|')[0].strip())
            lead = re.match(r'\s*[□ㅇ○◦·\-]?\s*([^:：()]{2,25}?(?:\([^)]*\))?)\s*[:：]', body)  # "□ ○○ 연결도로: …"
            if lead:
                cands.append(lead.group(1))
            for c in cands:
                if re.fullmatch(pat, c.strip()) and not re.search(r'\d{4}|억|km|㎡', c):
                    add(c.strip())
    out = []
    for name, _ in sorted(seen.items(), key=lambda x: -x[1]):
        if not any(name != o and name in o for o in seen) and not is_generic(name):  # 더 긴 이름 우선, 일반 낱말 제외
            out.append({'name': name, 'type': facility_type({'types': {}}, '', name)})
    return out[:12]


def ai_facilities(texts, cfg=None, district=''):
    """규칙으로 사업을 못 찾았을 때: AI가 문서 제목·앞부분을 읽고 광역교통개선대책 사업 목록을 고른다(문서에 나온 이름만)."""
    from common import llm
    if not llm.available(cfg):
        return []
    heads = '\n\n'.join(f'[문서 {i + 1}]\n' + (t or '')[:1500] for i, t in enumerate(texts[:12]))
    prompt = ('아래 문서들은 한 사업지구의 광역교통개선대책 관련 보고서다. 이 지구의 광역교통 사업(도로·IC·철도·BRT·버스·환승센터·차고지 등) '
              '목록을 뽑아라. 문서에 나온 이름 그대로 쓰되 앞의 지구 이름("다온 ", "○○지구 ")과 뒤의 "조성"은 뗀다. '
              '지구 전체(공공주택지구 조성사업)·기관·회의는 빼고, 같은 사업은 한 번만.\n'
              f'유형은 {", ".join(["도로", "철도", "환승", "대중교통", "접속시설"])} 중 하나.\n'
              f'{heads}\n출력 형식: {{"projects": [{{"name": "...", "type": "..."}}]}}')
    try:
        data = llm.ask_json(prompt, cfg=cfg)
    except Exception:
        return []
    joined = re.sub(r'\s', '', ' '.join(texts))
    out = []
    for x in data.get('projects') or []:
        name = _clean_fac(str(x.get('name') or ''), district)
        if name and not is_generic(name) and re.sub(r'\s', '', name) in joined and name not in [o['name'] for o in out]:
            t = str(x.get('type') or '')
            out.append({'name': name, 'type': t if t in ('도로', '철도', '환승', '대중교통', '접속시설') else facility_type({'types': {}}, '', name)})
    return out[:12]


def entity_class(name):
    """시행주체 문구 → 구분. 예) 가온시 → 지자체(기초), A도 → 지자체(광역), 사업시행자(LH) → LH(사업시행자)."""
    s = (name or '').strip()
    if not s:
        return '미정'
    if re.search(r'LH|사업시행자|토지주택', s):
        return 'LH(사업시행자)'
    if re.search(r'국가철도공단|국토교통부|국토부|공단|국가', s):
        return '국가·공공기관'
    if re.search(r'(특별시|광역시|특별자치시|[가-힣A-Z]도)(\s|$|\()', s + ' '):
        return '지자체(광역)'
    if re.search(r'[가-힣]+(시|군|구)(\s|$|\()', s + ' '):
        return '지자체(기초)'
    return '기타'
