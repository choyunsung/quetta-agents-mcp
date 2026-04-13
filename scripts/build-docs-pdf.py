#!/usr/bin/env python3
"""docs/*.md → 단일 HTML → PDF 변환 (Chrome headless 사용).

사용:
    python scripts/build-docs-pdf.py
    → dist/quetta-agents-mcp-docs.pdf 생성
"""
import os, sys, subprocess, tempfile, pathlib, re

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
DIST = ROOT / "dist"
DIST.mkdir(exist_ok=True)

ORDER = [
    "README.md",
    "01-architecture.md",
    "02-llm-routing.md",
    "03-smart-dispatcher.md",
    "04-remote-agent.md",
    "05-paper-analysis.md",
    "06-blueprint-analysis.md",
    "07-upload-rag.md",
    "08-tools-reference.md",
    "09-configuration.md",
    "10-operations.md",
    "11-shared-memory.md",
    "12-install-token.md",
    "13-conversation-history.md",
    "14-workspaces.md",
    "15-auto-research-system-paper.md",
]

try:
    import markdown
except ImportError:
    print("ERROR: markdown 패키지 필요. 설치: sudo apt install python3-markdown", file=sys.stderr)
    sys.exit(1)


CSS = """
@page {
  size: A4;
  margin: 18mm 16mm;
  @top-right { content: "Quetta Agents MCP"; font-size: 9pt; color: #888; }
  @bottom-center { content: counter(page) " / " counter(pages); font-size: 9pt; color: #888; }
}
body {
  font-family: -apple-system, "Noto Sans KR", "Apple SD Gothic Neo", sans-serif;
  font-size: 10.5pt;
  line-height: 1.55;
  color: #222;
}
h1 { font-size: 22pt; border-bottom: 2px solid #111; padding-bottom: 6px; margin-top: 0; page-break-before: always; }
h1:first-of-type { page-break-before: avoid; }
h2 { font-size: 16pt; border-bottom: 1px solid #ccc; padding-bottom: 4px; margin-top: 1.5em; }
h3 { font-size: 13pt; margin-top: 1.2em; }
h4 { font-size: 11.5pt; margin-top: 1em; }
p  { margin: 0.5em 0; }
code {
  font-family: "SF Mono", Monaco, Consolas, monospace;
  font-size: 9.5pt;
  background: #f4f4f4;
  padding: 1px 5px;
  border-radius: 3px;
}
pre {
  background: #f8f8f8;
  border: 1px solid #e4e4e4;
  border-radius: 4px;
  padding: 10px 12px;
  font-size: 9pt;
  line-height: 1.4;
  overflow-x: auto;
  page-break-inside: avoid;
}
pre code { background: transparent; padding: 0; font-size: 9pt; }
table {
  border-collapse: collapse;
  margin: 0.8em 0;
  font-size: 9.5pt;
  page-break-inside: avoid;
}
th, td {
  border: 1px solid #ddd;
  padding: 6px 10px;
  text-align: left;
  vertical-align: top;
}
th { background: #f0f0f0; font-weight: 600; }
blockquote {
  border-left: 3px solid #4a90e2;
  padding: 4px 14px;
  margin: 0.5em 0;
  color: #555;
  background: #f5f9fd;
}
a { color: #2860b4; text-decoration: none; }
img { max-width: 100%; height: auto; }
hr { border: none; border-top: 1px solid #ccc; margin: 1.5em 0; }
.cover {
  page-break-after: always;
  text-align: center;
  padding-top: 18vh;
}
.cover h1 {
  font-size: 36pt;
  border: none;
  padding: 0;
  margin: 0 0 0.4em;
  page-break-before: avoid;
}
.cover .subtitle { font-size: 14pt; color: #555; margin-bottom: 3em; }
.cover .meta { font-size: 11pt; color: #777; margin-top: 4em; }
.toc ul { list-style: none; padding-left: 1.2em; }
.toc li { margin: 4px 0; }
"""


def read_version() -> str:
    """pyproject.toml 에서 버전 읽기."""
    try:
        text = (ROOT / "pyproject.toml").read_text()
        m = re.search(r'version\s*=\s*"([^"]+)"', text)
        return m.group(1) if m else "?"
    except Exception:
        return "?"


def fix_relative_links(html: str) -> str:
    """./XX-*.md 링크를 PDF 내부 앵커(#xx-...)로 변환."""
    return re.sub(r'href="\./?([0-9]{2})-([^"]+?)\.md"', r'href="#doc-\1"', html)


def md_to_html(md_text: str, doc_id: str) -> str:
    ext = ["fenced_code", "tables", "codehilite", "toc", "sane_lists"]
    md = markdown.Markdown(extensions=ext, extension_configs={
        "codehilite": {"guess_lang": False, "noclasses": True},
    })
    html = md.convert(md_text)
    # 각 문서 시작을 앵커로 감쌈
    return f'<section id="{doc_id}">\n{html}\n</section>'


def build():
    version = read_version()
    print(f"버전: {version}")

    # 문서 수집 + 병합
    bodies = []
    toc_entries = []
    for fn in ORDER:
        p = DOCS / fn
        if not p.exists():
            print(f"  skip: {fn} 없음")
            continue
        stem = p.stem  # "00-README" → doc id
        doc_id = "doc-" + (stem.split("-", 1)[0] if "-" in stem else stem)
        md_text = p.read_text(encoding="utf-8")
        # 첫 헤딩 추출 (ToC용)
        m = re.search(r"^#\s+(.+)$", md_text, re.MULTILINE)
        title = m.group(1) if m else fn
        toc_entries.append((doc_id, title))
        bodies.append(md_to_html(md_text, doc_id))
        print(f"  + {fn} ({len(md_text):,} chars)")

    # 표지 + 목차 + 본문 조립
    cover = f"""
    <div class="cover">
      <h1>Quetta Agents MCP</h1>
      <div class="subtitle">사용자 매뉴얼 &amp; 기술 개요</div>
      <p>Smart LLM Gateway + 원격 PC 제어 + 문서·설계도 분석 + RAG 지식베이스</p>
      <div class="meta">
        Version {version}<br>
        Documentation Build<br>
        <span style="font-size:9pt;">https://github.com/choyunsung/quetta-agents-mcp</span>
      </div>
    </div>
    """
    toc_html = '<section class="toc"><h1>목차</h1><ul>'
    for did, title in toc_entries:
        toc_html += f'<li><a href="#{did}">{title}</a></li>'
    toc_html += '</ul></section>'

    full_body = cover + toc_html + "\n".join(fix_relative_links(b) for b in bodies)
    html_doc = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>Quetta Agents MCP v{version}</title>
<style>{CSS}</style>
</head>
<body>
{full_body}
</body>
</html>"""

    html_path = DIST / "quetta-agents-mcp-docs.html"
    html_path.write_text(html_doc, encoding="utf-8")
    print(f"HTML: {html_path} ({len(html_doc):,} bytes)")

    # Chrome headless → PDF
    pdf_path = DIST / "quetta-agents-mcp-docs.pdf"
    chrome = next((c for c in ("google-chrome", "chromium", "chromium-browser") if subprocess.run(["which", c], capture_output=True).returncode == 0), None)
    if not chrome:
        print("ERROR: Chrome/Chromium 필요", file=sys.stderr)
        sys.exit(1)

    cmd = [
        chrome,
        "--headless", "--disable-gpu", "--no-sandbox",
        f"--print-to-pdf={pdf_path}",
        "--print-to-pdf-no-header",
        "--no-pdf-header-footer",
        "--virtual-time-budget=5000",
        f"file://{html_path}",
    ]
    print(f"Chrome 실행: {chrome}")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if not pdf_path.exists() or pdf_path.stat().st_size < 5000:
        print(f"PDF 생성 실패\n{r.stderr[:1000]}", file=sys.stderr)
        sys.exit(1)
    print(f"✅ PDF: {pdf_path} ({pdf_path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    build()
