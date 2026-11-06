"""디딤돌 (agent 4개 구조).  실행: streamlit run app.py
화면은 담당자가 agent 4개를 차례로 부르는 곳이다. 계산은 모두 agents/ 안의 agent가 한다.
  A01 문서 내용 추출(agents/a01_extract) → A02 최신값 판정·DB 갱신(a02_resolve)
  → A03 목적별 자료 추출(a03_query) → A04 보고서 초안 작성(a04_draft)
화면: 🏠 처음 / 📊 대시보드(A02 결과 + 충돌 선택) / 💬 챗봇(A03) / 💾 DB(A01·A02, 통합 비교는 A03) / 📝 보고서 작성(A03→A04).
원본 문서는 읽기만 하고, DB·자료표·보고서·업로드 사본은 output/ 폴더에 만든다."""
import json
import re
from datetime import datetime
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from agents.a01_extract import agent as A01
from agents.a01_extract import reader as extract
from agents.a02_resolve import agent as A02
from agents.a02_resolve import store as db
from agents.a02_resolve.resolver import INFORMAL, norm  # noqa: F401
from agents.a03_query import agent as A03
from agents.a03_query import compare
from agents.a04_draft import agent as A04
from agents.a04_draft import draft
from common import catalog, llm

BASE = Path(__file__).parent
SAMPLE = BASE / 'sample'
UPLOADS = db.OUTPUT / 'uploads'
NAV = ['🏠 처음', '📊 대시보드', '💬 챗봇', '💾 DB', '📝 보고서 작성']  # 처음 화면 뒤로는 상단 메뉴 줄(처음 제외 4개)
HOME, DASH, CHAT, DOCS, REPORT = NAV
DB_VIEWS = ['📂 문서 관리', '🔎 통합 비교']
# 지구 구분 색: 기준 팔레트 범주형 순서(파랑·주황·청록 …), 지구 순서대로 고정
DISTRICT_COLOR = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#6250d6', '#e34948']
NO_VERSION = '없음'
METHOD_LABEL = {'충돌 없음': '충돌 없음', '규칙(단계 우선순위)': '규칙: 상위 단계', '규칙(같은 단계에서 최근 일자)': '규칙: 최근 일자',
                '사람 선택': '담당자 선택', '사람 선택 필요': '확인 필요', '공식 문서 없음': '공식 문서 없음'}
# 문서 단계(서열) 색: 기준 팔레트의 파랑 단계 ramp, 비공식은 회색
STAGE_ORDER = ['확정·승인본', '협의결과', '보고', '초안', '비공식']
STAGE_COLOR = ['#104281', '#256abf', '#5598e7', '#86b6ef', '#898781']

st.set_page_config(page_title='디딤돌', page_icon='📑', layout='wide')
cfg = llm.load_config()
CAT = catalog.load(cfg)  # 지구·사업·항목 목록 (config.yaml districts × item_templates)
KINDS = CAT['kinds']  # 문장형 항목: attr / status / issue / plan
DEPT = cfg.get('report', {}).get('dept', '')
HAS_LLM = llm.available(cfg)
con = db.connect()

st.markdown("""<style>
.dd-kpi{border:1px solid rgba(128,128,128,.28);border-radius:10px;padding:10px 14px;margin-bottom:8px}
.dd-kpi .n{font-size:1.8rem;font-weight:700;line-height:1.2}
.dd-kpi .l{font-size:.85rem;opacity:.75}
.dd-kpi.warn{border-color:#fab219;background:rgba(250,178,25,.10)}
.dd-card{border:1px solid rgba(128,128,128,.28);border-radius:12px;padding:12px 16px 8px;margin-bottom:14px}
.dd-card h4{margin:0 0 4px;font-size:1.05rem;padding:0}
.dd-row{display:flex;justify-content:space-between;align-items:center;padding:7px 0;
        border-top:1px solid rgba(128,128,128,.16);gap:10px}
.dd-item{font-size:.92rem}
.dd-change{font-size:.75rem;opacity:.7}
.dd-val{font-size:1.2rem;font-weight:700;text-align:right;white-space:nowrap}
.dd-meta{font-size:.74rem;opacity:.68;text-align:right}
.dd-chip{display:inline-block;font-size:.72rem;font-weight:600;padding:0 7px;border-radius:9px;margin-left:6px;
         border:1px solid #0ca30c;vertical-align:middle}
.dd-chip.warn{border-color:#fab219;background:rgba(250,178,25,.20)}
.dd-chip.ref{border-color:#898781}
.dd-ico-ok{color:#0ca30c}.dd-ico-warn{color:#c98500}
.dd-memo{font-size:.8rem;margin:2px 0 8px;padding:5px 9px;border-radius:8px;background:rgba(137,135,129,.13)}
.dd-status{font-size:.9rem;font-weight:600;margin:0 0 6px}
.dd-dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:#2a78d6;margin-right:6px;vertical-align:middle}
.dd-text{font-size:.86rem;padding:7px 0;border-top:1px solid rgba(128,128,128,.16);line-height:1.5}
.dd-tl{font-size:.74rem;font-weight:700;opacity:.75;margin-bottom:1px}
.dd-cand{border:1px solid rgba(128,128,128,.3);border-radius:10px;padding:10px 12px;margin-bottom:6px}
.dd-cand .v{font-size:1.6rem;font-weight:700}
.dd-cand .f{font-size:.82rem}.dd-cand .m{font-size:.76rem;opacity:.7}
.rp-paper{background:#fff;color:#111;border:1px solid #c9c9c9;border-radius:6px;padding:26px 30px;
          font-family:'Malgun Gothic','맑은 고딕',sans-serif;line-height:1.75;max-width:900px}
.rp-title{border:2px solid #1c5cab;background:#eef4fc;text-align:center;padding:10px;font-size:1.3rem;font-weight:700}
.rp-title small{display:block;font-size:.75rem;font-weight:400;color:#52514e}
.rp-date{text-align:right;font-size:.88rem;margin:6px 0 10px}
.rp-h{font-weight:700;font-size:1.06rem;margin:14px 0 2px}
.rp-b{padding-left:12px}.rp-s{padding-left:34px;font-size:.9rem;color:#333}.rp-act{font-weight:600}
.rp-cap{text-align:center;font-weight:600;margin:6px 0 2px;font-size:.88rem}
.rp-tw{overflow-x:auto}.rp-t{border-collapse:collapse;width:100%;font-size:.8rem;margin-bottom:6px}
.rp-t th,.rp-t td{border:1px solid #999;padding:3px 6px;text-align:center}.rp-t th{background:#efefec}
.rp-note{font-size:.8rem;margin-top:14px;color:#444}
.v2-title{font-size:1.9rem;font-weight:700;margin:4px 0 0}
.v2-sub{font-size:.92rem;opacity:.75;margin-bottom:12px}.v2-warn{color:#d03b3b}
.v2-q{font-weight:600;margin:6px 0 2px}
.v2-card{border:1px solid rgba(128,128,128,.25);border-left:5px solid;border-radius:12px;padding:12px 16px 10px;margin-bottom:6px}
.v2-h{display:flex;justify-content:space-between;align-items:center;gap:8px}
.v2-name{font-size:1.08rem;font-weight:700}
.v2-pill{font-size:.75rem;font-weight:700;border:1.5px solid;border-radius:10px;padding:0 8px;white-space:nowrap}
.v2-status{font-size:.85rem;opacity:.8;margin:2px 0 8px}
.v2-nums{display:flex;gap:22px;flex-wrap:wrap;margin-bottom:6px}
.v2-n .v{font-size:1.25rem;font-weight:700;line-height:1.2}.v2-n .l{font-size:.72rem;opacity:.65}
.v2-issue{font-size:.86rem;line-height:1.45;margin:4px 0 2px}
.v2-plan{font-size:.8rem;opacity:.75;margin-bottom:4px}
.v2-tag{display:inline-block;font-size:.72rem;padding:0 7px;margin:2px 4px 0 0;border-radius:8px;background:rgba(137,135,129,.14)}
.v3-tiles{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:4px 0 14px}
.v3-tile{border:1px solid rgba(128,128,128,.25);border-radius:10px;padding:8px 12px}
.v3-tile .v{font-size:1.35rem;font-weight:700;line-height:1.2}.v3-tile .l{font-size:.75rem;opacity:.7}
.v3-tile.warn{border-color:#d03b3b;background:rgba(208,59,59,.07)}.v3-tile.warn .v{color:#d03b3b}
.v3-list{margin:6px 0 14px}
.v3-row{display:grid;grid-template-columns:minmax(120px,1fr) 76px 84px minmax(84px,auto) 70px;
        gap:2px 12px;align-items:center;padding:8px 10px;border-left:4px solid transparent;border-bottom:1px solid rgba(128,128,128,.16);
        font-size:.88rem}
.v3-head{font-size:.74rem;opacity:.65;font-weight:600;border-bottom:1px solid rgba(128,128,128,.35)}
.v3-row .r{text-align:right;white-space:nowrap}.v3-row .b{font-weight:700}
.v3-name{font-weight:700}
.v3-issue{grid-column:1/-1;font-size:.78rem;opacity:.72;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
@media (max-width:640px){
  .v3-tiles{grid-template-columns:repeat(2,1fr)}
  .v3-head{display:none}
  .v3-row{grid-template-columns:1fr auto}
  .v3-row .r{text-align:left}.v3-row .r::before{content:attr(data-l) " ";opacity:.6;font-weight:400}
  .v3-issue{white-space:normal}
}
.tn-line{border-bottom:1px solid rgba(128,128,128,.25);margin:-4px 0 10px}
.st-key-tn_home button p{font-size:1.15rem;font-weight:800}
.hm-logo{text-align:center;font-size:2.6rem;font-weight:800;margin:6vh 0 0;letter-spacing:-1px}
.hm-sub{text-align:center;font-size:.95rem;opacity:.7;margin-bottom:18px}
.st-key-home_q [data-baseweb="input"]{border-radius:24px;padding:4px 10px}
.st-key-home_q input{font-size:1.02rem}
.hm-sec{text-align:center;font-size:.8rem;font-weight:600;opacity:.65;margin:26px 0 6px}
.hm-card{text-align:center;padding:4px 0 2px}.hm-card .i{font-size:1.8rem}.hm-card .t{font-size:1.05rem;font-weight:700}
.hm-card .d{font-size:.8rem;opacity:.7;min-height:2.4em}
</style>""", unsafe_allow_html=True)


def flash(msg):
    st.session_state['flash'] = msg


def show_flash():
    if msg := st.session_state.pop('flash', None):
        st.success(msg)


def esc(s):
    return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def fmt(vs):
    if not vs:
        return '(없음)'
    v, s = vs
    return f"{'—' if v is None else v} [{s}]"


def kpi(col, n, label, warn=False):
    col.markdown(f'<div class="dd-kpi{" warn" if warn else ""}"><div class="n">{n}</div>'
                 f'<div class="l">{label}</div></div>', unsafe_allow_html=True)


def ordered(facts):
    rank = {k: i for i, k in enumerate(catalog.order(CAT))}
    return sorted(facts, key=lambda f: (rank.get((f['facility'], f['item']), 999), f['facility'], f['item']))


def district_options():
    present = db.districts(con)
    return [d for d in CAT['districts'] if d in present] + [d for d in present if d not in CAT['districts']] \
        or CAT['districts']


def district_picker():
    """대시보드·보고서에서 볼 사업지구. 화면 사이를 오가도 같은 지구를 유지한다."""
    opts = district_options()
    if st.session_state.get('district') not in opts:
        st.session_state['district'] = CAT['default'] if CAT['default'] in opts else opts[0]
    return st.selectbox('사업지구', opts, key='district')


# ---------------- 📂 문서 ----------------
def doc_table(docs, with_count=False):
    st.dataframe(pd.DataFrame([{'문서ID': d['doc_id'], '지구': d.get('district') or '', '단계': d['stage'],
                                '일자': d['date'], '버전 종류': d.get('version_kind') or NO_VERSION, '형식': d['format'],
                                **({'후보 수': d['n_cand']} if with_count else {}), '파일명': d['file']}
                               for d in docs]), hide_index=True, width='stretch')


def doc_meta_form(registered):
    """문서 하나를 골라 지구·단계·일자·버전을 고치고, 전체 후보로 다시 판정한다."""
    by_id = {d['doc_id']: d for d in registered}
    versions = [NO_VERSION] + extract.VERSIONS[1:]
    sel = st.selectbox('수정할 문서', list(by_id), format_func=lambda i: f"{i}  {by_id[i]['file']}")
    d = by_id[sel]
    tag = f"{sel}_{d['district']}_{d['stage']}_{d['date']}_{d['version_kind']}"  # DB 값이 바뀌면 입력칸도 새 값으로
    try:
        cur_date = datetime.strptime(d['date'], '%Y-%m-%d').date()
    except ValueError:
        cur_date = datetime.now().date()
    dists = list(dict.fromkeys(CAT['districts'] + [d['district']]))
    c0, c1, c2, c3, c4 = st.columns(5, vertical_alignment='bottom')
    dist = c0.selectbox('지구', dists, key=f'ds_{tag}', index=dists.index(d['district']))
    stage = c1.selectbox('단계', extract.STAGES, key=f'st_{tag}', help='확정·승인본 > 협의결과 > 보고 > 초안. 비공식은 판정에 쓰지 않음',
                         index=extract.STAGES.index(d['stage']) if d['stage'] in extract.STAGES else 2)
    new_date = c2.date_input('일자', cur_date, key=f'dt_{tag}', format='YYYY-MM-DD')
    ver = c3.selectbox('버전 종류', versions, key=f'vk_{tag}', help='같은 단계·같은 일자일 때 최종 > 변경안 > 원안',
                       index=versions.index(d['version_kind'] or NO_VERSION))
    if c4.button('저장하고 다시 판정', type='primary'):
        db.update_source_meta(con, sel, stage, new_date.isoformat(), '' if ver == NO_VERSION else ver, dist)
        res = A02.rejudge(con, CAT['default'])  # A02: 전체 후보로 다시 판정
        changed = [f"{d} {fac} / {item}: {fmt(b)} → {fmt(a)}" for d, fac, item, b, a in res['changed']]
        flash(f"{sel} 수정 → 지구 {dist}, 단계 {stage}, 일자 {new_date.isoformat()}, 버전 {ver}. 다시 판정했습니다.\n\n" +
              ('바뀐 항목:\n' + '\n'.join(f'- {c}' for c in changed[:20]) +
               (f'\n- 외 {len(changed) - 20}건' if len(changed) > 20 else '') if changed else '바뀐 항목 없음'))
        st.rerun()


def page_docs():
    st.caption('원본 문서는 읽기만 합니다. 올린 파일의 사본과 DB는 output/ 폴더에만 만듭니다.')
    mode = st.segmented_control('문서 가져오기', ['📁 샘플(모의 문서)', '⬆ 내 문서 올리기'], default='⬆ 내 문서 올리기',
                                key='doc_mode', label_visibility='collapsed') or '⬆ 내 문서 올리기'
    if mode.startswith('📁'):
        sample_section()
    else:
        upload_section()

    registered = db.sources(con)
    if not registered:
        show_flash()
        return
    st.subheader(f'등록된 문서 {len(registered)}건')
    doc_table(registered, with_count=True)
    with st.container(border=True):
        st.markdown('**문서 지구·단계·일자·버전 수정** — 저장하면 전체 후보로 다시 판정합니다.')
        doc_meta_form(registered)
        show_flash()
    c1, c2 = st.columns(2)
    del_id = c1.selectbox('문서 빼기', ['—'] + [d['doc_id'] for d in registered], key='del_doc',
                          format_func=lambda i: i if i == '—' else f"{i}  {next(d['file'] for d in registered if d['doc_id'] == i)}")
    if c1.button('이 문서 빼고 다시 판정', disabled=del_id == '—'):
        db.delete_document(con, del_id)
        A02.rejudge(con, CAT['default'])
        flash(f'{del_id}를 DB에서 뺐습니다. (원본 파일은 그대로입니다)')
        st.rerun()
    if c2.button('DB 초기화'):
        db.reset(con)
        flash('DB를 비웠습니다. (원본 문서는 그대로입니다)')
        st.rerun()


def sample_section():
    st.caption('가상 지구(누리마루·한빛·솔내) 모의 문서와 그 추출 예시로 판정 이후 흐름을 실행합니다. DB를 새로 만듭니다.')
    c1, c2 = st.columns(2)
    extra = c1.checkbox('누리마루 현안 문서 7개 포함', value=True)
    other = c2.checkbox('다른 지구 문서 8개 포함 (한빛·솔내)', value=True)
    docs, cands = A01.load_sample(SAMPLE, extra, other, CAT['default'])  # A01 출력(추출 결과 예시)
    with st.expander(f'모의 문서 {len(docs)}개 보기'):
        doc_table(docs)
    if st.button('샘플 불러오기', type='primary'):
        res = A02.run(con, [(d, [c for c in cands if c['doc_id'] == d['doc_id']]) for d in docs], CAT['default'], reset=True)
        flash(f'A01 샘플 추출 결과 {len(cands)}건을 A02가 지구별로 판정했습니다. 담당자 선택이 필요한 충돌 {len(res["conflicts"])}건.')
        st.session_state['goto'] = DASH
        st.rerun()


NEW_DISTRICT = '＋ 새 사업지구 추가'


def upload_section():
    global CAT
    how = 'AI 추출(LLM)' if HAS_LLM else '간이 추출(규칙, 키 없음)'
    st.caption(f'문서를 올리고 사업지구를 고른 뒤 "값 뽑기"를 누르세요. 추출 방식: **{how}**. '
               '뽑힌 값을 확인한 뒤 저장하면 기존 DB에 더해 판정합니다. 시험에는 가상·공개 자료를 쓰세요.')
    files = st.file_uploader('문서 선택 (PDF·한글 hwpx·워드·엑셀·텍스트, 여러 개)', type=[e[1:] for e in extract.FORMATS],
                             accept_multiple_files=True, key='up_files')
    paths = []
    UPLOADS.mkdir(parents=True, exist_ok=True)
    for f in files or []:  # 업로드 사본은 output/uploads에만 저장
        p = UPLOADS / f.name
        if not p.exists() or p.stat().st_size != f.size:
            p.write_bytes(f.getvalue())
        paths.append(p)
    if not paths:
        st.info('아직 올린 문서가 없습니다. 위 상자에 파일을 끌어다 놓거나 "Upload" 버튼을 누르세요.')
        return

    # 사업지구: 등록된 지구 또는 새 지구(사업 목록을 함께 입력)
    names = CAT['districts']
    guess = catalog.guess_district(CAT, paths[0].name)
    if 'up_district_next' in st.session_state:
        st.session_state['up_district'] = st.session_state.pop('up_district_next')
    c1, c2 = st.columns([1, 2])
    district = c1.selectbox('사업지구', names + [NEW_DISTRICT], index=names.index(guess) if guess in names else 0,
                            key='up_district')
    if district == NEW_DISTRICT:
        new_name = c2.text_input('새 사업지구 이름', placeholder='예: 미리내지구', key='up_new_name')
        texts = []
        for p in paths:
            try:
                texts.append(extract.read_text(p))
            except Exception:
                pass
        sug = catalog.suggest_facilities(texts)
        default = '\n'.join(f"{s['name']}, {s['type']}" for s in sug)
        st.markdown('**사업 목록** — 한 줄에 "사업명, 유형"(유형: 도로·철도·환승·대중교통). 문서에서 찾은 후보를 미리 채웠으니 고쳐 쓰세요.')
        fac_text = st.text_area('사업 목록', default, height=150, key=f'up_facs_{len(paths)}', label_visibility='collapsed')
        facs = []
        for line in fac_text.splitlines():
            parts = [x.strip() for x in line.split(',')]
            if parts and parts[0]:
                t = parts[1] if len(parts) > 1 and parts[1] in compare.TYPES else catalog.facility_type(CAT, '', parts[0])
                facs.append({'name': parts[0], 'type': t})
        if not new_name or not facs:
            st.warning('새 사업지구 이름과 사업을 하나 이상 입력하세요.')
            return
        if st.button(f'"{new_name}" 등록 (사업 {len(facs)}개)'):
            catalog.save_local_district(new_name.strip(), facs)
            CAT = catalog.load(cfg)
            st.session_state['up_district_next'] = new_name.strip()  # 다음 실행에서 지구 선택칸에 넣는다
            flash(f'{new_name} 등록 완료. 이제 "값 뽑기"를 누르세요.')
            st.rerun()
        return
    show_flash()
    facs = sorted({i['facility'] for i in catalog.items_for(CAT, district)})
    st.caption(f'{district} 사업 {len(facs)}개: ' + ', '.join(facs))

    docs = A01.describe(paths, db.next_doc_num(con), CAT)
    for d in docs:
        d['doc_id'] = db.doc_id_for_file(con, d['file']) or d['doc_id']  # 이미 등록된 파일은 같은 문서ID로 교체
        d['district'] = district
    st.markdown(f'**올린 문서 {len(docs)}개** — 단계·일자는 파일명으로 추정한 값이며 저장 후에도 고칠 수 있습니다.')
    doc_table(docs)
    if st.button('값 뽑기', type='primary'):
        st.session_state['pending'] = extract_all(docs, catalog.items_for(CAT, district))
    pending = st.session_state.get('pending')
    if not pending or {d['file'] for d, _, _ in pending} != {d['file'] for d in docs}:
        return

    st.markdown('**뽑힌 값 확인** — 틀린 값은 빼고 저장하세요. 빠진 값은 문서 표현이 규칙과 달라 못 찾은 것입니다.')
    keep_all = []
    for d, cands, err in pending:
        with st.expander(f"{d['doc_id']} {d['file']} — {len(cands)}건" + (f' ⚠ {err}' if err else ''), expanded=len(pending) <= 3):
            if not cands:
                st.caption('찾은 값이 없습니다.')
                continue
            labels = [f"{c['facility']} · {c['item']} = {c['value']}{c['unit']}" for c in cands]
            st.dataframe(pd.DataFrame([{'사업': c['facility'], '항목': c['item'], '값': f"{c['value']}{c['unit']}",
                                        '위치': c['location']} for c in cands]), hide_index=True, width='stretch')
            drop = st.multiselect('뺄 값', labels, key=f"drop_{d['file']}", placeholder='뺄 값이 있으면 고르세요')
            keep_all.append((d, [c for c, lab in zip(cands, labels) if lab not in drop]))
    n = sum(len(cs) for _, cs in keep_all)
    if st.button(f'DB에 저장하고 판정 ({n}건)', type='primary', disabled=not n):
        A02.run(con, keep_all, CAT['default'])  # A02: 기존 DB에 더해 판정
        st.session_state.pop('pending', None)
        st.session_state['district'] = district
        flash(f'{district} 문서 {len(keep_all)}개에서 {n}건을 저장하고 판정했습니다.')
        st.session_state['goto'] = DASH
        st.rerun()


def extract_all(docs, items):
    """A01 실행(문서마다 AI 또는 규칙 추출) + 항목 후보 표 저장. 반환: [(문서, 후보 목록, 오류 문구)]"""
    bar = st.progress(0.0, text='값 뽑는 중...')
    out = A01.run(docs, items, HAS_LLM, cfg,
                  on_progress=lambda i, n, d: bar.progress((i - 1) / n, text=f'{d["file"]} ({i}/{n})'))
    A01.save_table(out)
    bar.empty()
    return out


# ---------------- 📊 대시보드 (간결판) ----------------
TYPE_ICON = {'도로': '🛣', '철도': '🚆', '환승': '🔁', '대중교통': '🚌'}
# 추진상태 → (구분, 색). 색만으로 구분하지 않게 늘 글자와 함께 쓴다
STATE_STYLE = {'확인': ('확인 필요', '#d03b3b'), '협의': ('협의 중', '#c98500'), '진행': ('진행', '#2a78d6'),
               '없음': ('상태 미상', '#898781')}


def state_key(p):
    s = p['추진상태']
    if p['확인 필요'] or any(k in s for k in ('지연', '반대', '재조사')):
        return '확인'
    if any(k in s for k in ('협의', '조건부', '검토', '이견')):
        return '협의'
    return '진행' if s else '없음'


def short(d):
    m = re.fullmatch(r'20(\d\d)-(\d\d)-(\d\d)', d or '')
    return f'{int(m.group(2))}.{int(m.group(3))}.' if m else (d or '')


def district_switch():
    """지구 전환: 버튼 줄(지구가 하나면 숨김). 다른 화면과 같은 지구를 쓴다."""
    opts = district_options()
    if st.session_state.get('district') not in opts:
        st.session_state['district'] = CAT['default'] if CAT['default'] in opts else opts[0]
    if len(opts) == 1:
        return opts[0]
    pick = st.segmented_control('사업지구', opts, default=st.session_state['district'], key='dash_district',
                                label_visibility='collapsed')
    if pick and pick != st.session_state['district']:
        st.session_state['district'] = pick
    return st.session_state['district']


def page_dashboard():
    if not db.facts(con):
        st.header('📊 대시보드')
        st.info('아직 판정한 문서가 없습니다. 💾 DB 화면에서 샘플을 불러오거나 문서를 올리세요.')
        return
    district = district_switch()
    facts = ordered(db.facts(con, district=district))
    sources = db.sources(con, district)
    cands = db.load_candidates(con, district)
    projects = A03.projects(facts, CAT)
    order = list(dict.fromkeys(f['facility'] for f in facts))
    # 급한 것부터: 확인 필요 → 협의 중 → 진행 → 상태 미상, 같은 상태면 사업 목록 순서
    projects.sort(key=lambda p: (list(STATE_STYLE).index(state_key(p)),
                                 order.index(p['사업명']) if p['사업명'] in order else 99))
    dates = sorted(s['date'] for s in sources if s['date'])
    conf = [f for f in facts if f['status'] == '미확정(충돌)']
    count = {k: sum(state_key(p) == k for p in projects) for k in STATE_STYLE}
    cost = sum(p['사업비(억원)'] or 0 for p in projects)

    st.markdown(f'<div class="v2-title">{esc(district)}</div>'
                f'<div class="v2-sub">문서 {len(sources)}건 · 최근 문서 {short(dates[-1]) if dates else "—"}</div>',
                unsafe_allow_html=True)
    # 한눈 요약: 숫자 4개
    tiles = [(f'{len(projects)}개', '사업'), (draft.fmt_value(compare._fmt(cost), '억원') if cost else '—', '사업비 합계'),
             (f"{count['협의']}개", '협의 중'), (f"{count['확인']}개", '확인 필요')]
    st.markdown('<div class="v3-tiles">' + ''.join(
        f'<div class="v3-tile{" warn" if l == "확인 필요" and count["확인"] else ""}"'
        + (' title="지원액 포함"' if l == '사업비 합계' else '') + f'><div class="v">{esc(v)}</div>'
        f'<div class="l">{esc(l)}</div></div>' for v, l in tiles) + '</div>', unsafe_allow_html=True)
    show_flash()

    # 1) 지금 확인할 것: 값 충돌을 버튼 한 번으로 확정
    for f in conf:
        tops = json.loads(f['conflict_candidates'] or '[]')
        with st.container(border=True):
            st.markdown(f"**⚠ {esc(f['facility'])} · {esc(f['item'])}** — 같은 단계·같은 날짜 문서끼리 값이 달라요. 맞는 값을 고르세요.")
            cols = st.columns(len(tops) or 1)
            for i, c in enumerate(tops):
                label = f"{draft.fmt_value(c['value'], c['unit'])}  ({c['doc_id']} · {short(c['date'])})"
                if cols[i].button(label, key=f"v3ch{f['id']}_{i}", width='stretch',
                                  help=f"{c['file']} · {c['stage']} · {c['location']}"):
                    A02.choose(con, f['district'], f['facility'], f['item'], c['value'], '담당자')  # A02 사람 개입
                    flash(f"{f['facility']} {f['item']} → {draft.fmt_value(c['value'], c['unit'])} 확정 (선택 기록 저장)")
                    st.rerun()

    # 2) 사업 목록: 한 사업 한 줄 (상태 · 사업비 · 규모 · 완료 · 현안)
    by_key = {}
    for c in cands:
        by_key.setdefault((c['facility'], c['item']), []).append(c)
    st.markdown('<div class="v3-list">' + '<div class="v3-row v3-head"><span>사업</span><span>상태</span>'
                '<span class="r">사업비</span><span class="r">규모</span><span class="r">완료</span></div>'
                + ''.join(project_row(p) for p in projects) + '</div>', unsafe_allow_html=True)

    # 3) 자세히: 고른 사업 하나만
    names = [p['사업명'] for p in projects]
    pick = st.selectbox('자세히 볼 사업', ['—'] + names, key=f'v3pick_{district}',
                        format_func=lambda n: '사업을 고르면 현안·향후 계획·근거 문서를 보여 줍니다' if n == '—' else n)
    if pick != '—':
        p = projects[names.index(pick)]
        project_card(p, [f for f in facts if f['facility'] == pick], by_key)

    with st.expander(f'문서 {len(sources)}건 흐름 보기'):
        st.caption('위로 갈수록 우선하는 단계. 같은 단계면 오른쪽(최근) 문서가 이깁니다. 비공식은 판정에 쓰지 않습니다.')
        st.altair_chart(timeline_chart(sources), width='stretch')


def project_row(p):
    word, color = STATE_STYLE[state_key(p)]
    cost = draft.fmt_value(compare._fmt(p['사업비(억원)']), '억원') if p['사업비(억원)'] is not None else '—'
    spec = ' · '.join(x for x in (f"{compare._fmt(p['연장(km)'])}km" if p['연장(km)'] is not None else '',
                                  f"{p['차로']}차로" if p['차로'] else '',
                                  draft.fmt_value(compare._fmt(p['규모(㎡)']), '㎡') if p['규모(㎡)'] is not None else '') if x) or '—'
    when = '확인 필요' if '개통목표' in p['확인 필요'] or '완료시기' in p['확인 필요'] else (p['시기'] or '—')
    issue = p['현안'] or p['추진상태'] or ''
    return (f'<div class="v3-row" style="border-left-color:{color}">'
            f'<span class="v3-name">{TYPE_ICON.get(p["유형"], "•")} {esc(p["사업명"])}</span>'
            f'<span><span class="v2-pill" style="color:{color};border-color:{color}">{esc(word)}</span></span>'
            f'<span class="r b" data-l="사업비">{esc(cost)}</span><span class="r" data-l="규모">{esc(spec)}</span>'
            f'<span class="r" data-l="완료">{esc(when)}</span>'
            + (f'<span class="v3-issue" title="{esc(issue)}">⚑ {esc(issue)}</span>' if issue else '') + '</div>')


def project_card(p, fs, by_key):
    k = state_key(p)
    word, color = STATE_STYLE[k]
    nums = []
    if p['사업비(억원)'] is not None:
        nums.append((draft.fmt_value(compare._fmt(p['사업비(억원)']), '억원'), p['비용 구분'] or '사업비'))
    spec = ' · '.join(x for x in (f"{compare._fmt(p['연장(km)'])}km" if p['연장(km)'] is not None else '',
                                  f"{p['차로']}차로" if p['차로'] else '',
                                  draft.fmt_value(compare._fmt(p['규모(㎡)']), '㎡') if p['규모(㎡)'] is not None else '') if x)
    if spec:
        nums.append((spec, '규모'))
    if p['시기']:
        nums.append(('확인 필요' if '개통목표' in p['확인 필요'] or '완료시기' in p['확인 필요'] else p['시기'],
                     '개통' if p['시기 구분'] == '개통목표' else '완료'))
    memo = sum(1 for f in fs for c in by_key.get((f['facility'], f['item']), [])
               if c['stage'] in INFORMAL and (f['value'] is None or norm(c['value']) != norm(f['value'])))
    num_html = ''.join(f'<div class="v2-n"><div class="v">{esc(v)}</div><div class="l">{esc(l)}</div></div>' for v, l in nums)
    issue = f'<div class="v2-issue">⚑ {esc(p["현안"])}</div>' if p['현안'] else ''
    plan = f'<div class="v2-plan">→ {esc(p["향후계획"])}</div>' if p['향후계획'] else ''
    tags = (f'<span class="v2-tag">{esc(p["시행주체"])} 시행</span>' if p['시행주체'] else '') + \
           (f'<span class="v2-tag">ⓘ 비공식 메모 {memo}</span>' if memo else '')
    st.markdown(
        f'<div class="v2-card" style="border-left-color:{color}">'
        f'<div class="v2-h"><span class="v2-name">{TYPE_ICON.get(p["유형"], "•")} {esc(p["사업명"])}</span>'
        f'<span class="v2-pill" style="color:{color};border-color:{color}">{esc(word)}</span></div>'
        f'<div class="v2-status">{esc(p["추진상태"] or "추진상태 정보 없음")}</div>'
        f'<div class="v2-nums">{num_html}</div>{issue}{plan}<div>{tags}</div></div>', unsafe_allow_html=True)
    with st.container():
        st.caption('항목별 최신값과 근거 문서')
        rows = []
        for f in fs:
            off = sorted((c for c in by_key.get((f['facility'], f['item']), []) if c['stage'] not in INFORMAL),
                         key=lambda c: (c['date'], c['doc_id']))
            first = off[0]['value'] if off else None
            rows.append({'항목': f['item'],
                         '최신값': '확인 필요' if f['status'] == '미확정(충돌)' else draft.fmt_value(f['value'], f['unit']),
                         '처음 값': draft.fmt_value(first, f['unit']) if first is not None and f['value'] is not None
                         and norm(first) != norm(f['value']) else '',
                         '판정': METHOD_LABEL.get(f['method'], f['method']),
                         '근거': f"{f['source_doc']} {short(f['doc_date'])} {f['doc_stage']}" if f['source_doc'] else ''})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width='stretch')
        for f in fs:
            for c in by_key.get((f['facility'], f['item']), []):
                if c['stage'] in INFORMAL and (f['value'] is None or norm(c['value']) != norm(f['value'])):
                    st.caption(f"ⓘ 비공식 메모({c['doc_id']}) · {f['item']}: {c['value']}{c['unit']} — 반영 안 함")


def stage_scale():
    return alt.Scale(domain=STAGE_ORDER, range=STAGE_COLOR)


def timeline_chart(sources):
    df = pd.DataFrame([{'문서': s['doc_id'], '파일': s['file'], '단계': s['stage'], '일자': s['date'],
                        '후보 수': s['n_cand']} for s in sources])
    df['일자'] = pd.to_datetime(df['일자'], errors='coerce')
    base = alt.Chart(df).encode(
        x=alt.X('일자:T', title=None, axis=alt.Axis(format='%m/%d', grid=False)),
        y=alt.Y('단계:N', sort=STAGE_ORDER, title=None, scale=alt.Scale(domain=STAGE_ORDER)),
        tooltip=['문서', '파일', '단계', alt.Tooltip('일자:T', format='%Y-%m-%d'), '후보 수'])
    pts = base.mark_circle(size=170, opacity=1, stroke='white', strokeWidth=2).encode(
        color=alt.Color('단계:N', scale=stage_scale(), legend=None))
    lab = df.dropna(subset=['일자']).groupby(['일자', '단계'], as_index=False)['문서'].agg('·'.join)
    lbl = alt.Chart(lab).mark_text(dy=-14, fontSize=11).encode(
        x='일자:T', y=alt.Y('단계:N', sort=STAGE_ORDER, scale=alt.Scale(domain=STAGE_ORDER)), text='문서')
    return (pts + lbl).properties(height=230)


# ---------------- 📝 보고서·자료 ----------------
def page_report():
    st.header('📝 보고서 작성')
    if not db.facts(con):
        st.info('먼저 💾 DB 화면에서 샘플을 불러오거나 문서를 올리세요.')
        return
    district = district_picker()
    facts = ordered(db.facts(con, district=district))
    c0, c00 = st.columns([2, 3], vertical_alignment='bottom')
    form = c0.selectbox('회사 양식 (모양)', list(A04.FORMS), key='rp_form',
                        help='회사 권장양식(보고서 작성 가이드라인)에 맞춘 글꼴·제목 띠·기호 단계·간격으로 만듭니다.')
    c00.caption(A04.FORM_HELP[A04.FORMS[form][0]])
    press = A04.FORMS[form][0] == 'press'
    st.caption('보고 유형을 고르면 목차가 미리 체크됩니다. 체크한 목차만으로 초안을 만들고, 숫자는 모두 DB 최신값입니다.'
               if not press else '보도자료는 기사제목·소제목·리드문·본문을 사업 DB 값으로 자동 작성합니다(목차 선택 없음).')

    preset = st.radio('보고 유형 (내용)', list(A04.PRESETS), horizontal=True, key='rp_preset',
                      disabled=press)
    tail, defaults = A04.PRESETS[preset]
    c1, c2 = st.columns([3, 2])
    title = c1.text_input('보고서 제목', f'{district} {tail}', key=f'rp_title_{preset}_{district}')
    dept = c2.text_input('작성 부서', DEPT, key='rp_dept')
    facs = list(dict.fromkeys(f['facility'] for f in facts))
    pick_facs = st.multiselect('대상 사업', facs, default=facs, key=f'rp_facs_{district}')
    show_basis = st.checkbox('근거 표시(검토용)', value=False, key='rp_basis',
                             help='켜면 값마다 근거 문서·문서ID·판정 설명을 붙입니다. 보고용은 끈 상태로 쓰세요.')

    st.markdown('**목차** (체크한 목차만 보고서에 들어갑니다)')
    cols = st.columns(3)
    chosen = []
    for i, sec in enumerate(A04.SECTIONS):
        ai = sec == '종합 의견(AI)'
        on = cols[i % 3].checkbox(sec, value=sec in defaults and not (ai and not HAS_LLM), key=f'rp_{preset}_{sec}',
                                  help=A04.SECTION_HELP[sec] + ('' if not ai or HAS_LLM else ' — API 키가 없어 사용할 수 없음'),
                                  disabled=ai and not HAS_LLM)
        if on:
            chosen.append(sec)
    extra = {}
    hints = {'주요 현안': '(사업비) 철도 사업비 증액분 분담 협의 필요\n⇒ (대응방안) 관계기관 협의 착수',
             '향후 계획': '(협의) 제21차 실무협의체에서 개통 목표 재확인\n- 11월 중 개최 예정'}
    for sec in ('주요 현안', '향후 계획'):
        if sec in chosen:
            extra[sec] = st.text_area(f'{sec} 직접 입력 (선택)', key=f'rp_extra_{sec}', height=90,
                                      placeholder=f'한 줄에 하나. "(핵심어) 내용", "- 세부", "⇒ 조치"\n예)\n{hints[sec]}',
                                      help='자동으로 만든 문장 뒤에 덧붙습니다. 문서에 없는 계획·현안을 담당자가 적는 칸입니다.')
    if not chosen and not press:
        st.warning('목차를 하나 이상 체크하세요.')
    if st.button('보도자료 초안 만들기' if press else '보고서 초안 만들기', type='primary',
                 disabled=(not chosen and not press) or not pick_facs):
        chosen = chosen or list(A04.SECTIONS[:-1])
        # A03: 목적(보고 유형) + 대상 사업 → 자료표(출처·기준일·부족·미확정 표시)
        res3 = A03.run(facts, preset, facilities=pick_facs, use_llm=HAS_LLM, cfg=cfg)
        cands = db.load_candidates(con, district)
        # A04: 자료표 + 양식 → 보고서 초안, 그리고 자동 점검
        blocks = A04.run(res3, cands, db.sources(con, district), db.choices(con, district),
                         title, district, dept, chosen, extra, HAS_LLM, cfg, order=catalog.order(CAT, district),
                         kinds=KINDS, show_basis=show_basis)
        st.session_state['report'] = {'blocks': blocks, 'a03': res3, 'sections': chosen, 'district': district,
                                      'checks': A04.check(blocks, res3, cands, chosen if not press else []),
                                      'stamp': datetime.now().strftime('%Y%m%d_%H%M%S')}
    rep = st.session_state.get('report')
    if not rep or rep.get('district') != district:
        return
    res3 = rep['a03']
    lay = A04.Layout(rep['blocks'], form, res3['facts'], district, dept, KINDS)
    safe = re.sub(r'[\\/:*?"<>|]', '_', lay.title)
    st.divider()
    st.caption(f"A03 자료표 {len(res3['table'])}행({res3['basis']}) → A04 초안 · 양식: {form} · 목차: "
               f"{' · '.join(rep['sections']) if lay.kind != 'press' else '보도자료 구성'}")
    if res3['lacking']:
        st.warning(f"부족·미확정 {len(res3['lacking'])}건이 '확인 필요'로 들어갔습니다. 대시보드에서 확정한 뒤 다시 만들면 반영됩니다.")
    with st.container(border=True):  # A04 ④ 자동 점검 → ⑤ 담당자 최종 검토
        ok = all(c['결과'] == '통과' for c in rep['checks'])
        st.markdown(f"**A04 자동 점검** — {'모두 통과' if ok else '확인할 항목이 있습니다'} · 내려받기 전에 담당자가 최종 검토하세요.")
        for c in rep['checks']:
            st.markdown(f"{'✅' if c['결과'] == '통과' else '⚠️'} **{c['점검']}** · {esc(c['설명'])}")
    d1, d2, d3 = st.columns(3)
    files = [('한글(hwpx) 내려받기', f"{safe}_{rep['stamp']}.hwpx", lay.hwpx, 'application/octet-stream', d1),
             ('워드(docx) 내려받기', f"{safe}_{rep['stamp']}.docx", lay.docx,
              'application/vnd.openxmlformats-officedocument.wordprocessingml.document', d2),
             ('자료표 엑셀 내려받기', f"자료표_{rep['stamp']}.xlsx",
              lambda: A03.to_excel(res3, lay.title, db.sources(con, district)),
              'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', d3)]
    for label, name, make, mime, col in files:
        data = make()
        if col.download_button(label, data, file_name=name, mime=mime, width='stretch'):
            (db.OUTPUT / name).write_bytes(data)
    if lay.styled:
        st.caption('한글(hwpx)은 회사 양식 서식 파일에 그대로 채워 만들고, 워드는 같은 규칙(글꼴·제목 띠·기호 단계·간격)으로 만듭니다.'
                   if lay.use_form else '워드 파일에 회사 양식을 적용합니다. 이 양식의 한글 서식 파일(templates/company/)이 없어 한글본은 기본 서식입니다.')
    st.markdown(lay.html(), unsafe_allow_html=True)
    with st.expander(f"A03 자료표 (표로 보기, {len(res3['table'])}행)"):
        st.dataframe(pd.DataFrame(res3['table']), hide_index=True, width='stretch')


# ---------------- 🔎 통합 비교 ----------------
SHOW_COLS = ['지구', '사업명', '유형', '사업비(억원)', '비용 구분', '연장(km)', '시기', '시행주체', '주체 구분', '추진상태', '현안']


NUM_COLS = {'사업비(억원)': st.column_config.NumberColumn(format='%,.0f'), '연장(km)': st.column_config.NumberColumn(format='%.1f')}


def district_scale(names):
    domain = [d for d in CAT['districts'] if d in names] + [d for d in names if d not in CAT['districts']]
    order = {d: i for i, d in enumerate(CAT['districts'] + [d for d in names if d not in CAT['districts']])}
    return alt.Scale(domain=domain, range=[DISTRICT_COLOR[order[d] % len(DISTRICT_COLOR)] for d in domain])


def project_table(rows):
    df = pd.DataFrame(rows)
    return df[[c for c in SHOW_COLS if c in df.columns]] if not df.empty else df


def page_compare():
    facts = db.facts(con)
    if not facts:
        st.info('먼저 💾 DB 화면에서 샘플을 불러오거나 문서를 올리세요. (샘플의 "다른 지구 문서"를 켜면 3개 지구를 비교합니다)')
        return
    rows = A03.projects(facts, CAT)
    st.caption('여러 사업지구의 광역교통 사업을 같은 기준으로 모아 봅니다. 값은 지구별로 판정한 DB 최신값입니다. '
               '유형·시행주체 구분을 비워 두면 전체입니다.')
    dists = list(dict.fromkeys(r['지구'] for r in rows))
    c1, c2, c3 = st.columns(3)
    pick_d = c1.multiselect('사업지구', dists, default=dists, key='cmp_d')
    pick_t = c2.multiselect('사업 유형', compare.TYPES, key='cmp_t', placeholder='전체')
    ents = [e for e in compare.ENTITY if any(r['주체 구분'] == e for r in rows)]
    pick_e = c3.multiselect('시행주체 구분', ents, key='cmp_e', placeholder='전체')
    top = max([r['사업비(억원)'] for r in rows if r['사업비(억원)'] is not None] or [100])
    top = int(-(-top // 500) * 500)
    c4, c5 = st.columns([3, 2])
    lo, hi = c4.slider('사업비(지원액) 범위, 억원', 0, top, (0, top), step=50, key='cmp_cost')
    kw = c5.text_input('현안·추진상태 검색', key='cmp_kw', placeholder='예: 반대, 지연, 보상 (쉼표로 여러 개)')
    flt = {'districts': pick_d, 'types': pick_t, 'entities': pick_e,
           'keywords': [k.strip() for k in kw.split(',') if k.strip()]}
    if (lo, hi) != (0, top):  # 범위를 움직였을 때만 금액 조건(사업비 없는 사업이 빠지지 않게)
        flt.update(cost_min=lo, cost_max=hi)
    res = compare.run(rows, flt)
    st.caption('조건: ' + compare.describe({k: v for k, v in flt.items() if k != 'districts' or len(v) < len(dists)}))

    c = st.columns(4)
    total = sum(r['사업비(억원)'] or 0 for r in res if r['비용 구분'] == '사업비')
    kpi(c[0], len(res), '사업')
    kpi(c[1], len({r['지구'] for r in res}), '사업지구')
    kpi(c[2], draft.fmt_value(compare._fmt(total), '억원') if total else '—', '사업비 합계')
    kpi(c[3], sum(bool(r['현안']) for r in res), '현안 있는 사업', warn=False)
    if not res:
        st.info('조건에 맞는 사업이 없습니다.')
        return
    plot = pd.DataFrame([r for r in res if r['사업비(억원)'] is not None])
    if not plot.empty:
        st.markdown('**사업비(지원액) 비교**')
        plot['라벨'] = plot['사업비(억원)'].map(lambda v: draft.fmt_value(compare._fmt(v), '억'))
        plot['항목'] = plot['지구'].str.replace('지구', '') + ' · ' + plot['사업명']
        base = alt.Chart(plot).encode(
            y=alt.Y('항목:N', sort='-x', title=None, axis=alt.Axis(labelLimit=260, labelOverlap=False)),
            x=alt.X('사업비(억원):Q', title='억원', axis=alt.Axis(format=',.0f', grid=True, tickCount=6)),
            tooltip=['지구', '사업명', '유형', alt.Tooltip('사업비(억원):Q', format=',.0f'), '비용 구분', '시행주체', '추진상태'])
        bars = base.mark_bar(cornerRadiusEnd=4).encode(
            color=alt.Color('지구:N', scale=district_scale(list(plot['지구'].unique())),
                            legend=alt.Legend(title='사업지구', orient='bottom')))
        text = base.mark_text(align='left', dx=4, fontSize=11).encode(text='라벨')
        st.altair_chart((bars + text).properties(height=alt.Step(26)), width='stretch')
    st.markdown('**사업 목록**')
    df = project_table(res)
    st.dataframe(df, hide_index=True, width='stretch',
                 column_config=NUM_COLS | {'현안': st.column_config.TextColumn(width='large')})
    st.download_button('CSV 내려받기', df.to_csv(index=False).encode('utf-8-sig'), '통합비교.csv', 'text/csv')
    issues = [r for r in res if r['현안']]
    if issues:
        with st.expander(f'현안 모아 보기 ({len(issues)}건)', expanded=True):
            for r in issues:
                st.markdown(f"- **({r['지구']}) {r['사업명']}** · {r['추진상태'] or '상태 미상'}  \n  {r['현안']}"
                            + (f"  \n  → {r['향후계획']}" if r['향후계획'] else ''))


# ---------------- 💬 챗봇 ----------------
EXAMPLES = ['지자체에서 1천억 미만의 유사 도로사업들을 검토해보라고 하는데 다른 사업지구에 이런 사례가 있을까?',
            '개별 광역시설 사업 중에 시행주체(공사주체)가 지자체인 사업의 사례가 있을까?',
            '주민 반대로 협의가 지연되고 있는 사업이 있어?',
            '사업비 5천억 이상 철도사업 알려줘']


def show_answer(m):
    st.markdown(m['text'])
    st.caption(f"검색 조건({m['mode']} 해석): {m['conditions']} → {len(m['rows'])}건")
    for n in m.get('notes') or []:
        st.caption(f'ⓘ {n}')
    if m['rows']:
        st.dataframe(project_table(m['rows']), hide_index=True, width='stretch',
                     column_config=NUM_COLS)


def page_chat():
    st.header('💬 챗봇')
    if not db.facts(con):
        st.info('먼저 💾 DB 화면에서 샘플을 불러오거나 문서를 올리세요.')
        return
    st.caption('질문을 검색 조건(지구·유형·사업비·시행주체·현안 낱말)으로 바꿔 DB에서 바로 찾습니다. 답의 숫자는 모두 DB 값입니다. '
               + ('AI가 질문을 해석하고 답을 씁니다.' if HAS_LLM else 'API 키가 없어 규칙으로 질문을 해석합니다.'))
    c1, c2 = st.columns([2, 1], vertical_alignment='bottom')
    with c1:
        current = district_picker()
    c2.caption('"다른 지구" 질문은 이 지구를 빼고 찾습니다.')
    msgs = st.session_state.setdefault('chat', [])
    if not msgs:
        st.markdown('**예시 질문**')
        for i, q in enumerate(EXAMPLES):
            if st.button(q, key=f'ex{i}'):
                st.session_state['ask'] = q
                st.rerun()
    for m in msgs:
        with st.chat_message(m['role']):
            if m['role'] == 'user':
                st.markdown(m['text'])
            else:
                show_answer(m)
    q = st.chat_input('예: 1천억 미만 도로사업 중 지자체가 시행하는 사례가 있을까?') or st.session_state.pop('ask', None)
    if q:
        msgs.append({'role': 'user', 'text': q})
        with st.spinner('DB 검색 중...'):
            res = A03.search(q, db.facts(con), CAT, current, HAS_LLM, cfg)  # A03: 질문 → DB 검색
        msgs.append({'role': 'assistant', **res})
        st.rerun()
    if msgs and st.button('대화 지우기'):
        st.session_state['chat'] = []
        st.rerun()


# ---------------- 🏠 처음 ----------------
def page_home():
    """첫 화면: 검색창(질문하기로 넘김) + 할 일 고르기 + DB에 있는 사업지구."""
    facts = db.facts(con)
    st.markdown('<div class="hm-logo">디딤돌</div><div class="hm-sub">사업지구 문서의 최신값을 근거와 함께 찾아 드립니다</div>',
                unsafe_allow_html=True)
    _, mid, _ = st.columns([1, 4, 1])
    with mid:
        with st.form('home_search', border=False, enter_to_submit=True):
            c1, c2 = st.columns([5, 1], vertical_alignment='center')
            q = c1.text_input('질문', key='home_q', label_visibility='collapsed', disabled=not facts,
                              placeholder='무엇이든 물어보세요  예: 주민 반대로 지연되는 사업이 있어?' if facts
                              else '먼저 문서를 올리면 질문할 수 있어요')
            go = c2.form_submit_button('검색', width='stretch', disabled=not facts)
        if go and q.strip():
            st.session_state['ask'] = q.strip()
            st.session_state['goto'] = CHAT
            st.rerun()

        st.markdown('<div class="hm-sec">무엇을 할까요?</div>', unsafe_allow_html=True)
        a, b = st.columns(2)
        for col, (ico, title, desc, target, ok) in zip((a, b), (
                ('📂', '문서 올리기', '새 문서를 올려 값을 뽑고 DB에 더합니다', DOCS, True),
                ('📊', '대시보드 보기', '지구별 요약·확인 필요·사업 목록을 봅니다' if facts else '문서를 먼저 올려야 볼 수 있어요', DASH, bool(facts)))):
            with col.container(border=True):
                st.markdown(f'<div class="hm-card"><div class="i">{ico}</div><div class="t">{title}</div>'
                            f'<div class="d">{desc}</div></div>', unsafe_allow_html=True)
                if st.button(f'{title} →', key=f'hm_{title}', width='stretch', type='primary' if ok and target == DASH else 'secondary',
                             disabled=not ok):
                    st.session_state['goto'] = target
                    if target == DOCS:
                        st.session_state['db_view'] = DB_VIEWS[0]
                    st.rerun()

        st.markdown('<div class="hm-sec">현재 DB에 있는 사업지구</div>', unsafe_allow_html=True)
        if not facts:
            st.caption('아직 없습니다. 📂 문서 올리기에서 샘플을 불러오거나 문서를 올리세요.')
            return home_footer()
        names = district_options()
        cols = st.columns(min(len(names), 3))
        for i, d in enumerate(names):
            fs = [f for f in facts if f['district'] == d]
            n_proj = len({f['facility'] for f in fs})
            n_conf = sum(f['status'] == '미확정(충돌)' for f in fs)
            label = f"{'⚠ ' if n_conf else ''}{d} · 사업 {n_proj}"
            tip = f'{d} 대시보드로 이동' + (f' (값 충돌 {n_conf}건 확인 필요)' if n_conf else '')
            if cols[i % len(cols)].button(label, key=f'hm_d_{d}', width='stretch', help=tip):
                st.session_state['district'] = st.session_state['dash_district'] = d
                st.session_state['goto'] = DASH
                st.rerun()
        home_footer()


def home_footer():
    lc = cfg.get('llm', {})
    st.markdown('<div class="hm-sec"></div>', unsafe_allow_html=True)
    st.caption(f"모델 {lc.get('model')} · " + ('AI 추출 사용' if HAS_LLM else '키 없음 → 샘플·간이 추출'),
               help='모델 교체는 config.yaml의 provider·model·base_url·api_key_env를 바꾸면 됩니다. '
                    '판정은 LLM 없이 규칙(resolver.py)만으로 합니다.')


# ---------------- 💾 DB ----------------
def page_db():
    st.header('💾 DB')
    view = st.segmented_control('DB 보기', DB_VIEWS, key='db_view', label_visibility='collapsed') or DB_VIEWS[0]
    (page_docs if view == DB_VIEWS[0] else page_compare)()


# ---------------- 화면 전환 ----------------
def top_nav(page):
    """처음 화면을 뺀 모든 화면 위에 메뉴 줄: [🏠 디딤돌] 대시보드 · 챗봇 · DB · 보고서 작성"""
    st.session_state['top_nav'] = page  # 다른 화면에서 넘어와도 현재 화면이 눌린 상태로 보이게
    c1, c2 = st.columns([1, 5], vertical_alignment='center')
    if c1.button('🏠 디딤돌', key='tn_home', type='tertiary', help='처음 화면'):
        st.session_state['goto'] = HOME
        st.rerun()
    c2.segmented_control('메뉴', NAV[1:], key='top_nav', label_visibility='collapsed',
                         on_change=lambda: st.session_state.update(nav=st.session_state['top_nav'] or st.session_state['nav']))
    st.markdown('<div class="tn-line"></div>', unsafe_allow_html=True)


if 'goto' in st.session_state:
    st.session_state['nav'] = st.session_state.pop('goto')
st.session_state.setdefault('nav', HOME)
st.session_state.setdefault('db_view', DB_VIEWS[0])
page = st.session_state['nav']
if page != HOME:
    top_nav(page)
{HOME: page_home, DASH: page_dashboard, CHAT: page_chat, DOCS: page_db, REPORT: page_report}[page]()
