"""추가 모의문서와 A01 추출 결과 예시를 만든다.
- sample/extra: 누리마루지구 현안·추진상태·향후계획·시행주체 문서 7개 + candidates_extra.csv
- sample/other: 다른 가상 지구(한빛·솔내) 문서 8개 + candidates_other.csv (통합 비교용)
모두 합성 데이터이며 실제 사업·기관·인물과 무관하다. 문서 본문과 후보 CSV를 같은 데이터에서 만들어 서로 어긋나지 않게 한다.
실행(개발용, 앱 실행에는 필요 없음):  pip install fpdf2  →  python tools/make_extra_samples.py"""
import csv
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from agents.a04_draft import draft  # noqa: E402  (한글 문서는 보고서 서식 생성기를 재사용)
from common import llm  # noqa: E402

CFG = llm.load_config()

OUT = BASE / 'sample' / 'extra'
FONT = Path('C:/Windows/Fonts/malgun.ttf')

GA, DA, RAIL, HUB, BUS = '가온방면 연결도로', '다온방면 도로확장', '누리마루선(광역철도)', '환승센터', '입주 초기 버스 지원'

# 문서마다: 메타, 후보(시설, 항목, 값, 위치), 본문 구성
DOCS = [
    dict(doc_id='E01', file='260415 가온시 광역교통개선대책(안) 협의의견 회신.pdf', date='2026-04-15', stage='협의결과', version_kind='',
         title='누리마루지구 광역교통개선대책(안) 협의의견 회신', org='가온시 도시교통과',
         facts=[(GA, '추진상태', '협의 지연(가온시 노선 반대)', '1쪽 2항'),
                (GA, '현안', '가온시가 중앙로 상가 밀집 구간 통과 노선에 반대하고 우회 대안노선 검토를 요구함', '1쪽 2항'),
                (GA, '향후계획', '사업시행자가 우회 대안노선을 검토해 가온시와 재협의', '1쪽 3항')],
         body=[('h', '1. 관련'), ('t', 'A도 광역교통과-1234(2026.03.20.) 「누리마루지구 광역교통개선대책(안) 의견 조회」'),
               ('h', '2. 협의의견'),
               ('t', '가. (가온방면 연결도로) 가온시는 중앙로 상가 밀집 구간을 통과하는 현재 노선에 반대합니다. '
                     '상가 진출입과 보행 안전 문제로 우회 대안노선 검토를 요구합니다.'),
               ('t', '나. 그 밖의 시설(다온방면 도로확장, 환승센터)은 별도 의견 없음.'),
               ('h', '3. 요청사항'), ('t', '사업시행자는 우회 대안노선을 검토하여 가온시와 재협의하여 주시기 바랍니다.'),
               ('t', '구분: 관계기관 협의의견 회신 (협의결과)')]),
    dict(doc_id='E02', file='260702 누리마루 광역교통 노선별 현안 점검회의 결과보고.hwpx', date='2026-07-02', stage='보고', version_kind='',
         title='누리마루 광역교통 노선별 현안 점검회의 결과보고', org='누리마루사업단 광역교통팀',
         facts=[(GA, '추진상태', '협의 지연(가온시 노선 반대)', '현안 (가온방면)'),
                (GA, '향후계획', '우회 대안노선 2개안 비교 후 가온시와 재협의', '향후계획 (가온방면)'),
                (DA, '추진상태', '실시설계 착수 준비', '현안 (다온방면)'),
                (DA, '현안', '확장 구간 내 상수도관 이설 협의 필요', '현안 (다온방면)'),
                (DA, '향후계획', '8월 중 다온시 협의 완료 후 실시설계 발주', '향후계획 (다온방면)'),
                (RAIL, '추진상태', '기본계획 반영 협의 중', '현안 (철도)'),
                (RAIL, '현안', '가온시가 개통 시기 단축을 요구하나 기본계획 반영 기간에 따라 단축 여부가 달라짐', '현안 (철도)'),
                (RAIL, '향후계획', '제20차 실무협의체에서 노선분담과 개통 목표 확정', '향후계획 (철도)'),
                (HUB, '추진상태', '부지 협의 중', '현안 (환승센터)'),
                (HUB, '현안', '환승센터 부지 일부가 학교용지와 겹쳐 교육청 협의 필요', '현안 (환승센터)'),
                (HUB, '향후계획', '교육청과 부지 조정 협의', '향후계획 (환승센터)'),
                (BUS, '추진상태', '운영방식 검토 중', '현안 (대중교통)'),
                (BUS, '현안', '입주 초기 버스 운송사업자 선정 방식(공모 또는 협약)이 정해지지 않음', '현안 (대중교통)'),
                (BUS, '향후계획', '운영방식 결정 후 A도와 협약', '향후계획 (대중교통)')],
         body='bullets'),
    dict(doc_id='E03', file='260818 다온시 도로확장 실시설계 협의결과 통보.pdf', date='2026-08-18', stage='협의결과', version_kind='',
         title='다온방면 도로확장 실시설계 협의결과 통보', org='다온시 도로과',
         facts=[(DA, '추진상태', '실시설계 착수', '1쪽 2항'),
                (DA, '현안', '다온시가 실시설계 착수에 동의함. 상수도관 이설은 다온시 상하수도사업소와 별도 협의', '1쪽 2항'),
                (DA, '향후계획', '11월 실시설계 용역 발주', '1쪽 3항')],
         body=[('h', '1. 관련'), ('t', '누리마루사업단-567(2026.08.04.) 「다온방면 도로확장 실시설계 착수 협의」'),
               ('h', '2. 협의결과'),
               ('t', '다온시는 다온방면 도로확장(연장 0.8km, 4차로) 실시설계 착수에 동의합니다.'),
               ('t', '확장 구간 내 상수도관 이설은 다온시 상하수도사업소와 별도 협의하여 주시기 바랍니다.'),
               ('h', '3. 향후 일정'), ('t', '사업시행자는 11월 실시설계 용역을 발주할 계획임을 알려 왔습니다.'),
               ('t', '구분: 협의결과 통보 (협의결과)')]),
    dict(doc_id='E04', file='260925 가온시 광역교통 TF 회의결과.docx', date='2026-09-25', stage='협의결과', version_kind='',
         title='가온시 광역교통 현안 대응 TF 회의결과', org='가온시 도시교통과',
         facts=[(GA, '추진상태', '대안노선 조건부 합의', '2. 결정사항 1'),
                (GA, '현안', '가온시가 우회 대안노선을 조건부로 수용함. 노선 변경에 따른 증가 사업비 분담 협의 필요', '2. 결정사항 1'),
                (GA, '향후계획', '증가 사업비 분담안 마련 후 11월 A도·가온시·사업시행자 3자 협의', '3. 향후계획'),
                (RAIL, '현안', '가온시 개통 시기 단축 요구 지속. 제20차 실무협의체 결과 문서 간 개통 목표 불일치로 확인 필요', '2. 결정사항 2')],
         body=[('h', '1. 회의 개요'), ('t', '일시: 2026.09.25.(금) 14:00, 장소: 가온시청 소회의실'),
               ('t', '참석: 가온시 도시교통과, A도 광역교통과, 누리마루사업단'),
               ('h', '2. 결정사항'),
               ('t', '1) (가온방면 연결도로) 가온시는 우회 대안노선을 조건부로 수용한다. '
                     '단, 노선 변경에 따른 증가 사업비 분담은 별도 협의한다.'),
               ('t', '2) (누리마루선) 가온시는 개통 시기 단축 요구를 유지한다. 제20차 실무협의체 결과 문서 간 개통 목표가 '
                     '서로 달라(붙임 2031.12, 알림 공문 2032.6) 사실 확인이 필요하다.'),
               ('h', '3. 향후계획'), ('t', '증가 사업비 분담안 마련 후 11월 A도·가온시·사업시행자 3자 협의'),
               ('t', '구분: 회의결과 (협의결과)')]),
    dict(doc_id='E05', file='261015 누리마루 광역교통 현안 보고(초안).docx', date='2026-10-15', stage='초안', version_kind='',
         title='누리마루 광역교통 현안 보고(초안)', org='누리마루사업단 광역교통팀',
         facts=[(GA, '추진상태', '협의 지연(가온시 노선 반대)', '1. 노선별 현안'),
                (GA, '현안', '가온시가 중앙로 상가 밀집 구간 통과 노선에 반대하고 우회 대안노선 검토를 요구함', '1. 노선별 현안'),
                (HUB, '추진상태', '부지 협의 중', '1. 노선별 현안'),
                (BUS, '추진상태', '운영방식 검토 중', '1. 노선별 현안')],
         body=[('h', '1. 노선별 현안 (초안, 9월 이전 자료 기준)'),
               ('t', 'ㅇ (가온방면 연결도로) 협의 지연(가온시 노선 반대): 가온시가 중앙로 상가 밀집 구간 통과 노선에 반대하고 '
                     '우회 대안노선 검토를 요구함'),
               ('t', 'ㅇ (환승센터) 부지 협의 중'), ('t', 'ㅇ (입주 초기 버스 지원) 운영방식 검토 중'),
               ('t', '※ 9.25. 가온시 TF 결과 미반영 초안'), ('t', '구분: 보고 (초안)')]),
    dict(doc_id='E06', file='261020 환승센터 교육청 협의 메모.txt', date='2026-10-20', stage='비공식', version_kind='',
         title='', org='',
         facts=[(HUB, '현안', '교육청 담당자 구두 의견으로는 학교용지 조정이 어려워 환승센터 부지 축소 검토가 필요할 수 있음', '2행')],
         body=['[메모 - 비공식, 확인 안 됨] 2026.10.20 교육청 통화',
               '- 교육청 담당자 구두 의견으로는 학교용지 조정이 어려워 환승센터 부지 축소 검토가 필요할 수 있음',
               '- 공식 회신 오기 전까지는 보고서에 쓰지 말 것']),
    dict(doc_id='E07', file='261028 누리마루 노선별 현안 관리대장.xlsx', date='2026-10-28', stage='보고', version_kind='',
         title='누리마루 광역교통 노선별 현안 관리대장', org='누리마루사업단 광역교통팀',
         facts=[(GA, '추진상태', '대안노선 조건부 합의', '관리대장 3행'),
                (GA, '향후계획', '증가 사업비 분담안 마련 후 11월 A도·가온시·사업시행자 3자 협의', '관리대장 3행'),
                (DA, '추진상태', '실시설계 착수', '관리대장 4행'),
                (DA, '향후계획', '11월 실시설계 용역 발주', '관리대장 4행'),
                (RAIL, '추진상태', '기본계획 반영 협의 중', '관리대장 5행'),
                (RAIL, '향후계획', '개통 목표 확인 후 기본계획 반영 요청', '관리대장 5행'),
                (HUB, '추진상태', '교육청 협의 중', '관리대장 6행'),
                (HUB, '현안', '학교용지 중첩 구간 조정안을 교육청에 제출(10.27.)하고 회신 대기', '관리대장 6행'),
                (HUB, '향후계획', '교육청 회신 후 부지 조정안 확정', '관리대장 6행'),
                (BUS, '추진상태', '운영방식 검토 중', '관리대장 7행'),
                (BUS, '현안', '운송사업자 공모 방식으로 가닥, A도와 협약 필요', '관리대장 7행'),
                (BUS, '향후계획', '12월 운송사업자 공모 공고', '관리대장 7행')],
         body='table'),
]

# 누리마루 관리대장(E07)에 사업별 시행주체 추가 (지자체 시행 사례 비교용)
next(d for d in DOCS if d['doc_id'] == 'E07')['facts'] += [
    (GA, '시행주체', '가온시', ''), (DA, '시행주체', '사업시행자(LH)', ''), (RAIL, '시행주체', 'A도', ''),
    (HUB, '시행주체', '사업시행자(LH)', ''), (BUS, '시행주체', 'A도', '')]

# ---------- 다른 가상 지구 (통합 비교용) ----------
HB_IC, HB_SS, HB_RAIL, HB_BRT, HB_PARK = '한빛IC 연결도로', '새솔로 확장', '한빛선 연장(광역철도)', '한빛 BRT', '한빛 환승주차장'
SN_RD, SN_HUB, SN_BUS = '솔내 연결도로', '솔내역 환승센터', '솔내 순환버스 지원'

OTHER_DOCS = [
    dict(district='한빛지구', doc_id='H01', file='260410 한빛지구 광역교통개선대책(안) 요약.pdf', date='2026-04-10', stage='보고',
         version_kind='원안', title='한빛지구 광역교통개선대책(안) 요약', org='한빛사업단 광역교통팀',
         intro='한빛 공공주택지구(약 2.1만 세대) 광역교통개선대책(안)을 아래와 같이 보고합니다.',
         facts=[(HB_IC, '연장', '1.4'), (HB_IC, '차로', '4'), (HB_IC, '사업비', '350'), (HB_IC, '완료시기', '2030.12'),
                (HB_SS, '연장', '3.2'), (HB_SS, '차로', '6'), (HB_SS, '사업비', '1100'), (HB_SS, '완료시기', '2031.12'),
                (HB_RAIL, '연장', '8.6'), (HB_RAIL, '사업비', '9200'), (HB_RAIL, '개통목표', '2033.6'),
                (HB_BRT, '연장', '6.0'), (HB_BRT, '사업비', '640'), (HB_BRT, '완료시기', '2031.12'),
                (HB_PARK, '규모', '8500'), (HB_PARK, '사업비', '150'), (HB_PARK, '완료시기', '2031.6')]),
    dict(district='한빛지구', doc_id='H02', file='260630 한빛지구 광역교통개선대책 관계기관 협의결과 통보.pdf', date='2026-06-30',
         stage='협의결과', version_kind='', title='한빛지구 광역교통개선대책 관계기관 협의결과 통보', org='B도 광역교통과',
         intro='관계기관 협의 결과 사업비와 시행주체를 아래와 같이 정합니다.',
         facts=[(HB_IC, '사업비', '380'), (HB_IC, '시행주체', '한빛시'),
                (HB_SS, '사업비', '1250'), (HB_SS, '시행주체', '사업시행자(LH)'),
                (HB_RAIL, '사업비', '9800'), (HB_RAIL, '개통목표', '2033.12'), (HB_RAIL, '시행주체', '국가철도공단'),
                (HB_BRT, '시행주체', 'B도'), (HB_PARK, '시행주체', '한빛시')]),
    dict(district='한빛지구', doc_id='H03', file='260912 한빛 광역교통 현안 점검 결과보고.hwpx', date='2026-09-12', stage='보고',
         version_kind='', title='한빛 광역교통 현안 점검 결과보고', org='한빛사업단 광역교통팀', intro='', body=None,
         facts=[(HB_IC, '추진상태', '보상 착수 준비'), (HB_IC, '현안', '한빛시 시행으로 확정, 편입 토지 보상 일정 협의 필요'),
                (HB_IC, '향후계획', '10월 보상계획 공고'),
                (HB_SS, '추진상태', '협의 지연(주민 반대)'),
                (HB_SS, '현안', '인접 아파트 주민이 소음·분진을 이유로 6차로 확장에 반대하고 방음시설 보강을 요구'),
                (HB_SS, '향후계획', '방음터널 설치안 검토 후 주민설명회 재개최'),
                (HB_RAIL, '추진상태', '예타 재조사 중'),
                (HB_RAIL, '현안', '사업비 증가(9,200억원→9,800억원)로 예비타당성 재조사 대상, 개통 지연 우려'),
                (HB_RAIL, '향후계획', '재조사 결과 반영 후 기본계획 수립'),
                (HB_BRT, '추진상태', '기본설계 중'), (HB_BRT, '현안', 'B도가 시행하나 정류장 위치를 두고 한빛시와 이견'),
                (HB_BRT, '향후계획', '정류장 위치 조정안 B도·한빛시 협의'),
                (HB_PARK, '추진상태', '부지 확보 완료'), (HB_PARK, '향후계획', '2027년 착공')]),
    dict(district='한빛지구', doc_id='H04', file='261005 한빛시 IC 연결도로 협의결과.docx', date='2026-10-05', stage='협의결과',
         version_kind='', title='한빛IC 연결도로 시행 협의결과', org='한빛시 도로과',
         intro='한빛IC 연결도로 시행 방식에 대한 협의 결과입니다.',
         facts=[(HB_IC, '추진상태', '보상 착수'),
                (HB_IC, '현안', '한빛시가 직접 시행하며 사업비 380억원 중 사업시행자 부담분은 협약으로 정산'),
                (HB_IC, '향후계획', '11월 보상 착수, 2027년 상반기 착공')]),
    dict(district='한빛지구', doc_id='H05', file='261021 한빛지구 사업별 관리카드.xlsx', date='2026-10-21', stage='보고',
         version_kind='', title='한빛지구 미완료 개선대책사업 관리카드', org='한빛사업단 광역교통팀', intro='',
         facts=[(HB_IC, '사업비', '380'), (HB_IC, '완료시기', '2030.12'),
                (HB_SS, '사업비', '1250'), (HB_SS, '완료시기', '2032.6'), (HB_SS, '추진상태', '협의 지연(주민 반대)'),
                (HB_RAIL, '사업비', '9800'), (HB_RAIL, '개통목표', '2033.12'),
                (HB_BRT, '사업비', '640'), (HB_BRT, '추진상태', '기본설계 중'),
                (HB_PARK, '사업비', '150'), (HB_PARK, '추진상태', '부지 확보 완료')]),
    dict(district='솔내지구', doc_id='S01', file='260520 솔내지구 광역교통개선대책(안) 요약.pdf', date='2026-05-20', stage='보고',
         version_kind='원안', title='솔내지구 광역교통개선대책(안) 요약', org='솔내사업단 광역교통팀',
         intro='솔내 공공주택지구(약 0.9만 세대) 광역교통개선대책(안)입니다.',
         facts=[(SN_RD, '연장', '2.6'), (SN_RD, '차로', '4'), (SN_RD, '사업비', '720'), (SN_RD, '완료시기', '2031.6'),
                (SN_RD, '시행주체', '솔내시'),
                (SN_HUB, '규모', '6000'), (SN_HUB, '사업비', '180'), (SN_HUB, '완료시기', '2031.12'),
                (SN_HUB, '시행주체', '사업시행자(LH)'),
                (SN_BUS, '지원액', '60'), (SN_BUS, '시행주체', 'C도')]),
    dict(district='솔내지구', doc_id='S02', file='260915 솔내시 광역교통개선대책 협의의견 회신.pdf', date='2026-09-15',
         stage='협의결과', version_kind='', title='솔내지구 광역교통개선대책(안) 협의의견 회신', org='솔내시 교통정책과',
         intro='솔내시 협의의견을 아래와 같이 회신합니다.',
         facts=[(SN_RD, '추진상태', '협의 지연(솔내시 사업비 증액 요구)'),
                (SN_RD, '현안', '솔내시가 연결도로 사업비를 720억원에서 950억원으로 증액해 줄 것을 요구, 사업시행자는 수용 곤란 입장'),
                (SN_RD, '향후계획', 'C도 중재로 사업비 조정 협의'),
                (SN_HUB, '현안', '역사 출입구 연계 동선을 두고 철도 운영사와 협의 필요')]),
    dict(district='솔내지구', doc_id='S03', file='261012 솔내지구 사업별 관리카드.xlsx', date='2026-10-12', stage='보고',
         version_kind='', title='솔내지구 미완료 개선대책사업 관리카드', org='솔내사업단 광역교통팀', intro='',
         facts=[(SN_RD, '사업비', '720'), (SN_RD, '추진상태', '협의 지연(솔내시 사업비 증액 요구)'),
                (SN_RD, '향후계획', 'C도 중재로 사업비 조정 협의'),
                (SN_HUB, '사업비', '180'), (SN_HUB, '추진상태', '설계 중'), (SN_HUB, '향후계획', '철도 운영사 협의 후 실시설계'),
                (SN_BUS, '지원액', '60'), (SN_BUS, '추진상태', '운영방식 검토 중'), (SN_BUS, '향후계획', '2027년 운행 개시 목표')]),
]
TEXT_ITEMS = ('시행주체', '추진상태', '현안', '향후계획')


def unit_of(item):
    for tpl in CFG['item_templates'].values():
        for it in tpl:
            if it['item'] == item:
                return it.get('unit') or ''
    return ''


def show(item, val):
    return f'{item} {val}' if item in TEXT_ITEMS else f"{item} {draft.fmt_value(val, unit_of(item))}"


def grouped(doc):
    by = {}
    for f in doc['facts']:
        by.setdefault(f[0], {})[f[1]] = f[2]
    return by


def auto_body(doc):
    """다른 지구 문서 본문: 사업별 한 줄씩(값이 후보 CSV와 같도록 같은 데이터에서 만든다)."""
    body = [('t', doc['intro'])] if doc.get('intro') else []
    body.append(('h', '1. 사업별 내용'))
    for i, (fac, v) in enumerate(grouped(doc).items()):
        body.append(('t', f"{'가나다라마바사'[i]}. ({fac}) " + ', '.join(show(k, x) for k, x in v.items())))
    body.append(('t', f"구분: {doc['stage']}"))
    return body


def make_pdf(doc, path):
    from fpdf import FPDF
    pdf = FPDF(format='A4')
    pdf.add_page()
    pdf.add_font('malgun', '', str(FONT))
    pdf.set_font('malgun', size=16)
    pdf.multi_cell(0, 10, doc['title'], align='C', new_x='LMARGIN', new_y='NEXT')
    pdf.set_font('malgun', size=10)
    pdf.multi_cell(0, 7, f"{doc['org']}   {doc['date'].replace('-', '.')}.", align='R', new_x='LMARGIN', new_y='NEXT')
    pdf.ln(3)
    for kind, text in doc['body']:
        pdf.set_font('malgun', size=12 if kind == 'h' else 11)
        pdf.multi_cell(0, 8 if kind == 'h' else 7, text, new_x='LMARGIN', new_y='NEXT')
        pdf.ln(1)
    pdf.output(str(path))


def make_docx(doc, path):
    import docx
    from docx.oxml.ns import qn
    from docx.shared import Pt
    d = docx.Document()
    st = d.styles['Normal']
    st.font.name = '맑은 고딕'
    st.element.rPr.rFonts.set(qn('w:eastAsia'), '맑은 고딕')
    d.add_paragraph().add_run(doc['title']).bold = True
    d.paragraphs[0].runs[0].font.size = Pt(15)
    d.add_paragraph(f"<’{doc['date'][2:4]}.{doc['date'][5:7]}.{doc['date'][8:10]}. {doc['org']}>")
    for kind, text in doc['body']:
        p = d.add_paragraph()
        r = p.add_run(text)
        r.bold = kind == 'h'
    d.save(path)


def make_hwpx(doc, path):
    blocks = [('title', doc['title'], doc['org']),
              ('date', f"<’{doc['date'][2:4]}.{doc['date'][5:7]}.{doc['date'][8:10]}. {doc['org']}>")]
    g = grouped(doc)
    blocks.append(('h', '□ 노선별 현안'))
    for fac, v in g.items():
        if '추진상태' in v or '현안' in v:
            blocks.append(('b', fac, v.get('추진상태', '')))
            if '현안' in v:
                blocks.append(('s', v['현안']))
    blocks.append(('h', '□ 향후계획'))
    for fac, v in g.items():
        if '향후계획' in v:
            blocks.append(('b', fac, v['향후계획']))
    blocks.append(('note', '※ 구분: 회의 결과보고 (보고)'))
    Path(path).write_bytes(draft.to_hwpx(blocks))


def make_xlsx(doc, path):
    """관리대장·관리카드: 사업마다 한 행, 열은 그 문서에 있는 항목들. 위치(시트·행)는 후보 CSV에 그대로 쓴다."""
    import openpyxl
    from openpyxl.styles import Font
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = '관리대장'
    ws.append([f"※ {doc['title']} ({doc['date'].replace('-', '.')} 기준, 보고 단계)"])
    g = grouped(doc)
    cols = list(dict.fromkeys(k for v in g.values() for k in v))
    ws.append(['사업명'] + [f'{c}({unit_of(c)})' if unit_of(c) else c for c in cols])
    for c in ws[2]:
        c.font = Font(bold=True)
    rows = {}
    for r, (fac, v) in enumerate(g.items(), 3):
        ws.append([fac] + [v.get(c, '-') for c in cols])
        rows[fac] = f'관리대장 {r}행'
    for col, w in zip('ABCDEFGHI', (24, 22, 22, 50, 50, 20, 20, 20, 20)):
        ws.column_dimensions[col].width = w
    wb.save(path)
    return rows


def make_txt(doc, path):
    Path(path).write_text('\n'.join(doc['body']) + '\n', encoding='utf-8')


def write(docs, out, csv_name):
    out.mkdir(parents=True, exist_ok=True)
    makers = {'.pdf': make_pdf, '.docx': make_docx, '.hwpx': make_hwpx, '.xlsx': make_xlsx, '.txt': make_txt}
    rows = []
    for doc in docs:
        if not doc.get('body') or doc['body'] in ('auto', 'table', 'bullets'):
            doc['body'] = auto_body(doc) if doc.get('district') else doc.get('body')
        path = out / doc['file']
        locs = makers[path.suffix](doc, path) or {}
        for f in doc['facts']:
            fac, item, val = f[:3]
            loc = locs.get(fac) or (f[3] if len(f) > 3 and f[3] else ('1쪽 1항' if path.suffix == '.pdf' else '본문'))
            rows.append(dict(district=doc.get('district', '누리마루지구'), doc_id=doc['doc_id'], file=doc['file'],
                             date=doc['date'], stage=doc['stage'], version_kind=doc['version_kind'], facility=fac,
                             item=item, value=val, unit=unit_of(item), location=loc))
        print('만듦:', path.name)
    with open(out / csv_name, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f'후보 {len(rows)}건 → {csv_name}')


def main():
    write(DOCS, OUT, 'candidates_extra.csv')
    write(OTHER_DOCS, BASE / 'sample' / 'other', 'candidates_other.csv')


if __name__ == '__main__':
    main()
