# 08. 도구 레퍼런스

Quetta Agents MCP가 제공하는 모든 도구의 상세 파라미터.

## 🎯 스마트 디스패처

### `quetta_auto`
자연어 요청을 자동 분류해 적절한 도구로 라우팅.

| 파라미터 | 타입 | 기본 | 설명 |
|---------|------|------|------|
| `request` | string | — | 자연어 요청 (필수) |
| `agent_id` | string | `""` | (GPU/remote 의도 시) |
| `file_path` | string | `""` | (file/paper/blueprint 의도 시) |
| `dry_run` | bool | `false` | 실행 없이 분류만 |

---

## 🧠 LLM 게이트웨이

### `quetta_ask`
| 파라미터 | 타입 | 기본 | 설명 |
|---------|------|------|------|
| `query` | string | — | 질문 (필수) |
| `model` | string | `"auto"` | `auto`/`gemma4`/`claude`/`claude-opus` |
| `system_prompt` | string | `""` | 커스텀 시스템 프롬프트 |

### `quetta_code`
| 파라미터 | 타입 | 기본 | 설명 |
|---------|------|------|------|
| `task` | string | — | 코딩 작업 설명 (필수) |
| `language` | string | `""` | 프로그래밍 언어 |
| `context` | string | `""` | 관련 코드 |

### `quetta_medical`
| 파라미터 | 타입 | 기본 | 설명 |
|---------|------|------|------|
| `query` | string | — | 의료 질문 (필수) |
| `domain` | string | `"auto"` | `auto`/`imaging`/`clinical`/`pharmacy` |

### `quetta_multi_agent`
| 파라미터 | 타입 | 기본 | 설명 |
|---------|------|------|------|
| `task` | string | — | 복잡 태스크 (필수) |

### `quetta_routing_info`
| 파라미터 | 타입 | 기본 | 설명 |
|---------|------|------|------|
| `query` | string | — | 라우팅 예측할 질문 |

### `quetta_list_agents`
파라미터 없음 — 등록된 에이전트 목록.

### `quetta_run_agent`
| 파라미터 | 타입 | 기본 | 설명 |
|---------|------|------|------|
| `agent_name` | string | — | 에이전트 이름 |
| `task` | string | — | 위임할 태스크 |

---

## 💻 원격 제어

### `quetta_remote_connect`
| 파라미터 | 타입 | 기본 | 설명 |
|---------|------|------|------|
| `action` | enum | `"list"` | `list`/`install-link` |
| `os` | enum | `"linux"` | `linux`/`windows`/`mac` |

### `quetta_remote_screenshot`
| 파라미터 | 타입 | 기본 | 설명 |
|---------|------|------|------|
| `agent_id` | string | `""` | (미지정 시 자동) |
| `max_width` | int | `1280` | 리사이즈 최대폭 |

### `quetta_remote_click`
| 파라미터 | 타입 | 기본 | 설명 |
|---------|------|------|------|
| `agent_id` | string | `""` | |
| `x` | int | — | 필수 |
| `y` | int | — | 필수 |
| `button` | enum | `"left"` | `left`/`right`/`middle` |
| `double` | bool | `false` | 더블클릭 |

### `quetta_remote_type`
| 파라미터 | 타입 | 기본 | 설명 |
|---------|------|------|------|
| `agent_id` | string | `""` | |
| `text` | string | — | 입력할 텍스트 (필수) |
| `interval` | float | `0.03` | 글자 간 지연(sec) |

### `quetta_remote_key`
| 파라미터 | 타입 | 기본 | 설명 |
|---------|------|------|------|
| `agent_id` | string | `""` | |
| `key` | string | — | e.g. `ctrl+c`, `alt+tab` |

### `quetta_remote_shell`
| 파라미터 | 타입 | 기본 | 설명 |
|---------|------|------|------|
| `agent_id` | string | `""` | |
| `command` | string | — | 필수 |
| `timeout` | int | `30` | 초 |
| `cwd` | string | `""` | 작업 디렉토리 |
| `prefer_gpu` | bool | `false` | GPU 에이전트 강제 |

---

## 🚀 GPU 자동 라우팅

### `quetta_gpu_exec`
| 파라미터 | 타입 | 기본 | 설명 |
|---------|------|------|------|
| `command` | string | — | 필수 |
| `agent_id` | string | `""` | (미지정 시 GPU 자동) |
| `timeout` | int | `300` | |
| `cwd` | string | `""` | |

### `quetta_gpu_python`
| 파라미터 | 타입 | 기본 | 설명 |
|---------|------|------|------|
| `code` | string | — | Python 코드 (필수) |
| `agent_id` | string | `""` | |
| `timeout` | int | `300` | |
| `python` | string | `"python"` | 실행 파일 |

### `quetta_gpu_status`
파라미터 없음 — 모든 GPU 에이전트 `nvidia-smi` 요약.

---

## 📑 논문 분석

### `quetta_analyze_paper`
| 파라미터 | 타입 | 기본 | 설명 |
|---------|------|------|------|
| `file_path` | string | `""` | 로컬 PDF |
| `file_id` | string | `""` | TUS file_id |
| `query` | string | `""` | 초점 |
| `agent_id` | string | `""` | GPU 에이전트 |
| `install_nougat` | bool | `true` | 자동 설치 |
| `skip_gemini` | bool | `false` | |
| `skip_claude` | bool | `false` | |
| `ingest_to_rag` | bool | `true` | RAG 저장 |
| `tags` | array | `[]` | |

### `quetta_paper_query`
| 파라미터 | 타입 | 기본 | 설명 |
|---------|------|------|------|
| `query` | string | `""` | |
| `filename` | string | `""` | 특정 논문만 |
| `list` | bool | `false` | 목록 모드 |
| `top_k` | int | `8` | |

---

## 📐 설계도 분석

### `quetta_analyze_blueprint`
| 파라미터 | 타입 | 기본 | 설명 |
|---------|------|------|------|
| `file_path` | string | `""` | PDF/PNG/JPG |
| `file_id` | string | `""` | |
| `drawing_type` | enum | `"auto"` | `mechanical`/`electrical`/`cpld`/`auto` |
| `query` | string | `""` | |
| `tags` | array | `[]` | |
| `ingest_to_rag` | bool | `true` | |
| `skip_gemini` | bool | `false` | |

### `quetta_blueprint_query`
| 파라미터 | 타입 | 기본 | 설명 |
|---------|------|------|------|
| `query` | string | `""` | |
| `filename` | string | `""` | |
| `drawing_type` | string | `""` | 필터 |
| `list` | bool | `false` | |
| `top_k` | int | `8` | |

---

## 📁 파일 업로드 & 분석

### `quetta_analyze_file`
| 파라미터 | 타입 | 기본 | 설명 |
|---------|------|------|------|
| `file_path` | string | `""` | |
| `content` | string | `""` | 텍스트 직접 |
| `filename` | string | `"upload.txt"` | |
| `query` | string | `""` | |
| `source` | string | `""` | RAG 소스 태그 |
| `tags` | array | `[]` | |

### `quetta_upload_file`
| 파라미터 | 타입 | 기본 | 설명 |
|---------|------|------|------|
| `file_path` | string | `""` | |
| `content` | string | `""` | |
| `filename` | string | `"upload.txt"` | |

### `quetta_upload_list`
파라미터 없음.

### `quetta_upload_process`
| 파라미터 | 타입 | 기본 | 설명 |
|---------|------|------|------|
| `file_id` | string | — | 필수 |
| `usage_type` | string | `"measurement_data"` | |
| `source` | string | `""` | |
| `tags` | array | `[]` | |
| `chunk_size` | int | `4000` | |

### `quetta_upload_process_all`
파라미터 없음.

---

## 🔧 버전 관리

### `quetta_version`
파라미터 없음 — 현재 버전 + GitHub 최신 커밋.

### `quetta_update`
파라미터 없음 — GitHub 최신으로 자동 업데이트.

---

## 반환 타입

대부분 도구는 `TextContent` 배열 반환. 예외:
- `quetta_remote_screenshot`: `[ImageContent, TextContent]` — Claude가 이미지 직접 분석
- `quetta_analyze_paper` / `quetta_analyze_blueprint`: 마크다운 리포트 (접을 수 있는 `<details>` 포함)

## 에러 핸들링

- GPU 에이전트 없음: 설치 링크 포함한 에러
- TUS 업로드 실패: 네트워크 에러 메시지
- RAG 인제스트 실패: 경고만 표시, 분석 결과는 유지
- WebSocket 타임아웃: 자동 재시도 (3회)
