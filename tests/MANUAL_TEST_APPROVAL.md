# SSE Bidirectional (Human-in-the-Loop) — 수동 테스트 절차서

## 사전 조건

| 서비스 | 포트 | 시작 스크립트 |
|--------|------|-------------|
| ACP Server | 8888 | `./logosai/scripts/start.sh` |
| logos_api | 8090 | `./logos_api/scripts/start.sh` |
| logos_web | 8010 | `./logos_web/scripts/start.sh` |

## 테스트 1: 카카오톡 메시지 전송 승인

1. logos_web (http://localhost:8010) 접속
2. "홍길동에게 카카오톡으로 '내일 회의 참석 부탁드립니다' 보내줘" 입력
3. **기대**: 스트리밍 로그에 `🔐 Approval required: 카카오톡 메시지를...` 표시
4. **기대**: ApprovalDialog 팝업 (recipient, message 미리보기)
5. Approve 클릭 → 카카오톡 전송 실행
6. Reject 클릭 → "사용자가 카카오톡 메시지 전송을 취소했습니다" 응답

## 테스트 2: 이메일 전송 승인

1. "maiordba@gmail.com에게 주간 보고서 이메일 보내줘" 입력
2. **기대**: ApprovalDialog — to, subject, preview 표시
3. Approve → 이메일 전송
4. 타임아웃(30초) 무응답 → 자동 취소

## 테스트 3: 일정 삭제 승인

1. "내일 팀 미팅 삭제해줘" 입력
2. **기대**: ApprovalDialog — title, event_id 표시
3. Reject → "사용자가 일정 삭제를 취소했습니다"

## 테스트 4: 타이머 바 확인

1. 아무 승인 요청 트리거
2. **기대**: 다이얼로그 하단 보라색 타이머 바가 줄어듦
3. **기대**: 우측 상단 카운트다운 숫자 표시

## 검증 체크리스트

- [ ] ApprovalDialog 표시됨
- [ ] 타이머 바 동작
- [ ] Approve 클릭 → 에이전트 계속 실행
- [ ] Reject 클릭 → 취소 메시지 반환
- [ ] 타임아웃 → 자동 취소
- [ ] 스트리밍 로그에 승인 요청 표시
- [ ] 다이얼로그 닫힌 후 스트리밍 계속 진행

## cURL로 직접 확인

```bash
# Pending 확인
curl http://localhost:8090/api/v1/approval/pending

# 승인 (request_id는 pending 결과에서 확인)
curl -X POST http://localhost:8090/api/v1/approval/{request_id} \
  -H "Content-Type: application/json" \
  -d '{"approved": true}'

# 거부
curl -X POST http://localhost:8090/api/v1/approval/{request_id} \
  -H "Content-Type: application/json" \
  -d '{"approved": false}'

# 취소
curl -X POST http://localhost:8090/api/v1/approval/{request_id}/cancel
```
