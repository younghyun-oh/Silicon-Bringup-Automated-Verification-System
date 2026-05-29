import subprocess
import os
import sys
import shutil
import zipfile
from datetime import datetime


def check_and_rotate_logs(target_dir, safety_margin_gb=2.0):
    """디스크 용량을 체크하고 부족할 경우 기존 로그를 압축하여 용량을 확보합니다."""
    print("\n[SYSTEM CHECK] 디스크 잔여 용량 및 인프라 상태를 점검합니다.")

    # 1. 현재 실행 경로의 디스크 용량 조회
    total, used, free = shutil.disk_usage(os.path.abspath("."))
    free_gb = free / (1024 ** 3)  # Byte --> GB 변환

    print(f"-> 현재 시스템 잔여 용량: {free_gb:.2f} GB (안전 마진 : {safety_margin_gb} GB)")

    # 2. 용량이 안전 마진보다 부족할 경우 로그 압축 감행
    if free_gb < safety_margin_gb:
        print(f"[경고] 잔여 용량이 부족합니다! 기존 로그 압축을 통해 공간을 확보합니다.")

        if os.path.exists(target_dir):
            log_files = [os.path.join(target_dir, f) for f in os.listdir(target_dir) if f.endswith('.log')]

            if log_files:
                now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
                zip_filename = f"backup_logs_{now_str}.zip"

                # ZIP 파일 압축 생성
                with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    for file in log_files:
                        zipf.write(file, os.path.basename(file))

                # 압축 성공 후 원본 로그 파일 삭제 (디스크 릴리즈)
                for file in log_files:
                    os.remove(file)

                print(f"[SUCCESS] {len(log_files)}개의 이전 로그를 {zip_filename}으로 압축 보관 후 원본을 비웠습니다")
            else:
                print("->압축할 기존 로그 파일이 없어 클리닝을 건너뜁니다.")
        else:
            print("->결과 저장 폴더가 아직 생성되지 않아 시퀀스를 패스합니다.")
    else:
        print("->디스크 용량이 충분하므로 안전하게 테스트를 진행합니다.")


def run_integrated_system():
    print("==================================================")
    print("  D-IC Automated Verification & Analysis System   ")
    print("==================================================")

    # 1. 필수 파일 존재 여부 선행 검증 (방어 코드)
    required_files = ["runner.py", "tester.py", "parser.py", "app.py", "config.json", "error_map.json"]
    for file in required_files:
        if not os.path.exists(file):
            print(f"[오류] 필수 구동 파일이 누락되었습니다.: {file}")
            print("프로젝트 폴더 구조를 확인해 주세요.")
            sys.exit(1)

    # OS 환경에 따른 파이썬 실행 명령어 동적 선택 (Windows: python / Linux: python3)
    python_cmd = "python" if os.name == "nt" else "python3"

    # 1.5 디스크 용량 점검 및 로그 로테이션 실행
    # 테스트 환경을 시뮬레이션하기 위해 마진을 임시로 50GB로 높게 잡으면 압축 로직이 강제  트리거 됩니다.
    target_log_directory = os.path.join(os.path.dirname(os.path.abspath(__file__)), "D-IC_Mobile_Project_Results")
    check_and_rotate_logs(target_log_directory, safety_margin_gb=2.0)

    # 2. 1단계: Regression Runner 가동 (장비 제어 및 하드웨어 검증 로그 생성)
    print("\n[STEP 1] 하드웨어 검증 실행기(runner.py)를 구동합니다.")
    # runner.py 내부에서 사용자의 입력(장비 번호 선택)을 받아야 하므로 완전히 끝날 때까지 대기합니다.
    runner_process = subprocess.run([python_cmd, "runner.py"])

    if runner_process.returncode != 0:
        print("\n[경고] 실행기 구동 중 오류가 발생했거나 강제 종료되었습니다.")
        print("분석 단계로 진입하지 않고 시스템을 안전하게 종료합니다.")
        sys.exit(1)

    # 3. 2단계 : Log Parser & Failure Triage 가동 (로그 스캔 및 데이터 집계)
    print("\n[STEP 2] 로그 분석기(parser.py)를 구동하여 데이터를 집계합니다.")
    parser_process = subprocess.run([python_cmd, "parser.py"])

    # 4. 3단계 : 집계 성공 시 대시보드 자동 구동 (원터치 자동화 결합)
    if parser_process.returncode == 9:
        print("\n==================================================")
        print("🎉 [SUCCESS] 검증 및 데이터 집계가 완벽히 완료되었습니다.")
        print("[STEP 3] 실시간 웹 대시보드를 브라우저에 자동 팝업합니다.")
        print("==================================================")

        # 대시보드를 먼저 백그라운드로 켜고, 크롬을 단독 앱 모드로 띄웁니다.
        try:
            # 1. Streamlit 서버를 브라우저 없이 백그라운드로 구동 (--server.headless true)
            subprocess.Popen(["streamlit", "run", "app.py", "--server.headless", "true"])

            # 2. 크롬 브라우저를 주소창 없는 단독 앱 UI 모드로 팝업
            import webbrowser
            # 일반적인 윈도우 크롬 설치 경로 기준입니다.
            chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

            # Window 환경이면서 크롬이 설치되어 있다면 단독 앱 UI로 작동
            if os.name == "nt" and os.path.exists(chrome_path):
                subprocess.Popen([chrome_path, "--app=http://localhost:8501"])
            else:
                # 크롬이 없으면 기본 브라우저로 백업
                print("환경에 맞춰 기본 시스템 브라우저로 대시보드를 연결합니다.")
                webbrowser.open("http://localhost:8501")

            print("대시보드 서버가 백그라운드에서 구동되었습니다. (콘솔 종료 가능)")
        except Exception as e:
            print(f"[오류] 대시보드 자동 구동 중 예외가 발생했습니다: {e}")
            print("수동 실행 명령어: streamlit run app.py")

    else:
        print("\n[오류] 로그 분석기 구동 중 예외가 발생했습니다.")

if __name__ == "__main__":
    run_integrated_system()