# dist/

빌드 산출물 디렉토리.

| 파일 | 설명 |
|------|------|
| `quetta-agents-mcp-docs.pdf` | 전체 사용자 매뉴얼 PDF (외부 배포용) |
| `quetta-agents-mcp-docs.html` | 단일 HTML (PDF 생성 중간본) |

## 재생성

```bash
# markdown 라이브러리 + Chromium 필요
sudo apt install python3-markdown python3-pygments google-chrome-stable

python3 scripts/build-docs-pdf.py
```

PDF는 `docs/` 디렉토리의 모든 `.md` 문서를 자동으로 병합합니다.
