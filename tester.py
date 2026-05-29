import sys
import argparse
from sys import exception
import pyvisa
import time
import random

# True: 시뮬레이션 모드, False: 실제 장비 연결 모드
IS_SIM = True

# 각 테스트 모드별 에러 코드와 시뮬레이션 용 특수 불량 처리 기준을 한곳에서 관리합니다.
GLOBAL_ERROR_CONFIG = {
    "SYSTEM": {
        "ERR_MAP": {
            "IDENTIFY_FAIL": "0X501",
            "TIMEOUT": "0X502"
        },
        "RAW_LOGS": {
            "0X501": "[SYSTEM_ERR] DEVICE_IDENTIFY_FAILED_UNABLE_TO_PARSE_IDN_STRING",
            "0X502": "[TIMEOUT_ERR] SYSTEM_CONNECTION_TIMEOUT_NO_RESPONSE_FROM_TERMINAL"
        }
    },
    "VOLTAGE": {
        "ERR_MAP": {
            "LOW": "0X101",
            "HIGH": "0X102",
            "UNDER": "0X103",
            "OVER_I": "0X104",
            "LDO": "0X105",
            "AVDD_DROP": "0X601",
            "SKEW_ERR": "0X701",
            "LINK_ERR": "0X801",
        },
        "SPECIAL_CASES": {
            "OVER_I": {"msg": "OVER_CURRENT_PROTECTION_OCP_TRIGGERED", "action": None, "v_fact": 1.0, "i_fact": 10.0},
            # 전류 폭증
            "LDO": {"msg": "LDO_OUTPUT_STAGE_DEAD_NO_VOLTAGE_GENERATED", "action": None, "v_fact": 0.0, "i_fact": 0.0},
            # 출력 사망
            "LINK_ERR": {"msg": "LINK_TRAINING_SEQUENCE_HANDSHAKE_TIMEOUT", "action": "LINK_TRAINING", "v_fact": -1.0,
                         "i_fact": 0.0},
            "AVDD_DROP": {"msg": "AVDD_VOLTAGE_DROP_UNDER_HIGH_FRAME_RATE_BURST", "action": "HIGH_FRAME",
                          "v_fact": 0.85, "i_fact": 0.02}
        },
        "RAW_LOGS": {
            "0X101": "[MEAS_ALERT] VOLT_OUT_LOW_LIMIT_FAIL - Measured value out of specification",
            "0X102": "[MEAS_ALERT] VOLT_OUT_HIGH_LIMIT_FAIL - Voltage surge detected on line",
            "0X103": "[MEAS_CRITICAL] UNDER_VOLTAGE_LOCKOUT_UVLO_STATE_DETECTED",
            "0X601": "[PMIC_WARN] AVDD_VOLTAGE_DROP_UNDER_HIGH_FRAME_RATE_BURST",
            "0X701": "[TEK_CH2] MIPI_DPHY_ERR_SKEW_LANE violation over limits"
        }
    },
    "HIGH_SPEED": {
        "ERR_MAP": {
            "WIDTH": "0X301",
            "HEIGHT": "0X302",
            "PLL": "0X303",
            "SI": "0X304",
            "SYNC": "0X305",
            "VCO": "0X306",
            "SKEW": "0X701",
            "LINK": "0X801",
            "BOOT": "0X201",
            "WATCHDOG": "0X202",
        },
        "SPECIAL_CASES": {
            "BOOT": {"msg": "HARDWARE_BOOTING_FAILED_REASON_UNKNOWN", "action": None, "w_fact": 0.0, "h_fact": 0.0},
            "WATCHDOG": {"msg": "WATCHDOG_TIMER_RESET_TIMEOUT_BURST", "action": None, "w_fact": 0.0, "h_fact": 0.0},
            "LINK": {"msg": "LINK_TRAINING_SEQUENCE_HANDSHAKE_TIMEOUT", "action": "LINK_TRAINING", "w_fact": 0.0,
                     "h_fact": 0.0}
        },
        "RAW_LOGS": {
            "0X301": "[SCOPE_EYE] EYE_DIAGRAM_WIDTH_VIOLATION captured during horizontal jitter trace",
            "0X302": "[SCOPE_EYE] EYE_DIAGRAM_HEIGHT_VIOLATION captured during vertical noise trace",
            "0X304": "[PHY_ERR] SIGNAL_INTEGRITY_SI_SEVERE_CLOSURE_DETECTED",
            "0X305": "[PHY_CRITICAL] CLOCK_SYNC_SIGNAL_LOSS_TERMINAL_DISCONNECTED",
            "0X701": "[TEK_CH2] MIPI_DPHY_ERR_SKEW_LANE violation over limits"
        }
    },
    "REGISTER": {
        "ERR_MAP": {
            "MISMATCH": "0X401",
            "CRC": "0X402",
            "ADDR_ERR": "0X403"
        },
        "SIM_VALS": {
            "MISMATCH": 0x00,
            "CRC": 0xAB,
            "ADDR_ERR": 0xFF
        },
        "RAW_LOGS": {
            "0X401": "[REG_ERR] REGISTER_READ_WRITE_DATA_MISMATCH_SHADOW_LAYER",
            "0X402": "[REG_ERR] PACKET_CRC_CHECKSUM_ERROR_BURST_DETECTED",
            "0X403": "[REG_ERR] INVALID_ADDRESS_ACCESS_VIOLATION_BLOCKED"
        }
    }
}


# IC 동작 제어 모듈 (실제 장비 시 Write Reg 동작 시뮬레이션)
def set_ic_state(mode="NORMAL"):
    """측정 전 IC의 동작 상태를 물리적으로 변경"""
    if mode == "HIGH_FRAME":
        # 0x601 고부하 상태 설정
        print(" > [IC_CONTROL] High-Frame Rate Drive Enable (Reg: 0x10 -> 0x01)")
    elif mode == "LINK_TRAINING":
        # 0x801 통신 세션 시작
        print(" > [IC_CONTROL] 6.6Gbps Link Training Sequence Start...")
    time.sleep(0.1)  # Settling Time


# 장비 초기화 및 셋팅
# 장비 초기화 및 셋팅 (문법 오류 수정 및 실제 장비 자동 전환 버전)
def setup_scope(scope, mode="GENERIC"):
    # 1. 자원 이름 및 시뮬레이션 여부 판단 (try 바깥에서 안전하게 처리)
    resource_name = getattr(scope, 'resource_name', "")
    is_sim = IS_SIM or ("@sim" in resource_name if isinstance(resource_name, str) else True)

    ## [0x502 시뮬레이션 모드] IS_SIM = True 일 때만 실행됨
    # if is_sim:
    #    print(" > [Debug] 시뮬레이션 장비 초기화 중... (10초 무한 대기 유발)")
    #    time.sleep(2.0)
    #    # 상위 함수(test_voltage 등)로 타임아웃 예외를 곧장 던집니다.
    #    raise pyvisa.errors.VisaIOError(pyvisa.constants.StatusCode.error_timeout)

    # [실제 장비 모드] IS_SIM = False 이면 위의 if문을 건너뛰고 여기로 직행합니다.
    try:
        scope.write("*RST")
        idn = scope.query('*IDN?').upper()
        is_keysight = "KEYSIGHT" in idn or "AGILENT" in idn
        is_tek = "TEKTRONIX" in idn

        if mode == "HS":  # 고속 인터페이스 모드 전용 셋팅
            scope.write(":AUToscale")
            time.sleep(1)
        else:  # 일반 전압/전류 측정 셋팅
            scope.write(":CHAN1:DISP ON")
            scope.write(":CHAN1:SCAL 0.5")

        return is_keysight, is_tek

    except Exception as e:
        print(f" > [Debug] 실제 장비 setup_scope 에러: {e}")
        return False, False


# 장비 타임아웃 예외처리
def safe_setup_scope(scope, mode="GENERIC"):
    # TIMEOUT 보호막 함수
    sys_config = GLOBAL_ERROR_CONFIG["SYSTEM"]
    try:
        is_ks, is_tk = setup_scope(scope, mode=mode)
        return True, is_ks, is_tk
    except (pyvisa.errors.VisaIOError, TimeoutError):
        # 딕셔너리에서 날것의 장비 메시지 매핑 출력
        timeout_code = sys_config["ERR_MAP"]["TIMEOUT"]
        print(sys_config["RAW_LOGS"][timeout_code])
        print("Final Status: FAIL")
        return False, False, False


# 테스트별 판별 로직
def check_spec_and_report(value, target, tolerance, low_code, high_code, unit, domain="VOLTAGE"):
    """범위를 벗어나면 사전 (RAW_LOGS)을 참조해 날 것의 장비 문구를 던지는 공통 분석기"""
    lower_bound = target - (target * tolerance)
    upper_bound = target + (target * tolerance)
    # 해당 계열(VOLTAGE, HIGH_SPEED 등)의 날것의 로그 맵 참조
    raw_log_map = GLOBAL_ERROR_CONFIG.get(domain, {}).get("RAW_LOGS", {})


    if low_code and value < lower_bound:
        # 일반 마진 아웃 불량 터졌을 때도 날 것의 장비 측정 범위 이탈 키워드를 출력하여 parser.py의 정규식 그물망에 걸리게 유도
        print(raw_log_map.get(low_code, f"[ERROR] Code: {low_code}, Message: Spec Out (Low/Fail)"))
        print(f"[SPEC_OUT] {value:.3f}{unit} < {lower_bound:.3f}{unit}")
        return "FAIL"
    elif high_code and value > upper_bound:
        print(raw_log_map.get(high_code, f"[ERROR] Code: {high_code}, Message: Spec Out (High/Over)"))
        print(f"[SPEC_OUT] {value:.3f}{unit} > {upper_bound:.3f}{unit}")
        return "FAIL"

    print(f" < [SPEC OK] {value:.3f}{unit} (Range: {lower_bound:.2f}~{upper_bound:.2f})")
    return "PASS"


def check_reg_match(addr, write_val, read_val, fail_code):
    """레지스터 값이 일치하는지 확인하고 에러 코드를 출력하는 모듈"""
    if write_val != read_val:
        raw_log_map = GLOBAL_ERROR_CONFIG["REGISTER"]["RAW_LOGS"]
        print(raw_log_map.get(fail_code, f"[ERROR] Code: {fail_code}, Message: Register Mismatch"))
        print(f"[SPEC_OUT] Addr: {hex(addr)} | Write: {hex(write_val)} | Read: {hex(read_val)}")
        return "FAIL"
    return "PASS"


# [A] 전압 측정 모드 (TC001,002)
def test_voltage(scope, target_v, unit, tolerance):
    print(f"\n[Mode] 전압 측정 모드 (Target: {target_v}{unit})")
    raw_v = "0.0"  # 초기값 셋팅
    measured_val = 0.0

    if not safe_setup_scope(scope):  # 장비 셋팅 호출
        return "FAIL"

    # 1. 전역사전에서 전압 관련 설정 가져오기
    v_config = GLOBAL_ERROR_CONFIG["VOLTAGE"]
    volt_err_map = v_config["ERR_MAP"]
    special_cases = v_config["SPECIAL_CASES"]

    fail_case = None  # fail_case 초기화

    if IS_SIM:
        # [시뮬레이션] 노이즈가 섞인 가상의 측정값 생성 (60% pass, 40% fail)
        if random.random() < 0.4:
            fail_case = random.choice(list(volt_err_map.keys()))

            # 특수 케이스 처리
            if fail_case in special_cases:
                case_info = special_cases[fail_case]
                if case_info["action"]:
                    set_ic_state(case_info["action"])
                print(f"[POWER_ALERT] {case_info['msg']} triggered on Power Rail")
                return "FAIL"

            # 일반 전압 마진 불량 시뮬레이션 (글로벌 키 매핑 추종)
            v_factors = {'HIGH': 1.08, 'LOW': 0.92, 'UNDER': 0.5, 'SKEW_ERR': 1.02}
            measured_val = target_v * v_factors.get(fail_case, 1.0)


        else:
            # 정상범위
            measured_val = target_v + random.uniform(-0.01, 0.01)

    else:
        # [실제 장비용] 쿼리 후 float 변환 과정
        try:
            # 다이나믹 전압은 VAV(평균)가 아니라 VMIN(최솟값)으로 측정
            measured_raw = scope.query(":MEAS:VMIN? CHAN1")  # 장비에 데이터 요청
            measured_val = float(measured_raw.strip())  # 공백 제거 및 실수 변환
        except Exception as e:
            print(f" > [Error] 장비 데이터 읽기 실패: {e}")
            measured_val = -999.0  # 에러 시 판정 실패 유도

    # 판정
    # 1. 우선 순위에 따른 에러 코드 결정
    if measured_val < (target_v * 0.7):
        current_low_code = volt_err_map["UNDER"]  # 0X103 # 아주 낮은 Under Voltage 최우선
    elif fail_case == 'AVDD_DROP':
        current_low_code = volt_err_map["AVDD_DROP"]  # "0X601"  # 고주사율 드랍
    elif fail_case == "SKEW_ERR":
        current_low_code = volt_err_map["SKEW_ERR"]
    else:
        current_low_code = volt_err_map["LOW"]  # "0X101"  # 일반적인 전압 낮음

    status = check_spec_and_report(measured_val, target_v, tolerance, current_low_code, volt_err_map["HIGH"], unit)
    print(f"Final Status: {status}")
    return status


# [B] 6.6Gbps 고속 인터페이스 & eye diagram (TC003,004)
def test_high_speed_interface(scope, target_gbps, unit):
    print(f"\n[Mode] High-Speed Interface Analysis (Target: {target_gbps}{unit})")
    if not safe_setup_scope(scope, mode="HS"):  # 장비 셋팅 호출
        return "FAIL"

        # 전역 사전에서 고속 인터페이스 설정 가져오기
    hs_config = GLOBAL_ERROR_CONFIG["HIGH_SPEED"]
    phy_err_map = hs_config["ERR_MAP"]
    special_cases = hs_config["SPECIAL_CASES"]

    # 변수 초기화
    eye_width, eye_height = 0.0, 0.0
    err_code, err_msg = "", ""
    res_name = getattr(scope, 'resource_name', "").lower()
    is_sim = IS_SIM or ("@sim" in res_name.lower())  # 시뮬레이션 장비 설정
    is_fail = random.random() < 0.4 if is_sim else False
    fail_type = None

    try:
        # 1. Eye diagram 측정을 위한 스코프 설정
        if not is_sim:
            # 실제 장비용
            scope.write(":MEASure:EYE:WIDTh CHAN1")
            scope.write(":MEASure:EYE:HEIGht CHAN1")
            time.sleep(0.5)

        if is_sim:
            if random.random() < 0.15:
                fail_type = random.choice(list(special_cases.keys()))
                print(f"[SYSTEM_CRITICAL] {special_cases[fail_type]['msg']} detected on SerDes Core")
                print("Final Status: FAIL")
                return "FAIL"

            # 시뮬레이션 : 6.6Gbps 기준 정상 범위 내 랜덤값 생성 (60% pass, 40% fail)
            if random.random() < 0.4:

                fail_type = random.choice(list(phy_err_map.keys()))

                # 1. BOOT, WATCHDOG, LINK 등 시스템 결함 특수 케이스 ㅓ리
                if fail_type in special_cases:
                    case_info = special_cases[fail_type]
                    if case_info.get("action"):
                        set_ic_state(case_info["action"])
                    print(f"[SYSTEM_CRITICAL] {case_info['msg']} detected on SerDes Core")
                    print("Final Status: FAIL")
                    return "FAIL"
                else:

                    # 2. 일반 마진형 에러 데이터 시뮬레이션
                    w_factors = {'WIDTH': 0.5, 'HEIGHT': 1.0, 'SI': 0.75, 'SKEW': 0.9}
                    h_factors = {'WIDTH': 1.0, 'HEIGHT': 0.65, 'SI': 0.75, 'SKEW': 0.95}

                    eye_width = 140e-12 * w_factors.get(fail_type, 0.0)
                    eye_height = 0.42 * h_factors.get(fail_type, 0.0)
            else:
                eye_width, eye_height = 140e-12, 0.42  # 정상 동작

        else:
            # 실제 장비 측정 로직
            raw_width = scope.query(":MEASure:EYE:WIDTh?").strip()
            raw_height = scope.query(":MEASure:EYE:HEIGht?").strip()

            # 문자열에서 숫자만 추출
            def safe_float(val):
                # 문자열 중 숫자와 마침표만 남깁니다.
                filtered = "".join(c for c in val if c.isdigit() or c == '.')
                # 결과가 비었으면 0.0을 아니면 float으로 반환합니다.
                return float(filtered) if filtered else 0.0

            eye_width = safe_float(raw_width)
            eye_height = safe_float(raw_height)

        # 단위 변환 출력(ps,mV)
        print(f" > Eye Width  : {eye_width * 1e12:.1f} ps")
        print(f" > Eye Height : {eye_height * 1000:.1f} mV")

        # 1. 최우선 판정: SYNC LOSS (0X305 기본)
        if eye_width == 0 or eye_height == 0:
            # 2. get()을 사용하여 fail_type에 맞는 코드를 가져오고, 없으면 기본값 SYNC("0X305") 반환
            selected_code = phy_err_map.get(fail_type, phy_err_map['SYNC'])
            print(hs_config["RAW_LOGS"].get(selected_code))
            print("Final Status: FAIL")
            return "FAIL"

        # 2. 전반적 신호 무결성 체크 (0X304)
        # width와 height가 둘 다 spec에 간당간당하면 SI 문제로 판정
        if eye_width < 115e-12 and eye_height < 0.33:
            print(hs_config["RAW_LOGS"][phy_err_map['SI']])
            return "FAIL"

        # 3. 개별 스펙 판정 기준: 6.6Gbps 기준 eye가 충분히 열리는지 확인
        # Skew 이슈일 때는 w_low_code를 0x701로, 아니면 일반 0x301로 설정
        w_low_code = phy_err_map['SKEW'] if fail_type == 'SKEW' else phy_err_map['WIDTH']
        # Width 판정: 120ps 기준 (오차 5% 적용 시 약 114ps~126ps 지만, 여기선 단방향 하한선 검증으로 활용)
        # 0X301(Low), 0X399(High-의미없음)
        width_status = check_spec_and_report(eye_width, 140e-12, 0.15, w_low_code, None, "s", domain="HIGH_SPEED")

        # Height 판정: 0.35V 기준
        # 0X302(Low), 0X399(High-의미없음)
        height_status = check_spec_and_report(eye_height, 0.40, 0.15, phy_err_map['HEIGHT'], None, "V",
                                              domain="HIGH_SPEED")

        # 3. 최종 결과
        status = "PASS" if (width_status == "PASS" and height_status == "PASS") else "FAIL"
        print(f"Final Status: {status}")
        return status

    except Exception as e:
        print(f" > [Error] PHY Analysis 도중 오류 발생: {e}")
        return "FAIL"


# [C] Register Read/Write 판정 (TC004,005,006)
virtual_ram = {}
def test_ram_storage(scope, addr_start, addr_end):
    print(f"\n[Mode] Register R/W: {addr_start} ~ {addr_end}")

    # 통합 공통 함수 호출
    if not safe_setup_scope(scope):
        return "FAIL"

    # 글로벌 관리 맵 매핑
    reg_config = GLOBAL_ERROR_CONFIG["REGISTER"]
    reg_err_map = reg_config["ERR_MAP"]
    reg_sim_vals = reg_config["SIM_VALS"]

    all_pass = True

    # 초기화
    err_addr, err_w, err_r = "", "", ""

    # 주소를 문자열(0X00)에서 정수로 변환하여 루프 실행
    start_int = int(addr_start, 16)
    end_int = int(addr_end, 16)
    status = "PASS"

    # 시뮬레이션: 30% 확률로 특정 주소에서 불량 발생시키기
    is_fail_test = random.random() < 0.3 if IS_SIM else False
    fail_target_addr = random.randint(start_int, end_int) if is_fail_test else -1
    selected_fault = random.choice(list(reg_err_map.keys())) if is_fail_test else None

    for addr in range(start_int, end_int + 1):
        write_val = 0XAA  # 검증용 고정 패턴
        read_val = write_val

        # 불량 대상 주소라면 의도적으로 다른 값을 읽게 함
        if addr == fail_target_addr and selected_fault:
            # 딕셔너리에서 에러 코드에 맞는 값을 가져옴 (없으면 기본 write_val 유지)
            read_val = reg_sim_vals.get(selected_fault, 0X00)

        # 공통 함수 호출 (0X401)
        res = check_reg_match(addr, write_val, read_val, reg_err_map[selected_fault])
        if res == "FAIL":
            status = "FAIL"
            break  # 첫 번째 에러 발생 시 중단

    # 정상 주소들은 그냥 통과 (로그 없음)

    if status == "PASS":
        print(f" < [SPEC OK] ALL Registers Verified ({hex(start_int)}~{hex(end_int)})")

    print(f"Final Status: {status}")
    return status


# [D] Voltage Sweep & 소비전력 (TC007,008,010)
def test_power_sweep(scope, v_start, v_end, v_step, unit, mode="SWEEP"):
    # 변수 초기화
    raw_v = "0.0"
    raw_i = "0.0"
    measured_v = 0.0
    measured_i = 0.0
    power_mw = 0.0
    sweep_pass = True
    err_code, err_msg = "", ""
    current_v = v_start

    # mode에 따라 출력 문구 변경
    title = "Sweep Test" if mode == "SWEEP" else "Single Check"
    print(f"\n[Mode] Power Consumption Sweep: {v_start}{unit} to {v_end}{unit} (Step: {v_step}{unit})")

    # sweep 시작 전 장비 셋팅 단계에서 타임 아웃 발생시 0X502처리

    success, is_ks, is_tk = safe_setup_scope(scope)  # 장비 셋팅 미 모델 식별
    if not success:
        return "FAIL"

    res_name = getattr(scope, 'resource_name', "")
    is_sim = IS_SIM or ("@sim" in res_name)

    # VOLTAGE 맵 가져오기
    volt_config = GLOBAL_ERROR_CONFIG["VOLTAGE"]
    volt_err_map = volt_config["ERR_MAP"]
    special_cases = volt_config["SPECIAL_CASES"]

    # 3. sweep 루프 실행
    # 스텝이 0인 경우 방지(무한 루프 방지)
    if v_step == 0 and mode == "SWEEP":
        print(" > [ERROR] Sweep Step은 0일 수 없습니다.")
        return "FAIL"

    max_retries = 3  # 최대 재시도 횟수 설정

    while True:
        # 루프 종료 조건 (양수 스텝/음수 스텝 모두 대응)
        if v_step > 0 and current_v > v_end + 0.01: break
        if v_step < 0 and current_v < v_end - 0.01: break
        if v_step == 0 and mode == "SWEEP": return "FAIL"

        time.sleep(0.1)

        # 재시도 루프 도칩
        success_step = False  # 해당 스텝 측정 성공 여부 플래그

        # 각 스텝 시작 시 타임스탬프 기록
        step_start_time = time.time()

        for attempt in range(1, max_retries + 1):
            try:
                # 2초 타임 아웃 체크 (물리적 루프 지연 방어)
                if time.time() - step_start_time > 2.0:
                    # PyVISA 내장 타임아웃 예외 규격과 동일한 에러 강제 발생
                    raise pyvisa.errors.VisaIOError(pyvisa.constants.StatusCode.error_timeout)

                # 1. 전압 인가 (D-IC 레지스터 설정)
                # controller.set_voltage(current_v) #실제 전압 인가
                time.sleep(0.1)

                # 2. 실제 전압 측정 (오실로스코프/멀티미터 제조사별)
                # 변수 초기화
                measured_v = 0.0
                measured_i = 0.0
                power_mw = 0.0

                if is_sim:
                    # 시뮬레이션 용 랜덤 값
                    is_fail = random.random() < 0.2  # 스텝별 실패 확률은 낮게 설정
                    if not is_fail:
                        # 정상 동작 시뮬레이션
                        measured_v = current_v + random.uniform(-0.02, 0.02)
                        measured_i = abs(current_v) * 0.02
                    else:
                        # 글로벌 맵에 등록된 에러 키 중 하나를 타겟으로 선정
                        fail_case = random.choice(list(volt_err_map.keys()))

                        if fail_case in special_cases:
                            # OVER_I, LDO, LINK_ERR 등 특수 불량은 사전의 팩터(v_fact, i_fact)를 그대로 반영
                            measured_v = current_v * special_cases[fail_case]["v_fact"]
                            measured_i = special_cases[fail_case]["i_fact"]
                        else:
                            # 일반 HIGH, LOW, UNDER 등은 기본 배율 적용
                            v_factors = {'HIGH': 1.15, 'LOW': 0.92, 'UNDER': 0.5, 'SKEW_ERR': 1.01}

                            measured_v = current_v * v_factors.get(fail_case, 1.0)
                            measured_i = abs(current_v) * 0.02

                else:
                    # 실제 장비: 제조사별 쿼리 및 데이터 파싱
                    if is_ks:
                        raw_v = scope.query(":MEAS:VAV? CHAN1")
                        raw_i = scope.query(":MEAS:CURR? CHAN1")
                    elif is_tk:
                        # Tektronix: 측정 설정 후 값 읽기
                        scope.write('MEASU:IMM:TYPE MEAN')
                        raw_v = scope.query("MEASU:IMM:VAL?")
                        raw_i = "0.02"  # Tektronix 전류 측정 로직 (예시)

                    # 데이터 파싱
                    measured_v = float(str(raw_v).strip())  # 측정전압
                    measured_i = float(str(raw_i).strip())  # 측정전류

                # 성공적으로 측정했다면 재시도 루프 탈출
                success_step = True
                break

            # 장비 타임아웃 예외 집중 처리
            except (pyvisa.errors.VisaIOError, TimeoutError):
                print(f" > [TIMEOUT ERROR] 장비가 2초 동안 응답하지 않습니다. (시도 {attempt}/{max_retries})")
                if attempt == max_retries:
                    sys_config = GLOBAL_ERROR_CONFIG["SYSTEM"]
                    print(sys_config["RAW_LOGS"][sys_config["ERR_MAP"]["TIMEOUT"]])
                    return "FAIL"
                time.sleep(0.5)

            except Exception as e:
                print(f" > [Retry {attempt}/{max_retries}] 에러 발생: {e}")
                if attempt == max_retries:
                    print(" > [Final Fail] 재시도 횟수 초과.")
                    return "FAIL"
                time.sleep(0.5)  # 재시도 전 대기

        # 5. 소비전력 계산(P = V*I)
        if success_step:
            power_mw = abs(measured_v * measured_i * 1000)  # mA 단위 환산 시 1000 곱함

            # 6. 판정
            # 전압(각 스텝마다 +-0.2V 내외인지 확인. 0X103: Low, 0X102: High)
            v_stat = check_spec_and_report(measured_v, current_v, 0.2, volt_err_map["UNDER"], volt_err_map["HIGH"], "V",
                                           domain="VOLTAGE")

            # 전류 상한선 체크 (0X104: over current) - 0.1A(100mA) 기준 예시 (0X104)
            # 0X104 코드를 위해 목표를 0.05A로 잡고 오차를 100% 줘서 0.1A까지 상한선으로 잡음
            i_stat = check_spec_and_report(measured_i, 0.05, 1.0, None, volt_err_map["OVER_I"], "A", domain="VOLTAGE")

            # LDO 출력 사망 판정
            # 타겟 전압은 있는데 측정값이 0.1V 미만이면 강제로 0X105 에러 발생
            if current_v > 1.0 and measured_v < 0.1:
                print(volt_config["RAW_LOGS"][volt_err_map['LDO']])
                v_stat = "FAIL"

            # Parser 인식용 통합 데이터 한 줄 (이건 디버깅용으로 유지)
            print(f"[Tester] 데이터 요약: {measured_v:.2f}V | {measured_i:.3f}A | {power_mw:.1f}mW")

            # 전압이나 전류 둘 중 하나라도 FAIL이면 전체 Sweep FAIL 처리
            if v_stat == "FAIL" or i_stat == "FAIL":
                sweep_pass = False
                break  # 에러 발생시 즉시 중단

            # 7. 결과 출력
            print(
                f"[Tester] Step OK: V_Target {current_v:2f}{unit} | I_Meas {measured_i:.2f}{unit} | Power: {power_mw:.2f}{unit}")

        # SINGLE 모드 처리
        if mode == "SINGLE":
            break  # 단일 측정(TC_010)이면 한 번만 수행 후 루프 탈출

        # 다음 스텝 준비 (seep 모드일때만)
        current_v += v_step
        time.sleep(0.1)

    return "PASS" if sweep_pass else "FAIL"

    # [E] 시스템 초기화 확인 (TC_009)


def test_init_check(scope):
    print("\n[Mode] System Init/Connection Check")
    sys_config = GLOBAL_ERROR_CONFIG["SYSTEM"]
    sys_err_map = sys_config["ERR_MAP"]
    try:
        idn = scope.query('*IDN?')
        if idn:
            print(f" < [SYSTEM OK] Device: {idn.strip()}")
            return "PASS"
        else:
            print(sys_config["RAW_LOGS"][sys_err_map['IDENTIFY_FAIL']])
            return "FAIL"
    except:
        print(sys_config["RAW_LOGS"][sys_err_map['TIMEOUT']])
        return "FAIL"


def main():
    # 1. runner.py가 보낸 옵션 해석기 (argparse)
    parser = argparse.ArgumentParser()
    parser.add_argument("--voltage", type=float, default=-1.0)  # TC001
    parser.add_argument("--freq", type=float, default=-1.0)  # TC002
    parser.add_argument("--unit", type=str, default="V")  # TC003 #존재 여부만 판단
    parser.add_argument("--reg_rw", action="store_true")  # TC004
    parser.add_argument("--start_addr", type=str, default="0X00")  # TC005
    parser.add_argument("--end_addr", type=str, default="0X00")  # TC006
    parser.add_argument("--sweep", action="store_true")  # TC007
    parser.add_argument("--start_v", type=float, default=0.0)  # TC008
    parser.add_argument("--end_v", type=float, default=0.0)  # TC009
    parser.add_argument("--init_check", action="store_true")  # TC009
    parser.add_argument("--current_check", action="store_true")  # TC_010
    parser.add_argument("--step", type=float, default=1.0)  # TC010
    parser.add_argument("--address", type=str, default="")  # 장비 주소
    parser.add_argument("--phy", type=float, default=-1.0)  # 고속 인터페이스 속도 설정

    args = parser.parse_args()  # args.voltage 등에 값이 담김

    # 4. 공통 변수 및 초기화
    VOLT_TOLERANCE = 0.05  # 허용 오차 5%
    PHY_TOLERANCE = 0.15
    status = "FAIL"  # 기본 결과
    measured_val = 0.0  # 측정 초기값

    # 3. 장비 주소 결정 및 연결
    rm_path = '@sim' if IS_SIM else ''
    rm = pyvisa.ResourceManager(rm_path)  # 리소스 매니저 소환 (통로 열기)

    target_addr = args.address
    if not target_addr:
        resources = rm.list_resources()  # runner.py에서 주소 안줬으면 list 보여줌
        if resources:
            target_addr = resources[0]  # 0번 장비 자동 연결
            print(f"[Tester] 주소가 입력되지 않아 자동 연결을 시도합니다: {target_addr}")
        else:
            print("[Tester] 에러: 연결 가능한 장비가 없습니다.")
            sys.exit(1)

    try:
        # 장비 연결 및 타임아웃 설정
        scope = rm.open_resource(target_addr)

        # 주소에 @sim이 포함되어 있는지 확인
        is_sim = IS_SIM or ("@sim" in target_addr.lower())

        if is_sim:
            idn_info = "Simulation Mode (PyVISA-sim)"
            print(f"연결 성공: {idn_info}")
        else:
            try:
                idn_info = scope.query('*IDN?').strip()
                print(f"연결 성공: {idn_info}")
            except:
                idn_info = "Unknown Device"
                print("연결 성공: 장비 정보를 가져올 수 없습니다.")

        scope.timeout = 2000

        # 4. 조건에 따른 함수 호출
        # IS_SIM 모드일 때는 각 함수 내부에서 가상의 데이터를 생성합니다.
        if args.init_check:
            # 시스템 초기화 확인 (TC009)
            status = "PASS" if idn_info else "FAIL"
        elif args.voltage > 0:
            # 전압 측정 (TC_001, 002)
            status = test_voltage(scope, args.voltage, args.unit, VOLT_TOLERANCE)

        elif args.phy > 0 or args.freq > 0:
            # PHY/고속 인터페이스 : 변수명을 phy로 통일하거나 둘 다 체크
            target_speed = args.phy if args.phy > 0 else args.freq
            status = test_high_speed_interface(scope, target_speed, args.unit)

        elif args.reg_rw:
            # 레지스터 R/W 검증 (TC_005, 006)
            status = test_ram_storage(scope, args.start_addr, args.end_addr)

        elif args.sweep:
            # 전압 스윕 측정 (TC_007, 008)
            status = test_power_sweep(scope, args.start_v, args.end_v, args.step, args.unit)

        elif args.current_check:
            # 소비전력 단일 측정 (TC_010)
            # v_start, v_end를 도일하게 주어 1회만 측정하게 유도
            status = test_power_sweep(scope, 1.2, 1.2, 0.0, args.unit, mode="SINGLE")

        # 5. 결과 보고 및 종료

        scope.close()
        print(f"최종 결과: {status}")
        if status == "PASS":
            sys.exit(0)
        else:
            sys.exit(1)

    except Exception as e:
        print(f"[Tester] 에러 발생: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
