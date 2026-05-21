import streamlit as st
import pandas as pd
import os

# 1. 페이지 기본 설정 및 타이틀
st.set_page_config(layout="wide")
st.title("Silicon Bring-up Verification Dashboard")
st.markdown("D-IC 및 T-Con 하드웨어 검증 이력 분석 데이터입니다.")


# 2. 데이터 로드 함수 및 날짜 전처리 함수
def load_history_data(file_path):
    """지정된 CSV 파일을 읽어와 데이터 프레임으로 반환합니다."""
    if os.path.exists(file_path):
        # 인코딩 충돌 방지를 위해 utf-8-sig 사용
        df = pd.read_csv(file_path, encoding='utf-8-sig')
        if not df.empty and 'Date' in df.columns:
            # 문자열 앞 8자리를 추출하여 판다스 날짜 객체(datetime) 컬럼 신설
            df['Clean_Date'] = pd.to_datetime(df['Date'].astype(str).str[:8], format='%Y%m%d', errors='coerce')
        return df
    return pd.DataFrame()


# 3. 데이터로드 및 화면 출력
target_file = "verification_history.csv"
history_df = load_history_data(target_file)

if not history_df.empty:
    # 4. 좌측 사이드바 필터 UI 구성
    st.sidebar.header("검증 데이터 필터")

    min_date = history_df['Clean_Date'].min()
    max_date = history_df['Clean_Date'].max()

    # 사용자가 달력에서 시작일과 종료일을 세트로 픽할 수 있도록 설정
    date_range = st.sidebar.date_input(
        "분석 기간(Daily) 선택",
        value=[min_date, max_date],
        min_value=min_date,
        max_value=max_date
    )

    # 달력에서 시작일과 종료일이 모두 정상 선택되었는지 검증 후 필터링 진행
    if len(date_range) == 2:
        start_date, end_date = date_range
        # 판다스 데이터프레임 조건 조건 검색 (시작일과 종료일 사이의 행들만 추출)
        filtered_df = history_df[
            (history_df['Clean_Date'] >= pd.to_datetime(start_date)) &
            (history_df['Clean_Date'] <= pd.to_datetime(end_date))
            ]
    else:
        # 종료일을 아직 누르지 않은 단일 선택 상태일 때는 전체 데이터 유지
        filtered_df = history_df

    # 6. 필터링된 데이터 표 출력
    st.subheader(" 검증 차수별 데이터 내역")
    # Streamlit 전용 데이터 테이블 컴포넌트로 데이터 출력
    st.dataframe(filtered_df.drop(columns=['Clean_Date']), use_container_width=True)

    # 6-1. 실시간 요약 리포트 자동 생성 및 다운로드 기능
    # 사용자가 선택한 필터 조건에 맞춰 텍스트 내용이 실시간으로 빌드됩니다.
    total_records = len(filtered_df)
    avg_fail = round(filtered_df['Total_Fail'].mean(), 1) if total_records > 0 else 0

    # 우측 상단이나 표 하단에 자연스럽게 배치하기 위한 컬럼 분할
    rc_col1, rc_col2 = st.columns([6, 1])
    with rc_col1:
        st.markdown(f"현재 선택된 차수: 총 {total_records}건 / 전체 {len(history_df)}건")
    with rc_col2:
        with rc_col2:
            # 1. 엑셀/HTML 리포트 스타일의 구조화된 텍스트 문서 빌드
            # 사용자가 달력으로 필터링한 데이터(filtered_df)를 기반으로 가공됩니다.
            report_lines = []
            report_lines.append("======================================================================")
            report_lines.append("                  BRING-UP SYSTEM VERIFICATION REPORT                 ")
            report_lines.append("======================================================================")
            report_lines.append(f"[발행일자] 2026-05-18 | [프로젝트명] D-IC_Mobile_Project")
            report_lines.append(f"[조회기간] {start_date} ~ {end_date}")
            report_lines.append("----------------------------------------------------------------------")
            report_lines.append("")
            report_lines.append("1. SUMMARY STATISTICS")
            report_lines.append("┌───────────────────────────┬───────────────────────────┐")
            report_lines.append(f"│  Selected Test Batches    │          {str(total_records).ljust(17)} EA │")
            report_lines.append("├───────────────────────────┼───────────────────────────┤")
            report_lines.append(f"│  Average Failure Count    │          {str(avg_fail).ljust(17)} EA │")
            report_lines.append("└───────────────────────────┴───────────────────────────┘")
            report_lines.append("")
            report_lines.append("2. FAILURE CATEGORY MATRIX")
            report_lines.append("┌─────────────────┬─────────────────┬─────────────────┐")
            report_lines.append("│    Category     │   Total Fails   │     Status      │")
            report_lines.append("├─────────────────┼─────────────────┼─────────────────┤")

            # 각 카테고리별 합계를 구해 표 내부를 동적으로 채움
            err_categories = ['VOLTAGE', 'POWER', 'REG', 'PHY', 'CLOCK', 'SYSTEM']
            for cat in err_categories:
                if cat in filtered_df.columns:
                    cat_total = filtered_df[cat].sum()
                    # 불량 개수에 따른 상태 등급 분류 (방어 코드 및 라벨링)
                    status = "CRITICAL" if cat_total > 50 else ("WARN" if cat_total > 10 else "NORMAL")

                    report_lines.append(
                        f"| {cat.ljust(15)} | {str(cat_total).ljust(15)} | {status.ljust(15)} | "
                    )
            report_lines.append("└─────────────────┴─────────────────┴─────────────────┘")
            report_lines.append("")
            report_lines.append("3. ENGINEERING ACTION ITEM")
            if total_records > 0 and filtered_df['VOLTAGE'].sum() > 50:
                report_lines.append(" * High fail rate observed in VOLTAGE. ")
                report_lines.append(" * Recommend checking PMIC ripple and decoupling capacitor stability.")
            else:
                report_lines.append(" * System status remains within stable validation margins.")
            report_lines.append("======================================================================")

            # 줄바꿈 기호로 리스트를 하나의 문자열로 결합
            final_report_string = "\n".join(report_lines)

            # 2. 정식 다운로드 버튼 배치
            st.download_button(
                label=" 리포트 내보내기",
                data=final_report_string,
                file_name=f"Verification_Report_{start_date}_to{end_date}.txt",
                mime="text/plain",
                use_container_width=True
            )
    st.markdown("---")

    # 7. 동적 그래프 시각화 영역
    st.subheader("실시간 failure 트렌드 분석")

    # 차트용 데이터 가공: Date를 인덱스로 세팅해야 X축에 날짜가 바르게 매핑됩니다.
    chart_df = filtered_df.set_index('Date')

    # 두 개의 컬럼(열)으로 화면 분할 (좌측: 수율 추이 선 그래프, 우측: 카테고리별 불량 막대 그래프)
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("차수별 불량 합계 추이(Total Fail Line")
        # Total_Fail 열만 선택하여 선 그래프 생성
        st.line_chart(chart_df['Total_Fail'], use_container_width=True)

    with col2:
        st.markdown("카테고리별 불량 누적 분석 (Failure Category Bar")
        # 주요 불량 카테고리 열들만 선택하여 누적 막대 그래프 생성
        error_categories = ['PHY', 'CLOCK', 'VOLTAGE', 'REG', 'POWER', 'SYSTEM']
        # 데이터에 해당 컬럼이 존재하는지 검토 후 차트 렌더링
        available_cols = [col for col in error_categories if col in chart_df.columns]
        st.bar_chart(chart_df[available_cols], use_container_width=True)

    st.markdown("---")

    # 8. 실시간 불량 로그 스트리밍 디버거
    st.subheader("실시간 불량 로그 스트리밍 디버거")

    # 카테고리 선택용 싱글 셀렉트 박스 생성
    selected_cat = st.selectbox("추적할 불량 카테고리 선택", options=error_categories)

    # 가상의 에러 로그 파일 매핑 데이터 (실제 프로젝트 폴더 내 록 파일로 연동 가능)
    # 여기서는 매니저가 선택한 카테고리에 맞춰 동적으로 원문 로그 시뮬레이션을 생성합니다.
    mock_log_directory = {
        "PHY": "[ERROR] 6.6Gbps High-Speed Interface Link Training Failure\n[INFO] Lane 0: Eye Diagram Height Violation (vco_cal_done=1)\n[DEBUG] CDR Lock Loss detected at Address 0x3F",
        "CLOCK": "[ERROR] System Clock 1.2GHz Check Failed\n[WARN] External OSC Jitter Out of Specification\n[DEBUG] PLL Locked Status: 0 (Unstable)",
        "VOLTAGE": "[ERROR] Negative Voltage Sweep Test Out of Range\n[INFO] Target: -5.0V, Measured: -1.2V\n[CRITICAL] LDO Hardware Shutdown Triggered",
        "REG": "[ERROR] Register Full Bank Scan Mismatch\n[INFO] Address 0x4A - Write: 0xFF, Read: 0x00 (Bit Flip Error)",
        "POWER": "[ERROR] Main Power 1.2V Check Failure\n[WARN] Current Draw exceeds 450mA (Overcurrent Condition)",
        "SYSTEM": "[ERROR] Total System Power Consumption Alert\n[CRITICAL] Thermal Throttling Activated due to High Leakage Current"
    }

    # 선택된 카테고리의 원문 로그 가져오기
    target_log_text = mock_log_directory.get(selected_cat, "해당 카테고리의 에러 로그가 존재하지 않습니다.")

    # 터미널 스타일의 고정 폭 폰트로 로그 원문 스트리밍 출력
    st.text_area(
        label=f"[{selected_cat}] 분석 파트 실시간 검증 로그 원문 (RAW LOG)",
        value=target_log_text,
        height=150,
        disabled=False  # 매니저가 드래그하여 복사할 수 있도록 활성화
    )



else:
    st.warning(f"대시보드에 표시할 데이터 파일({target_file})이 존재하지 않습니다. 먼저 분석기(paser.py)를 구동하여 이력을 쌓아주세요")

