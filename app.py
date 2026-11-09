"""디딤돌 (agent 4개 구조).  실행: streamlit run app.py
화면은 담당자가 agent 4개를 차례로 부르는 곳이다. 계산은 모두 agents/ 안의 agent가 한다.
  A01 문서 내용 추출(agents/a01_extract) → A02 최신값 판정·DB 갱신(a02_resolve)
  → A03 목적별 자료 추출(a03_query) → A04 보고서 초안 작성(a04_draft)
화면: 🏠 처음 / 📊 대시보드(A02 결과 + 충돌 선택) / 💬 챗봇(A03) / 💾 DB(A01·A02, 통합 비교는 A03) / 📝 보고서 작성(A03→A04).
원본 문서는 읽기만 하고, DB·자료표·보고서·업로드 사본은 output/ 폴더에 만든다."""
import json
import os
import re
from datetime import datetime
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from agents.a01_extract import agent as A01
from agents.a01_extract import classify as K
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
NAV = ['자료 DB', '보고서 작성']  # 자료 DB가 처음(올리기·분류·적재), 보고서 작성(설정 → 초안 검토 → 한글 저장)
DOCS, REPORT = NAV
DB_VIEWS = ['📥 자료 적재', '🗂 적재 현황·관리']  # 올리기는 자료 적재 한 곳, 적재 현황·관리는 DB 보기·고치기만
DB_HELP = {'📥 자료 적재': '여러 자료를 한 번에 올리면 → 교통대책·내용별로 나누고 → 애매한 것만 사람이 확인한 뒤 → DB에 적재합니다.',
           '🗂 적재 현황·관리': 'DB에 들어간 값·추진경위와 적재된 문서를 보고, 문서 정보를 고치거나 빼는 곳입니다. '
                            '새 사업지구 등록도 여기(맨 아래)에서 합니다.',
           '🔎 통합 비교': '여러 사업지구의 사업을 같은 기준으로 비교합니다.'}
# 지구 구분 색: 기준 팔레트 범주형 순서(파랑·주황·청록 …), 지구 순서대로 고정
DISTRICT_COLOR = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#6250d6', '#e34948']
NO_VERSION = '없음'
METHOD_LABEL = {'충돌 없음': '충돌 없음', '규칙(단계 우선순위)': '규칙: 상위 단계', '규칙(같은 단계에서 최근 일자)': '규칙: 최근 일자',
                '사람 선택': '담당자 선택', '사람 선택 필요': '확인 필요', '공식 문서 없음': '공식 문서 없음'}
# 문서 단계(서열) 색: 기준 팔레트의 파랑 단계 ramp, 비공식은 회색
STAGE_ORDER = ['확정·승인본', '협의결과', '보고', '초안', '비공식']
STAGE_COLOR = ['#104281', '#256abf', '#5598e7', '#86b6ef', '#898781']

st.set_page_config(page_title='디딤돌', page_icon='📑', layout='wide')
# 클라우드(Streamlit Community Cloud)에서는 키를 앱 설정의 Secrets에 넣는다 → 환경변수로 옮겨 llm.py가 읽게 함.
# 내 PC에서는 지금처럼 환경변수(setx)나 .streamlit/secrets.toml(저장소에 올리지 않음)을 쓴다. 키 값은 코드·저장소에 쓰지 않는다.
for _k in ('ANTHROPIC_API_KEY', 'ANTHROPIC_WORKSPACE_ID', 'GEMINI_API_KEY', 'APP_PASSWORD'):
    try:
        if _k in st.secrets and not os.environ.get(_k):
            os.environ[_k] = str(st.secrets[_k])
    except Exception:  # secrets 파일이 없으면 그냥 넘어감
        break
if os.environ.get('APP_PASSWORD') and not st.session_state.get('auth_ok'):  # 공개 주소에서 AI 사용료를 지키는 접근 비밀번호(선택)
    st.markdown('<div style="max-width:420px;margin:12vh auto 0"><h2 style="color:#0B3A8A">디딤돌</h2>'
                '<p>심사·시연용 주소입니다. 안내받은 접근 비밀번호를 넣어 주세요.</p></div>', unsafe_allow_html=True)
    _, mid_, _ = st.columns([1, 1.2, 1])
    pw = mid_.text_input('접근 비밀번호', type='password', key='app_pw')
    if pw:
        if pw == os.environ['APP_PASSWORD']:
            st.session_state['auth_ok'] = True
            st.rerun()
        mid_.error('비밀번호가 맞지 않습니다.')
    st.stop()
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

# 조원 디자인 시안(광역교통개선대책_DB_v0.3.html): 남색·연두, 왼쪽 메뉴, 초록 줄 제목 막대, 연한 바탕 위 흰 카드
st.markdown("""<style>
:root{--dg-pri:#1f6f5c;--dg-grn:#1f6f5c;--dg-grn-ink:#15513f;--dg-gray:#4a4740;--dg-bg:#fbfbfa;--dg-card:#fff;
      --dg-line:#e7e5e0;--dg-mut:#6b6760;--dg-ink:#1c1b19;
      --bg:#fbfbfa;--surface:#fff;--sunken:#efeeea;--line:#e7e5e0;--line-strong:#cfccc4;--ink:#1c1b19;--ink-2:#4a4740;
      --muted:#6b6760;--accent:#1f6f5c;--accent-soft:#e8f3ef;--accent-mark:#d9efe7;--warn:#b45309;--warn-bg:#fff6e5;
      --warn-ink:#7a4700;--warn-mark:#ffe9c2;--box-bg:#fdfeeb;--r-sm:12px;--r-md:14px;--r-lg:20px}
[data-testid="stMain"]{background:var(--dg-bg)}
[data-testid="stHeader"]{background:transparent}
[data-testid="stMainBlockContainer"]{padding-top:1.2rem;max-width:1400px}
/* 카드: 테두리 있는 상자 → 흰 카드 + 둥근 모서리 + 옅은 그림자 */
[data-testid="stMain"] [class*="st-key-card"],
[data-testid="stMain"] .dg-cardify{background:var(--dg-card);border:0 !important;border-radius:14px !important;
      box-shadow:0 1px 4px rgba(20,40,90,.08)}
/* 왼쪽 메뉴 */
[data-testid="stSidebar"]{min-width:200px !important;max-width:230px !important}
[data-testid="stSidebarUserContent"]{padding-top:.4rem}
.dg-logo{font-weight:800;font-size:1.35rem;color:var(--dg-pri);padding:0 6px;margin-bottom:14px}
.dg-logo:after{content:'';display:block;width:34px;height:4px;background:var(--dg-grn);border-radius:2px;margin-top:6px}
.dg-logo small{display:block;font-weight:400;color:var(--dg-mut);font-size:.78rem}
[class*="st-key-sn_"] button{justify-content:flex-start;padding:10px 12px;border-radius:8px;min-height:0}
[class*="st-key-sn_"] button>div{justify-content:flex-start;width:100%}
/* 입력칸: 연한 바탕 위에서는 흰색, 흰 카드 안에서는 연한 색(시안과 같게) */
[data-testid="stMain"] [data-testid="stTextInputRootElement"],[data-testid="stMain"] [data-testid="stTextAreaRootElement"],
[data-testid="stMain"] [data-testid="stDateInputField"],[data-testid="stMain"] [data-baseweb="select"]>div{background:var(--dg-card)}
[data-testid="stMain"] [class*="st-key-card"] [data-testid="stTextInputRootElement"],
[data-testid="stMain"] [class*="st-key-card"] [data-testid="stTextAreaRootElement"],
[data-testid="stMain"] [class*="st-key-card"] [data-baseweb="select"]>div{background:var(--dg-bg)}
[data-testid="stMain"] [data-testid="stTextAreaRootElement"] textarea{background:transparent}
.st-key-home_q [data-testid="stTextInputRootElement"]{border-radius:24px;padding:4px 10px;box-shadow:0 1px 4px rgba(20,40,90,.10)}
[class*="st-key-sn_"] button[kind="tertiary"]:hover{background:var(--dg-bg)}
[class*="st-key-sn_"] button[kind="primary"] p{font-weight:700}
[data-testid="stSidebar"] [data-testid="stVerticalBlock"]{gap:.25rem}
.dg-foot{margin-top:28px;background:var(--dg-gray);color:#fff;border-left:5px solid var(--dg-grn);border-radius:10px;
         padding:12px;font-size:.78rem;line-height:1.5}
/* 제목 막대(흰 바탕 + 아래 초록 줄) */
.dg-head{display:flex;align-items:center;gap:12px;background:var(--dg-card);border-bottom:3px solid var(--dg-grn);
         margin:0 0 16px;padding:12px 20px;border-radius:12px 12px 0 0}
.dg-head h1{font-size:1.25rem;margin:0;padding:0;color:var(--dg-pri);font-weight:800}
.dg-head small{color:var(--dg-mut);font-size:.8rem}
.dg-chip{margin-left:auto;border:1px solid var(--dg-gray);color:var(--dg-ink);border-radius:8px;padding:4px 12px;font-size:.8rem;white-space:nowrap}
/* 주 버튼: 남색, 올리면 연두 */
[data-testid="stMain"] button[kind="primary"]:hover,[data-testid="stMain"] [data-testid="stBaseButton-primary"]:hover{
      background:var(--dg-grn) !important;border-color:var(--dg-grn) !important;color:#1a2a05 !important}
/* 알약 선택(보고 유형 등): 고른 것은 남색 바탕(시안의 pill.on) */
[data-testid="stMain"] button[data-variant][data-selected="true"]{background:var(--dg-pri) !important;border-color:var(--dg-pri) !important}
[data-testid="stMain"] button[data-variant][data-selected="true"] p{color:#fff;font-weight:700}
[data-testid="stMain"] button[data-variant="pills"]{border-radius:999px}
/* 보고서 2단 화면 */
.dg-pane-h{color:var(--dg-pri);font-weight:800;font-size:1.02rem;padding:4px 2px 2px}
.dg-q{font-weight:700;margin:14px 0 4px;font-size:.9rem}
.dg-skill{background:var(--dg-bg);border-left:4px solid var(--dg-grn);border-radius:8px;padding:8px 12px;font-weight:700;font-size:.9rem;margin-bottom:6px}
.dg-skill small{display:block;font-weight:400;color:var(--dg-mut);font-size:.78rem}
.dg-empty{height:560px;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;
          color:var(--dg-mut);gap:14px;font-size:.92rem}
.dg-empty small{display:block;font-size:.8rem}
.dg-empty .ico{width:84px;height:84px;border-radius:50%;border:5px solid var(--dg-grn);position:relative}
.dg-empty .ico:after{content:'';position:absolute;left:50%;top:50%;width:26px;height:4px;background:var(--dg-pri);
          transform-origin:left center;transform:rotate(30deg);border-radius:2px}
.st-key-card_pane_view .lh{max-width:none;padding:24px 26px}
/* KPI·카드 모양도 시안 색으로 */
.dd-kpi,.v3-tile{background:var(--dg-card);border-color:var(--dg-line)}
.dd-kpi .n,.v3-tile .v{color:var(--dg-pri)}
.hm-logo{color:var(--dg-pri)}
.hm-logo:after{content:'';display:block;width:48px;height:5px;background:var(--dg-grn);border-radius:3px;margin:8px auto 0}
@media (max-width:640px){.dg-head{padding:10px 12px}.dg-chip{display:none}.dg-empty{height:320px}}
/* 상단 메뉴 줄(사이드바 대신) */
[data-testid="stSidebar"],[data-testid="stSidebarCollapsedControl"],[data-testid="stExpandSidebarButton"]{display:none !important}
.st-key-topbar{background:var(--dg-card);border-bottom:3px solid var(--dg-grn);border-radius:12px 12px 0 0;
      padding:6px 16px;margin-bottom:6px}
.st-key-tb_home button p{font-size:1.35rem;font-weight:800;color:var(--dg-pri)}
.st-key-tb_home button:after{content:'';display:block;width:30px;height:4px;background:var(--dg-grn);border-radius:2px;margin:2px 0 0 2px}
.st-key-tb_home button{flex-direction:column;align-items:flex-start}
.tb-right{display:flex;gap:10px;justify-content:flex-end;align-items:center;font-size:.8rem;color:var(--dg-mut)}
.tb-sub{font-size:.8rem;color:var(--dg-mut);margin:0 4px 10px}
/* 📥 자료 적재 (시안: 데이터 적재 화면) */
.ik-cap{font-size:.8rem;color:var(--dg-mut);margin-bottom:-6px}
.st-key-ik_head [data-baseweb="select"]>div{background:transparent !important;border:0 !important;font-size:1.35rem;font-weight:800}
.ik-steps{display:flex;gap:6px;justify-content:flex-end;flex-wrap:wrap;padding-bottom:6px}
.ik-steps span{background:var(--dg-card);color:var(--dg-mut);border-radius:999px;padding:7px 15px;font-size:.85rem}
.ik-steps span.past{color:var(--dg-pri)}
.ik-steps span.on{background:var(--dg-pri);color:#fff;font-weight:700}
.ik-up{display:flex;justify-content:space-between;gap:6px;align-items:baseline}.ik-up b{font-size:.92rem}
.ik-up span{color:var(--dg-mut);font-size:.8rem;white-space:nowrap}
.ik-uph{font-size:.76rem;color:var(--dg-mut);min-height:2.3em;margin-bottom:-4px}
[class*="st-key-ik_up_"] [data-testid="stFileUploaderDropzone"]{padding:8px;border:1.5px dashed var(--dg-line);background:transparent}
[class*="st-key-ik_up_"] [data-testid="stFileUploaderDropzoneInstructions"] small{display:none}
.ik-stat{display:flex;gap:18px;align-items:center;flex-wrap:wrap;font-size:.86rem;color:var(--dg-mut)}
.ik-stat b{font-size:1.25rem;margin-left:4px;color:var(--dg-ink)}.ik-stat i{width:1px;height:24px;background:var(--dg-line)}
.ik-stat em{font-style:normal;background:#fff4e0;color:#b45309;font-weight:700;border-radius:999px;padding:2px 9px;margin-left:6px}
.ik-stat b.ok{color:#0f7a4a}.ik-stat b.warn{color:#b45309}.ik-stat b.blue{color:var(--dg-pri)}
.ik-stat .ai{background:var(--dg-bg);color:var(--dg-pri);border-radius:999px;padding:2px 10px;font-weight:700}
.ik-lh{font-weight:700;font-size:.85rem;color:var(--dg-mut);margin:2px 4px 6px}
[class*="st-key-ik_fac_"] button{justify-content:flex-start;min-height:0;padding:6px 8px;border-radius:8px}
[class*="st-key-ik_fac_"] button>div{justify-content:flex-start;width:100%}
[class*="st-key-ik_fac_"] button p{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:.86rem}
.ik-legend{font-size:.7rem;color:var(--dg-mut);margin:0 4px 8px;line-height:1.4}
.ik-bar{display:grid;grid-template-columns:repeat(4,1fr) 52px;align-items:center;gap:3px;margin:-8px 8px 2px}
.ik-bar i{height:5px;border-radius:3px;background:var(--dg-line)}
.ik-bar i.on{background:color-mix(in srgb,var(--dg-pri) 45%,transparent)}.ik-bar i.cur{background:var(--dg-pri)}
.ik-bar em{font-style:normal;font-size:.72rem;color:var(--dg-mut);text-align:right;white-space:nowrap}
.ik-need{font-size:.7rem;color:#b45309;font-weight:700;margin:0 8px 6px;text-align:right}
.ik-dh{display:flex;justify-content:space-between;align-items:center;font-size:.85rem;color:var(--dg-mut)}
.ik-st{border-radius:999px;padding:2px 10px;font-size:.78rem}
.ik-st.warn{background:#fff4e0;color:#b45309}.ik-st.ok{background:#e5f6ee;color:#0f7a4a}
.ik-st.blue{background:var(--dg-bg);color:var(--dg-pri)}.ik-st.done{background:var(--dg-line);color:var(--dg-mut)}
.ik-dm{font-size:.8rem;color:var(--dg-mut);margin-top:8px;font-family:Consolas,monospace}
.ik-dt{font-size:1.12rem;font-weight:800;margin:2px 0 10px}
.ik-clue{background:var(--dg-bg);border-radius:8px;padding:10px 12px;font-size:.9rem;line-height:1.6;margin-bottom:8px}
.ik-clue>small{display:block;color:var(--dg-mut);font-size:.75rem;font-weight:700;margin-bottom:4px}
.ik-clue .ln{display:grid;grid-template-columns:34px 1fr;gap:6px;padding:5px 0;border-bottom:1px dashed var(--dg-line)}
.ik-clue .ln span{font-size:.7rem;color:var(--dg-mut);background:var(--dg-card);border-radius:4px;text-align:center;height:1.5em;line-height:1.5em;margin-top:2px}
.ik-clue .ln p{margin:0;word-break:keep-all}
.ik-clue ul{margin:8px 0 0;padding-left:18px;font-size:.8rem;color:var(--dg-mut)}
.ik-clue mark,.ik-orig mark{background:#fff1b8;color:inherit;padding:0 2px;border-radius:3px}
.ik-orig{background:#fff;color:#111;border:1px solid var(--dg-line);border-radius:8px;padding:16px 20px;line-height:1.8;
         font-size:.95rem;max-height:60vh;overflow:auto;margin:8px 0;word-break:keep-all}
.ik-why{background:#fff4e0;color:#b45309;border-radius:8px;padding:10px 12px;font-size:.85rem;line-height:1.55;margin-bottom:12px}
.ik-why b{display:block}.ik-why small{display:block;margin-top:6px;color:var(--dg-ink)}
.ik-why.ok{background:#e5f6ee;color:#0f7a4a}
.ik-none,.ik-empty{color:var(--dg-mut);text-align:center;padding:40px 10px;font-size:.9rem;line-height:1.7}
.ik-empty{padding:18px 10px 6px}.ik-empty small{display:block;margin-top:6px}
.ik-det{font-size:.88rem;background:#e5f6ee;color:#0f7a4a;border-radius:8px;padding:8px 12px;margin:0 0 10px}
.ik-det.bad{background:#fdeceb;color:#b42318}.ik-det small{display:block;color:var(--dg-mut);font-size:.76rem;margin-top:2px}
.ik-cap small{font-weight:400}
.db-help{font-size:.84rem;color:var(--dg-mut);background:var(--dg-card);border-left:4px solid var(--dg-grn);border-radius:8px;
         padding:8px 12px;margin:-4px 0 12px}
</style>""", unsafe_allow_html=True)

# 새 디자인 시안(2026-11-08): 따뜻한 무채색 + 초록 포인트, 검은 주 버튼, 테두리 카드, Noto Sans KR
st.markdown("""<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;700&display=swap');
[data-testid="stMain"] *{word-break:keep-all}
[data-testid="stMain"]{background:var(--bg)}
[data-testid="stMainBlockContainer"]{max-width:1280px;padding-top:.6rem}
/* 상단 바: 로고 + 알약 메뉴 */
.st-key-topbar{background:transparent !important;border:0 !important;padding:6px 0 !important;margin-bottom:4px}
.st-key-tb_home button{background:transparent !important;border:0 !important;padding:0;min-height:0}
.st-key-tb_home button p{font-size:20px !important;font-weight:700;color:var(--ink) !important;letter-spacing:-.03em}
.st-key-tb_home button:after{display:none}
.st-key-top_nav button[data-variant]{border:0 !important;background:transparent !important;border-radius:999px !important;padding:8px 14px}
.st-key-top_nav button[data-variant] p{color:#5f5b54 !important;font-size:15px;font-weight:400 !important}
.st-key-top_nav button[data-variant][data-selected="true"]{background:var(--sunken) !important}
.st-key-top_nav button[data-variant][data-selected="true"] p{color:var(--ink) !important;font-weight:500 !important}
.st-key-top_nav [role="radiogroup"]{border:0;gap:4px}
.tb-sub{display:none}
/* 버튼: 주 버튼은 검정, 나머지는 흰 바탕 + 테두리 */
[data-testid="stMain"] [data-testid="stBaseButton-primary"]{background:var(--ink) !important;border-color:var(--ink) !important;
  color:#fff !important;font-weight:700;min-height:48px}
[data-testid="stMain"] [data-testid="stBaseButton-primary"]:hover{background:#000 !important;border-color:#000 !important}
[data-testid="stMain"] [data-testid="stBaseButton-primary"] p{color:#fff !important}
[data-testid="stMain"] [data-testid="stBaseButton-secondary"],[data-testid="stMain"] [data-testid="stDownloadButton"] button{
  min-height:48px;border-color:var(--line-strong);background:var(--surface)}
/* 카드: 테두리만(그림자 없음), 모서리 20px */
[data-testid="stMain"] [class*="st-key-card"]{background:var(--surface) !important;border:1px solid var(--line) !important;
  border-radius:var(--r-lg) !important;box-shadow:none !important}
/* 입력칸: 흰 바탕 + 진한 테두리 */
[data-testid="stMain"] [data-testid="stTextInputRootElement"],[data-testid="stMain"] [data-baseweb="select"]>div,
[data-testid="stMain"] [data-testid="stTextAreaRootElement"],
[data-testid="stMain"] [class*="st-key-card"] [data-testid="stTextInputRootElement"],
[data-testid="stMain"] [class*="st-key-card"] [data-baseweb="select"]>div,
[data-testid="stMain"] [class*="st-key-card"] [data-testid="stTextAreaRootElement"]{background:var(--surface) !important}
[data-testid="stMain"] label p{font-weight:500;color:var(--ink-2)}
/* 고른 알약·탭: 연한 회색 바탕 */
[data-testid="stMain"] button[data-variant][data-selected="true"]{background:var(--sunken) !important;border-color:var(--line-strong) !important}
[data-testid="stMain"] button[data-variant][data-selected="true"] p{color:var(--ink) !important;font-weight:500}
/* 1. 새 보고서 */
.nw-steps{margin:8px 0 0;padding:0;list-style:none;display:flex;flex-wrap:wrap;gap:8px 24px;font-size:15px;color:var(--muted)}
.nw-steps li{display:flex;align-items:center;gap:8px}
.nw-steps li::before{content:'';width:8px;height:8px;border-radius:50%;background:#d6d3cc}
.nw-steps li.on{color:var(--accent);font-weight:700}.nw-steps li.on::before{background:var(--accent)}
.nw-hero h1{margin:16px 0 12px;font-size:40px;line-height:1.3;font-weight:700;letter-spacing:-.035em;color:var(--ink);padding:0}
.nw-hero p{margin:0 0 8px;font-size:18px;line-height:1.7;color:#5f5b54}
.st-key-nw_drop [data-testid="stFileUploaderDropzone"]{background:var(--surface);border:1.5px dashed #bdb9b0;border-radius:var(--r-lg);
  padding:36px 24px}
.st-key-nw_drop [data-testid="stFileUploaderDropzoneInstructions"] span{font-size:14px;font-weight:400;color:var(--muted)}
.st-key-nw_drop label p{font-size:20px !important;font-weight:700 !important;color:var(--ink) !important;letter-spacing:-.02em}
.st-key-nw_drop label{margin-bottom:6px}
.st-key-nw_drop [data-testid="stFileUploaderDropzone"] button{border:1px solid var(--ink);min-height:44px;padding:0 20px}
.nw-files{margin:6px 0 0;padding:0;list-style:none;display:flex;flex-direction:column;gap:10px}
.nw-file{display:flex;flex-wrap:wrap;align-items:center;gap:8px 16px;background:var(--surface);border:1px solid var(--line);
  border-radius:var(--r-md);padding:14px 18px}
.nw-file .ext{flex:none;width:48px;height:32px;border-radius:8px;background:var(--sunken);color:var(--ink-2);font-size:12px;
  font-weight:700;display:inline-flex;align-items:center;justify-content:center}
.nw-file .info{flex:1 1 280px;min-width:0;display:flex;flex-direction:column;gap:2px}
.nw-file .name{font-size:16px;font-weight:500;overflow-wrap:anywhere}.nw-file .meta{font-size:14px;color:var(--muted)}
.nw-file .ok{font-size:14px;color:var(--accent);font-weight:500}.nw-file .wait{font-size:14px;color:var(--muted)}
.nw-file .bad{font-size:14px;color:var(--warn);font-weight:500}
.nw-h2{margin:0 0 4px;font-size:18px;font-weight:700;letter-spacing:-.02em;color:var(--ink)}
.nw-hint{margin:4px 0 0;font-size:14px;line-height:1.6;color:var(--muted)}
.nw-dist{font-size:15px;background:var(--accent-soft);color:var(--accent);border-radius:var(--r-sm);padding:10px 14px;margin:4px 0}
.nw-dist.bad{background:var(--warn-bg);color:var(--warn-ink)}
.nw-dist small{display:block;color:var(--muted);font-size:13px;margin-top:2px}
.st-key-nw_go button{min-height:56px;font-size:18px;padding:0 32px;border-radius:var(--r-md) !important}
/* 2. 내 보고서(초안 검토) */
.rv-kicker{font-size:14px;color:var(--accent);font-weight:700}
.rv-h1{margin:6px 0 0;font-size:30px;line-height:1.35;font-weight:700;letter-spacing:-.03em;color:var(--ink)}
.rv-h2{margin:0 0 6px;font-size:15px;font-weight:700;color:var(--ink-2)}
.rv-src{background:var(--surface);border:1px solid var(--line);border-radius:var(--r-md);padding:14px 16px;margin-bottom:8px;
  display:flex;flex-direction:column;gap:4px}
.rv-src.main{border-color:var(--accent)}.rv-src .n{font-size:15px;font-weight:500;line-height:1.5;overflow-wrap:anywhere}
.rv-src .u{font-size:14px;color:var(--muted)}
.st-key-rv_doc{background:var(--sunken) !important;border:0 !important;border-radius:var(--r-lg) !important;padding:28px 16px !important}
.st-key-rv_doc .lh{max-width:680px;margin:0 auto;border:0;box-shadow:0 2px 12px rgba(28,27,25,.08)}
.st-key-rv_pdf{background:var(--sunken) !important;border-radius:var(--r-lg) !important;padding:24px 20px !important;gap:20px !important}
.st-key-rv_pdf img{max-width:720px;margin:0 auto;display:block;box-shadow:0 2px 12px rgba(28,27,25,.12);background:#fff}
.st-key-rv_pdf [data-testid="stImageCaption"]{text-align:center}
.rv-panel-head{display:flex;align-items:baseline;justify-content:space-between}
.rv-panel-head h2{margin:0;font-size:18px;font-weight:700;letter-spacing:-.02em;padding:0}
.rv-panel-head .score{font-size:14px;color:var(--accent);font-weight:700}
.rv-checks{margin:14px 0 4px;padding:0;list-style:none;display:flex;flex-direction:column;gap:14px}
.rv-checks li{display:flex;gap:12px;align-items:flex-start}
.rv-dot{flex:none;width:22px;height:22px;border-radius:50%;background:var(--accent);color:#fff;display:inline-flex;
  align-items:center;justify-content:center;font-size:13px;font-weight:700;margin-top:2px}
.rv-dot.warn{background:var(--warn)}
.rv-checks .t{display:block;font-size:16px;font-weight:500;line-height:1.5}
.rv-checks .d{display:block;font-size:14px;line-height:1.5;color:var(--muted)}
.rv-notice{background:var(--warn-bg);border-radius:var(--r-lg);padding:20px 24px;display:flex;flex-direction:column;gap:8px;margin:12px 0}
.rv-notice strong{font-size:16px;color:var(--warn-ink)}.rv-notice span{font-size:15px;line-height:1.6;color:#3d3a34}
.rv-ok{background:var(--accent-soft);border-radius:var(--r-lg);padding:16px 20px;margin:12px 0;color:var(--accent);font-weight:500}
/* 3. 서식 규칙 */
.rl-item{background:var(--surface);border:1px solid var(--line);border-radius:var(--r-md);padding:14px 18px;margin-bottom:8px;font-size:15px}
@media (max-width:640px){.nw-hero h1{font-size:30px}.rv-h1{font-size:24px}}
</style>""", unsafe_allow_html=True)


_cards = iter(range(10 ** 6))


def card(where=st):
    """흰 카드(디자인 시안). 테두리 상자에 card_ 키를 붙여 CSS로 꾸민다."""
    return where.container(border=True, key=f'card_{next(_cards)}')


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
    """DB·보고서에서 볼 사업지구. 화면 사이를 오가도 같은 지구를 유지한다."""
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


ITEM_GROUPS = [  # DB 적재 현황 화면의 묶음(1차 적재 항목, 현안보고 기준)
    ('기본정보', ['사업기호', '연장', '차로', '규모', '시행주체', '담당시행자']),
    ('사업비', ['사업비', '지원액', '시행자부담']),
    ('일정', ['완료시기', '개통목표', '착공시기', '예상완료']),
    ('추진상태', ['관리상태', '추진단계', '추진상태']),
    ('현안·대응', ['현안', '지연사유', '만회대책', '향후계획'])]


def db_overview():
    """지구를 골라 DB에 적재된 값(지구 공통·사업별 항목)과 추진경위·향후 일정 목록을 본다."""
    names = district_options()
    with st.container(border=True, key='card_overview'):
        st.markdown('**📋 DB 적재 현황** — 지구별 항목·추진경위')
        d = st.selectbox('사업지구', names, key='ov_district')
        facts = db.facts(con, district=d)
        dist = [f for f in facts if f['facility'] == catalog.DISTRICT_FAC]
        if dist:
            st.markdown('**지구 공통** · ' + ' · '.join(f"{f['item']} {draft.fmt_value(f['value'], f['unit'])}"
                                                    for f in dist if f['value'] is not None))
        by = {}
        for f in facts:
            if f['facility'] != catalog.DISTRICT_FAC:
                by.setdefault(f['facility'], {})[f['item']] = f
        grp = st.segmented_control('묶음', [g for g, _ in ITEM_GROUPS], default=ITEM_GROUPS[0][0], key='ov_grp') or ITEM_GROUPS[0][0]
        items = dict(ITEM_GROUPS)[grp]
        rows = []
        for fac, m in by.items():
            row = {'사업': fac}
            for it in items:
                f = m.get(it)
                row[it] = ('확인 필요' if f and f['status'] == '미확정(충돌)' else
                           draft.fmt_value(f['value'], f['unit']) if f and f['value'] is not None else '')
            rows.append(row)
        if rows:
            df = pd.DataFrame(rows)
            df = df[['사업'] + [c for c in items if df[c].astype(bool).any()]]  # 모두 빈 열은 숨김
            st.dataframe(df, hide_index=True, width='stretch',
                         column_config={c: st.column_config.TextColumn(width='large') for c in ('현안', '지연사유', '만회대책', '향후계획')})
        evs = db.events(con, d)
        if evs:
            st.markdown(f'**추진경위·향후 일정 {len(evs)}줄**')
            st.dataframe(pd.DataFrame([{'사업': e['facility'], '구분': e['kind'], '날짜': e['date'], '내용': e['content'],
                                        '근거 문서': e['doc_id']} for e in evs]), hide_index=True, width='stretch')
        elif facts:
            st.caption('추진경위·향후 일정 목록은 아직 없습니다(날짜와 함께 적힌 경위가 있는 문서를 올리면 쌓입니다).')


def page_docs():
    """🗂 적재 현황·관리: DB 보기·고치기만(올리기는 자료 적재에서) — 값 충돌 → DB 적재 현황 → 사업 목록·유형 → 적재된 문서(수정·빼기)"""
    conflict_box(st.session_state.get('district') or CAT['default'])  # 방금 저장한 지구에 값 충돌이 있으면 먼저 보여 줌
    registered = db.sources(con)
    if registered:
        db_overview()
        district_editor()
        docs_manage(registered)
    else:
        st.info('아직 DB에 적재된 문서가 없습니다. 📥 자료 적재에서 자료를 올리세요.')
    show_flash()


def district_editor():
    """화면에서 등록한 사업지구의 사업 목록·유형을 고친다(등록할 때 잘못 들어간 유형 바로잡기)."""
    local = {d['name']: d for d in catalog.local_districts()}
    with st.expander('🛠 사업 목록·유형 고치기 (화면에서 등록한 사업지구)'):
        if not local:
            st.caption('화면에서 등록한 사업지구가 없습니다. 기본 지구(config.yaml)는 설정 파일에서 고칩니다.')
            return
        d = st.selectbox('사업지구', list(local), key='ed_district')
        fixed = catalog._repair(local[d])['facilities']  # 지금 적용 중인 유형(예전 오류 바로잡은 값)
        df = pd.DataFrame([{'사업명': f['name'], '유형': f['type']} for f in fixed])
        new = st.data_editor(df, num_rows='dynamic', hide_index=True, width='stretch', key=f'ed_{d}',
                             column_config={'유형': st.column_config.SelectboxColumn(options=compare.TYPES, required=True,
                                                                                    help='환승 = 환승시설')})
        if st.button(f'{d} 사업 목록 저장', key='ed_save'):
            facs = [{'name': str(r['사업명']).strip(), 'type': r['유형'] or catalog.facility_type(CAT, '', str(r['사업명']))}
                    for _, r in new.iterrows() if str(r['사업명'] or '').strip()]
            catalog.save_local_district(d, facs, key=local[d].get('key'))
            flash(f'{d} 사업 목록 {len(facs)}개를 저장했습니다. 값 판정은 그대로이고, 보고서·비교 화면의 유형이 바뀝니다.')
            st.rerun()


def docs_manage(registered):
    st.subheader(f'적재된 문서 {len(registered)}건')
    doc_table(registered, with_count=True)
    with card():
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
        st.session_state['goto'] = DOCS
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
    sig = '|'.join(sorted(f'{p.name}:{p.stat().st_size}' for p in paths))
    if st.session_state.get('up_sig') != sig:  # 올린 파일이 바뀌면: 본문을 읽고 사업지구를 자동 인식
        texts = []
        for p in paths:
            try:
                texts.append(extract.read_text(p))
            except Exception:
                texts.append('')
        with st.spinner('문서에서 사업지구 이름을 찾는 중…'):
            det = catalog.detect_district(CAT, [p.name for p in paths], texts, cfg, use_llm=HAS_LLM)
        st.session_state.update(up_sig=sig, up_texts=texts, up_det=det)
        st.session_state.pop('pending', None)
        if det and det['known']:  # 이미 등록된 지구 → 그 지구를 고름
            st.session_state['up_district'] = det['known']
        elif det:  # 처음 보는 지구 → '새 사업지구 추가' + 이름 자동 입력
            st.session_state['up_district'] = NEW_DISTRICT
            st.session_state['up_new_name'] = det['name']
        else:
            guess = catalog.guess_district(CAT, paths[0].name)
            st.session_state['up_district'] = guess if guess in names else names[0]
    texts, det = st.session_state.get('up_texts', []), st.session_state.get('up_det')
    if 'up_district_next' in st.session_state:
        st.session_state['up_district'] = st.session_state.pop('up_district_next')
    if det:
        st.info(f"🔎 **사업지구 자동 인식: {det['name']}** "
                + ('(등록된 지구)' if det['known'] else '(**새 지구** — 아래에서 이름·사업 목록을 확인하고 등록하세요)')
                + f"  \n근거: {det['evidence']}" + (' · AI가 문서 앞부분을 읽고 추정' if det['source'] == 'AI' else ''))
        if det['others']:
            st.warning(f"다른 지구 문서도 섞여 있는 것 같습니다: {', '.join(det['others'])}. "
                       '지구가 다르면 값이 안 뽑히니 지구별로 나눠 올리세요.')
    else:
        st.caption('파일명·본문에서 사업지구 이름을 찾지 못했습니다. 아래에서 직접 고르거나 입력하세요.')
    c1, c2 = st.columns([1, 2])
    district = c1.selectbox('사업지구', names + [NEW_DISTRICT], key='up_district',
                            help='파일명과 본문(예: "○○ 공공주택지구", "○○사업본부")에서 지구 이름을 찾아 자동으로 고릅니다. '
                                 '처음 보는 지구면 "새 사업지구 추가"에 이름과 사업 목록을 미리 채웁니다.')
    if det and district != NEW_DISTRICT and district != (det['known'] or det['name']):
        st.warning(f"문서는 {det['name']} 것으로 보이는데 사업지구가 {district}로 되어 있습니다. "
                   f'{district}의 사업 이름으로 값을 찾으므로 다른 지구 문서에서는 값이 안 뽑힙니다.')
    if district == NEW_DISTRICT:
        new_name = c2.text_input('새 사업지구 이름', placeholder='예: 미리내지구', key='up_new_name',
                                 help='문서에서 자동으로 찾은 이름입니다. 틀리면 고쳐 쓰세요.')
        if new_name.strip() in names:  # 이미 있는 이름이면 새로 등록하지 않고 그 지구를 고르게 함
            st.warning(f'"{new_name.strip()}"는 이미 등록된 지구입니다. 왼쪽 사업지구에서 고르세요.')
            return
        sug = catalog.suggest_facilities([t for t in texts if t])
        default = '\n'.join(f"{s['name']}, {s['type']}" for s in sug)
        st.markdown('**사업 목록** — 한 줄에 "사업명, 유형"(유형: 도로·철도·환승시설·대중교통·접속시설). 문서에서 찾은 후보를 미리 채웠으니 고쳐 쓰세요.')
        fac_text = st.text_area('사업 목록', default, height=150, key=f'up_facs_{len(sig)}_{sum(map(ord, sig))}_{len(sug)}', label_visibility='collapsed')
        facs = []
        for line in fac_text.splitlines():
            parts = [x.strip() for x in line.split(',')]
            if parts and parts[0]:
                kind = {'환승시설': '환승'}.get(parts[1], parts[1]) if len(parts) > 1 else ''
                t = kind if kind in compare.TYPES else catalog.facility_type(CAT, '', parts[0])
                facs.append({'name': parts[0], 'type': t})
        if not new_name or not facs:
            st.warning('새 사업지구 이름과 사업을 하나 이상 입력하세요.')
            return
        if st.button(f'"{new_name}" 등록 (사업 {len(facs)}개)'):
            key = det['key'] if det and new_name.strip() == det['name'] else None  # 파일명 낱말(예: '해오름')로도 찾게
            catalog.save_local_district(new_name.strip(), facs, key=key)
            CAT = catalog.load(cfg)
            st.session_state['up_district_next'] = new_name.strip()  # 다음 실행에서 지구 선택칸에 넣는다
            flash(f'{new_name} 등록 완료. 이제 "값 뽑기"를 누르세요.')
            st.rerun()
        return
    show_flash()
    facs = catalog.projects_of(CAT, district)
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
            if d.get('events'):  # 추진경위·향후 일정(날짜별 여러 줄)
                st.caption(f"추진경위·향후 일정 {len(d['events'])}줄 (함께 저장)")
                st.dataframe(pd.DataFrame([{'사업': e['facility'], '구분': e['kind'], '날짜': e['date'], '내용': e['content']}
                                           for e in d['events']]), hide_index=True, width='stretch')
            keep_all.append((d, [c for c, lab in zip(cands, labels) if lab not in drop]))
    n = sum(len(cs) for _, cs in keep_all)
    if not any(cs for _, cs, _ in pending):
        st.warning(f'값을 하나도 못 찾았습니다. A01은 {district}에 등록된 사업({", ".join(facs)})의 값만 찾습니다. '
                   '문서가 다른 지구 것이면 위에서 사업지구를 바꾸거나 "새 사업지구 추가"로 등록하세요.')
    if st.button(f'DB에 저장하고 판정 ({n}건)', type='primary', disabled=not n):
        A02.run(con, keep_all, CAT['default'])  # A02: 기존 DB에 더해 판정
        st.session_state.pop('pending', None)
        st.session_state['district'] = district
        flash(f'{district} 문서 {len(keep_all)}개에서 {n}건을 저장하고 판정했습니다.')
        st.session_state['goto'] = DOCS
        st.rerun()


def extract_all(docs, items):
    """A01 실행(문서마다 AI 또는 규칙 추출) + 항목 후보 표 저장. 반환: [(문서, 후보 목록, 오류 문구)]"""
    bar = st.progress(0.0, text='값 뽑는 중...')
    out = A01.run(docs, items, HAS_LLM, cfg,
                  on_progress=lambda i, n, d: bar.progress((i - 1) / n, text=f'{d["file"]} ({i}/{n})'))
    A01.save_table(out)
    bar.empty()
    return out


# ---------------- ⚠ 값 충돌 선택 (A02 사람 개입, DB 화면에서) ----------------
def short(d):
    m = re.fullmatch(r'20(\d\d)-(\d\d)-(\d\d)', d or '')
    return f'{int(m.group(2))}.{int(m.group(3))}.' if m else (d or '')


def conflict_box(district):
    """같은 단계·같은 날짜 문서끼리 값이 다른 항목: 맞는 값을 버튼 한 번으로 확정(선택 기록 저장)."""
    conf = [f for f in db.facts(con, district=district) if f['status'] == '미확정(충돌)']
    if not conf:
        return
    with card():
        st.markdown(f"**⚠ 값 충돌 {len(conf)}건** — 같은 단계·같은 날짜 문서끼리 값이 다릅니다. 맞는 값을 고르면 DB에 확정됩니다.")
        for f in conf:
            tops = json.loads(f['conflict_candidates'] or '[]')
            st.markdown(f"**{esc(f['facility'])} · {esc(f['item'])}**")
            cols = st.columns(max(len(tops), 1))
            for i, c in enumerate(tops):
                label = f"{draft.fmt_value(c['value'], c['unit'])}  ({c['doc_id']} · {short(c['date'])})"
                if cols[i].button(label, key=f"cf{f['id']}_{i}", width='stretch',
                                  help=f"{c['file']} · {c['stage']} · {c['location']}"):
                    A02.choose(con, f['district'], f['facility'], f['item'], c['value'], '담당자')  # A02 사람 개입
                    flash(f"{f['facility']} {f['item']} → {draft.fmt_value(c['value'], c['unit'])} 확정 (선택 기록 저장)")
                    st.rerun()


# ---------------- 📝 보고서·자료 ----------------


def district_dept(district):
    """보고서 날짜줄의 작성 부서: 이 지구 문서에서 찾은 부서 → 없으면 기본 지구일 때만 config 값 → 없으면 빈칸"""
    cache = st.session_state.setdefault('dept_guess', {})
    if district not in cache:
        texts = []
        for s in db.sources(con, district):
            try:
                texts.append(extract.read_text(s['path']))
            except Exception:
                pass
        cache[district] = catalog.guess_dept(texts) or (DEPT if district == CAT['default'] else '')
    return cache[district]


def company_form_box(form):
    """회사 한글 양식(hwpx): 이 PC의 templates/company/ 에 있으면 그것을, 없으면(클라우드) 화면에서 올린 파일을 쓴다.
    올린 파일은 이 접속의 임시 폴더에만 두고(다른 접속자와 공유 안 함, 저장소에 안 올라감) 창을 닫으면 사라진다.
    반환: 이번에 쓸 양식 파일 경로(올린 것) 또는 None"""
    import tempfile
    from agents.a04_draft import hwpx_forms
    if A04.FORMS[form][0] == 'basic':
        return None
    local = hwpx_forms.available(form)
    store = st.session_state.setdefault('form_files', {})  # 양식 이름 → 올린 파일 경로
    with st.expander('🏢 회사 한글 양식 ' + ('(이 PC에 있음)' if local else '올리기 — 한글본을 회사 양식 그대로 만들려면'),
                     expanded=not local and form not in store):
        st.caption('회사 권장양식 hwpx 파일을 올리면 한글 보고서를 그 양식에 그대로 채웁니다. '
                   '올린 파일은 지금 접속에서만 쓰고 저장소·DB에 남기지 않습니다(창을 닫으면 사라짐).'
                   + (' 이 PC에는 templates/company/ 양식이 있어 올리지 않아도 됩니다.' if local else ''))
        ups = st.file_uploader('회사 양식(hwpx, 여러 개 가능)', type=['hwpx'], accept_multiple_files=True,
                               key='rp_company_forms', label_visibility='collapsed')
        if ups:
            folder = Path(st.session_state.setdefault('form_dir', tempfile.mkdtemp(prefix='didimdol_forms_')))
            for f in ups:
                p = folder / f.name
                if not p.exists() or p.stat().st_size != f.size:
                    p.write_bytes(f.getvalue())
                if not hwpx_forms.is_hwpx(p):
                    st.warning(f'{f.name}: 한글(hwpx) 문서가 아닙니다.')
                    continue
                guess = hwpx_forms.guess_form(f.name) or (form if len(ups) == 1 else None)
                if guess:
                    store[guess] = str(p)
                else:
                    st.warning(f'{f.name}: 어느 양식인지 파일 이름으로 알 수 없습니다. 하나씩 올리면 지금 고른 양식으로 씁니다.')
        if store:
            st.caption('올린 양식: ' + ' · '.join(f"{k} ← {Path(v).name}" for k, v in store.items()))
    if form in store:
        st.markdown(f'<div class="ik-det">🏢 한글본은 올린 회사 양식({esc(Path(store[form]).name)})에 채웁니다.</div>',
                    unsafe_allow_html=True)
        return store[form]
    return None






# ---------------- 📝 새 보고서 → 내 보고서 (새 디자인 시안: 자료 올리기 → 초안 검토 → 한글 파일로 저장) ----------------
EXT = {'.hwpx': 'HWPX', '.docx': 'DOCX', '.pdf': 'PDF', '.txt': 'TXT', '.xlsx': 'XLSX'}
STEPS3 = ['자료 올리기', '초안 검토', '한글 파일로 저장']


def steps3(cur):
    return '<ol class="nw-steps">' + ''.join(f'<li class="{"on" if i == cur else ""}">{s}</li>' for i, s in enumerate(STEPS3)) + '</ol>'


def parse_kdate(s):
    """보고 날짜 입력: ’26. 5. 28. / 2026-05-28 / 2026.5.28 → date (모르면 None)"""
    m = re.search(r"(?:(20)|[’'‘`])?(\d{2})[.\-/년\s]+(\d{1,2})[.\-/월\s]+(\d{1,2})", s or '')
    if not m:
        return None
    try:
        return datetime(int(f'20{m.group(2)}'), int(m.group(3)), int(m.group(4)))
    except ValueError:
        return None


def report_options(district, facts):
    """세부 설정(접힘): 작성 부서·대상 사업·목차·한글 문서 양식(회사 양식 올리기)·AI 문장 다듬기·근거 표시. 반환: 값 묶음"""
    preset = draft.REPORT
    tail, defaults = A04.PRESETS[preset]
    with st.expander('세부 설정 — 작성 부서·대상 사업·목차·한글 문서 양식'):
        dept = st.text_input('작성 부서', district_dept(district), key=f'rp_dept_{district}',
                             help='이 지구 문서에 가장 많이 나온 작성 부서를 미리 채웁니다. 다르면 고쳐 쓰세요.')
        facs = list(dict.fromkeys(f['facility'] for f in facts if f['facility'] != catalog.DISTRICT_FAC))
        pick_facs = st.multiselect('대상 사업', facs, default=facs, key=f'rp_facs_{district}_{len(facs)}')
        st.markdown('<div class="dg-q">목차</div>', unsafe_allow_html=True)
        cols = st.columns(3)
        chosen = []
        for i, sec in enumerate(draft.UI_SECTIONS):  # 담당자가 고친 현안 보고서 구조: 본문 □ 3개 + 붙임 3개
            if cols[i % 3].checkbox(sec.replace('붙임: ', '붙임 · '), value=sec in defaults, key=f'rp2_{sec}',
                                    help=A04.SECTION_HELP[sec]):
                chosen.append(sec)
        st.caption('붙임은 문서에 그 내용이 있을 때만 붙습니다(예: 관계기관 쟁점은 AI 추출로 쟁점을 찾았을 때).')
        st.markdown('<div class="dg-q">한글 문서 양식</div>', unsafe_allow_html=True)
        forms = [f for f in A04.FORMS if A04.FORMS[f][0] != 'press']
        if st.session_state.get('rp_form') not in forms:
            st.session_state['rp_form'] = '1쪽 보고서' if '1쪽 보고서' in forms else forms[0]
        form = st.selectbox('한글 문서 양식', forms, key='rp_form', label_visibility='collapsed',
                            help='회사 권장양식(보고서 작성 가이드라인)의 글꼴·제목 띠·기호 단계·간격으로 만듭니다.')
        company_form_box(form)
        extra = {}
        c1, c2 = st.columns(2)
        use_polish = c1.toggle('AI 본문 작성(담당자 수정본 문체)', value=HAS_LLM, disabled=not HAS_LLM, key='rp_ai_write',
                               help='담당자가 고친 보고서를 예시로 AI가 본문(□ 3개)을 다시 씁니다. 숫자는 DB에 있는 값만 쓰고, '
                                    '자료에 없는 숫자가 들어간 줄은 버립니다. 붙임 표는 DB 값 그대로입니다.')
        show_basis = c2.toggle('근거 표시(검토용)', value=False, key='rp_basis')
    return dict(preset=preset, dept=dept, pick_facs=pick_facs, chosen=chosen, extra=extra,
                use_polish=use_polish, show_basis=show_basis)


@st.cache_data(show_spinner=False, max_entries=16)
def pdf_pages(hwpx, docx):
    """저장 파일 → (PDF, 쪽 그림 목록, 변환한 파일 종류). 같은 파일이면 캐시를 쓴다."""
    from agents.a04_draft import pdf_preview
    return pdf_preview.preview(hwpx, docx)


def make_report(district, o):
    """DB의 그 지구 값으로 현안 보고자료 초안을 만들어 세션에 둔다(A03 → A04 → 서식 규칙 AI 다듬기 → 자동 점검)."""
    facts = ordered(db.facts(con, district=district))
    chosen = o['chosen'] or list(A04.PRESETS[o['preset']][1])
    pick = o['pick_facs'] or [f['facility'] for f in facts if f['facility'] != catalog.DISTRICT_FAC]
    res3 = A03.run(facts, o['preset'], facilities=list(dict.fromkeys(pick)) + [catalog.DISTRICT_FAC], use_llm=HAS_LLM, cfg=cfg)
    evs = db.events(con, district)
    cands = db.load_candidates(con, district)
    blocks = A04.run(res3, cands, db.sources(con, district), db.choices(con, district),
                     o['title'], district, o['dept'], chosen, o['extra'], HAS_LLM, cfg, order=catalog.order(CAT, district),
                     kinds=KINDS, show_basis=o['show_basis'], events=evs, report_date=o.get('date'))
    pol = None
    if o['use_polish']:  # AI 본문 작성(수정본 문체): 실패하거나 숫자가 어긋난 목차는 규칙 초안 그대로
        blocks, pol = A04.compose(blocks, res3, evs, cands, district, cfg=cfg, kinds=KINDS, sections=chosen)
    st.session_state['report'] = {'blocks': blocks, 'a03': res3, 'sections': chosen, 'district': district, 'opts': o,
                                  'dept': o['dept'], 'checks': A04.check(blocks, res3, cands, chosen, evs),
                                  'polish': pol, 'stamp': datetime.now().strftime('%Y%m%d_%H%M%S')}





def lh_style_date(d):
    return f"’{d:%y}. {d.month}. {d.day}."


def report_setup(has_report):
    """보고서 설정(사업지구·종류·제목·보고 날짜·세부 설정) → 초안 만들기. DB에 쌓인 값으로 만든다."""
    names = district_options()
    if st.session_state.get('rp_district') not in names:
        cur = st.session_state.get('district')
        st.session_state['rp_district'] = cur if cur in names else names[0]
    with st.container(border=True, key='card_settings'):
        st.markdown('<div class="nw-h2">보고서 설정</div>', unsafe_allow_html=True)
        c0, c1, c2, c3 = st.columns([1.1, 1.1, 2.2, 1])
        district = c0.selectbox('사업지구', names, key='rp_district', help='DB에 값이 쌓인 사업지구 중에서 고릅니다.')
        c1.selectbox('종류', ['현안 보고'], key='rp_kind', help='지금은 현안 보고자료 하나만 만듭니다.')
        tail = A04.PRESETS[draft.REPORT][0]
        title = c2.text_input('제목', f'{district} {tail}', key=f'rp_title_{district}')
        dtxt = c3.text_input('보고 날짜', lh_style_date(datetime.now()), key='rp_date')
        facts = db.facts(con, district=district)
        o = report_options(district, facts)
        _, cgo = st.columns([3, 1])
        with cgo.container(key='nw_go'):
            go = st.button('다시 만들기  →' if has_report else '초안 만들기  →', type='primary', width='stretch')
    if go:
        o.update(title=title, date=parse_kdate(dtxt))
        with st.spinner('DB 값으로 초안을 쓰는 중…' + (' (AI가 담당자 수정본 문체로 본문을 쓰는 중, 20~60초)' if o['use_polish'] else '')):
            make_report(district, o)
        st.rerun()


def page_report():
    """보고서 작성: 설정(세부 설정에 한글 양식) → 초안 만들기 → 초안 검토(근거 자료 | 저장 파일 PDF 미리보기) → 한글(hwpx)로 저장"""
    if not db.facts(con):
        st.markdown('<div class="nw-hero"><h1>먼저 자료를 올려 주세요.</h1>'
                    '<p>자료 DB에서 자료를 올리고 적재하면, 그 값으로 보고서 초안을 만들어요.</p></div>', unsafe_allow_html=True)
        if st.button('자료 DB로  →', type='primary'):
            st.session_state['goto'] = DOCS
            st.rerun()
        return
    rep = st.session_state.get('report')
    if rep:
        with st.expander('보고서 설정 바꾸기 · 다시 만들기', expanded=False):
            report_setup(True)
    else:
        report_setup(False)
        st.markdown('<div class="dg-empty"><div class="ico"></div><div>설정을 확인하고 <b>초안 만들기</b>를 누르세요.'
                    '<small>숫자는 모두 DB의 최신값에서 가져옵니다.</small></div></div>', unsafe_allow_html=True)
        return
    district, res3, o = rep['district'], rep['a03'], rep['opts']
    head = st.container()
    left, mid = st.columns([1, 3.2], gap='medium')
    forms = [f for f in A04.FORMS if A04.FORMS[f][0] != 'press']
    form = st.session_state.get('rp_form') if st.session_state.get('rp_form') in forms else \
        ('1쪽 보고서' if '1쪽 보고서' in forms else forms[0])
    form_path = st.session_state.get('form_files', {}).get(form)  # 세부 설정에서 올린 회사 양식(이 접속 동안만)

    # 왼쪽 아래: 확인 필요(문서 간 값이 다르거나 빈 항목) · AI가 고친 문장
    with left:
        lack = res3['lacking']
        if lack:
            items = [f"{f['facility']} {f['item']}" for f in lack[:4]]
            st.markdown(f'<div class="rv-notice"><strong>확인이 필요한 값 {len(lack)}건</strong><span>'
                        f"{esc(', '.join(items))}{' 등' if len(lack) > 4 else ''} — 문서끼리 값이 달라 보고서에 “확인 필요”로 "
                        '적었어요. 자료 DB › 적재 현황·관리에서 고르면 다시 만들 때 반영돼요.</span></div>', unsafe_allow_html=True)
        pol = rep.get('polish')
        if pol and 'written' in pol and not pol['error']:
            st.markdown(f'<div class="rv-ok">AI가 수정본 문체로 쓴 목차: {esc(", ".join(pol["written"]) or "없음")}</div>',
                        unsafe_allow_html=True)
            if pol['dropped'] or pol['kept_rule']:
                with st.expander(f"숫자 검사로 뺀 줄 {len(pol['dropped'])}개 · 규칙 초안 그대로 {len(pol['kept_rule'])}개"):
                    for line, why in pol['dropped']:
                        st.markdown(f"- {esc(line)}  \n  ✕ {esc(why)}")
                    for name, why in pol['kept_rule']:
                        st.markdown(f"- □ {esc(name)}: 규칙 초안 사용({esc(why)})")
        elif pol and pol['error']:
            st.caption(f"AI 본문 작성 실패 → 규칙 초안 그대로: {pol['error'][:120]}")

    lay = A04.Layout(rep['blocks'], form, res3['facts'], district, rep['dept'], KINDS, form_path=form_path)
    safe = re.sub(r'[\\/:*?"<>|]', '_', lay.title)

    # 머리: 제목 + 다시 만들기 / 한글(hwpx)로 저장
    with head:
        h1, h2 = st.columns([2.2, 2.4], vertical_alignment='bottom')
        h1.markdown(f'<div class="rv-kicker">초안 검토 · {esc(district)}</div>'
                    f'<div class="rv-h1">{esc(lay.title)}</div>', unsafe_allow_html=True)
        b1, b2, b3 = h2.columns([1, 1.5, 1])
        if b1.button('다시 만들기', width='stretch', help='DB의 최신 값으로 같은 설정의 초안을 다시 만듭니다.'):
            with st.spinner('초안을 다시 쓰는 중…'):
                make_report(district, o)
            st.rerun()
        hw = lay.hwpx()
        if b2.download_button('한글(hwpx)로 저장', hw, file_name=f"{safe}_{rep['stamp']}.hwpx", mime='application/octet-stream',
                              type='primary', width='stretch'):
            (db.OUTPUT / f"{safe}_{rep['stamp']}.hwpx").write_bytes(hw)
        b3.download_button('워드(docx)', lay.docx(), file_name=f"{safe}_{rep['stamp']}.docx", width='stretch',
                           mime='application/vnd.openxmlformats-officedocument.wordprocessingml.document')

    # 왼쪽: 근거 자료(값을 가져온 문서와 쓰인 횟수)
    with left:
        srcs = {s['doc_id']: s for s in db.sources(con, district)}
        use = {}
        for f in res3['facts']:
            if f['source_doc'] and f['value'] is not None:
                use[f['source_doc']] = use.get(f['source_doc'], 0) + 1
        st.markdown('<div class="rv-h2">근거 자료</div>' + ''.join(
            f'<div class="rv-src{" main" if i == 0 else ""}"><span class="n">{esc(srcs.get(d, {}).get("file", d))}</span>'
            f'<span class="u">값 {n}개에 사용 · {esc(srcs.get(d, {}).get("stage", ""))}</span></div>'
            for i, (d, n) in enumerate(sorted(use.items(), key=lambda x: -x[1]))) +
            '<p class="nw-hint">초안의 숫자는 모두 이 자료에서 가져왔어요. 값마다 근거는 아래 자료표(엑셀)에 있어요.</p>',
            unsafe_allow_html=True)
        st.download_button('자료표(xlsx)', A03.to_excel(res3, lay.title, db.sources(con, district)), width='stretch',
                           file_name=f"자료표_{rep['stamp']}.xlsx",
                           mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

    # 가운데: 보고서 미리보기 — 내려받는 파일을 PDF로 바꾼 쪽 그림(변환기가 없으면 화면용 미리보기)
    with mid:
        with st.spinner('저장 파일을 PDF로 바꿔 미리보기를 만드는 중…'):
            pdf, imgs, src = pdf_pages(hw, lay.preview_docx())
        if imgs:
            with st.container(key='rv_pdf'):
                for i, png in enumerate(imgs):
                    st.image(png, width='stretch', caption=f'{i + 1} / {len(imgs)}쪽')
            c1, c2 = st.columns([3, 1], vertical_alignment='center')
            c1.caption('한글 파일 그대로를 PDF로 바꾼 화면이에요.' if src == 'hwpx' else
                       ('한글본과 같은 내용·서식으로 만든 워드 파일을 PDF로 바꾼 화면이에요. 이 서버에 한글 글꼴(휴먼명조 등)이 없으면 '
                        '나눔 글꼴로 대신 보여서 줄바꿈이 조금 다를 수 있어요.')
                       + ('' if lay.use_form else ' 회사 한글 양식이 없어 기본 서식이에요 — 세부 설정에서 회사 양식을 올리면 그 양식으로 나와요.'))
            c2.download_button('PDF로 저장', pdf, file_name=f"{safe}_{rep['stamp']}.pdf", mime='application/pdf', width='stretch')
        else:
            with st.container(key='rv_doc'):
                st.markdown(lay.html(), unsafe_allow_html=True)
            st.caption('이 컴퓨터에는 PDF 변환기(LibreOffice)가 없어 화면용 미리보기로 보여 드려요. 클라우드에서는 저장 파일을 PDF로 바꿔 보여 줍니다.'
                       + ('' if lay.use_form else ' 회사 한글 양식이 없어 한글본은 기본 서식이에요 — 세부 설정에서 회사 양식을 올리세요.'))



# ---------------- 📥 자료 적재 (1 자료 올리기 → 2 AI 추출·분류 → 3 사람 확인 → 4 DB 적재) ----------------
STEPS = ['자료 올리기', 'AI 추출 · 분류', '사람 확인', 'DB 적재']
ST_CLS = {'확인 필요': 'warn', '자동 확정': 'ok', '사람 결정': 'blue', '적재 완료': 'done'}
INTAKE_SAMPLE = SAMPLE / 'intake'
INTAKE_KINDS = ['광역교통개선대책 보고서', '고시문', '내부 보고자료']  # 올리기 칸(도면·문서관리대장은 뺌, 2026-11-08)


def ik_register_path(district):
    return db.OUTPUT / f'intake_{district}.json'


def ik_key(d):
    return f"{d['kind']}|{d['title']}|{d.get('sub', '')}"


def ik_save(district, docs):
    keep = [{k: d.get(k) for k in ('kind', 'title', 'sub', 'date', 'facility', 'content', 'status', 'how')} for d in docs]
    ik_register_path(district).write_text(json.dumps(keep, ensure_ascii=False, indent=1), encoding='utf-8')


def ik_docs_from(path, kind):
    """파일 하나 → 적재 문서들(문서관리대장은 행마다 1건)."""
    p = Path(path)
    if kind == '문서관리대장' and p.suffix.lower() in ('.xlsx', '.csv'):
        return [{'kind': kind, 'title': r['title'], 'date': r['date'], 'sub': r['docno'], 'text': '', 'path': None,
                 'src': str(p), 'row': r['row']} for r in K.read_ledger(p)]  # row: 엑셀 행 번호
    try:
        text = extract.read_text(p)
    except Exception:
        text = ''
    meta = extract.guess_meta(p.name)
    title = re.sub(r'^\d{6}\s*', '', p.stem)
    date = (K.date_in_text(text, kind) or meta['date']) if kind == '고시문' else (meta['date'] or K.date_in_text(text, kind))
    return [{'kind': kind, 'title': title, 'date': date, 'sub': p.name, 'text': text, 'path': str(p)}]


def ik_build(district, files):
    """files: [(경로, 자료 종류)] → 분류된 문서 목록. 담당자가 이미 정한 것·DB에 실제로 들어간 것은 저장본을 따른다."""
    global CAT
    docs = []
    for path, kind in files:
        docs.extend(ik_docs_from(path, kind))
    basis = [d for d in docs if d['kind'] == K.KINDS[0]]  # 대책 보고서(기준정보 비교용, 표에도 함께 보임)
    added = catalog.merge_found(district, [d['text'] for d in docs if d.get('text')])  # 문서에 나온 사업을 목록에 보탬
    if added:
        CAT = catalog.load(cfg)
        flash(f"문서에서 사업 {len(added)}개를 찾아 {district} 사업 목록에 더했습니다: {', '.join(added)} "
              "(적재 현황·관리 › 사업 목록·유형 고치기에서 수정 가능)")
    facs = ik_facilities(district)
    with st.spinner('문서를 읽고 교통대책·내용을 분류하는 중…' + (' (AI가 확인 필요 문서를 추천하는 중)' if HAS_LLM else '')):
        n_ai = K.classify(docs, facs, district, use_llm=HAS_LLM, cfg=cfg)
    try:
        saved = {ik_key(s): s for s in json.loads(ik_register_path(district).read_text(encoding='utf-8'))}
    except Exception:
        saved = {}
    in_db = {x['file'] for x in db.sources(con, district)}
    for d in docs:
        s = saved.get(ik_key(d))
        if s and s.get('status') in ('사람 결정', '적재 완료'):
            s = dict(s)
            if s['status'] == '적재 완료' and not (d.get('path') and Path(d['path']).name in in_db):
                s['status'] = '사람 결정' if s.get('how') == '담당자' else d['status']  # 기록만 남고 DB엔 없으면 다시 적재 가능하게
            d.update({k: s[k] for k in ('facility', 'content', 'status', 'date') if s.get(k) is not None})
        elif d.get('path') and Path(d['path']).name in in_db and d['status'] == '자동 확정':
            d['status'] = '적재 완료'  # 이미 DB에 있는 문서
    # 문서마다 사업지구 확인: 다른 지구 문서로 보이면 확인 필요(그대로 적재되지 않게)
    for d in docs:
        if not d.get('path'):
            continue
        r = catalog.detect_district(CAT, [Path(d['path']).name], [d.get('text') or ''])
        other = (r['known'] or r['name']) if r else None
        if other and other != district:
            d['other_district'] = other
            if d.get('status') != '적재 완료':
                d['status'] = '확인 필요'
                d['reason'] = (f"이 문서는 {other} 문서로 보입니다(근거: {r['evidence']}). "
                               f"사업지구를 바꾸거나, {district} 문서가 맞으면 이대로 결정하세요. " + (d.get('reason') or '')).strip()
    return {'docs': docs, 'basis': basis, 'n_ai': n_ai}


def ik_detect(files):
    """올린 파일 전체로 사업지구 판단(파일명·본문 규칙 → 못 찾으면 AI). 같은 파일이면 다시 읽지 않는다."""
    sig = '|'.join(sorted(f'{p}:{Path(p).stat().st_size}' for p, _ in files))
    cached = st.session_state.get('ik_det')
    if cached and cached[0] == sig:
        return cached[1], sig
    texts = []
    for p, _ in files:
        try:
            texts.append(extract.read_text(p))
        except Exception:
            texts.append('')
    with st.spinner('올린 문서에서 사업지구를 찾는 중…'):
        det = catalog.detect_district(CAT, [Path(p).name for p, _ in files], texts, cfg, use_llm=HAS_LLM)
    if det and not det['known']:  # 새 지구면 등록할 때 쓸 사업 후보도 같이
        det['facilities'] = catalog.suggest_facilities([t for t in texts if t])
    st.session_state['ik_det'] = (sig, det)
    return det, sig


def ik_register_box(det):
    """올린 문서가 등록 안 된 새 사업지구일 때: 이름·사업 목록을 채워 바로 등록."""
    global CAT
    with card():
        st.markdown(f"**🆕 새 사업지구로 보입니다: {esc(det['name'])}** — 근거: {esc(det['evidence'])}"
                    + (' · AI가 문서 앞부분을 읽고 추정' if det['source'] == 'AI' else ''))
        st.caption('등록해야 문서를 교통대책별로 나눌 수 있습니다. 이름과 사업 목록(한 줄에 "사업명, 유형")을 확인하고 등록하세요.')
        c1, c2 = st.columns([1, 2])
        name = c1.text_input('사업지구 이름', det['name'], key=f"ik_new_{det['name']}")
        default = '\n'.join(f"{s['name']}, {s['type']}" for s in det.get('facilities') or [])
        fac_text = c2.text_area('사업 목록 (유형: 도로·철도·환승시설·대중교통·접속시설)', default, height=120,
                                key=f"ik_newf_{det['name']}")
        facs = []
        for ln in fac_text.splitlines():
            parts = [x.strip() for x in ln.split(',')]
            if parts and parts[0]:
                kind = {'환승시설': '환승'}.get(parts[1], parts[1]) if len(parts) > 1 else ''
                facs.append({'name': parts[0], 'type': kind if kind in compare.TYPES else catalog.facility_type(CAT, '', parts[0])})
        if st.button(f'"{name}" 등록하고 계속 (사업 {len(facs)}개)', type='primary', disabled=not (name.strip() and facs)):
            catalog.save_local_district(name.strip(), facs, key=det['key'] if name.strip() == det['name'] else None)
            CAT = catalog.load(cfg)
            st.session_state['ik_district_next'] = name.strip()
            st.session_state.pop('ik_det', None)
            flash(f'{name} 등록 완료. 문서를 이 지구로 나눕니다.')
            st.rerun()


def ik_facilities(district):
    return catalog.projects_of(CAT, district)


def ik_stepper(cur):
    return '<div class="ik-steps">' + ''.join(
        f'<span class="{"on" if i == cur else ("past" if i < cur else "")}">{i + 1} {s}</span>' for i, s in enumerate(STEPS)) + '</div>'


def ik_upload_cards(district, state):
    """올리기 칸 하나. 자료 종류(대책 보고서·고시문·내부 보고)는 파일 이름·내용으로 알아서 정한다. 반환: [(경로, 종류)]"""
    folder = UPLOADS / 'intake'  # 지구와 상관없이 한 곳(지구를 바꿔도 올린 파일이 남게)
    files = []
    with st.container(key='nw_drop'):
        ups = st.file_uploader('파일을 업로드하세요', type=[e[1:] for e in extract.FORMATS], accept_multiple_files=True,
                               key='ik_up_one', help='한글(hwpx)·워드·PDF·엑셀·텍스트, 여러 개를 한 번에 올릴 수 있습니다.')
    for f in ups or []:
        folder.mkdir(parents=True, exist_ok=True)
        p = folder / f.name
        if not p.exists() or p.stat().st_size != f.size:
            p.write_bytes(f.getvalue())
        kind = K.guess_kind(f.name)
        files.append((str(p), kind if kind in INTAKE_KINDS else '내부 보고자료'))
    return files


def ik_fac_list(facs, docs, sel):
    """왼쪽: 교통대책 목록(건수·진행 막대·최근 내용). 누르면 가운데 표를 그 대책으로 거른다."""
    st.markdown(f'<div class="ik-lh">교통대책 {len(facs)}건 · 등록 기준</div>'
                '<div class="ik-legend">막대: 설계 → 인허가 → 보상 → 공사<br>진한 칸 = 자료로 확인된 가장 뒤 단계</div>',
                unsafe_allow_html=True)
    rows = [('전체', len(docs), None)] + [(f, sum(d['facility'] == f for d in docs), f) for f in facs] + \
        [(K.COMMON, sum(d['facility'] == K.COMMON for d in docs), K.COMMON)]
    for i, (name, n, key) in enumerate(rows):
        need = key is not None and any(d['facility'] == key and d['status'] == '확인 필요' for d in docs)
        label = name if key in (None, K.COMMON) else f'{i:02d} {name}'
        if st.button(f'{label} · {n}건', key=f'ik_fac_{i}', type='primary' if sel == key else 'tertiary', width='stretch',
                     help=f'{name} 문서만 보기' if key else '모든 문서 보기'):
            st.session_state['ik_sel_fac'] = key
            st.rerun()
        if key not in (None, K.COMMON):
            cur, stage = K.stage_bar(docs, key)
            segs = ''.join(f'<i class="{"cur" if j == cur else ("on" if j < cur else "")}" title="{s}"></i>'
                           for j, s in enumerate(K.STAGE4))
            st.markdown(f'<div class="ik-bar">{segs}<em>{stage}</em></div>'
                        + ('<div class="ik-need">확인 필요 문서 있음</div>' if need else ''), unsafe_allow_html=True)


def ik_table(docs, idx):
    """가운데: 적재 문서 표(행을 고르면 오른쪽에 자세히). 반환: 고른 문서 번호 또는 None"""
    df = pd.DataFrame([{'자료': K.KIND_SHORT[d['kind']], '날짜': (d['date'] or '') + ('' if d['date'] else ' ?'),
                        '제목': d['title'], '교통대책': d['facility'],
                        '내용': d['content'], '상태': d['status']} for d in (docs[i] for i in idx)])

    def color(row):
        bg = {'확인 필요': 'background-color:#fff4e0', '사람 결정': 'background-color:#eef3fa'}.get(row['상태'], '')
        return [bg] * len(row)

    def chip(v):
        return {'확인 필요': 'color:#b45309;font-weight:700', '자동 확정': 'color:#0f7a4a;font-weight:700',
                '사람 결정': 'color:#0B3A8A;font-weight:700', '적재 완료': 'color:#5b6472'}.get(v, '')
    ev = st.dataframe(df.style.apply(color, axis=1).map(chip, subset=['상태']), hide_index=True, width='stretch',
                      height=min(36 * len(df) + 40, 640), on_select='rerun', selection_mode='single-row', key='ik_tbl',
                      column_config={'제목': st.column_config.TextColumn(width=260),
                                     '자료': st.column_config.TextColumn(width=62),
                                     '날짜': st.column_config.TextColumn(width=92),
                                     '교통대책': st.column_config.TextColumn(width=150),
                                     '내용': st.column_config.TextColumn(width=78),
                                     '상태': st.column_config.TextColumn(width=72)})
    rows = ev.selection.rows if ev and ev.selection else []
    return idx[rows[0]] if rows else None


def mark(html_text, d):
    """대책 이름에 형광 표시(이미 esc한 글에)."""
    for m in sorted(d.get('mentions') or [], key=len, reverse=True):
        html_text = html_text.replace(esc(m), f'<mark>{esc(m)}</mark>')
    return html_text


@st.dialog('원문 보기', width='large')
def show_original(d):
    """문서 원문: 파일이면 본문 전체 + 원본 내려받기, 문서관리대장 행이면 그 행 + 대장 파일."""
    st.markdown(f"**{esc(d['title'])}**  \n{d['kind']} · {esc(d.get('sub') or '')} · {d['date'] or '날짜 ?'}")
    if d.get('path'):
        p = Path(d['path'])
        body = d.get('text') or ''
        if body.strip():
            html_body = '<br>'.join(mark(esc(ln), d) for ln in body.splitlines() if ln.strip())
            st.markdown(f'<div class="ik-orig">{html_body}</div>', unsafe_allow_html=True)
        else:
            st.info('글자를 읽지 못한 파일입니다(그림·스캔 등). 원본을 내려받아 확인하세요.')
        if p.exists():
            st.download_button(f'원본 파일 내려받기 ({p.name})', p.read_bytes(), file_name=p.name, width='stretch',
                               icon=':material/download:')
    else:  # 문서관리대장의 한 줄
        st.markdown(f'<div class="ik-orig">문서관리대장 <b>{d.get("row", "?")}행</b><br>'
                    f'시행일자: {d["date"] or "(비어 있음)"}<br>문서번호: {esc(d.get("sub") or "")}<br>'
                    f'제목: {mark(esc(d["title"]), d)}</div>', unsafe_allow_html=True)
        st.caption('문서관리대장은 공문 목록이라 본문이 없습니다. 본문은 문서번호로 전자결재·문서함에서 확인하세요.')
        src = Path(d['src']) if d.get('src') else None
        if src and src.exists():
            st.download_button(f'문서관리대장 내려받기 ({src.name})', src.read_bytes(), file_name=src.name, width='stretch',
                               icon=':material/download:')


def ik_detail(district, docs, i, facs):
    """오른쪽: 고른 문서의 단서·AI 판단 + 사람 결정."""
    d = docs[i]
    st.markdown(f'<div class="ik-dh"><span>{d["kind"]}</span><b class="ik-st {ST_CLS[d["status"]]}">{d["status"]}</b></div>'
                f'<div class="ik-dm">{esc(d.get("sub") or "")} · {d["date"] or "날짜 ?"}</div>'
                f'<div class="ik-dt">{esc(d["title"])}</div>', unsafe_allow_html=True)
    if d['status'] == '확인 필요':  # 무엇을 정해야 하는지 먼저
        st.markdown(f'<div class="ik-why"><b>AI가 멈춘 이유</b>{esc(d["reason"])}'
                    + (f'<small>💡 AI 추천: <b>{esc(d["facility"])} · {esc(d["content"])}</b><br>{esc(d["ai_why"])}</small>'
                       if d.get('ai_why') else '') + '</div>', unsafe_allow_html=True)
    lines = ''.join(f'<div class="ln"><span>{w}</span><p>{mark(esc(t), d)}</p></div>' for w, t in K.clues(d))
    basis = ''.join(f'<li>{esc(x)}</li>' for x in K.why(d))
    st.markdown(f'<div class="ik-clue"><small>원문에서 찾은 단서</small>{lines}'
                f'<ul>{basis}</ul></div>', unsafe_allow_html=True)
    if st.button('📄 원문 전체 보기', key=f'ik_view_{district}_{i}', width='stretch',
                 help='문서 본문 전체(또는 문서관리대장의 해당 행)를 크게 띄우고, 원본 파일을 내려받을 수 있습니다.'):
        show_original(d)
    if d['status'] == '적재 완료':
        st.caption('DB에 적재된 문서입니다.')
        return
    opts = list(dict.fromkeys(d.get('options') or [d['facility'], K.COMMON]))
    tag = f'{district}_{i}'
    pick = st.radio('① 어느 교통대책인가요?', opts, key=f'ik_r_{tag}',
                    index=opts.index(d['facility']) if d['facility'] in opts else 0,
                    format_func=lambda f: f if f == K.COMMON else f'{facs.index(f) + 1:02d} {f}' if f in facs else f)
    other = st.selectbox('목록에 없으면', ['—'] + facs + [K.COMMON], key=f'ik_o_{tag}',
                         format_func=lambda f: f'{len(facs)}개 대책 중 고르기…' if f == '—' else f)
    content = st.selectbox('② 사업의 어떤 내용인가요?', K.CONTENTS, key=f'ik_c_{tag}',
                           index=K.CONTENTS.index(d['content']) if d['content'] in K.CONTENTS else len(K.CONTENTS) - 1)
    date = d['date']
    if not date:
        dv = st.date_input('③ 문서 날짜', value=None, key=f'ik_d_{tag}', format='YYYY-MM-DD')
        date = dv.isoformat() if dv else ''
    label = '결정하고 다음 확인 필요로' if d['status'] == '확인 필요' else '이대로 결정(고치기)'
    if st.button(label, type='primary', width='stretch', key=f'ik_go_{tag}', disabled=not date):
        d.update(facility=other if other != '—' else pick, content=content, date=date, status='사람 결정', how='담당자')
        K.save_example(d, district)
        ik_save(district, docs)
        nxt = next((j for j, x in enumerate(docs) if x['status'] == '확인 필요'), None)
        st.session_state['ik_focus'] = nxt
        st.session_state.pop('ik_tbl', None)
        st.rerun()
    st.caption('결정한 내용은 다음 분류 때 AI의 예시로 쓰입니다.' + ('' if date else ' 날짜를 넣어야 결정할 수 있습니다.'))


def ik_load_db(district, state):
    """④ 확인된 자료 DB 적재: 파일이 있는 문서는 A01 값 추출 → A02 판정, 대장 행은 적재 기록만."""
    docs = state['docs']
    ready = [d for d in docs if d['status'] in ('자동 확정', '사람 결정')]
    with_file = [d for d in ready if d.get('path')]
    n_vals = 0
    if with_file:
        metas = A01.describe([d['path'] for d in with_file], db.next_doc_num(con), CAT)
        by_path = {d['path']: d for d in with_file}
        for m in metas:
            src = by_path[m['path']]
            m['doc_id'] = db.doc_id_for_file(con, m['file']) or m['doc_id']
            m['district'] = district
            m['date'] = src.get('date') or m['date']
        with st.spinner(f'{len(metas)}개 문서에서 값을 뽑아 DB에 적재하는 중…'):
            res = A01.run(metas, catalog.items_for(CAT, district), use_llm=HAS_LLM, cfg=cfg)
            A02.run(con, res, CAT['default'])
        n_vals = sum(len(c) for _, c, _ in res)
    for d in ready:
        d['status'] = '적재 완료'
    ik_save(district, docs)
    flash(f'{len(ready)}건 적재 완료' + (f' · 파일 {len(with_file)}개에서 값 {n_vals}건을 DB에 더해 판정' if with_file else ''))


def page_intake():
    district_names = list(dict.fromkeys((district_options() if db.facts(con) else []) + CAT['districts']))
    if 'ik_district_next' in st.session_state:  # 문서로 찾은 지구·새로 등록한 지구로 바꿈(위젯 그리기 전에)
        st.session_state['district'] = st.session_state.pop('ik_district_next')
    if st.session_state.get('district') not in district_names:
        st.session_state['district'] = CAT['default'] if CAT['default'] in district_names else district_names[0]
    h1, h2 = st.columns([2, 3], vertical_alignment='bottom')
    with h1.container(key='ik_head'):
        district = st.selectbox('사업지구 · 문서를 올리면 자동으로 고릅니다', district_names, key='district')
    facs = ik_facilities(district)
    store = st.session_state.setdefault('ik', {})
    state = store.get(district, {'docs': [], 'basis': [], 'n_ai': 0, 'sig': ''})
    files = ik_upload_cards(district, state)
    if st.session_state.get('ik_sample_on'):
        files += [(str(p), k) for p in sorted(INTAKE_SAMPLE.iterdir()) if (k := K.guess_kind(p.name)) in INTAKE_KINDS]
    mismatch = None
    if files:  # ① 올린 문서로 사업지구를 찾는다
        det, fsig = ik_detect(files)
        if det and det['known'] and det['known'] != district and st.session_state.get('ik_auto_sig') != fsig:
            st.session_state['ik_auto_sig'] = fsig  # 같은 파일로는 한 번만 자동 전환(그 뒤 사람이 바꾸면 그대로)
            st.session_state['ik_district_next'] = det['known']
            flash(f"올린 문서를 보고 사업지구를 **{det['known']}**(으)로 골랐습니다. (근거: {det['evidence']})")
            st.rerun()
        if det and not det['known']:
            show_flash()
            ik_register_box(det)
            return
        if det:
            mismatch = det['known'] if det['known'] != district else None
            st.markdown(f"<div class='ik-det{' bad' if mismatch else ''}'>🔎 문서로 찾은 사업지구: <b>{esc(det['known'])}</b>"
                        + (f" — 지금 고른 지구({esc(district)})와 다릅니다. 이대로는 DB에 적재하지 않습니다." if mismatch else ' ✓')
                        + (f"<small>근거: {esc(det['evidence'])}" + (f" · 다른 지구 문서도 섞여 있음: {esc(', '.join(det['others']))}" if det['others'] else '')
                           + '</small>') + '</div>', unsafe_allow_html=True)
    sig = district + '|' + '|'.join(sorted(f'{p}:{k}:{Path(p).stat().st_size}' for p, k in files))
    if files and state.get('sig') != sig:
        state = ik_build(district, files) | {'sig': sig}
        store[district] = state
        st.session_state.pop('ik_tbl', None)
        st.session_state['ik_focus'] = next((j for j, x in enumerate(state['docs']) if x['status'] == '확인 필요'), None)
        st.rerun()
    docs = state['docs']
    cnt = {s: sum(d['status'] == s for d in docs) for s in K.STATUS}
    cur = 0 if not docs else (2 if cnt['확인 필요'] else (3 if cnt['적재 완료'] < len(docs) else 3))
    h2.markdown(ik_stepper(cur), unsafe_allow_html=True)
    if not docs:
        with card():
            st.markdown('<div class="ik-empty">파일을 올리면 사업지구를 알아서 고르고, 문서마다 <b>어느 교통대책</b>의 '
                        '<b>어떤 내용</b>인지 나눕니다. 처음 보는 사업지구면 그 자리에서 등록합니다.</div>',
                        unsafe_allow_html=True)
            if INTAKE_SAMPLE.exists():  # 모의 자료는 누리마루지구 문서(올리면 지구가 자동으로 바뀜)
                n_s = sum(K.guess_kind(p.name) in INTAKE_KINDS for p in INTAKE_SAMPLE.iterdir())
                if st.button(f'📁 모의 자료로 해 보기 (누리마루지구 · 문서 {n_s}건)'):
                    st.session_state['ik_sample_on'] = True
                    st.rerun()
        show_flash()
        conflict_box(district)
        return

    ready = cnt['자동 확정'] + cnt['사람 결정']
    with card():
        c1, c2 = st.columns([4, 1], vertical_alignment='center')
        basis = f"대책 보고서 {len(state['basis'])}건" if state['basis'] else '대책 보고서 없음(등록된 대책 기준)'
        c1.markdown(f'<div class="ik-stat"><span>대책 기준정보 <em>{basis}</em></span><i></i>'
                    f'<span>적재 문서 {len(docs)}건</span><span>자동 확정 <b class="ok">{cnt["자동 확정"]}</b></span>'
                    f'<span>확인 필요 <b class="warn">{cnt["확인 필요"]}</b></span><span>사람 결정 <b class="blue">{cnt["사람 결정"]}</b></span>'
                    f'<span>적재 완료 <b>{cnt["적재 완료"]}</b></span>'
                    + (f'<span class="ai">AI 추천 {state["n_ai"]}건</span>' if state.get('n_ai') else '') + '</div>',
                    unsafe_allow_html=True)
        if c2.button(f'확인된 자료 DB 적재 ({ready}건)', type='primary', width='stretch', disabled=not ready or bool(mismatch),
                     help='자동 확정·사람 결정 문서를 DB에 적재합니다. 확인 필요 문서는 남겨 둡니다.'
                          + (f' — 문서는 {mismatch} 것으로 보여 잠겨 있습니다. 사업지구를 맞추세요.' if mismatch else '')):
            ik_load_db(district, state)
            st.rerun()
    show_flash()
    conflict_box(district)  # 적재 뒤 문서끼리 값이 다르면 여기서 고름(예전 대시보드 기능)

    left, mid, right = st.columns([0.95, 3.6, 1.35], gap='small')
    sel_fac = st.session_state.get('ik_sel_fac')
    with left, card():
        ik_fac_list(facs, docs, sel_fac)
    with mid, card():
        tab = st.segmented_control('보기', ['대책 기준정보 · 보고서 추출', f'적재 문서 {len(docs)}건'], key='ik_tab',
                                   default=f'적재 문서 {len(docs)}건', label_visibility='collapsed') or f'적재 문서 {len(docs)}건'
        if tab.startswith('대책'):
            ik_basis(district, facs, state, docs)
            pick = None
        else:
            f1, f2 = st.columns([1, 1.2])
            kinds = ['전체'] + [K.KIND_SHORT[k] for k in INTAKE_KINDS if any(d['kind'] == k for d in docs)]
            kf = f1.pills('자료', kinds, key='ik_kf', default='전체', label_visibility='collapsed') or '전체'
            sf = f2.pills('상태', ['모든 상태'] + K.STATUS, key='ik_sf', default='모든 상태', label_visibility='collapsed') or '모든 상태'
            idx = [j for j, d in enumerate(docs) if (kf == '전체' or K.KIND_SHORT[d['kind']] == kf)
                   and (sf == '모든 상태' or d['status'] == sf) and (sel_fac is None or d['facility'] == sel_fac)]
            pick = ik_table(docs, idx) if idx else None
            if not idx:
                st.info('조건에 맞는 문서가 없습니다.')
            st.caption('행을 누르면 오른쪽에서 원문 단서와 AI 판단을 봅니다. 확인 필요 문서는 오른쪽에서 바로 결정합니다.')
    focus = pick if pick is not None else st.session_state.get('ik_focus')
    with right, card():
        if focus is None or focus >= len(docs):
            st.markdown('<div class="ik-none">표에서 문서를 고르면<br>여기에서 확인·결정합니다.</div>', unsafe_allow_html=True)
        else:
            ik_detail(district, docs, focus, facs)


def ik_basis(district, facs, state, docs):
    """대책 기준정보 탭: 등록된 교통대책과, 올린 대책 보고서에서 찾은 사업 이름 비교."""
    found = catalog.suggest_facilities([b['text'] for b in state['basis'] if b.get('text')]) if state['basis'] else []
    names = {f['name'] for f in found}
    rows = [{'번호': f'{i + 1:02d}', '교통대책': f, '유형': CAT['types'].get((district, f), ''),
             '적재 문서': sum(d['facility'] == f for d in docs),
             '대책 보고서': ('있음' if any(_ns_eq(f, n) for n in names) else '없음') if state['basis'] else '—'}
            for i, f in enumerate(facs)]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width='stretch')
    extra = [n for n in names if not any(_ns_eq(f, n) for f in facs)]
    if extra:
        st.warning('대책 보고서에는 있지만 등록되지 않은 사업: ' + ', '.join(extra)
                   + ' — 💾 DB › 📂 문서 관리의 "새 사업지구 추가"에서 사업 목록을 고치세요.')
    if not state['basis']:
        st.caption('"광역교통개선대책 보고서" 칸에 대책 보고서를 올리면, 보고서에서 찾은 사업과 등록된 대책을 비교합니다.')


def _ns_eq(a, b):
    n = lambda s: re.sub(r'\s|\(.*?\)', '', s)  # noqa: E731
    return n(a) == n(b) or n(a) in n(b) or n(b) in n(a)


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


# ---------------- 🏠 처음 ----------------


# ---------------- 💾 DB ----------------
def page_db():
    st.markdown('<div class="nw-hero"><h1>자료만 올리세요.<br>보고서는 알아서 쓸게요.</h1>'
                '<p>올린 자료를 교통대책별로 나눠 DB에 쌓고, 양식에 맞춘 보고서 초안을 작성해서 보여 드려요.</p>'
                '</div>', unsafe_allow_html=True)
    if st.session_state.get('db_view') not in DB_VIEWS:
        st.session_state['db_view'] = DB_VIEWS[0]
    view = st.segmented_control('DB 보기', DB_VIEWS, key='db_view', label_visibility='collapsed') or DB_VIEWS[0]
    {DB_VIEWS[0]: page_intake, DB_VIEWS[1]: page_docs}[view]()


# ---------------- 화면 전환 (상단 바: 디딤돌 로고 · 새 보고서 · 내 보고서 · 자료 DB · 서식 규칙) ----------------
LOGO = ('<svg width="28" height="28" viewBox="0 0 28 28" aria-hidden="true"><circle cx="7" cy="20" r="4" fill="#1f6f5c"/>'
        '<circle cx="14" cy="14" r="4" fill="#1f6f5c" opacity="0.7"/><circle cx="21" cy="8" r="4" fill="#1f6f5c" opacity="0.4"/></svg>')


def top_bar(page):
    st.session_state['top_nav'] = page
    with st.container(key='topbar'):
        c1, c2 = st.columns([1, 3], vertical_alignment='center')
        with c1:
            a, b = st.columns([0.18, 1], vertical_alignment='center')
            a.markdown(LOGO, unsafe_allow_html=True)
            if b.button('디딤돌', key='tb_home', type='tertiary', help='자료 DB'):
                st.session_state['goto'] = DOCS
                st.rerun()
        with c2:
            _, nav = st.columns([1.6, 1])
            nav.segmented_control('메뉴', NAV, key='top_nav', label_visibility='collapsed',
                                  on_change=lambda: st.session_state.update(nav=st.session_state['top_nav'] or st.session_state['nav']))


if 'goto' in st.session_state:
    st.session_state['nav'] = st.session_state.pop('goto')
if st.session_state.get('nav') not in NAV:
    st.session_state['nav'] = DOCS
st.session_state.setdefault('db_view', DB_VIEWS[0])
page = st.session_state['nav']
top_bar(page)
{DOCS: page_db, REPORT: page_report}[page]()
