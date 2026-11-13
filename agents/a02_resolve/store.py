"""SQLite 저장소 (facts, history, sources, choices + A01 후보 candidates). 산출물은 output/ 아래에만 만든다.
값을 정하는 것은 resolver.resolve()이고, 이 파일은 그 결과를 DB에 반영하고 이력·선택 기록을 남긴다.
문서마다 사업지구(district)가 있고, 판정은 지구별로 그 지구 문서의 후보만 모아 resolver를 따로 돌린다.
전체 후보로 매번 다시 판정하므로 문서를 넣는 순서와 관계없이 같은 결과가 된다."""
import json
import re
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from agents.a02_resolve.resolver import INFORMAL, key, norm, resolve

OUTPUT = Path(__file__).resolve().parents[2] / 'output'  # 프로젝트 맨 위 output/
DB_PATH = OUTPUT / 'didimdol.db'

SCHEMA = """
create table if not exists sources(doc_id text primary key, district text, file text, date text, stage text,
    version_kind text, format text, path text);
create table if not exists candidates(id integer primary key, doc_id text, facility text, item text,
    value text, unit text, location text);
create table if not exists facts(id integer primary key, district text, facility text, item text, value text,
    unit text, status text, method text, source_doc text, source_file text, source_loc text, doc_stage text,
    doc_date text, updated_at text, note text, history_text text, conflict_candidates text,
    unique(district, facility, item));
create table if not exists history(id integer primary key, facts_id integer, prev_value text, new_value text,
    reason text, kind text, changed_at text);
create table if not exists choices(id integer primary key, district text, facility text, item text, candidates text,
    value text, chooser text, chosen_at text, active integer default 1);
create table if not exists events(id integer primary key, doc_id text, district text, facility text, kind text,
    date text, content text, location text);
"""


def now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def connect(path=DB_PATH):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    cols = [r[1] for r in con.execute('pragma table_info(sources)')]
    if cols and 'district' not in cols:  # 지구 구분 전 DB(시연용)는 새 구조로 다시 만든다
        con.executescript('drop table if exists sources; drop table if exists candidates; drop table if exists facts; '
                          'drop table if exists history; drop table if exists choices;')
    con.executescript(SCHEMA)
    refresh_views(con)
    return con


# ---------- 사람이 보기 좋은 가로형 보기(View) ----------
# facts 표는 '사업 | 항목 | 값'을 한 줄씩 쌓는 세로형이라 항목이 늘어도 표를 고칠 필요가 없다.
# 사람이 DB 파일을 열어 볼 때는 사업 한 줄에 항목이 칸으로 펼쳐진 보기가 편하므로, 같은 데이터를 보여 주는 View를 둔다.
# View는 저장 공간을 따로 쓰지 않고 facts·events를 그때그때 펼쳐 보여 준다(값을 고치는 곳은 여전히 facts).
VIEW_WIDE = '사업별_최신값'
VIEW_EVENTS = '경위_일정_쟁점'


def _config_items():
    """config.yaml 항목 → [(항목, 단위)] 보기 좋은 순서: 속성 → 수치 → 날짜 → 문장 → 지구 공통"""
    try:
        import yaml
        cfg = yaml.safe_load((OUTPUT.parent / 'config.yaml').read_text(encoding='utf-8')) or {}
    except Exception:
        return []
    tpl, common = cfg.get('item_templates') or {}, cfg.get('common_items') or []
    attrs = [x for x in common if x.get('kind') == 'attr']
    texts = [x for x in common if x.get('kind') != 'attr']
    typed = [x for k, v in tpl.items() if k != '지구' for x in (v or [])]
    nums = [x for x in typed if x.get('unit')]
    dates = [x for x in typed if not x.get('unit')]
    out = {}
    for x in attrs + nums + dates + texts + (tpl.get('지구') or []):
        out.setdefault(x['item'], x.get('unit') or '')
    return list(out.items())


def refresh_views(con):
    """가로형 보기를 다시 만든다(항목 목록이 바뀌어도 칸이 맞게). DB를 열 때마다 부른다."""
    items = _config_items()
    known = {i for i, _ in items}
    items += [(r[0], r[1] or '') for r in con.execute('select item, max(unit) from facts group by item') if r[0] not in known]

    def q(s):
        return "'" + str(s).replace("'", "''") + "'"

    def name(s):
        return '"' + str(s).replace('"', '""') + '"'
    # 값이 없는 미확정(충돌) 칸에는 후보들을 ' / '로 이어 보여 준다(예: 2031.12 / 2032.6 [미확정(충돌)])
    cell = ("coalesce(value, (select group_concat(json_extract(j.value, '$.value'), ' / ') "
            "from json_each(case when json_valid(conflict_candidates) then conflict_candidates else '[]' end) j), '')"
            " || case when status = '확정' then '' else ' [' || status || ']' end")
    cols = ',\n    '.join(f"max(case when item = {q(i)} then {cell} end) as {name(f'{i}({u})' if u else i)}" for i, u in items)
    con.executescript(
        f'drop view if exists {name(VIEW_WIDE)};\n'
        f'create view {name(VIEW_WIDE)} as select district as "사업지구", facility as "사업",\n'
        f"    sum(status <> '확정') as \"확인 필요 수\",\n    {cols}\n"
        f"from facts group by district, facility\n"
        f"order by district, case when facility = '지구 공통' then 0 else 1 end, facility;\n"
        f'drop view if exists {name(VIEW_EVENTS)};\n'
        f'create view {name(VIEW_EVENTS)} as select e.district as "사업지구", e.facility as "사업", e.kind as "종류",\n'
        f'    e.date as "날짜", e.content as "내용", s.file as "출처 문서", e.location as "위치"\n'
        f'from events e left join sources s on s.doc_id = e.doc_id\n'
        f"order by e.district, e.facility, case e.kind when '경위' then 0 when '계획' then 1 else 2 end, e.date;\n")


def rows(con, sql, args=()):
    return [dict(r) for r in con.execute(sql, args)]


def reset(con):
    con.executescript('delete from sources; delete from candidates; delete from facts; '
                      'delete from history; delete from choices; delete from events;')
    con.commit()


# ---------- 문서·후보 ----------
def next_doc_num(con):
    nums = [int(m.group(1)) for (d,) in con.execute('select doc_id from sources')
            if (m := re.fullmatch(r'D(\d+)', d))]
    return max(nums, default=0) + 1


def doc_id_for_file(con, file):
    r = con.execute('select doc_id from sources where file=?', (file,)).fetchone()
    return r[0] if r else None


def save_document(con, doc, cands):
    """문서 정보와 그 문서의 후보를 저장(같은 문서ID는 교체)."""
    con.execute('insert or replace into sources(doc_id, district, file, date, stage, version_kind, format, path) '
                'values(?,?,?,?,?,?,?,?)', (doc['doc_id'], doc.get('district') or '', doc['file'], doc['date'],
                                            doc['stage'], doc.get('version_kind') or '', doc.get('format', ''),
                                            doc.get('path', '')))
    con.execute('delete from candidates where doc_id=?', (doc['doc_id'],))
    con.executemany('insert into candidates(doc_id, facility, item, value, unit, location) values(?,?,?,?,?,?)',
                    [(doc['doc_id'], c['facility'], c['item'], c['value'], c.get('unit', ''), c.get('location', ''))
                     for c in cands])
    # 추진경위·향후 일정(날짜별 여러 줄): 판정 없이 문서별로 쌓는다(같은 문서를 다시 넣으면 교체)
    con.execute('delete from events where doc_id=?', (doc['doc_id'],))
    con.executemany('insert into events(doc_id, district, facility, kind, date, content, location) values(?,?,?,?,?,?,?)',
                    [(doc['doc_id'], doc.get('district') or '', e['facility'], e['kind'], e['date'], e['content'],
                      e.get('location', '')) for e in doc.get('events') or []])
    con.commit()


def events(con, district, facility=None, kind=None, informal=False):
    """추진경위(kind='경위')·향후 일정(kind='계획') 목록. 같은 사업·날짜·내용은 한 줄로(가장 최근 문서 기준).
    반환: [{'facility','kind','date','content','doc_id','doc_date','stage','location'}] (날짜순)"""
    sql = ('select e.facility, e.kind, e.date, e.content, e.doc_id, e.location, s.date as doc_date, s.stage '
           'from events e join sources s on s.doc_id=e.doc_id where e.district=?')
    args = [district]
    if facility:
        sql += ' and e.facility=?'
        args.append(facility)
    if kind:
        sql += ' and e.kind=?'
        args.append(kind)
    seen = {}
    for r in rows(con, sql, args):
        if not informal and r['stage'] in INFORMAL:
            continue
        k = (r['facility'], r['kind'], r['date'], re.sub(r'\s+', '', r['content']))
        if k not in seen or (r['doc_date'] or '') > (seen[k]['doc_date'] or ''):
            seen[k] = r
    return sorted(seen.values(), key=lambda r: (r['facility'], _date_key(r['date']), r['content']))


def _date_key(d):
    """'2026.9' · '2026.9.17' · '2026 하반기' → 정렬용 (연, 월, 일)"""
    m = re.match(r'(20\d\d)(?:\.(\d{1,2}))?(?:\.(\d{1,2}))?', d or '')
    if not m:
        return (9999, 99, 99)
    mo = int(m.group(2)) if m.group(2) else (7 if '하반기' in (d or '') else (1 if '상반기' in (d or '') else 12))
    return (int(m.group(1)), mo, int(m.group(3) or 0))


def delete_document(con, doc_id):
    con.execute('delete from events where doc_id=?', (doc_id,))
    con.execute('delete from candidates where doc_id=?', (doc_id,))
    con.execute('delete from sources where doc_id=?', (doc_id,))
    con.commit()


def update_source_meta(con, doc_id, stage, date, version_kind, district=None):
    con.execute('update sources set stage=?, date=?, version_kind=?, district=coalesce(?, district) where doc_id=?',
                (stage, date, version_kind or '', district, doc_id))
    con.commit()


def load_candidates(con, district=None):
    """resolver 입력 형식(doc_id, file, date, stage, version_kind, facility, item, value, unit, location) + district."""
    return rows(con, """select s.doc_id, s.district, s.file, s.date, s.stage, coalesce(s.version_kind,'') version_kind,
        c.facility, c.item, c.value, coalesce(c.unit,'') unit, coalesce(c.location,'') location
        from candidates c join sources s on s.doc_id = c.doc_id
        where c.value is not null and trim(c.value) <> ''""" + (' and s.district=?' if district else '') + """
        order by s.doc_id, c.facility, c.item, c.id""", (district,) if district else ())


def active_choices(con, district):
    return {(r['facility'], r['item']): r['value']
            for r in rows(con, 'select facility, item, value from choices where active=1 and district=?', (district,))}


# ---------- 판정 결과 반영 ----------
def _winner(r, cs):
    """최신값의 근거 후보(출처 문서·위치·단계·일자)."""
    if r['value'] is None:
        return None
    if r['method'] == '사람 선택':
        docs = {d for v, d in r['candidates'] if norm(v) == norm(r['value'])}
    else:
        docs = {r['source'].split(' ', 1)[0]}
    official = [c for c in cs if c['stage'] not in INFORMAL]
    for c in sorted(official, key=lambda c: (key(c), c['doc_id']), reverse=True):
        if c['doc_id'] in docs and norm(c['value']) == norm(r['value']):
            return c
    return None


def _doc_history(con, fid, cs):
    """문서 기준 이력: 공식 후보를 우선순위 순으로 놓고 값이 바뀐 지점마다 기록(매번 다시 만듦)."""
    con.execute("delete from history where facts_id=? and kind='문서'", (fid,))
    last = None
    for c in sorted((c for c in cs if c['stage'] not in INFORMAL), key=lambda c: (key(c), c['doc_id'])):
        if norm(c['value']) != (norm(last) if last is not None else None):
            con.execute("insert into history(facts_id, prev_value, new_value, reason, kind, changed_at) "
                        "values(?,?,?,?,'문서',?)",
                        (fid, None if last is None else f"{last}{c['unit']}", f"{c['value']}{c['unit']}",
                         f"{c['stage']}{' ' + c['version_kind'] if c['version_kind'] else ''} {c['date']} "
                         f"{c['doc_id']} {c['file']} ({c['location']})", c['date']))
            last = c['value']


def _fact_id(con, district, facility, item):
    r = con.execute('select id from facts where district=? and facility=? and item=?', (district, facility, item)).fetchone()
    return r[0] if r else None


def recompute(con, default_district=''):
    """지구별로 resolver를 돌려 facts를 다시 만든다. 지구가 비어 있는 문서는 default_district로 본다."""
    if default_district:
        con.execute("update sources set district=? where district is null or district=''", (default_district,))
    cands = load_candidates(con)
    by_district = defaultdict(list)
    for c in cands:
        by_district[c['district']].append(c)
    ts, seen, results = now(), set(), []
    for district, dcands in sorted(by_district.items()):
        by_key = defaultdict(list)
        for c in dcands:
            by_key[(c['facility'], c['item'])].append(c)
        res = resolve(dcands, active_choices(con, district))
        res_map = {(r['facility'], r['item']): r for r in res}
        for r in res:
            k = (district, r['facility'], r['item'])
            seen.add(k)
            cs = by_key[(r['facility'], r['item'])]
            old = con.execute('select * from facts where district=? and facility=? and item=?', k).fetchone()
            value, w = r['value'], _winner(r, cs)
            src = dict(source_doc=w['doc_id'], source_file=w['file'], source_loc=w['location'],
                       doc_stage=w['stage'], doc_date=w['date']) if w else \
                dict(source_doc='', source_file='', source_loc='', doc_stage='', doc_date='')
            if r['status'] == '미확정(충돌)' and old and old['value'] is not None:
                # 선택 전에는 이전 확정값을 지우지 않고 '미확정' 표시만 붙인다
                value = old['value']
                src = {f: old[f] for f in src}
            tops = []
            for v, d in r['candidates']:
                c = next((c for c in cs if c['doc_id'] == d and norm(c['value']) == norm(v)), None)
                if c:
                    tops.append({f: c[f] for f in ('value', 'unit', 'doc_id', 'file', 'stage', 'date', 'location')})
            con.execute("""insert into facts(district, facility, item, value, unit, status, method, source_doc,
                    source_file, source_loc, doc_stage, doc_date, updated_at, note, history_text, conflict_candidates)
                values(:district,:facility,:item,:value,:unit,:status,:method,:source_doc,:source_file,:source_loc,
                    :doc_stage,:doc_date,:updated_at,:note,:history_text,:conflict_candidates)
                on conflict(district, facility, item) do update set value=excluded.value,
                    unit=excluded.unit, status=excluded.status, method=excluded.method, source_doc=excluded.source_doc,
                    source_file=excluded.source_file, source_loc=excluded.source_loc, doc_stage=excluded.doc_stage,
                    doc_date=excluded.doc_date, note=excluded.note, history_text=excluded.history_text,
                    conflict_candidates=excluded.conflict_candidates,
                    updated_at=case when facts.value is excluded.value and facts.status = excluded.status
                        then facts.updated_at else excluded.updated_at end""",
                        dict(district=district, facility=r['facility'], item=r['item'], value=value, unit=r['unit'],
                             status=r['status'], method=r['method'], updated_at=ts, note=r['note'],
                             history_text=r['history'], conflict_candidates=json.dumps(tops, ensure_ascii=False), **src))
            _doc_history(con, _fact_id(con, *k), cs)
        # 사람 선택 이후 더 높은 우선순위 문서가 들어와 충돌이 풀리면, 그 문서가 이기고 선택 기록은 이력으로 보관
        for ch in rows(con, 'select * from choices where active=1 and district=?', (district,)):
            r = res_map.get((ch['facility'], ch['item']))
            if r is None or r['method'] != '사람 선택':
                con.execute('update choices set active=0 where id=?', (ch['id'],))
                fid = _fact_id(con, district, ch['facility'], ch['item'])
                if fid:
                    con.execute("insert into history(facts_id, prev_value, new_value, reason, kind, changed_at) "
                                "values(?,?,?,?,'선택 보관',?)",
                                (fid, ch['value'], r['value'] if r else None,
                                 f"상위 문서 반영으로 담당자 선택({ch['value']}, {ch['chooser']} {ch['chosen_at']})을 "
                                 f"이력으로 보관 → {r['source'] if r else ''}", ts))
        results += [dict(r, district=district) for r in res]
    # 문서가 빠져 후보가 없어진 항목 정리
    for f in rows(con, 'select id, district, facility, item from facts'):
        if (f['district'], f['facility'], f['item']) not in seen:
            con.execute('delete from facts where id=?', (f['id'],))
            con.execute('delete from history where facts_id=?', (f['id'],))
    con.commit()
    return results


def save_choice(con, district, facility, item, value, chooser):
    f = con.execute('select * from facts where district=? and facility=? and item=?', (district, facility, item)).fetchone()
    ts = now()
    con.execute('update choices set active=0 where district=? and facility=? and item=? and active=1',
                (district, facility, item))
    con.execute('insert into choices(district, facility, item, candidates, value, chooser, chosen_at, active) '
                'values(?,?,?,?,?,?,?,1)',
                (district, facility, item, f['conflict_candidates'] if f else '[]', value, chooser, ts))
    if f:
        cands = json.loads(f['conflict_candidates'] or '[]')
        cand_txt = ' / '.join(f"{c['value']}{c['unit']}({c['doc_id']})" for c in cands)
        con.execute("insert into history(facts_id, prev_value, new_value, reason, kind, changed_at) "
                    "values(?,?,?,?,'사람 선택',?)",
                    (f['id'], f['value'], value, f'담당자 선택({chooser}) — 후보: {cand_txt}', ts))
    con.commit()
    return recompute(con)


# ---------- 조회 ----------
def facts(con, status=None, district=None):
    where = [w for w, v in (('status=?', status), ('district=?', district)) if v]
    sql = 'select * from facts' + (' where ' + ' and '.join(where) if where else '') + ' order by district, facility, item'
    return rows(con, sql, tuple(v for v in (status, district) if v))


def districts(con):
    return [r[0] for r in con.execute('select distinct district from sources where district <> "" order by district')]


def history(con, facts_id):
    # 문서 이력은 우선순위 순으로 넣었고, 선택·보관 기록은 발생 순으로 넣었으므로 id 순서가 곧 표시 순서
    return rows(con, "select * from history where facts_id=? order by kind <> '문서', id", (facts_id,))


def sources(con, district=None):
    return rows(con, 'select s.*, (select count(*) from candidates c where c.doc_id=s.doc_id) n_cand '
                     'from sources s' + (' where s.district=?' if district else '') + ' order by s.date, s.doc_id',
                (district,) if district else ())


def choices(con, district=None):
    return rows(con, 'select * from choices' + (' where district=?' if district else '') +
                ' order by chosen_at desc, id desc', (district,) if district else ())
