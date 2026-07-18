"""Desktop Native Artifact Demo — PowerPoint를 직접 제어하여 PPT 생성.

AI가 PowerPoint를 실행하고, 사람처럼 슬라이드를 하나씩 만듭니다.
사용자는 실시간으로 만들어지는 과정을 볼 수 있습니다.

Usage:
    python samples/desktop_native_artifact_demo.py

macOS + Microsoft PowerPoint 필요.
"""

import asyncio
import subprocess
import time


def applescript(script: str) -> str:
    """AppleScript 실행."""
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=10,
        )
        return result.stdout.strip()
    except Exception as e:
        print(f"  AppleScript error: {e}")
        return ""


async def demo_powerpoint_native():
    """PowerPoint를 직접 제어하여 프레젠테이션 생성 데모."""

    print("=" * 60)
    print("  Desktop Native Artifact Demo")
    print("  PowerPoint를 직접 제어하여 PPT를 생성합니다")
    print("=" * 60)
    print()

    # ── Step 1: PowerPoint 실행 ──
    print("[Step 1] PowerPoint 실행...")
    subprocess.run(["open", "-a", "Microsoft PowerPoint"], timeout=5)
    await asyncio.sleep(3)
    applescript('tell application "Microsoft PowerPoint" to activate')
    await asyncio.sleep(2)
    print("  → PowerPoint 활성화 완료")
    print()

    # ── Step 2: 새 프레젠테이션 생성 ──
    print("[Step 2] 새 프레젠테이션 생성...")
    applescript('''
        tell application "Microsoft PowerPoint"
            set newPres to make new presentation
        end tell
    ''')
    await asyncio.sleep(2)
    print("  → 빈 프레젠테이션 생성 완료")
    print()

    # ── Step 3: 제목 슬라이드 작성 ──
    print("[Step 3] 슬라이드 1 — 제목 작성...")
    applescript('''
        tell application "Microsoft PowerPoint"
            tell active presentation
                tell slide 1
                    set content of text range of text frame of shape 1 to "SpaceX"
                    set content of text range of text frame of shape 2 to "우주 산업의 혁신 — 2026"
                end tell
            end tell
        end tell
    ''')
    await asyncio.sleep(1.5)
    print("  → 제목: 'SpaceX'")
    print("  → 부제목: '우주 산업의 혁신 — 2026'")
    print()

    # ── Step 4: 두 번째 슬라이드 추가 ──
    print("[Step 4] 슬라이드 2 — 회사 개요...")
    applescript('''
        tell application "Microsoft PowerPoint"
            tell active presentation
                set newSlide to make new slide at after slide 1
                tell newSlide
                    set content of text range of text frame of shape 1 to "회사 개요"
                    set content of text range of text frame of shape 2 to "• 2002년 일론 머스크 설립
• 본사: 미국 캘리포니아 호손
• 직원 수: 13,000명+
• 핵심 미션: 인류의 다행성 종족화
• 주요 성과: 재사용 로켓 세계 최초 상용화"
                end tell
            end tell
        end tell
    ''')
    await asyncio.sleep(1.5)
    print("  → 제목: '회사 개요'")
    print("  → 내용: 5개 불릿 포인트")
    print()

    # ── Step 5: 세 번째 슬라이드 ──
    print("[Step 5] 슬라이드 3 — 주요 로켓...")
    applescript('''
        tell application "Microsoft PowerPoint"
            tell active presentation
                set newSlide to make new slide at after slide 2
                tell newSlide
                    set content of text range of text frame of shape 1 to "주요 로켓 라인업"
                    set content of text range of text frame of shape 2 to "• Falcon 9 — 재사용 중형 로켓 (290+ 성공 발사)
• Falcon Heavy — 현존 최강 운용 로켓
• Starship — 차세대 초대형 (화성 탐사용)
• Dragon — 유인 우주선 (NASA ISS 수송)"
                end tell
            end tell
        end tell
    ''')
    await asyncio.sleep(1.5)
    print("  → 제목: '주요 로켓 라인업'")
    print("  → 내용: 4개 로켓 소개")
    print()

    # ── Step 6: 네 번째 슬라이드 ──
    print("[Step 6] 슬라이드 4 — Starlink...")
    applescript('''
        tell application "Microsoft PowerPoint"
            tell active presentation
                set newSlide to make new slide at after slide 3
                tell newSlide
                    set content of text range of text frame of shape 1 to "Starlink — 위성 인터넷"
                    set content of text range of text frame of shape 2 to "• 7,000+ 위성 운용 중 (세계 최대 위성 군)
• 100+ 국가 서비스
• 다운로드 속도: 50~200 Mbps
• 지연 시간: 20~40ms
• 매출: 연 $6.6B+ (2025 추정)"
                end tell
            end tell
        end tell
    ''')
    await asyncio.sleep(1.5)
    print("  → 제목: 'Starlink — 위성 인터넷'")
    print("  → 내용: 5개 핵심 지표")
    print()

    # ── Step 7: 마지막 슬라이드 ──
    print("[Step 7] 슬라이드 5 — 전망...")
    applescript('''
        tell application "Microsoft PowerPoint"
            tell active presentation
                set newSlide to make new slide at after slide 4
                tell newSlide
                    set content of text range of text frame of shape 1 to "미래 전망"
                    set content of text range of text frame of shape 2 to "• 2026: Starship 화성 무인 비행
• 2028: Starship 유인 화성 착륙 목표
• Starlink V3: 위성 인터넷 속도 10배 향상
• 경쟁 우위: 재사용 기술로 발사 비용 90% 절감
• IPO 가능성: Starlink 부문 분할 상장 검토"
                end tell
            end tell
        end tell
    ''')
    await asyncio.sleep(1.5)
    print("  → 제목: '미래 전망'")
    print("  → 내용: 5개 전망")
    print()

    # ── Step 8: 슬라이드 1로 이동 ──
    print("[Step 8] 첫 슬라이드로 이동...")
    applescript('''
        tell application "Microsoft PowerPoint"
            tell active presentation
                set view of active window to slide view
                set slide number of slide range of active window to 1
            end tell
        end tell
    ''')
    await asyncio.sleep(1)
    print("  → 슬라이드 1 표시")
    print()

    # ── 결과 ──
    slide_count = applescript('''
        tell application "Microsoft PowerPoint"
            return count of slides of active presentation
        end tell
    ''')

    print("=" * 60)
    print(f"  완료! PowerPoint에서 {slide_count}장의 슬라이드가 생성되었습니다.")
    print()
    print("  사용자는 이 과정을 실시간으로 볼 수 있습니다.")
    print("  PowerPoint에서 직접 편집, 디자인 적용이 가능합니다.")
    print()
    print("  이것은 LogosAI만 할 수 있는 Desktop Native Artifact입니다.")
    print("  Claude, ChatGPT는 웹 브라우저 안에 갇혀 있습니다.")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(demo_powerpoint_native())
