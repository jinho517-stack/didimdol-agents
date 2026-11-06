"""값 표기(여러 agent가 같이 쓰는 공통 함수)."""
import re


def fmt_value(v, unit=''):
    if v is None:
        return '미확정'
    s = str(v)
    if re.fullmatch(r'\d{4,}', s):
        s = f'{int(s):,}'
    return f'{s}{unit or ""}'


def short_date(d):
    """2026-10-06 → ’26. 10. 6. (회사 보고서 표기: 년·월·일 글자 대신 온점)"""
    m = re.fullmatch(r'20(\d\d)-(\d\d)-(\d\d)', d or '')
    return f'’{m.group(1)}. {int(m.group(2))}. {int(m.group(3))}.' if m else (d or '')
