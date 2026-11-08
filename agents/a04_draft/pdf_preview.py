"""초안 미리보기: 내려받는 파일 그대로를 PDF로 바꿔 쪽 그림으로 보여 준다(화면용 HTML과 따로 놀지 않게).

변환기 순서
 1) LibreOffice + H2Orestart 확장이 있으면 → 한글(hwpx) 파일 자체를 PDF로(저장 파일과 같은 내용·서식)
 2) LibreOffice만 있으면 → 같은 블록으로 만든 워드(docx)를 PDF로(글꼴은 나눔 글꼴로 대신할 수 있음)
 3) 둘 다 없으면 None → 화면에서 HTML 미리보기로 대신한다
클라우드(Streamlit Community Cloud)는 packages.txt의 libreoffice-writer·fonts-nanum으로 2)가 된다.
"""
import os
import shutil
import subprocess
import sys
import tempfile
from io import BytesIO
from pathlib import Path

CANDIDATES = ['soffice', 'libreoffice', r'C:\Program Files\LibreOffice\program\soffice.exe',
              r'C:\Program Files (x86)\LibreOffice\program\soffice.exe', '/usr/bin/soffice', '/usr/lib/libreoffice/program/soffice']
# 회사 양식 글꼴이 없는 리눅스(클라우드)에서 비슷한 나눔 글꼴로 대신 그린다
FONT_ALIAS = {'휴먼명조': 'NanumMyeongjo', 'HY헤드라인M': 'NanumGothic', '중고딕': 'NanumGothic', '한양중고딕': 'NanumGothic',
              '맑은 고딕': 'NanumGothic', 'Malgun Gothic': 'NanumGothic', '바탕': 'NanumMyeongjo', '돋움': 'NanumGothic'}
PROFILE = Path(tempfile.gettempdir()) / 'didimdol_lo_profile'  # LibreOffice 사용자 설정(쓰기 가능한 곳)


def soffice():
    for c in CANDIDATES:
        p = shutil.which(c) or (c if Path(c).exists() else None)
        if p:
            return p
    return None


def _env():
    env = dict(os.environ)
    if sys.platform.startswith('linux'):
        conf = Path(tempfile.gettempdir()) / 'didimdol_fonts.conf'
        if not conf.exists():
            alias = ''.join(f'<alias binding="same"><family>{a}</family><prefer><family>{b}</family></prefer></alias>'
                            for a, b in FONT_ALIAS.items())
            conf.write_text('<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "fonts.dtd"><fontconfig>'
                            '<include ignore_missing="yes">/etc/fonts/fonts.conf</include>' + alias + '</fontconfig>',
                            encoding='utf-8')
        env['FONTCONFIG_FILE'] = str(conf)
        env.setdefault('HOME', tempfile.gettempdir())
    return env


def hwpx_ready(exe=None):
    """H2Orestart(한글 문서 가져오기 확장)가 LibreOffice에 설치돼 있는지. 없으면 hwpx를 글자 파일로 잘못 열 수 있어 쓰지 않는다."""
    exe = exe or soffice()
    if not exe:
        return False
    unopkg = Path(exe).with_name('unopkg.exe' if exe.lower().endswith('.exe') else 'unopkg')
    if not unopkg.exists():
        unopkg = shutil.which('unopkg')
    if not unopkg:
        return False
    for extra in ([f'-env:UserInstallation={PROFILE.as_uri()}'], ['--shared']):
        try:
            r = subprocess.run([str(unopkg), 'list', *extra], capture_output=True, text=True, timeout=60, env=_env())
            if 'h2orestart' in (r.stdout + r.stderr).lower():
                return True
        except Exception:
            pass
    return False


def to_pdf(data, ext, timeout=150):
    """파일 바이트(docx·hwpx) → PDF 바이트. 변환기가 없거나 실패하면 None."""
    exe = soffice()
    if not exe:
        return None
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / f'report{ext}'
        src.write_bytes(data)
        cmd = [exe, f'-env:UserInstallation={PROFILE.as_uri()}', '--headless', '--norestore', '--nolockcheck',
               '--convert-to', 'pdf', '--outdir', d, str(src)]
        try:
            subprocess.run(cmd, capture_output=True, timeout=timeout, env=_env())
        except Exception:
            return None
        out = Path(d) / 'report.pdf'
        return out.read_bytes() if out.exists() and out.stat().st_size > 0 else None


def pages(pdf, scale=1.6):
    """PDF → 쪽마다 PNG 바이트(pypdfium2: pdfplumber와 함께 설치됨)."""
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(pdf)
    out = []
    try:
        for i in range(len(doc)):
            buf = BytesIO()
            doc[i].render(scale=scale).to_pil().save(buf, 'PNG')
            out.append(buf.getvalue())
    finally:
        doc.close()
    return out


def preview(hwpx, docx):
    """반환: (PDF 바이트, 쪽 PNG 목록, 무엇을 변환했는지) — 변환기가 없으면 (None, [], '')"""
    exe = soffice()
    if not exe:
        return None, [], ''
    if hwpx and hwpx_ready(exe):
        pdf = to_pdf(hwpx, '.hwpx')
        if pdf:
            return pdf, pages(pdf), 'hwpx'
    pdf = to_pdf(docx, '.docx')
    return (pdf, pages(pdf), 'docx') if pdf else (None, [], '')
