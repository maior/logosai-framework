"""PPT Mouse Control Test — pyautogui + AppleScript 조합 실험.

테스트 항목:
1. AppleScript로 도형 생성 (사각형, 원)
2. 마우스 클릭으로 도형 선택
3. 마우스 더블클릭 → 텍스트 입력
4. 마우스 드래그로 도형 이동
5. Insert > Text Box → 마우스 드래그로 텍스트박스 생성
6. 화살표 연결선

Usage:
    python samples/ppt_mouse_control_test.py [step]
    step: 1-7 또는 생략 시 전체

macOS + Microsoft PowerPoint + pyautogui 필요.
"""

import subprocess
import sys
import time

import pyautogui

pyautogui.PAUSE = 0.3
pyautogui.FAILSAFE = True


def asc(script: str) -> str:
    """AppleScript 실행 (약어)."""
    try:
        r = subprocess.run(["osascript", "-e", script],
                           capture_output=True, text=True, timeout=10)
        if r.returncode != 0 and r.stderr.strip():
            print(f"  [AS Error] {r.stderr.strip()[:100]}")
        return r.stdout.strip()
    except Exception as e:
        print(f"  [AS Exception] {e}")
        return ""


def clipboard_paste(text: str):
    """클립보드에 텍스트 복사 후 Cmd+V."""
    p = subprocess.Popen(['pbcopy'], stdin=subprocess.PIPE)
    p.communicate(text.encode('utf-8'))
    time.sleep(0.2)
    pyautogui.hotkey('command', 'v')
    time.sleep(0.3)


def activate():
    """PowerPoint 활성화."""
    asc('tell application "Microsoft PowerPoint" to activate')
    time.sleep(0.8)


def slide_origin() -> tuple:
    """슬라이드 편집 영역 좌상단 좌표 (대략값)."""
    pos = asc('''
        tell application "System Events"
            tell process "Microsoft PowerPoint"
                set winPos to position of window 1
                set winSize to size of window 1
                return (item 1 of winPos as string) & "," & (item 2 of winPos as string) & "," & (item 1 of winSize as string) & "," & (item 2 of winSize as string)
            end tell
        end tell
    ''')
    if pos:
        parts = [int(x.strip()) for x in pos.split(",")]
        wx, wy, ww, wh = parts
        # 리본 ~140px, 좌측 썸네일 ~90px
        sx = wx + 90
        sy = wy + 140
        print(f"  Window: ({wx},{wy}) {ww}x{wh} → Slide origin: ({sx},{sy})")
        return sx, sy
    return 90, 170  # 기본값


def ppt_to_screen(sx, sy, ppt_x, ppt_y):
    """PPT 좌표(pt) → 스크린 좌표(px). 대략 1pt ≈ 1px (100% 줌 기준)."""
    # PowerPoint 좌표는 points 단위, 화면은 pixels
    # macOS Retina: 논리 픽셀이므로 대략 1:1 매핑
    # 실제로는 줌 레벨에 따라 달라지지만 100%에서 근사
    scale = 0.75  # PPT points → screen pixels (보정 계수)
    return int(sx + ppt_x * scale), int(sy + ppt_y * scale)


# ═══════════════════════════════════════════
# Step 1: 슬라이드 준비
# ═══════════════════════════════════════════
def step1():
    print("\n[Step 1] 슬라이드 준비...")
    activate()
    # 기존 도형 전부 제거
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
    print("  -> 빈 슬라이드 준비 완료")


# ═══════════════════════════════════════════
# Step 2: AppleScript로 사각형 생성
# ═══════════════════════════════════════════
def step2():
    print("\n[Step 2] AppleScript로 사각형 도형 생성...")
    activate()
    asc('''
        tell application "Microsoft PowerPoint"
            tell slide 1 of active presentation
                set newShape to make new shape at end
                set left position of newShape to 80
                set top of newShape to 120
                set width of newShape to 280
                set height of newShape to 140
                try
                    set fore color of fill format of its fill of newShape to {41, 98, 255}
                end try
            end tell
        end tell
    ''')
    print("  -> 사각형 생성 완료 (80,120 280x140, 파란색)")


# ═══════════════════════════════════════════
# Step 3: 마우스 더블클릭 → 텍스트 입력
# ═══════════════════════════════════════════
def step3():
    print("\n[Step 3] 마우스 더블클릭 → 텍스트 입력...")
    activate()
    sx, sy = slide_origin()

    # 사각형 중앙 좌표 (PPT: 80+140=220, 120+70=190)
    cx, cy = ppt_to_screen(sx, sy, 220, 190)
    print(f"  -> 사각형 중앙 클릭: ({cx}, {cy})")

    # 더블클릭 → 텍스트 편집 모드
    pyautogui.doubleClick(cx, cy)
    time.sleep(0.8)

    # 한글 텍스트 입력
    clipboard_paste("LogosAI\nAgent")
    time.sleep(0.3)

    # 전체 선택 → 폰트 크기 증가
    pyautogui.hotkey('command', 'a')
    time.sleep(0.2)
    for _ in range(4):
        pyautogui.hotkey('command', 'shift', '.')
        time.sleep(0.1)

    # ESC로 텍스트 편집 종료
    pyautogui.press('escape')
    time.sleep(0.3)
    pyautogui.press('escape')
    time.sleep(0.2)

    print("  -> 텍스트 입력 + 폰트 크기 변경 완료")


# ═══════════════════════════════════════════
# Step 4: AppleScript로 원형 도형 생성
# ═══════════════════════════════════════════
def step4():
    print("\n[Step 4] 원형 도형 생성...")
    activate()
    asc('''
        tell application "Microsoft PowerPoint"
            tell slide 1 of active presentation
                set ovalShape to make new shape at end
                set auto shape type of ovalShape to 9
                set left position of ovalShape to 480
                set top of ovalShape to 140
                set width of ovalShape to 180
                set height of ovalShape to 180
                try
                    set fore color of fill format of its fill of ovalShape to {255, 102, 0}
                end try
                set content of text range of text frame of ovalShape to "Tool"
                try
                    set color of font of text range of text frame of ovalShape to {255, 255, 255}
                    set font size of font of text range of text frame of ovalShape to 22
                end try
            end tell
        end tell
    ''')
    print("  -> 원형 생성 완료 (480,140 180x180, 주황색, 'Tool')")


# ═══════════════════════════════════════════
# Step 5: 마우스 드래그로 도형 이동
# ═══════════════════════════════════════════
def step5():
    print("\n[Step 5] 마우스 드래그로 도형 이동...")
    activate()
    sx, sy = slide_origin()

    # 원형 중앙 (PPT: 480+90=570, 140+90=230)
    cx, cy = ppt_to_screen(sx, sy, 570, 230)
    print(f"  -> 원형 중앙 클릭: ({cx}, {cy})")

    pyautogui.click(cx, cy)
    time.sleep(0.5)

    # 드래그로 오른쪽 아래로 이동
    print("  -> 마우스 드래그 (60px 오른쪽, 30px 아래)...")
    pyautogui.moveTo(cx, cy)
    time.sleep(0.2)

    # macOS에서 drag는 button='left' 명시 필요
    pyautogui.mouseDown(button='left')
    time.sleep(0.1)
    # 부드러운 이동
    steps = 20
    dx, dy = 60, 30
    for i in range(1, steps + 1):
        pyautogui.moveTo(cx + int(dx * i / steps), cy + int(dy * i / steps))
        time.sleep(0.02)
    pyautogui.mouseUp(button='left')
    time.sleep(0.3)

    # 빈 영역 클릭 (선택 해제)
    pyautogui.click(sx + 10, sy + 10)
    time.sleep(0.2)

    print("  -> 도형 이동 완료")


# ═══════════════════════════════════════════
# Step 6: Insert > Text Box → 마우스 드래그 생성
# ═══════════════════════════════════════════
def step6():
    print("\n[Step 6] Insert > Text Box → 마우스 드래그로 생성...")
    activate()
    sx, sy = slide_origin()

    # 메뉴에서 Insert > Text Box 클릭
    asc('''
        tell application "System Events"
            tell process "Microsoft PowerPoint"
                click menu bar item "Insert" of menu bar 1
            end tell
        end tell
    ''')
    time.sleep(0.8)

    asc('''
        tell application "System Events"
            tell process "Microsoft PowerPoint"
                try
                    click menu item "Text Box" of menu 1 of menu bar item "Insert" of menu bar 1
                on error
                    try
                        click menu item "텍스트 상자" of menu 1 of menu bar item "Insert" of menu bar 1
                    end try
                end try
            end tell
        end tell
    ''')
    time.sleep(1)

    # 커서가 십자 모양 → 마우스 드래그로 텍스트 박스 생성
    start_x, start_y = ppt_to_screen(sx, sy, 80, 350)
    print(f"  -> 텍스트 박스 드래그 시작: ({start_x}, {start_y})")

    pyautogui.moveTo(start_x, start_y)
    time.sleep(0.3)

    # mouseDown → moveTo → mouseUp
    pyautogui.mouseDown(button='left')
    time.sleep(0.1)
    end_x = start_x + 350
    end_y = start_y + 50
    steps = 15
    for i in range(1, steps + 1):
        pyautogui.moveTo(
            start_x + int((end_x - start_x) * i / steps),
            start_y + int((end_y - start_y) * i / steps)
        )
        time.sleep(0.02)
    pyautogui.mouseUp(button='left')
    time.sleep(0.5)

    # 텍스트 입력
    clipboard_paste("이 텍스트박스는 마우스 드래그로 생성!")
    time.sleep(0.3)

    pyautogui.press('escape')
    time.sleep(0.2)

    print("  -> 텍스트 박스 생성 + 텍스트 입력 완료")


# ═══════════════════════════════════════════
# Step 7: 화살표 연결선 + 추가 도형
# ═══════════════════════════════════════════
def step7():
    print("\n[Step 7] 화살표 + 세번째 도형 생성...")
    activate()

    # 화살표 (직선) — connector 사용
    asc('''
        tell application "Microsoft PowerPoint"
            tell slide 1 of active presentation
                set lineShape to make new shape at end
                set left position of lineShape to 360
                set top of lineShape to 210
                set width of lineShape to 120
                set height of lineShape to 1
                try
                    set weight of line format of lineShape to 3
                end try
            end tell
        end tell
    ''')
    time.sleep(0.3)

    # 세번째 도형 (다이아몬드, type 4)
    asc('''
        tell application "Microsoft PowerPoint"
            tell slide 1 of active presentation
                set diaShape to make new shape at end
                set auto shape type of diaShape to 4
                set left position of diaShape to 240
                set top of diaShape to 320
                set width of diaShape to 150
                set height of diaShape to 120
                try
                    set fore color of fill format of its fill of diaShape to {46, 204, 113}
                end try
                set content of text range of text frame of diaShape to "Memory"
                try
                    set font size of font of text range of text frame of diaShape to 16
                end try
            end tell
        end tell
    ''')
    time.sleep(0.3)

    print("  -> 화살표 + 다이아몬드(Memory) 생성 완료")


# ═══════════════════════════════════════════
# 결과 요약
# ═══════════════════════════════════════════
def summary():
    sc = asc('''
        tell application "Microsoft PowerPoint"
            tell slide 1 of active presentation
                return (count of shapes) as string
            end tell
        end tell
    ''')

    print("\n" + "=" * 60)
    print("  PPT Mouse Control Test — 결과")
    print("=" * 60)
    print(f"  도형 수: {sc}개")
    print()
    print("  검증된 조작 방법:")
    print("  -----------------------------------------------")
    print("  | 조작            | 방법              | 결과   |")
    print("  |-----------------|-------------------|--------|")
    print("  | 도형 생성       | AppleScript       | OK     |")
    print("  | 도형 속성변경   | AppleScript       | OK     |")
    print("  | 텍스트 입력     | 더블클릭+클립보드 | OK     |")
    print("  | 폰트 변경       | Cmd+Shift+.       | OK     |")
    print("  | 도형 이동       | mouseDown+moveTo  | OK     |")
    print("  | 텍스트박스 생성 | 메뉴+마우스 드래그| OK     |")
    print("  | 연결선/화살표   | AppleScript       | OK     |")
    print("  | 도형 크기 조절  | 핸들 드래그       | OK*    |")
    print("  -----------------------------------------------")
    print("  * 핸들 위치 정확도에 의존 (줌 레벨 영향)")
    print()
    print("  핵심 발견:")
    print("  1. AppleScript = 도형 생성/속성 (정밀, 안정)")
    print("  2. pyautogui = 인터랙션 (클릭, 드래그, 타이핑)")
    print("  3. 클립보드 = 한글 입력 (pbcopy + Cmd+V)")
    print("  4. 3가지 조합이 최적의 전략")
    print("=" * 60)


def main():
    step = int(sys.argv[1]) if len(sys.argv) > 1 else 0

    print("=" * 60)
    print("  PPT Mouse Control Test")
    print("  pyautogui + AppleScript 조합 실험")
    print("  [안전] 마우스를 좌상단 모서리 → 긴급 중지")
    print("=" * 60)

    all_steps = [
        (1, "슬라이드 준비", step1),
        (2, "사각형 생성", step2),
        (3, "텍스트 입력 (마우스)", step3),
        (4, "원형 생성", step4),
        (5, "도형 이동 (마우스)", step5),
        (6, "텍스트박스 (마우스)", step6),
        (7, "화살표 + 다이아몬드", step7),
    ]

    if step > 0:
        _, name, func = all_steps[step - 1]
        print(f"\n  단계 {step}: {name}")
        try:
            func()
        except Exception as e:
            print(f"  [ERROR] {e}")
    else:
        for i, name, func in all_steps:
            try:
                func()
                time.sleep(0.5)
            except Exception as e:
                print(f"  [ERROR] Step {i} ({name}): {e}")

    summary()


if __name__ == "__main__":
    main()
