"""[Expose 방향] LogosAI ACP를 'A2A 에이전트'로 소비하는 표준 클라이언트 예제.

외부 조직의 에이전트가 이 시퀀스로 LogosAI와 협업한다:
  ① AgentCard discovery → ② message/send(Task) → ③ tasks/get
  ④ 되묻기: input-required → 같은 taskId로 continuation

사전 조건: ACP가 A2A flag로 실행 중이어야 함
  ACP_ENABLE_A2A=true ./acp_server/scripts/start.sh

실행:  ACP_URL=http://localhost:8888 python a2a_client_sample.py
"""

import asyncio
import json
import os

import aiohttp

ACP_URL = os.getenv("ACP_URL", "http://localhost:8888")


def text_of(task: dict) -> str:
    for artifact in task.get("artifacts", []):
        for part in artifact.get("parts", []):
            if part.get("kind") == "text":
                return part.get("text", "")
    return ""


async def rpc(session, method: str, params: dict, req_id=1):
    body = {"jsonrpc": "2.0", "method": method, "id": req_id, "params": params}
    async with session.post(f"{ACP_URL}/a2a", json=body) as resp:
        data = await resp.json()
    if "error" in data:
        raise RuntimeError(f"{method} → {data['error']}")
    return data["result"]


def message(text: str, skill_id: str = "", task_id: str = "", data: dict | None = None) -> dict:
    parts = []
    if text:
        parts.append({"kind": "text", "text": text})
    if data:
        parts.append({"kind": "data", "data": data})
    msg = {"role": "user", "kind": "message", "messageId": "m1", "parts": parts}
    if task_id:
        msg["taskId"] = task_id
    params = {"message": msg}
    if skill_id:
        params["metadata"] = {"skillId": skill_id}
    return params


async def main():
    async with aiohttp.ClientSession() as session:
        # ① Discovery — 카드 하나로 상대 에이전트의 능력 전부를 파악
        async with session.get(f"{ACP_URL}/.well-known/agent-card.json") as resp:
            card = await resp.json()
        print(f"① AgentCard   → {card['name']} (skills {len(card['skills'])}개, "
              f"streaming={card['capabilities']['streaming']})")
        sample = card["skills"][0]
        print(f"   skill 예시: {sample['id']} — {sample['name']}")

        # ② message/send — skillId 지정 실행
        task = await rpc(session, "message/send",
                         message("120 나누기 8은?", skill_id="math_agent"))
        print(f"② message/send → Task {task['status']['state']}")
        print(f"   {text_of(task)[:80].strip()}...")

        # ③ tasks/get — 태스크 조회 (TTL 내)
        got = await rpc(session, "tasks/get", {"id": task["id"]}, req_id=2)
        print(f"③ tasks/get   → state={got['status']['state']} (id 일치: {got['id'] == task['id']})")

        # ④ 되묻기(ask-and-retry) — 외부 도구의 필수 인자가 부족하면
        #    시스템은 값을 지어내지 않고 input-required로 질문을 되돌려준다.
        #    (southbound 가상 에이전트가 편입된 ACP에서 동작 — 예: sample_tools)
        if any(s["id"] == "sample_tools" for s in card["skills"]):
            ask = await rpc(session, "message/send",
                            message("격자 예보 알려줘", skill_id="sample_tools"), req_id=3)
            print(f"④ 되묻기      → state={ask['status']['state']}")
            if ask["status"]["state"] == "input-required":
                fields = ask.get("inputRequest", {}).get("fields", [])
                print(f"   질문 필드: {[(f['id'], f['type']) for f in fields]}")
                # 같은 taskId로 답을 보내 이어간다 (data part 권장)
                done = await rpc(session, "message/send",
                                 message("", task_id=ask["id"], data={"nx": 60, "ny": 127}),
                                 req_id=4)
                print(f"   continuation → state={done['status']['state']}")
                print(f"   {text_of(done)}")
        else:
            print("④ 되묻기 데모 생략 — southbound 편입(sample_tools)이 없는 ACP입니다. "
                  "acp_integration_demo.py 참조.")


if __name__ == "__main__":
    asyncio.run(main())
