# LogosAI 표준 프로토콜 샘플 — MCP · A2A 양방향

LogosAI ACP는 환경변수 옵션만으로 **MCP(Model Context Protocol)** 와 **A2A(Agent2Agent)** 표준을
양방향으로 제공한다. 이 폴더는 그 두 방향을 실행 가능한 최소 예제로 보여준다.

```
┌── 표준 노출 (Expose) ──────────────────────────────────────────┐
│  외부 MCP/A2A 클라이언트  →  ACP(/mcp, /a2a)  →  86+ 에이전트   │
│  예제: mcp_client_sample.py · a2a_client_sample.py            │
└────────────────────────────────────────────────────────────────┘
┌── 표준 소비 (Consume) ─────────────────────────────────────────┐
│  ACP  →  [Driver 자동전환]  →  외부 MCP 서버 · 외부 A2A 에이전트 │
│  예제: mcp_server_sample.py · a2a_server_sample.py (외부 역할)  │
│  선언: external_endpoints.sample.json (설정 1항목 = 편입 완료)  │
└────────────────────────────────────────────────────────────────┘
```

핵심: **호출자는 프로토콜을 모른다.** 외부 시스템이 편입되면 로컬 에이전트와 완전히
동일한 문법(`agent_id` + 자연어)으로 호출되고, MCP `tools/call`이냐 A2A `message/send`냐는
Driver가 자동으로 전환한다. 외부 시스템이 N개여도 통합 코드는 0줄이다.

## 파일 구성

| 파일 | 방향 | 설명 |
|------|:---:|------|
| `mcp_server_sample.py` | Consume 상대역 | 외부 MCP 서버 예제 (:8901). 도구 2개 — `add`(a,b), `get_grid_forecast`(nx,ny 필수 → **되묻기 데모용**) |
| `a2a_server_sample.py` | Consume 상대역 | 외부 A2A 에이전트 예제 (:8902). AgentCard + message/send — "파트너사 요약 에이전트" 역할 |
| `external_endpoints.sample.json` | Consume 선언 | 위 두 서버를 ACP 가상 에이전트(`sample_tools`, `partner_summary`)로 편입하는 선언 |
| `mcp_client_sample.py` | Expose | ACP의 `/mcp`를 소비하는 표준 MCP 클라이언트 (initialize→tools/list→tools/call, 직접 지정+자동 라우팅) |
| `a2a_client_sample.py` | Expose | ACP의 agent-card discovery + message/send + tasks/get + **되묻기 continuation** |
| `acp_integration_demo.py` | 통합 | 전 과정 데모 — 샘플 서버 기동 → ACP 편입 확인 → Consume 2종 + 되묻기 + Expose 시연 |
| `sdk_export_sample.py` | SDK (P8) | **ACP 불필요** — 에이전트가 `to_mcp_tool()`/`to_a2a_skill()`로 자기 자신을 표준 스키마로 파생 (SDK 단독 배포용) |
| `standard-protocols-guide.html` | 문서 | PPT형 슬라이드 — 아키텍처·개념·데모 흐름 설명 (브라우저로 열기, ←/→ 키 탐색) |

## 빠른 시작

### 1) 통합 데모 (권장 — 전 과정 한 번에)

```bash
# 터미널 1 — ACP를 표준 flag + 샘플 편입 선언으로 기동 (데모 전용 포트 8899)
cd <repo>/acp_server
ACP_ENABLE_MCP=true ACP_ENABLE_A2A=true ACP_ENABLE_EXTERNAL=true \
  ACP_EXTERNAL_CONFIG=<repo>/logosai/samples/standard_protocols/external_endpoints.sample.json \
  python standalone_acp_server.py --port 8899 --enable-auto-agent-selection

# 터미널 2 — 샘플 외부 서버 2개 기동 (ACP 기동 유예 내에 discovery됨)
cd <repo>/logosai/samples/standard_protocols
PORT=8901 python mcp_server_sample.py &
PORT=8902 python a2a_server_sample.py &

# 터미널 3 — 데모 실행
ACP_URL=http://localhost:8899 python acp_integration_demo.py
```

기대 출력 (2026-07-02 검증):
```
[Consume] query → sample_tools → [McpDriver] → tools/call
  응답: 3 + 5 = 8
[Consume] query → partner_summary → [A2aDriver] → message/send
  응답: [요약] LogosAI는 멀티에이전트 오케스트레이션 시스템으로 … (원문 12단어)
[되묻기] 1차 → input-required, 질문 필드 [(nx, number), (ny, number)]
  답 전달({nx:60, ny:127}) → completed — "격자(60,127) 예보: 맑음, 26.5°C"
[Expose] agent-card skills 119개 — 편입된 외부 시스템도 skill로 노출
```

### 2) SDK 단독 표준 파생 (ACP 불필요)

```bash
python sdk_export_sample.py
# → agent.to_mcp_tool() / agent.to_a2a_skill() 결과 출력
#   (self.config + self._tools 에서 파생 — 선언 없이 코드와 항상 일치)
```

### 3) Expose 방향만 (실행 중인 ACP 대상)

```bash
ACP_URL=http://localhost:8888 python mcp_client_sample.py   # ACP_ENABLE_MCP=true 필요
ACP_URL=http://localhost:8888 python a2a_client_sample.py   # ACP_ENABLE_A2A=true 필요
```

### 4) Claude Code에서 ACP 사용 (가장 짧은 Expose 데모)

```bash
claude mcp add --transport http logosai http://localhost:8888/mcp
# 이후 Claude Code 대화에서 acp_query 도구로 86+ 에이전트 사용
```

## 되묻기(Ask-and-Retry) — 이 샘플이 보여주는 핵심 패턴

외부 도구의 필수 인자(`get_grid_forecast`의 nx/ny)를 자연어에서 알 수 없으면,
시스템은 **값을 지어내지 않고** A2A 표준 `input-required` 태스크로 **구조화된 질문**을 되돌려준다:

```json
{"status": {"state": "input-required", "message": "필수 파라미터 누락: nx, ny"},
 "inputRequest": {"fields": [
   {"id": "nx", "label": "격자 X좌표", "type": "number", "required": true},
   {"id": "ny", "label": "격자 Y좌표", "type": "number", "required": true}]}}
```

**같은 taskId**로 답(data part `{"nx":60,"ny":127}`)을 보내면 보존된 컨텍스트와 병합해 이어서 실행된다.
LLM 시스템의 고질병인 "그럴듯한 날조"를 아키텍처 수준에서 차단하는 장치다.

## 요구 사항

- Python 3.10+ / `aiohttp`
- ACP 서버 (acp_server) — 표준 어댑터는 `acp_modules/standard_adapters/`에 구현
- 샘플 자체는 **HTTP 프로토콜만 사용** — acp_server 내부 코드를 import하지 않는다

## 관련 문서

- 사용 가이드(산출물): `docs/MCP_A2A_USAGE_GUIDE.md` — 옵션 전체·트러블슈팅·검증 이력
- 설계: `docs/MCP_A2A_INTEGRATION_DESIGN.md` · 아키텍처(ADR D1~D16): `docs/MCP_A2A_ARCHITECTURE.md`
- 전체 아키텍처 프레젠테이션: `docs/logosai-mcp-a2a-architecture.html`
