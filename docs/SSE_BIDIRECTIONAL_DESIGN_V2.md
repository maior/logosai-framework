# SSE Bidirectional V2 — Workflow-Level Interaction Design

## 핵심 원칙

> **에이전트는 실행기, 판단은 워크플로우가 한다.**
> 사용자 인터랙션은 에이전트 호출 **전에** logos_api에서 처리.

## 아키텍처

```
┌─────────────┐        SSE (양방향)        ┌──────────┐
│  logos_web   │◄─────────────────────────►│ logos_api │
│  (Frontend)  │  question/answer/select   │ Workflow  │
│              │  checkbox/confirm          │ Engine    │
└─────────────┘                            └────┬─────┘
                                                │ 정보 수집 완료 후
                                                │ enriched query 전달
                                                ▼
                                           ┌──────────┐
                                           │   ACP    │
                                           │  Agent   │
                                           │ (실행만) │
                                           └──────────┘
```

## 플로우

### 1. 기본 플로우 (인터랙션 불필요)

```
사용자: "오늘 날씨 알려줘"
  → logos_api 쿼리 분석 → 인터랙션 불필요
  → ACP weather_agent 호출
  → 결과 반환
```

### 2. 확인 플로우 (Yes/No)

```
사용자: "내일 팀 미팅 삭제해줘"
  → logos_api 쿼리 분석 → 삭제 행위 감지 → 확인 필요
  
  ← SSE: interaction_required {
      type: "confirm",
      question: "일정 '팀 미팅'을 삭제하시겠습니까?",
      details: { title: "팀 미팅", date: "2026-04-07" }
    }
  
  → REST: /api/v1/interaction/{id} { confirmed: true }
  
  → ACP scheduler_agent.process("팀 미팅 삭제", context={confirmed: true})
  → 결과 반환
```

### 3. 선택 플로우 (1,2,3,4)

```
사용자: "번역해줘: 안녕하세요"
  → logos_api 쿼리 분석 → 대상 언어 미지정 → 선택 필요
  
  ← SSE: interaction_required {
      type: "select",
      question: "어떤 언어로 번역할까요?",
      options: [
        { id: "en", label: "영어" },
        { id: "ja", label: "일본어" },
        { id: "zh", label: "중국어" },
        { id: "fr", label: "프랑스어" }
      ]
    }
  
  → REST: /api/v1/interaction/{id} { selected: "ja" }
  
  → ACP translation_agent.process("안녕하세요", context={target_lang: "ja"})
  → 결과 반환
```

### 4. 체크박스 플로우 (다중 선택)

```
사용자: "쇼핑 에이전트로 노트북 검색해줘"
  → logos_api 쿼리 분석 → 검색 조건 세분화 가능 → 체크박스 제공
  
  ← SSE: interaction_required {
      type: "checkbox",
      question: "검색 조건을 선택해주세요",
      options: [
        { id: "price_low", label: "50만원 이하" },
        { id: "price_mid", label: "50-100만원" },
        { id: "price_high", label: "100만원 이상" },
        { id: "brand_apple", label: "Apple" },
        { id: "brand_samsung", label: "Samsung" },
        { id: "brand_lg", label: "LG" },
        { id: "lightweight", label: "경량 (1.5kg 이하)" },
        { id: "gaming", label: "게이밍" }
      ]
    }
  
  → REST: /api/v1/interaction/{id} { selected: ["price_mid", "brand_apple", "lightweight"] }
  
  → ACP shopping_agent.process("노트북", context={
      price_range: "50-100만원",
      brand: "Apple",
      features: ["경량"]
    })
```

### 5. 추가 정보 입력 플로우

```
사용자: "이메일 보내줘"
  → logos_api 쿼리 분석 → 수신자/제목/내용 부족 → 입력 필요
  
  ← SSE: interaction_required {
      type: "form",
      question: "이메일 정보를 입력해주세요",
      fields: [
        { id: "to", label: "수신자", type: "text", required: true },
        { id: "subject", label: "제목", type: "text", required: true },
        { id: "body", label: "내용", type: "textarea", required: false },
        { id: "send_now", label: "즉시 전송", type: "checkbox", default: true }
      ]
    }
  
  → REST: /api/v1/interaction/{id} {
      to: "user@example.com",
      subject: "회의록",
      body: "오늘 회의 내용 정리입니다.",
      send_now: true
    }
  
  → ACP mail_agent.process("이메일 전송", context={
      to: "user@example.com",
      subject: "회의록",
      body: "오늘 회의 내용 정리입니다."
    })
```

### 6. 멀티 스텝 인터랙션

```
사용자: "맛집 추천해줘"
  → logos_api 쿼리 분석 → 위치/종류 부족
  
  [Step 1] ← SSE: interaction_required {
      type: "select",
      question: "어떤 지역에서 찾으시나요?",
      options: ["강남", "홍대", "이태원", "종로", "직접 입력"]
    }
  → REST: { selected: "강남" }
  
  [Step 2] ← SSE: interaction_required {
      type: "checkbox",
      question: "어떤 종류의 음식을 원하시나요?",
      options: ["한식", "일식", "중식", "양식", "카페/디저트"]
    }
  → REST: { selected: ["일식", "카페/디저트"] }
  
  [Step 3] → ACP restaurant_finder_agent.process(
      "강남 맛집 추천",
      context={ location: "강남", cuisine: ["일식", "카페/디저트"] }
    )
```

## 컴포넌트 설계

### Layer 1: logos_api — InteractionEngine (새 컴포넌트)

```python
# logos_api/app/services/interaction_engine.py

class InteractionEngine:
    """쿼리 분석 후 사용자 인터랙션 필요 여부 판단 + 인터랙션 관리"""
    
    async def analyze_and_interact(
        self, query: str, context: dict
    ) -> InteractionResult:
        """
        1. LLM으로 쿼리 분석
        2. 인터랙션 필요 여부 판단
        3. 필요하면 InteractionRequest 생성
        4. 사용자 응답 대기
        5. enriched context 반환
        """
        
        # LLM 분석: 어떤 인터랙션이 필요한가?
        analysis = await self._analyze_interaction_needs(query, context)
        
        if not analysis.needs_interaction:
            return InteractionResult(query=query, context=context)
        
        # 인터랙션 요청 생성
        interaction = InteractionRequest(
            type=analysis.interaction_type,  # confirm/select/checkbox/form
            question=analysis.question,
            options=analysis.options,
            fields=analysis.fields,
        )
        
        # 대기 (SSE로 보내고 REST 응답 대기)
        response = await self._wait_for_response(interaction)
        
        # 응답을 context에 반영
        enriched = self._enrich_context(query, context, response)
        return InteractionResult(
            query=enriched.query,
            context=enriched.context,
            interaction_log=interaction,
        )
```

### Layer 2: logos_api — Workflow에 통합

```python
# orchestrator_service.py stream_with_orchestrator 수정

async def stream_with_orchestrator(self, query, ...):
    # 1. 쿼리 분석 (기존)
    yield {"event": "ontology_init", ...}
    
    # 2. ★ 인터랙션 체크 (새로운 단계)
    interaction_engine = InteractionEngine()
    result = await interaction_engine.analyze_and_interact(query, context)
    
    if result.had_interaction:
        # 인터랙션이 있었으면 enriched query로 교체
        query = result.query
        context = result.context
        yield {"event": "interaction_complete", "data": {...}}
    
    # 3. 에이전트 선택 + 실행 (기존)
    async for event in self._orchestrator.run_streaming(
        query=query, context=context
    ):
        ...
```

### Layer 3: logos_web — InteractionDialog (확장)

```typescript
// logos_web/components/InteractionDialog.tsx

interface InteractionRequest {
  id: string;
  type: 'confirm' | 'select' | 'checkbox' | 'form';
  question: string;
  options?: Array<{ id: string; label: string; description?: string }>;
  fields?: Array<{ id: string; label: string; type: string; required: boolean }>;
  details?: Record<string, any>;
  timeout: number;
}

// confirm → 간단한 Yes/No 다이얼로그
// select → 라디오 버튼 리스트
// checkbox → 체크박스 리스트
// form → 입력 폼 (텍스트, 체크박스 등)
```

### Layer 4: 에이전트 변경 — 단순화

```python
# 에이전트에서 request_approval() 제거
# 에이전트는 context에서 confirmed=True를 받으면 그냥 실행

class SchedulerAgent(LogosAIAgent):
    async def process(self, query, context=None):
        # context에 이미 확인 정보가 포함되어 있음
        # logos_api에서 사전에 사용자 확인 완료
        if context.get("confirmed"):
            await self.delete_event(...)
        # 또는 context에서 필요한 정보 추출
        target_lang = context.get("target_lang", "en")
```

## SSE 이벤트 스펙

### 서버 → 클라이언트

```json
// 인터랙션 요청
{
  "event": "interaction_required",
  "data": {
    "request_id": "int_abc123",
    "type": "confirm|select|checkbox|form",
    "question": "질문 내용",
    "options": [...],      // select/checkbox
    "fields": [...],       // form
    "details": {...},      // 추가 정보 (미리보기 등)
    "timeout": 60,
    "step": 1,             // 멀티스텝일 때 현재 단계
    "total_steps": 2       // 멀티스텝일 때 전체 단계
  }
}
```

### 클라이언트 → 서버

```
POST /api/v1/interaction/{request_id}
{
  "response": "ja"                    // select: 선택한 ID
  "response": ["opt1", "opt3"]        // checkbox: 선택한 ID 리스트
  "response": true                    // confirm: yes/no
  "response": {                       // form: 필드별 값
    "to": "user@example.com",
    "subject": "제목"
  }
}
```

## 구현 순서

| 순서 | 작업 | 설명 |
|------|------|------|
| 1 | InteractionEngine 설계 + 테스트 | LLM 분석 + 인터랙션 결정 로직 |
| 2 | logos_api SSE + REST 엔드포인트 | interaction_required SSE + 응답 REST |
| 3 | logos_web InteractionDialog | confirm/select/checkbox/form UI |
| 4 | orchestrator 통합 | stream_with_orchestrator에 인터랙션 단계 삽입 |
| 5 | 에이전트 단순화 | request_approval 제거, context 기반 처리 |
| 6 | 테스트 + 평가 | E2E 검증 |

## V1 vs V2 비교

| 항목 | V1 (에이전트 내 승인) | V2 (워크플로우 사전 인터랙션) |
|------|---------------------|--------------------------|
| 인터랙션 위치 | 에이전트 내부 | logos_api 워크플로우 |
| SSE 체인 | ACP→logos_api→frontend (데드락) | logos_api↔frontend (직접) |
| 에이전트 복잡도 | 승인 로직 포함 | 실행만 |
| 인터랙션 다양성 | Yes/No만 | confirm/select/checkbox/form |
| 멀티스텝 | 어려움 | 자연스러움 |
| 데드락 | 있음 | 없음 |
| 테스트 용이성 | 어려움 (SSE 체인 필요) | 쉬움 (logos_api 단독) |
