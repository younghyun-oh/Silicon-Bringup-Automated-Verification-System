import json
import os
import subprocess  # 외부 명령 실행을 위해 추가
import pyvisa  # 장비 주소를 따오기 위해 추가
import threading  # Lock 기능을 위해 추가
from concurrent.futures import ThreadPoolExecutor  # 병렬 실행 엔진 호출
import shutil
import zipfile
from datetime import datetime
import time
import logging


# 표준 로깅 설정 함수 (화면 출력 + 파일 저장 통합)
def setup_logging(output_dir):
    log_file = os.path.join(output_dir, "verification_system.log")

    logger = logging.getLogger("BringUpLogger")
    logger.setLevel(logging.INFO)

    # 중복 핸들러 방지 로직
    if logger.hasHandlers():
        logger.handlers.clear()

    # 1. 파일 저장 설정 (시간, 레벨, 메시지 규격화)
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
    file_handler.setFormatter(file_formatter)

    # 2. 콘솔 화면 출력 설정
    stream_handler = logging.StreamHandler()
    stream_formatter = logging.Formatter("[%(levelname)s] %(message)s")
    stream_handler.setFormatter(stream_formatter)

    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    return logger


# 1. config.json 읽기
def load_test_config(file_path):
    # JSON 파일 읽기
    with open(file_path, 'r', encoding='utf-8') as f:
        config_data = json.load(f)
    return config_data


# lock 선언
device_lock = threading.Lock()


# 8. 테스트 리스트 반복문 실행
def run_single_test(test, target_address, output_dir, logger):
    t_name = test['name']
    t_id = test['test_id']
    t_opt = test['option']
    t_unit = test.get('unit', '')

    # 진입하자마자 파일부터 생성 (실패해도 흔적을 남겨 Resume가 인식하도록 방어)
    log_file_name = f"{t_id}_{t_name}.log"
    log_path = os.path.join(output_dir, log_file_name)

    # 진입 직후 디스크에 빈 파일 즉시 새기기
    # 초기 빈 파일 생성
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(f"--- TEST STARTED AT {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
        f.flush()
        os.fsync(f.fileno())

    logger.info(f" [READY] {t_id}")

    # Lock 장비제어
    # device_lock.acquire()와 release()를 자동으로 해주는 with문을 씁니다.
    with device_lock:

        logger.info(f"\n{'=' * 10} [RUNNING: {t_id}] {'=' * 10}")
        logger.info(f"  ▶ Test Name: {t_name}")
        logger.info(f"  ▶ Config   : {t_opt} ({t_unit})")

        # [실제 실행 구간]
        # 기존 t_opt(전압) 뒤에 따온 target_address(주소)를 붙여줍니다.
        # python dummy_tester.py --voltage 1.2 --address USB0::..와 같은 명령어를 생성하여 실행합니다.
        cmd = ["python", "tester.py"]

        # JSON의 'option' 항목 분리해서 추가
        cmd.extend(t_opt.split())
        # 사용자 선택 장비 주소 추가
        cmd.extend(["--address", target_address])
        # 단위 추가 (단위 없을때 중복 방지)
        if t_unit and "--unit" not in t_opt:
            cmd.extend(["--unit", t_unit])

        try:
            # 15초 타임아웃을 걸어 장비 응답 대기 시 무한 루프 방지
            # errors='replace'를 추가하여 인코딩 충돌 시 프로그램을 멈추지 않고 진행합니다.
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                encoding='utf-8', errors='replace', timeout=15
            )

            # 결과값(stdout)이 None인 경우를 대비해 빈 문자열로 초기화
            stdout = result.stdout if result.stdout else ""
            stderr = result.stderr if result.stderr else ""

            # 결과 판독
            # 테스터가 뱉은 글자들(stdout) 속에 정상종료(0) 또는"PASS"가 있는지 확인합니다.
            if result.returncode == 0 and "PASS" in stdout:
                status = "SUCCESS"
            else:
                status = "FAILED"

        except subprocess.TimeoutExpired as e:
            # 10초가 지나면 이리로 점프하여 프로그램을 계속 살립니다.
            status = "TIMEOUT"
            logger.warning(f"  ㄴ [{t_id}] [경고] 장비 응답 시간 초과 (15s Timeout)!")
            # e.stdout 등에서 읽어올 때도 대비
            stdout = e.stdout.decode('utf-8', 'replace') if e.stdout else "[Error] Timeout"
            stderr = e.stderr.decode('utf-8', 'replace') if e.stderr else ""

        except Exception as e:
            status = "ERROR"
            logger.error(f"  ㄴ [{t_id}] [치명적 에러] 시스템 예외 발생: {str(e)}")
            stdout, stderr = f"[Error] {str(e)}", ""

    # [수정] 한 개의 테스트가 끝날 때 깔끔하게 마무리 표시
    logger.info(f"  ◀ [FINISH] {t_id} Result: {status}")


    # 개별 로그 파일 저장

    with open(log_path, "w", encoding="utf-8") as f:
        f.write(stdout)
        if stderr:
            f.write("\n" + "=" * 20 + " ERR " + "=" * 20 + "\n" + stderr)
        f.flush()
        os.fsync(f.fileno())

    logger.info(f"  ㄴ [{t_id}] 완료 기록 저장 완료: {status}")

    return {"id": t_id, "name": t_name, "result": status}


def main():
    # 1. 설정 파일 경로 지정
    config_file = 'config.json'

    # 2. 파일이 실제로 존재하는지 체크 (예외 처리)
    if not os.path.exists(config_file):
        print(f"에러: {config_file} 파일을 찾을 수 없습니다.")
        return

    # 3. JSON 데이터 불러오기
    config = load_test_config(config_file)
    tests = config['test_list']

    # 실행 전 디스크 용량 체크. 현재 경로의 디스크 정보를 가져옵니다.
    total, used, free = shutil.disk_usage(".")
    free_gb = free // (2 ** 30)  # 바이트를 GB로 변환
    if free_gb < 1:  # 1GB 미만이면 위험하다고 판단
        print(f"⚠️ 경고: 디스크 여유 공간이 부족합니다 ({free_gb}GB).")
        print("공간 확보 후 다시 실행해주세요.")
        return

    # 4.  장비 주소 딱 한번만 따오기
    # rm = pyvisa.ResourceManager('')
    rm = pyvisa.ResourceManager('@sim')  # simulation mode
    resources = rm.list_resources()

    if not resources:
        print("연결된 장비가 없습니다.")
        return

    print("\n=== 테스트 시작 전 장비 선택 ===")
    for i, addr in enumerate(resources):
        print(f"[{i}] {addr}")

    # 장비 번호 입력 예외 처리
    while True:
        try:
            val = input("사용할 장비 번호를 입력하세요: ")
            selection = int(val)
            if 0 <= selection < len(resources):
                target_address = resources[selection]  # 이 주소를 기억
                break
            else:
                print(f"에러: 0에서 {len(resources) - 1} 사이의 번호를 입력하세요.")
        except ValueError:
            print("에러: 숫자만 입력 가능합니다.")

    # 5. 저장 폴더 생성
    base_prefix = config['project_name'] + "_Results_"
    existing_dirs = [d for d in os.listdir('.') if os.path.isdir(d) and d.startswith(base_prefix)]
    output_dir = ""
    completed_tests = set()

    # 기존 실행 폴더가 존재하면 이어 돌릴지 말지 사용자에게 물어봄
    if existing_dirs:
        existing_dirs.sort(key=lambda x: os.path.getmtime(x), reverse=True)

        latest_dir = existing_dirs[0]  # 가장 최근에 만졌던 세션 폴더 선택
        print(f"\n[RESUME CHECK] 직전에 중단되거나 실행된 검증 세션 폴더를 발견했습니다.")
        print(f" -> 대상 폴더 경로: {latest_dir}")
        ans = input("이 폴더에 이어서 검증을 누적 진행하시겠습니까? (y/n): ").strip().lower()
        if ans == 'y':
            output_dir = latest_dir
            # 해당 폴더 안에서 텍스트 내부에 진짜 장비 완료 신호인 "PASS"가 각인된 로그만 참값(스킵 대상)으로 인정
            for file_name in os.listdir(output_dir):
                if file_name.endswith(".log") and file_name.startswith("TC"):
                    tc_id = file_name.split("_")[0]
                    chk_path = os.path.join(output_dir, file_name)
                    try:
                        with open(chk_path, "r", encoding="utf-8", errors="replace") as rf:
                            if "PASS" in rf.read():
                                completed_tests.add(tc_id)
                    except Exception:
                        pass

    # 완전히 새로 도는 것이거나 'n'을 누른 경우 고유한 신규 타임스탬프 세션 폴더 생성
    if not output_dir:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = f"{base_prefix}{timestamp}"
        os.makedirs(output_dir, exist_ok=True)

    # 핸들러 베이스의 로깅 모듈 가동 (이 시점부터 모든 출력은 파일과 화면에 동시 인쇄됨)
    logger = setup_logging(output_dir)

    logger.info("==========================================================")
    logger.info("  High-Speed Interface Automated Verification System Start")
    logger.info("==========================================================")
    if completed_tests:
        logger.info(f"[RESUME ALERT] 기존 완료 이력 확인: {len(completed_tests)}건 스킵 대기")

    # 6. 프로젝트 정보 출력 및 폴더 생성 결과 출력
    logger.info(f"--- 프로젝트명: {config['project_name']} (ver {config['version']}) ---")
    logger.info(f">>> 병렬 실행 시작 (최대 {config.get('parallel_workers', 4)}개 동시 진행)")

    # 7. 전체 결과를 담을 리스트 (요약 리포트용)
    final_report = []

    active_tests = []
    # 실행할 타겟과 스킵할 타겟 분리 제어문
    for t in tests:
        if t['test_id'] in completed_tests:
            # 이미 로그가 있는 주소는 실행 안 하고 레포트 결과만 채워둠
            final_report.append({"id": t['test_id'], "name": t['name'], "result": "SUCCESS"})
            logger.info(f" -> [SKIP] {t['test_id']} ({t['name']}) -> 이미 로그가 존재합니다.")
        else:
            active_tests.append(t)
    # ThreadPoolExecutor로 남은 테스트가 있을 때만 4개 병렬 실행
    if active_tests:

        with ThreadPoolExecutor(max_workers=4) as executor:
            # 각 테스트(t)를 'run_single_test' 함수에 넣어서 실행하라고 명령
            futures = [executor.submit(run_single_test, t, target_address, output_dir, logger) for t in active_tests]

            # 각 테스트가 끝나는(future.result()) 대로 보고서를 모음
            for future in futures:
                try:
                    final_report.append(future.result())
                except Exception as e:
                    logger.error(f"  ㄴ [에러] 스레드 결과 회수 실패: {e}")

    else:
        logger.info("[OK] 모든 시나리오가 이미 완료되어 추가 실행 없이 백업으로 직행합니다.")

    # 8. 모든 테스트 완료 후 로그 압축
    logger.info(f">>> [FINAL] 전체 시나리오 세션 마감 확인. 백업 압축을 시작합니다...")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_name = os.path.join(output_dir, f"{config['project_name']}_{timestamp}_Logs.zip")

    try:
        if os.path.exists(output_dir) and os.listdir(output_dir):
            with zipfile.ZipFile(zip_name, 'w', zipfile.ZIP_DEFLATED) as log_zip:
                for root, dirs, files in os.walk(output_dir):
                    for file in files:
                        if file.endswith(".log") and not file.endswith("verification_system.log"):
                            log_zip.write(os.path.join(root, file), arcname=file)
            logger.info(f" 압축 완료: {os.path.abspath(zip_name)}")
        else:
            logger.info("알림: 저장 폴더 내에 압축할 로그 파일이 존재하지 않습니다.")
    except Exception as e:
        logger.error(f" 압축 중 오류 발생: {e}")

    # 9. [전체 요약 리포트 출력]
    # 모든 for문이 끝난 뒤, final_report에 모인 데이터를 한꺼번에 보여줍니다.
    logger.info("=" * 40)
    logger.info("        FINAL TEST REPORT")
    logger.info("=" * 40)

    success_count = 0
    # 딕셔너리 순서가 꼬이지 않게 config 순서 기준으로 리포트 정렬 출력 방어
    report_map = {item['id']: item for item in final_report}
    for t in tests:
        item = report_map.get(t['test_id'])
        if item:
            logger.info(f"[{item['id']}] {item['name']}: {item['result']}")
            if item['result'] == "SUCCESS":
                success_count += 1
        else:
            logger.info(f"[{t['test_id']}] {t['name']}: FAILED")

    logger.info("-" * 40)
    logger.info(f"총 합계 : {len(tests)}건 중 {success_count}건 성공")
    logger.info("=" * 40)

    logger.info("모든 테스트가 완료되었습니다.")


if __name__ == "__main__":
    main()