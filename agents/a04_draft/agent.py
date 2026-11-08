"""A04 보고서 초안 작성 Agent  (Agent정의서_4_보고서초안작성)

시작 조건  담당자가 보고서 양식(보고 유형·목차·회사 양식)을 고르고 A03의 자료표가 준비되었을 때
입력      A03 자료표 + 보고서 양식(목차·필수 항목, 회사 양식 HWPX/DOCX) + 수정 의견(직접 입력 줄)
출력      보고서 초안(한글 hwpx·워드 docx·화면 미리보기) + 자동 점검 결과
사람 개입  담당자 최종 검토(필수). 고칠 점이 있으면 목차·직접 입력 줄을 고쳐 "다시 만들기"(같은 agent가 다시 씀).

수행 단계
 ① 양식의 목차와 필수 항목을 파악한다        draft.PRESETS / SECTIONS, 회사 양식은 lh_style.FORMS
 ② 자료표 값을 목차 위치에 배치한다          draft.build
 ③ 문장을 쓴다: 자료표에 없는 수치는 쓰지 않고 미확정은 "확인 필요"로 그대로 쓴다
    (AI는 키가 있을 때 '종합 의견' 문장을 쓴다)
 ③-2 보고서 작성 스킬(skills/lh_report_style/SKILL.md) 적용: 서식 숫자는 표·본문에, 문장 규칙은 AI 문장 다듬기에   polish
    (AI가 고친 줄은 숫자·'확인 필요' 표시가 그대로인지 줄마다 검사하고, 어긋나면 원래 문장을 쓴다)
 ④ 자동 점검: 수치가 자료표·DB와 맞는지, 값마다 출처가 있는지, 고른 목차가 다 있는지, 미확정이 표시됐는지   check
 ⑤ 초안을 저장(내려받기)하고 담당자 검토를 요청한다      layout → hwpx / docx / html
 ⑥ 반려되면 수정 의견을 반영해 ②부터 다시 쓴다
"""
import re

from agents.a04_draft import draft, hwpx_forms, lh_style
from agents.a04_draft import polish as _polish
from agents.a04_draft import skill

NAME = 'A04 보고서 초안 작성'
PRESETS, SECTIONS, SECTION_HELP, FORMS, FORM_HELP = draft.PRESETS, draft.SECTIONS, draft.SECTION_HELP, lh_style.FORMS, lh_style.FORM_HELP
NUM_UNIT = re.compile(r'(?<![\d.])(\d[\d,]*(?:\.\d+)?)\s*(억원|km|차로|㎡)')


def run(a03, cands, sources, choices, title='', district='', dept='', sections=None, extra=None,
        use_llm=False, cfg=None, order=None, kinds=None, show_basis=False, events=None, report_date=None):
    """①~③ A03 자료표(a03['facts'])로 보고서 블록(제목·□·ㅇ·- …)을 만든다. 반환: 블록 목록"""
    return draft.build(a03['facts'], cands, sources, choices, title, district, dept, sections, extra,
                       use_llm, cfg, order=order, kinds=kinds, show_basis=show_basis, events=events, report_date=report_date)


def polish(blocks, cfg=None):
    """③-2 보고서 작성 스킬의 문장 규칙으로 AI가 문장을 다듬는다. 반환: (블록, 결과{'skill','changed','kept','total','seconds','error'})"""
    return _polish.run(blocks, cfg)


# ---------- ④ 자동 점검 ----------
def _n(s):
    s = str(s).replace(',', '')
    try:
        x = float(s)
    except ValueError:
        return None
    return f'{x:g}'


def check(blocks, a03, cands=(), sections=(), events=()):
    """④ 초안 자동 점검. 반환: [{'점검', '결과'('통과'|'확인 필요'), '설명'}]"""
    text = draft.to_text(blocks)
    facs = {f['facility'] for f in a03['facts']}
    out = []

    # 1) 수치 대조: 초안의 '숫자+단위'가 자료표·문서 이력 값(또는 그 합계)에 있는지
    allowed = {}
    for v, u in [(f['value'], f['unit']) for f in a03['facts']] + \
                [(c['value'], c['unit']) for c in cands if c['facility'] in facs]:
        if v is None:
            continue
        if _n(v) is not None:  # 수치 항목(사업비·연장 …)
            allowed.setdefault(u or '', set()).add(_n(v))
        elif re.fullmatch(r'[\d.]+\s*→\s*[\d.]+', str(v)):  # 확장 차로 '4→6': 앞뒤 숫자 모두 허용
            for x in re.findall(r'[\d.]+', str(v)):
                allowed.setdefault(u or '', set()).add(_n(x))
        else:  # 문장 항목(현안 등) 안에 적힌 수치: 문서에 있던 숫자이므로 허용
            for m in NUM_UNIT.finditer(str(v)):
                allowed.setdefault(m.group(2), set()).add(_n(m.group(1)))
    for e in events:  # 추진경위·향후 일정 문장 안의 수치도 문서에 있던 숫자
        for m in NUM_UNIT.finditer(e['content']):
            allowed.setdefault(m.group(2), set()).add(_n(m.group(1)))
    totals = {}  # 합계(예: '사업비 합계'): 같은 항목·단위끼리 더한 값
    for f in a03['facts']:
        if f['status'] != '참고' and f['value'] is not None and _n(f['value']) is not None:
            totals[(f['item'], f['unit'] or '')] = totals.get((f['item'], f['unit'] or ''), 0) + float(f['value'])
            totals[('*', f['unit'] or '')] = totals.get(('*', f['unit'] or ''), 0) + float(f['value'])
    for (_, u), tot in totals.items():
        allowed.setdefault(u, set()).add(f'{tot:g}')
    bad = sorted({f'{m.group(1)}{m.group(2)}' for m in NUM_UNIT.finditer(text)
                  if _n(m.group(1)) not in allowed.get(m.group(2), set())})
    out.append({'점검': '수치 대조', '결과': '확인 필요' if bad else '통과',
                '설명': ('자료표·문서에서 찾지 못한 수치: ' + ', '.join(bad[:8])) if bad
                else f'초안의 수치 {len(NUM_UNIT.findall(text))}개가 모두 자료표·문서 값과 일치'})

    # 2) 출처: 쓰인 값마다 근거 문서가 있는지
    nosrc = [f"{f['facility']} {f['item']}" for f in a03['facts']
             if f['value'] is not None and f['status'] != '참고' and not f['source_doc']]
    out.append({'점검': '출처', '결과': '확인 필요' if nosrc else '통과',
                '설명': ('출처 없는 값: ' + ', '.join(nosrc[:8])) if nosrc else '모든 값에 근거 문서(문서ID·위치)가 있음 · 엑셀 자료표에 함께 기록'})

    # 3) 필수 항목: 고른 목차가 모두 들어갔는지
    heads = {b[1] for b in blocks if b[0] == 'h'}
    labels = {re.sub(r'^붙임\s*\d+\s*', '', h) for h in heads}
    miss = [s for s in sections if draft.HEADINGS.get(s, f'□ {s}') not in heads
            and not s.startswith('붙임:')]  # 붙임은 문서에 내용이 있을 때만 붙음
    out.append({'점검': '필수 항목(목차)', '결과': '확인 필요' if miss else '통과',
                '설명': ('빠진 목차: ' + ', '.join(miss)) if miss else f'고른 목차 {len(sections)}개 모두 있음'})

    # 4) 미확정 표시: 부족·미확정 항목이 초안에 '확인 필요'로 드러나는지
    lack = a03['lacking']
    shown = not lack or ('확인 필요' in text or '미확정' in text)
    out.append({'점검': '미확정 표시', '결과': '통과' if shown else '확인 필요',
                '설명': '미확정 항목 없음' if not lack else
                (f"미확정 {len(lack)}건을 '확인 필요'로 표시" if shown else f"미확정 {len(lack)}건이 초안에 드러나지 않음")})

    # 5) 꼭지 길이(스킬 담당자 원칙 2): 두 줄(약 80자)을 넘는 꼭지가 없고, 한 줄 반 이하 꼭지가 많지 않은지
    w = skill.load()['settings']['writing']
    lens = []
    for b in blocks:
        if b[0] not in ('b', 's', 'act') or (b[0] == 'b' and not b[2]):
            continue
        t = draft.line(b).strip()
        if re.match(r'^[ㅇ\-⇒]\s*\(’', t):  # 날짜로 시작하는 경위·일정 줄은 나열이라 빼고 셈
            continue
        lens.append((len(t), t.count(',') >= 2))
    long_ = sum(n > w['max_chars'] for n, _ in lens)
    short = sum(n < w['min_chars'] and not listing for n, listing in lens)
    out.append({'점검': '꼭지 길이', '결과': '확인 필요' if long_ else '통과',
                '설명': f"꼭지 {len(lens)}개 중 두 줄({w['max_chars']}자) 넘는 꼭지 {long_}개, "
                        f"한 줄 반({w['min_chars']}자) 이하 {short}개" + (' — AI 문장 다듬기나 직접 고치기로 줄이세요' if long_ else '')})
    return out


# ---------- ⑤ 회사 양식 적용·파일 만들기 ----------
class Layout:
    """고른 회사 양식으로 초안을 꾸미고 한글·워드·화면용으로 내보낸다."""

    def __init__(self, blocks, form, facts, district='', dept='', kinds=None, form_path=None):
        """form_path: 화면에서 올린 회사 한글 양식 파일(그 접속 동안만). 없으면 templates/company/ 를 찾는다."""
        self.blocks, self.form, self.form_path = blocks, form, form_path
        self.kind = FORMS[form][0]
        if self.kind == 'press':  # 보도자료: 사업 DB 값으로 따로 구성
            meta = next((b[1] for b in blocks if b[0] == 'meta'), {})
            self.styled = lh_style.press_release(blocks, facts, district, meta.get('dept') or dept, kinds)
            self.title = next(b[1] for b in self.styled if b[0] == 'ptitle')
            self.hwpx_blocks = lh_style.to_basic(self.styled)
        elif self.kind != 'basic':
            self.styled = lh_style.restyle(blocks, form)
            self.title, self.hwpx_blocks = next(b[1] for b in blocks if b[0] == 'title'), blocks
        else:
            self.styled, self.title, self.hwpx_blocks = None, next(b[1] for b in blocks if b[0] == 'title'), blocks
        # 회사 한글 서식 파일(올린 파일 또는 templates/company/)이 있으면 그 서식에 그대로 채운다
        self.use_form = self.styled is not None and hwpx_forms.available(form, form_path)

    def hwpx(self):
        return hwpx_forms.render(self.styled, self.form, self.form_path) if self.use_form else draft.to_hwpx(self.hwpx_blocks)

    def docx(self):
        return lh_style.to_docx(self.styled, self.form) if self.styled else draft.to_docx(self.blocks)

    def html(self):
        return lh_style.to_html(self.styled, self.form) if self.styled else draft.to_html(self.blocks)

    def preview_docx(self):
        """미리보기(PDF)용 워드: 한글본과 같은 모양으로. 회사 양식이 없어 한글본이 기본 서식이면 워드도 기본 서식."""
        return self.docx() if self.use_form else draft.to_docx(self.hwpx_blocks)
