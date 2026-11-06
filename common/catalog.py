"""사업지구·사업(시설)·항목 목록. config.yaml의 districts × item_templates(+common_items)로 만든다.
통합 비교에 쓰는 사업 유형 추정과 시행주체 구분(지자체/LH/국가)도 여기서 한다."""
import re
from pathlib import Path

from common import llm


LOCAL = Path(__file__).resolve().parents[1] / 'output' / 'local_districts.yaml'  # 화면에서 추가한 사업지구(산출물 폴더)


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


def load(cfg=None):
    cfg = dict(cfg or llm.load_config())
    names = {d['name'] for d in cfg.get('districts', [])}
    cfg['districts'] = list(cfg.get('districts', [])) + [d for d in local_districts() if d['name'] not in names]
    tpl, common = cfg.get('item_templates', {}), cfg.get('common_items', [])
    items, types = [], {}
    for d in cfg.get('districts', []):
        for fac in d.get('facilities', []):
            types[(d['name'], fac['name'])] = fac['type']
            for it in tpl.get(fac['type'], []) + common:
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
    for d, key in cat['keys'].items():
        if key and key in name:
            return d
    return cat['default']


def facility_type(cat, district, facility):
    t = cat['types'].get((district, facility))
    if t:
        return t
    if re.search(r'철도|[가-힣]선(\(|$| )|전철|지하철', facility):
        return '철도'
    if '환승' in facility:
        return '환승'
    if re.search(r'버스|BRT|대중교통', facility):
        return '대중교통'
    return '도로'


def suggest_facilities(texts):
    """새 지구 문서에서 사업명 후보 찾기: "ㅇ (○○도로) …", 표 첫 칸, "○○선/○○IC/○○센터" 같은 낱말."""
    pat = r'[가-힣A-Za-z0-9·]+(?:\s[가-힣A-Za-z0-9·]+){0,3}?\s?(?:연결도로|도로확장|도로|확장|IC|교차로|선(?:\([^)]*\))?|BRT|환승센터|환승주차장|센터|버스\s?지원|지원)'
    seen = {}
    for t in texts:
        for line in t.splitlines():
            body = re.sub(r'^\[[^\]]+\]\s*', '', line)
            cands = re.findall(r'\(([^()]{2,25}(?:\([^)]*\))?)\)', body)
            if '|' in body:
                cands.append(body.split('|')[0].strip())
            for c in cands:
                m = re.fullmatch(pat, c.strip())
                if m and not re.search(r'\d{4}|억|km|㎡', c):
                    seen[c.strip()] = seen.get(c.strip(), 0) + 1
    out = []
    for name, _ in sorted(seen.items(), key=lambda x: -x[1]):
        if not any(name != o and name in o for o in seen):  # 더 긴 이름이 있으면 그쪽
            out.append({'name': name, 'type': facility_type({'types': {}}, '', name)})
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
