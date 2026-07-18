"""PPT Live Demo — PowerPoint에서 실시간으로 전문가 슬라이드 구축.

AI가 PowerPoint를 열고, 도형과 텍스트를 하나씩 배치하며,
전문가 수준의 슬라이드가 만들어지는 과정을 실시간으로 보여줍니다.

영상 촬영용: 각 도형 사이에 딜레이가 있어 과정이 잘 보입니다.

Usage:
    python samples/ppt_live_demo.py          # 영상 촬영용 (약 70초)
    python samples/ppt_live_demo.py --fast   # 빠른 테스트 (약 40초)

macOS + Microsoft PowerPoint 필요.
"""

import subprocess
import sys
import time

# ── 설정 ──
FAST = "--fast" in sys.argv
D = 0.12 if FAST else 0.35       # 도형 간 기본 딜레이
D_SMALL = 0.05 if FAST else 0.15 # 작은 부속 도형
D_STEP = 0.3 if FAST else 0.7    # 단계 전환
D_SLIDE = 0.5 if FAST else 1.5   # 슬라이드 전환


def asc(script: str) -> str:
    try:
        r = subprocess.run(["osascript", "-e", script],
                           capture_output=True, text=True, timeout=15)
        return r.stdout.strip()
    except Exception:
        return ""


def shape(slide, left, top, width, height,
          fill=None, shape_type=1, text=None, font_size=12,
          font_color=None, bold=False,
          line_color=None, line_weight=1, no_line=True,
          delay=None):
    """도형 생성. fill 필수 — 투명이 필요하면 부모 배경색을 전달."""

    lines = [
        'tell application "Microsoft PowerPoint"',
        f'    tell slide {slide} of active presentation',
        '        set s to make new shape at end',
        f'        set auto shape type of s to {shape_type}',
        f'        set left position of s to {left}',
        f'        set top of s to {top}',
        f'        set width of s to {width}',
        f'        set height of s to {height}',
    ]

    # Fill — 항상 설정 (투명 대신 부모 배경색 사용)
    if fill:
        r, g, b = fill
        lines.append(f'        set fore color of fill format of s to {{{r}, {g}, {b}}}')
    else:
        # fill 미지정 = 슬라이드 배경(흰색)
        lines.append(f'        set fore color of fill format of s to {{255, 255, 255}}')

    # Line — transparency 1.0이 유일한 제거 방법 (weight 0은 라인 남음)
    if no_line:
        lines.append(f'        set transparency of line format of s to 1.0')
    elif line_color:
        r, g, b = line_color
        lines.append(f'        set fore color of line format of s to {{{r}, {g}, {b}}}')
        lines.append(f'        set weight of line format of s to {line_weight}')

    # Text — tell s 블록 안에서 of it 접근
    if text is not None:
        escaped = text.replace('"', '\\"')
        parts = escaped.split('\\n')
        text_expr = (' & return & '.join(f'"{p}"' for p in parts))

        lines.append(f'        tell s')
        lines.append(f'            set content of text range of text frame of it to {text_expr}')
        lines.append(f'            set font size of font of text range of text frame of it to {font_size}')
        if font_color:
            r, g, b = font_color
            lines.append(f'            set font color of font of text range of text frame of it to {{{r}, {g}, {b}}}')
        if bold:
            lines.append(f'            set bold of font of text range of text frame of it to true')
        lines.append(f'            set vertical anchor of text frame of it to 3')
        lines.append(f'        end tell')

    lines.append('    end tell')
    lines.append('end tell')

    asc('\n'.join(lines))
    time.sleep(delay if delay is not None else D)


# ═══════════════════════════════════════════════════════════
# Color Palette
# ═══════════════════════════════════════════════════════════
NAVY = (24, 42, 75)
NAVY_L = (35, 58, 95)
BLUE = (41, 98, 255)
BLUE_L = (230, 238, 255)
ORANGE = (255, 122, 0)
ORANGE_L = (255, 243, 230)
GREEN = (16, 185, 129)
GREEN_L = (230, 250, 243)
PURPLE = (124, 58, 237)
PURPLE_L = (245, 243, 255)
WHITE = (255, 255, 255)
G50 = (249, 250, 251)
G100 = (243, 244, 246)
G300 = (209, 213, 219)
G500 = (107, 114, 128)
G700 = (55, 65, 81)
G900 = (17, 24, 39)


def step(msg):
    print(f"  {msg}")
    time.sleep(D_STEP)


def add_slide(num):
    """슬라이드 추가 + 기본 shape 제거 + 뷰 이동."""
    asc('tell application "Microsoft PowerPoint" to tell active presentation to make new slide at end')
    time.sleep(0.5)
    asc(f'''
        tell application "Microsoft PowerPoint"
            tell slide {num} of active presentation
                set sc to count of shapes
                repeat while sc > 0
                    delete shape 1
                    set sc to count of shapes
                end repeat
            end tell
            try
                set slide number of slide range of view of active window to {num}
            end try
        end tell
    ''')
    time.sleep(0.5)


# ═══════════════════════════════════════════════════════════
# Slide 1: Title Page
# ═══════════════════════════════════════════════════════════
def slide_1():
    s = 1
    print("\n[Slide 1] 타이틀 페이지")

    # ── 사이드바 ──
    step("네이비 사이드바...")
    shape(s, 0, 0, 320, 540, fill=NAVY)
    shape(s, -30, 340, 180, 180, fill=NAVY_L, shape_type=9, delay=D_SMALL)
    shape(s, 210, -20, 70, 70, fill=NAVY_L, shape_type=9, delay=D_SMALL)

    # ── 로고 (사이드바 위에 — fill=NAVY로 배경 맞춤) ──
    step("로고 + 태그라인...")
    shape(s, 35, 45, 250, 40, fill=NAVY,
          text="LogosAI", font_size=28, font_color=WHITE, bold=True)
    shape(s, 35, 88, 260, 25, fill=NAVY,
          text="Desktop Native AI Platform", font_size=11, font_color=(150, 170, 210))
    shape(s, 35, 125, 55, 3, fill=BLUE, delay=D_SMALL)

    # ── 스펙 리스트 ──
    step("핵심 스펙...")
    for i, spec in enumerate([
        "56+ AI Agents",
        "Desktop Native Control",
        "Self-Evolution System",
        "Enterprise Ready",
        "On-Premise LLM",
    ]):
        shape(s, 35, 145 + i * 28, 250, 24, fill=NAVY,
              text=spec, font_size=11, font_color=(180, 195, 225), delay=D_SMALL)

    # ── 메인 영역 (배경 = 흰색) ──
    step("메인 타이틀...")
    shape(s, 355, 80, 560, 60, fill=WHITE,
          text="Agentic AI", font_size=38, font_color=G900, bold=True,
          delay=0.5 if not FAST else 0.2)
    shape(s, 355, 142, 560, 55, fill=WHITE,
          text="Framework", font_size=38, font_color=G900, bold=True,
          delay=0.4 if not FAST else 0.15)

    step("서브타이틀...")
    shape(s, 355, 210, 560, 22, fill=WHITE,
          text="에이전트가 스스로 학습하고, 진화하는", font_size=14, font_color=G500)
    shape(s, 355, 234, 560, 22, fill=WHITE,
          text="Desktop Native AI 플랫폼", font_size=14, font_color=G500)
    shape(s, 355, 270, 70, 4, fill=BLUE, delay=D_SMALL)

    # ── 지표 카드 ──
    step("지표 카드...")
    cards = [
        ("56+", "AI Agents", BLUE, BLUE_L),
        ("L2+", "Autonomy Level", ORANGE, ORANGE_L),
        ("99.9%", "Uptime", GREEN, GREEN_L),
    ]
    cw, ch = 150, 90
    for i, (num, label, accent, bg) in enumerate(cards):
        x = 355 + i * (cw + 18)
        y = 295
        shape(s, x, y, cw, ch, fill=bg,
              no_line=False, line_color=G100, line_weight=1, delay=D_SMALL)
        shape(s, x, y, cw, 4, fill=accent, delay=0.03)
        shape(s, x, y + 12, cw, 38, fill=bg,
              text=num, font_size=26, font_color=accent, bold=True, delay=D_SMALL)
        shape(s, x, y + 52, cw, 25, fill=bg,
              text=label, font_size=10, font_color=G500, delay=D_SMALL)

    # ── 하단 바 ──
    step("하단...")
    shape(s, 320, 505, 640, 35, fill=G50)
    shape(s, 335, 510, 300, 22, fill=G50,
          text="2026 LogosAI — Confidential", font_size=9, font_color=G300)

    print("  -> 타이틀 페이지 완료!")


# ═══════════════════════════════════════════════════════════
# Slide 2: Architecture
# ═══════════════════════════════════════════════════════════
def slide_2():
    add_slide(2)
    s = 2
    print("\n[Slide 2] 아키텍처 다이어그램")

    step("헤더...")
    shape(s, 0, 0, 960, 5, fill=BLUE)
    shape(s, 50, 15, 400, 30, fill=WHITE,
          text="System Architecture", font_size=22, font_color=G900, bold=True)
    shape(s, 50, 45, 400, 18, fill=WHITE,
          text="3-Tier Desktop Native AI Architecture", font_size=11, font_color=G500)

    tiers = [
        ("UI", "Frontend", "logos_web (Next.js)",
         ["Chat UI + Artifact", "SSE Streaming", "Conversation History"],
         BLUE, BLUE_L),
        ("API", "Backend", "logos_api (FastAPI)",
         ["Orchestrator", "Memory Engine", "Interaction Engine"],
         ORANGE, ORANGE_L),
        ("AI", "Agent Runtime", "ACP Server (8888)",
         ["56+ Agents", "ReAct + Tool Use", "Self-Evolution"],
         GREEN, GREEN_L),
    ]

    tw, th = 270, 280
    gap = 28
    sx = (960 - (tw * 3 + gap * 2)) // 2
    ty = 80

    for ti, (icon, title, sub, items, color, bg) in enumerate(tiers):
        x = sx + ti * (tw + gap)
        step(f"{title} 카드...")

        # 카드 배경
        shape(s, x, ty, tw, th, fill=WHITE,
              no_line=False, line_color=G100, line_weight=1, delay=D_SMALL)
        # 상단 컬러 바
        shape(s, x, ty, tw, 5, fill=color, delay=0.03)

        # 아이콘 원
        isz = 44
        shape(s, x + (tw - isz) // 2, ty + 18, isz, isz,
              fill=bg, shape_type=9,
              text=icon, font_size=15, font_color=color, bold=True, delay=D)

        # 타이틀 + 서브 (카드 배경 = WHITE)
        shape(s, x, ty + 70, tw, 25, fill=WHITE,
              text=title, font_size=17, font_color=G900, bold=True, delay=D_SMALL)
        shape(s, x, ty + 93, tw, 18, fill=WHITE,
              text=sub, font_size=9, font_color=G500, delay=D_SMALL)

        # 구분선
        shape(s, x + 35, ty + 118, tw - 70, 1, fill=G100, delay=0.03)

        # 항목
        for j, item in enumerate(items):
            iy = ty + 130 + j * 32
            shape(s, x + 25, iy + 5, 7, 7, fill=color, shape_type=9, delay=0.03)
            shape(s, x + 40, iy, tw - 60, 20, fill=WHITE,
                  text=item, font_size=11, font_color=G700, delay=D_SMALL)

    # 화살표
    step("연결...")
    for i in range(2):
        ax = sx + (i + 1) * tw + i * gap + gap // 2 - 8
        ay = ty + th // 2 - 8
        shape(s, ax, ay, gap + 16, 18, fill=WHITE,
              text="→", font_size=18, font_color=G300, delay=D_SMALL)

    # Desktop Native 배너
    step("Desktop Native 배너...")
    by = ty + th + 18
    bw = tw * 3 + gap * 2
    shape(s, sx, by, bw, 38, fill=PURPLE_L,
          no_line=False, line_color=(230, 225, 255), line_weight=1)
    shape(s, sx + 10, by + 2, bw - 20, 34, fill=PURPLE_L,
          text="Desktop Native: PowerPoint · Excel · VS Code · KakaoTalk · Chrome",
          font_size=10, font_color=PURPLE, bold=True)

    shape(s, 900, 515, 50, 18, fill=WHITE,
          text="2 / 3", font_size=9, font_color=G300, delay=D_SMALL)
    print("  -> 아키텍처 페이지 완료!")


# ═══════════════════════════════════════════════════════════
# Slide 3: Why LogosAI?
# ═══════════════════════════════════════════════════════════
def slide_3():
    add_slide(3)
    s = 3
    print("\n[Slide 3] 차별화 비교")

    step("헤더...")
    shape(s, 0, 0, 960, 5, fill=BLUE)
    shape(s, 50, 15, 400, 30, fill=WHITE,
          text="Why LogosAI?", font_size=22, font_color=G900, bold=True)
    shape(s, 50, 45, 500, 18, fill=WHITE,
          text="기존 AI 프레임워크와의 핵심 차별점", font_size=11, font_color=G500)

    features = [
        ("Native", "Desktop Native Control",
         "PowerPoint, Excel, Chrome 등 앱을 직접 제어", BLUE, BLUE_L),
        ("Evolve", "Self-Evolution (L2+)",
         "에이전트가 약한 부분을 자동 감지하여 개선", ORANGE, ORANGE_L),
        ("Multi", "Multi-Agent Orchestration",
         "56+ 에이전트를 직렬/병렬/하이브리드 조합", GREEN, GREEN_L),
        ("Secure", "On-Premise Ready",
         "Ollama/vLLM 폐쇄망 구동, 금융/공공 규제 대응", PURPLE, PURPLE_L),
    ]

    cw, ch = 410, 140
    gx, gy = 30, 20
    ox = (960 - (cw * 2 + gx)) // 2
    oy = 80

    for i, (icon, title, desc, color, bg) in enumerate(features):
        col, row = i % 2, i // 2
        x = ox + col * (cw + gx)
        y = oy + row * (ch + gy)

        step(f"{title}...")

        # 카드 배경
        shape(s, x, y, cw, ch, fill=bg,
              no_line=False, line_color=G100, line_weight=1, delay=D_SMALL)

        # 아이콘 원
        shape(s, x + 18, y + (ch - 48) // 2, 48, 48,
              fill=color, shape_type=9,
              text=icon, font_size=11, font_color=WHITE, bold=True)

        # 타이틀 (bg 맞춤)
        shape(s, x + 78, y + 18, cw - 100, 25, fill=bg,
              text=title, font_size=15, font_color=G900, bold=True, delay=D_SMALL)

        # 설명 (bg 맞춤)
        shape(s, x + 78, y + 50, cw - 100, 70, fill=bg,
              text=desc, font_size=11, font_color=G700, delay=D_SMALL)

    # CTA
    step("CTA 버튼...")
    cta_y = oy + 2 * (ch + gy) + 25
    shape(s, (960 - 250) // 2, cta_y, 250, 38, fill=BLUE,
          text="PoC 및 상세 데모 요청", font_size=13,
          font_color=WHITE, bold=True, delay=0.5 if not FAST else 0.2)

    shape(s, 900, 515, 50, 18, fill=WHITE,
          text="3 / 3", font_size=9, font_color=G300, delay=D_SMALL)
    print("  -> 차별화 페이지 완료!")


# ═══════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════
def main():
    mode = "Fast" if FAST else "영상 촬영용"
    print("=" * 60)
    print("  LogosAI — Live Slide Generation Demo")
    print(f"  Mode: {mode}")
    print("  PowerPoint에서 실시간으로 슬라이드가 만들어집니다")
    print("=" * 60)

    # PowerPoint
    print("\n[준비] PowerPoint 활성화...")
    subprocess.run(["open", "-a", "Microsoft PowerPoint"], timeout=5)
    time.sleep(2)
    asc('tell application "Microsoft PowerPoint" to activate')
    time.sleep(1)

    # 새 프레젠테이션 + 빈 슬라이드
    print("[준비] 새 프레젠테이션...")
    asc('''
        tell application "Microsoft PowerPoint"
            set newP to make new presentation
            tell newP
                make new slide at end
            end tell
        end tell
    ''')
    time.sleep(1.5)

    # 기본 shape 제거
    asc('''
        tell application "Microsoft PowerPoint"
            tell slide 1 of active presentation
                set sc to count of shapes
                repeat while sc > 0
                    delete shape 1
                    set sc to count of shapes
                end repeat
            end tell
        end tell
    ''')
    time.sleep(0.5)

    t0 = time.time()
    slide_1()
    time.sleep(D_SLIDE)
    slide_2()
    time.sleep(D_SLIDE)
    slide_3()
    elapsed = time.time() - t0

    # 첫 슬라이드로
    time.sleep(0.5)
    asc('''
        tell application "Microsoft PowerPoint"
            try
                set slide number of slide range of view of active window to 1
            end try
        end tell
    ''')

    sc1 = asc('tell application "Microsoft PowerPoint" to return (count of shapes of slide 1 of active presentation) as string')
    sc2 = asc('tell application "Microsoft PowerPoint" to return (count of shapes of slide 2 of active presentation) as string')
    sc3 = asc('tell application "Microsoft PowerPoint" to return (count of shapes of slide 3 of active presentation) as string')

    print("\n" + "=" * 60)
    print("  Live Demo 완료!")
    print(f"  소요 시간: {elapsed:.1f}초")
    print(f"  Slide 1: {sc1}개  |  Slide 2: {sc2}개  |  Slide 3: {sc3}개")
    total = int(sc1 or 0) + int(sc2 or 0) + int(sc3 or 0)
    print(f"  총 {total}개 도형을 실시간으로 생성했습니다.")
    print()
    print("  이것이 LogosAI의 Desktop Native Artifact입니다.")
    print("=" * 60)


if __name__ == "__main__":
    main()
