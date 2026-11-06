"""A01: 문서 읽기 + LLM으로 항목 후보 추출. 원본 문서는 읽기만 한다(수정·이동·삭제 안 함)."""
import csv
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from common import llm

FORMATS = {'.pdf': 'PDF', '.docx': '워드', '.xlsx': '엑셀', '.hwpx': '한글', '.txt': '텍스트'}
STAGES = ['확정·승인본', '협의결과', '보고', '초안', '비공식']
VERSIONS = ['', '최종', '변경안', '원안']
MAX_CHARS = 30000


# ---------- 문서 읽기 (표는 행 단위 텍스트로, 위치 표시를 [ ]로 붙임) ----------
def read_pdf(path):
    import pdfplumber
    out = []
    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages, 1):
            out.append(f'[{i}쪽]')
            out.append(page.extract_text() or '')
            for t, table in enumerate(page.extract_tables(), 1):
                for r, row in enumerate(table, 1):
                    out.append(f'[{i}쪽 표{t} {r}행] ' + ' | '.join((c or '').replace('\n', ' ') for c in row))
    return '\n'.join(out)


def read_docx(path):
    import docx
    from docx.table import Table
    d = docx.Document(path)
    out, t = [], 0
    for el in d.element.body.iterchildren():
        tag = el.tag.rsplit('}', 1)[-1]
        if tag == 'p':
            txt = ''.join(n.text or '' for n in el.iter() if n.tag.endswith('}t'))
            if txt.strip():
                out.append(txt)
        elif tag == 'tbl':
            t += 1
            for r, row in enumerate(Table(el, d).rows, 1):
                cells = []
                for c in row.cells:  # 병합 셀 중복 제거
                    if not cells or cells[-1] != c.text:
                        cells.append(c.text)
                out.append(f'[표{t} {r}행] ' + ' | '.join(x.replace('\n', ' ') for x in cells))
    return '\n'.join(out)


def read_xlsx(path):
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    out = []
    for ws in wb.worksheets:
        for r, row in enumerate(ws.iter_rows(values_only=True), 1):
            vals = [str(v) for v in row if v is not None and str(v).strip()]
            if vals:
                out.append(f'[{ws.title} {r}행] ' + ' | '.join(vals))
    wb.close()
    return '\n'.join(out)


def read_hwpx(path):
    """hwpx는 zip. Contents/section*.xml의 <hp:t> 텍스트를 문단(<hp:p>) 단위로 읽는다."""
    lines = []

    def walk(el, buf):
        tag = el.tag.rsplit('}', 1)[-1]
        if tag == 't':
            buf.append(''.join(el.itertext()))
        else:
            for ch in el:
                walk(ch, buf)
        if tag == 'p' and buf:
            line = ''.join(buf).strip()
            if line:
                lines.append(line)
            buf.clear()

    with zipfile.ZipFile(path) as z:
        names = sorted(n for n in z.namelist() if re.fullmatch(r'Contents/section\d+\.xml', n))
        for n in names:
            walk(ET.fromstring(z.read(n)), [])
    return '\n'.join(lines)


def read_txt(path):
    raw = Path(path).read_bytes()
    for enc in ('utf-8-sig', 'cp949'):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode('utf-8', 'replace')
    return '\n'.join(f'[{i}행] {line}' for i, line in enumerate(text.splitlines(), 1))


READERS = {'.pdf': read_pdf, '.docx': read_docx, '.xlsx': read_xlsx, '.hwpx': read_hwpx, '.txt': read_txt}


def read_text(path):
    ext = Path(path).suffix.lower()
    if ext not in READERS:
        raise ValueError(f'지원하지 않는 형식: {ext}')
    return READERS[ext](path)


# ---------- 문서 단위 정보 추정 (업로드 화면에서 사람이 확인·수정) ----------
def guess_meta(filename):
    name = Path(filename).stem
    m = re.match(r'(\d{2})(\d{2})(\d{2})', name)
    date = f'20{m.group(1)}-{m.group(2)}-{m.group(3)}' if m else ''
    if '메모' in name or '비공식' in name:
        stage = '비공식'
    elif any(k in name for k in ('협의결과', '회의결과', '결과 알림', '결과알림', '결과 통보', '회신')):
        stage = '협의결과'
    elif '초안' in name:
        stage = '초안'
    elif any(k in name for k in ('확정', '승인')):
        stage = '확정·승인본'
    else:
        stage = '보고'
    version = ''
    if stage == '보고':
        if '최종' in name:
            version = '최종'
        elif '변경(안)' in name or '변경안' in name:
            version = '변경안'
        elif '(안)' in name:
            version = '원안'
    return {'date': date, 'stage': stage, 'version_kind': version}


def describe(paths, start_num=1, cat=None):
    """파일 목록 → 문서 표(문서ID는 파일명 순으로 D01, D02 ...). cat이 있으면 파일명으로 사업지구도 추정."""
    from common import catalog
    docs = []
    for i, p in enumerate(sorted(paths, key=lambda x: Path(x).name), start_num):
        p = Path(p)
        docs.append({'doc_id': f'D{i:02d}', 'file': p.name, 'format': FORMATS.get(p.suffix.lower(), p.suffix),
                     'path': str(p), 'district': catalog.guess_district(cat, p.name) if cat else '',
                     **guess_meta(p.name)})
    return docs


def list_folder(folder):
    return sorted(p for p in Path(folder).iterdir() if p.is_file() and p.suffix.lower() in FORMATS)


# ---------- 샘플 모드: A01 추출 결과 예시(candidates_sample.csv) ----------
def load_sample(sample_dir, extra=False, other=False, default_district=''):
    """기본 모의문서 11개(candidates_sample.csv). extra=True면 누리마루 현안 문서 7개(extra/),
    other=True면 다른 가상 지구 문서 8개(other/)를 더한다. CSV에 지구 열이 없으면 default_district로 본다."""
    sets = [(Path(sample_dir), 'candidates_sample.csv')]
    if extra:
        sets.append((Path(sample_dir) / 'extra', 'candidates_extra.csv'))
    if other:
        sets.append((Path(sample_dir) / 'other', 'candidates_other.csv'))
    cands = []
    for folder, name in sets:
        with open(folder / name, encoding='utf-8') as f:
            cands += [dict(c, _dir=str(folder), district=c.get('district') or default_district) for c in csv.DictReader(f)]
    docs = {}
    for c in cands:
        p = Path(c.pop('_dir')) / c['file']
        if c['doc_id'] not in docs:
            docs[c['doc_id']] = {'doc_id': c['doc_id'], 'district': c['district'], 'file': c['file'], 'date': c['date'],
                                 'stage': c['stage'], 'version_kind': c['version_kind'],
                                 'format': FORMATS.get(p.suffix.lower(), p.suffix), 'path': str(p)}
    docs = sorted(docs.values(), key=lambda d: (d['date'], d['doc_id']))
    return docs, cands


# ---------- LLM 추출 ----------
SYSTEM = '너는 공공기관 사업 문서에서 지정된 항목의 값만 찾아 옮기는 도구다. 추측하거나 계산하지 않는다.'

PROMPT = """[추출할 항목 목록] (시설 / 항목 / 단위)
{items}

[규칙]
1. 위 목록에 있는 항목만 뽑는다. 문서에 없는 값은 절대 만들지 않는다.
2. 문서에서 찾지 못한 항목은 value를 null로 둔다.
3. 값마다 location(문서 속 위치: 쪽·표·행 또는 문단 제목)을 반드시 적는다. 본문의 [ ] 표시를 활용한다.
4. unit은 항목 목록의 단위로 통일한다. 숫자는 쉼표 없이 쓴다(예: 12,000㎡ → value "12000", unit "㎡"). 단위가 빈 항목(시기·목표)은 문서 표기 그대로(예: "2031.6").
5. 문장형 항목(추진상태·현안·향후계획)은 문서에 적힌 내용만 짧게 옮긴다. 추진상태는 15자 안팎의 상태 표현(예: "협의 지연(○○시 반대)", "실시설계 착수"), 현안·향후계획은 문서 표현을 살린 1~2문장. 문서에 그 시설의 현안·계획이 없으면 null.
6. 문서 단위 정보: stage는 {stages} 중 하나, date는 문서일자(YYYY-MM-DD), version_kind는 "최종", "변경안", "원안", "" 중 하나.

[출력 형식]
{{"stage": "...", "date": "YYYY-MM-DD", "version_kind": "...",
  "facts": [{{"facility": "...", "item": "...", "value": "..." 또는 null, "unit": "...", "location": "..."}}]}}

[문서] 파일명: {file}
{text}"""


def extract_candidates(doc, items, cfg=None, text=None):
    """문서 하나 → (후보 목록, LLM이 판단한 문서 정보). 문서 단계·일자는 업로드 화면의 값을 따른다."""
    text = text if text is not None else read_text(doc['path'])
    item_lines = '\n'.join(f"- {i['facility']} / {i['item']} / {i.get('unit') or '(없음)'}" for i in items)
    prompt = PROMPT.format(items=item_lines, stages=', '.join(STAGES), file=doc['file'], text=text[:MAX_CHARS])
    data = llm.ask_json(prompt, system=SYSTEM, cfg=cfg)
    if isinstance(data, list):
        data = {'facts': data}
    units = {(i['facility'], i['item']): i.get('unit') or '' for i in items}
    out = []
    for f in data.get('facts', []) or []:
        k = (f.get('facility'), f.get('item'))
        v = f.get('value')
        if k not in units or v is None or str(v).strip() in ('', 'null', 'None'):
            continue
        v = str(v).strip()
        if re.fullmatch(r'[\d,]+(\.\d+)?', v):  # 숫자만 쉼표 제거(문장형 값의 쉼표는 그대로)
            v = v.replace(',', '')
        out.append({'doc_id': doc['doc_id'], 'facility': k[0], 'item': k[1],
                    'value': v, 'unit': units[k], 'location': str(f.get('location') or '')})
    meta = {k: data.get(k) for k in ('stage', 'date', 'version_kind')}
    return out, meta


# ---------- 간이 추출(키 없을 때): 규칙으로 값 찾기 ----------
# 표: 머리글 행(연장·차로·사업비·완료 …)을 읽어 같은 표의 사업 행에서 칸별 값을 가져온다. "당초 | 변경" 표는 변경 값을 쓴다.
# 본문: 사업명이 나온 줄에서 "연장 2.1km", "4차로", "사업비 520억원", "완료 2031.6" 같은 표현을 찾는다.
# 문장형: "현안·향후계획" 제목 아래 "ㅇ (사업명) 내용" 줄, 또는 표의 해당 칸. 결과는 화면에서 확인한 뒤 저장한다.
HEADER_ITEMS = [('시행주체', '시행주체'), ('추진상태', '추진상태'), ('현안', '현안'), ('조치계획', '향후계획'),
                ('향후계획', '향후계획'), ('연장', '연장'), ('차로', '차로'), ('사업비', '사업비'), ('지원', '지원액'),
                ('규모', '규모'), ('완료', '@완료'), ('준공', '@완료'), ('개통', '@개통')]
LOC = re.compile(r'^\[([^\]]+)\]\s*')
BULLET = re.compile(r'^\s*(?:ㅇ|o|○|-|·|\d+\)|[가-하]\.)?\s*\(([^()]+(?:\([^)]*\))?[^()]*)\)\s*[:：]?\s*(.+)$')
UNIT_HINT = {'연장': 'km', '차로': '차로', '규모': '㎡'}
TEXT_ITEMS = ('시행주체', '추진상태', '현안', '향후계획')


def _ns(s):
    return re.sub(r'\s+', '', s or '')


def _aliases(facilities):
    """사업명 → 찾을 낱말들(띄어쓰기 무시). 괄호 앞 이름, 다른 사업과 겹치지 않는 첫 낱말도 쓴다."""
    out = {}
    firsts = [f.split()[0] for f in facilities if ' ' in f]
    for f in facilities:
        al = {_ns(f), _ns(re.sub(r'\(.*?\)', '', f))}
        w = f.split()[0]
        if ' ' in f and len(w) >= 3 and firsts.count(w) == 1:
            al.add(_ns(w))
        out[f] = sorted((a for a in al if len(a) >= 2), key=len, reverse=True)
    return out


def _time(y, m):
    return f'{y}.{int(m)}'


def _from_segment(seg, items, support=False, last=False):
    """띄어쓰기를 지운 조각에서 값 찾기 → {항목: 값}. support: 지원사업(금액은 지원액). last: 여러 값이면 마지막(변경 후)."""
    def pick(pat):
        ms = list(re.finditer(pat, seg))
        return (ms[-1] if last else ms[0]) if ms else None
    got = {}
    m = pick(r'(?:연장|L=)([\d.]+)km') or pick(r'([\d.]+)km')
    if m and '연장' in items:
        got['연장'] = m.group(1)
    m = pick(r'(\d+)차로')
    if m and '차로' in items:
        got['차로'] = m.group(1)
    if not re.search(r'→|증액|증가|요구|에서[\d,]+억', seg):  # 변경 요구·증액 문장의 금액은 값으로 보지 않음
        m = pick(r'([\d,]+(?:\.\d+)?)억원?')
        if m:
            sup = support or '지원' in seg[:m.start()] or '사업비' not in items
            key = '지원액' if sup and '지원액' in items else '사업비'
            if key in items:
                got[key] = m.group(1).replace(',', '')
    m = pick(r'([\d,]+)㎡')
    if m and '규모' in items:
        got['규모'] = m.group(1).replace(',', '')
    for m in re.finditer(r'(20\d\d)[.\-년](\d{1,2})(?![\d.])', seg):
        around = seg[max(0, m.start() - 8):m.end() + 6]
        if re.search(r'완료|개통|준공', around):
            key = '개통목표' if '개통목표' in items and ('개통' in around or '완료시기' not in items) else '완료시기'
            if key in items:
                got[key] = _time(m.group(1), m.group(2))
            break
    return got


def rule_extract(doc, items, text=None):
    """문서 하나 → 후보 목록(LLM 없이). items: 그 지구의 항목 목록(catalog.items_for)."""
    text = text if text is not None else read_text(doc['path'])
    by_fac = {}
    for i in items:
        by_fac.setdefault(i['facility'], {})[i['item']] = i.get('unit') or ''
    aliases = _aliases(list(by_fac))
    found, headers, raw_head = {}, {}, {}
    section, last_fac, mentioned = None, None, []

    def put(fac, item, value, loc):
        value = re.sub(r'\s+', ' ', str(value)).strip(' ,·|')
        if item in by_fac.get(fac, {}) and value and value not in ('-', '—'):
            found.setdefault((fac, item), (value, loc))  # 같은 문서 안에서는 처음 나온 값

    def facs_in(s):
        ns, hits = _ns(s), []
        for fac, als in aliases.items():
            for a in als:
                p = ns.find(a)
                if p >= 0:
                    hits.append((p, p + len(a), fac))
                    break
        out = []  # 같은 자리에서 겹치면 더 긴 이름(예: "미리내선(광역철도)" > "미리내")
        for h in sorted(hits, key=lambda h: (h[0], -(h[1] - h[0]))):
            if not out or h[0] >= out[-1][1]:
                out.append(h)
        return out

    for n, line in enumerate(text.splitlines(), 1):
        m = LOC.match(line)
        loc, body = (m.group(1), line[m.end():]) if m else (f'{n}번째 줄', line)
        if not body.strip():
            continue
        if '|' in body:  # 표의 행
            table = re.sub(r'\s*\d+행$', '', loc)
            raw_head.setdefault(table, body)
            changed = bool(re.search(r'당초|기존|변경\s*전', raw_head[table]))
            cells = [c.strip() for c in body.split('|')]
            cols = {}
            for ci, c in enumerate(cells):
                for word, item in HEADER_ITEMS:
                    if word in _ns(c) and item not in cols:
                        cols[item] = ci
                        break
            if len(cols) >= 2 and not facs_in(cells[0] + (cells[1] if len(cells) > 1 else '')):
                headers[table] = cols
                continue
            hits = facs_in(' '.join(cells[:2]))
            if hits and table in headers:
                fac = hits[0][2]
                mentioned.append(fac)
                items_f = by_fac[fac]
                for item, ci in headers[table].items():
                    if ci >= len(cells):
                        continue
                    c = cells[ci]
                    if item in ('@완료', '@개통'):
                        t = re.search(r'(20\d\d)[.\-년](\d{1,2})', _ns(c))
                        if t:
                            want = '개통목표' if item == '@개통' else '완료시기'
                            other = '완료시기' if want == '개통목표' else '개통목표'
                            put(fac, want if want in items_f else other, _time(*t.groups()), loc)
                    elif item in TEXT_ITEMS:
                        put(fac, item, c, loc)
                    else:
                        bare = re.fullmatch(r'[\d,.]+', _ns(c))
                        if bare:  # 단위 없는 숫자: 머리글 항목으로
                            key = '지원액' if item == '사업비' and '지원' in fac and '지원액' in items_f else item
                            put(fac, key, _ns(c).replace(',', ''), loc)
                        else:  # 단위가 적힌 칸: 단위로 항목을 정한다(예: 연장 칸의 12,000㎡ → 규모)
                            for k2, x in _from_segment(_ns(c), items_f, support='지원' in fac).items():
                                put(fac, k2, x, loc)
                continue
            if hits:  # 머리글 없는 표 행(예: 변경 항목 | 당초 | 변경): 본문처럼 읽되 변경 값을 쓴다
                fac = hits[0][2]
                mentioned.append(fac)
                seg = _ns(body)[hits[0][1]:]
                for item, v in _from_segment(seg, by_fac[fac], support='지원' in fac, last=changed).items():
                    put(fac, item, v, loc)
                continue
        # 제목 줄: 아래 내용이 현안인지 계획인지 기억
        head = re.match(r'^\s*(?:□|■|◇|\d+\.|[IVX]+\.)\s*(.{0,30})$', body)
        if head:
            t = _ns(head.group(1))
            section = 'plan' if re.search(r'향후|계획|일정|조치', t) else \
                'issue' if re.search(r'현안|결정|협의의견|협의결과|주요내용|쟁점', t) else None
            last_fac = None
            continue
        b = BULLET.match(body)
        bhit = facs_in(b.group(1)) if b else []
        bfac = bhit[0][2] if bhit else None
        if section and bfac:  # "ㅇ (사업명) 내용"
            text_v = b.group(2).strip()
            mentioned.append(bfac)
            if section == 'plan':
                put(bfac, '향후계획', text_v, loc)
            elif len(_ns(text_v)) <= 20 and not re.search(r'[.다]$', text_v):
                put(bfac, '추진상태', text_v, loc)
            else:
                put(bfac, '현안', text_v, loc)
            last_fac = bfac
        elif section == 'issue' and last_fac and re.match(r'^\s*-\s*', body):  # 바로 위 사업의 세부 내용
            put(last_fac, '현안', re.sub(r'^\s*-\s*', '', body), loc)
            continue
        elif section == 'plan' and not facs_in(body) and len(set(mentioned)) == 1 and len(_ns(body)) > 6:
            put(mentioned[0], '향후계획', body.strip(), loc)  # 사업 하나만 다루는 문서의 계획 문장
            continue
        # 본문 줄: 사업명이 나온 자리부터 다음 사업명 전까지를 그 사업의 내용으로 본다
        hits = facs_in(body)
        ns = _ns(body)
        for k, (s_, e, fac) in enumerate(hits):
            mentioned.append(fac)
            seg = ns[e:hits[k + 1][0]] if k + 1 < len(hits) else ns[e:]
            for item, v in _from_segment(seg, by_fac[fac], support='지원' in fac).items():
                put(fac, item, v, loc)
            for word in ('시행주체', '추진상태'):
                t = re.search(word + r'\s*[:：]?\s*([^,·|]+)', body)
                if t:
                    put(fac, word, t.group(1), loc)
    return [{'doc_id': doc['doc_id'], 'facility': f, 'item': it, 'value': v, 'unit': by_fac[f][it], 'location': loc}
            for (f, it), (v, loc) in found.items()]
