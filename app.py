import streamlit as st
import pandas as pd
import os
import glob

# 1. 페이지 기본 설정 및 타이틀
st.set_page_config(layout="wide")
st.title("Silicon Bring-up Verification Dashboard")
st.markdown("D-IC 및 T-Con 하드웨어 검증 이력 분석 데이터입니다.")

# 기본 베이스 경로 설정 (parser.py와 동일 위치 가동용)
BASE_PATH = os.path.dirname(os.path.abspath(__file__))

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
target_file = os.path.join(BASE_PATH, "verification_history.csv")
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
        st.markdown("차수별 불량 합계 추이(Total Fail Line)")
        # Total_Fail 열만 선택하여 선 그래프 생성
        st.line_chart(chart_df['Total_Fail'], use_container_width=True)

    with col2:
        st.markdown("카테고리별 불량 누적 분석 (Failure Category Bar)")
        # 주요 불량 카테고리 열들만 선택하여 누적 막대 그래프 생성
        error_categories = ['PHY', 'CLOCK', 'VOLTAGE', 'REG', 'POWER', 'SYSTEM']
        # 데이터에 해당 컬럼이 존재하는지 검토 후 차트 렌더링
        available_cols = [col for col in error_categories if col in chart_df.columns]
        st.bar_chart(chart_df[available_cols], use_container_width=True)

    st.markdown("---")

    # 8. 실시간 불량 로그 스트리밍 디버거
    st.subheader("실시간 불량 로그 스트리밍 디버거")
    # 8-1. 유저가 상단 표를 보며 분석하고 싶은 특정 회차(세션)를 선택할 수 있게 바인딩
    session_options = filtered_df['Date'].astype(str).tolist()

    col_sel1, col_sel2 = st.columns([2, 2])
    with col_sel1:
        selected_session = st.selectbox("📄 분석할 검증 회차(세션) 선택", options=session_options)
    with col_sel2:
        selected_cat = st.selectbox("🎯 추적할 불량 카테고리 선택", options=error_categories)

    # 8-2. 선택된 회차에 해당하는 상세 분석 결과 CSV 파일 경로 추적 연동
    target_session_dir = os.path.join(BASE_PATH, f"D-IC_Mobile_Project_Results_{selected_session}")
    detail_csv_pattern = os.path.join(target_session_dir, f"Final_Analysis_{selected_session}.csv")
    detail_csv_files = glob.glob(detail_csv_pattern)

    real_log_text = ""

    # 8-3. 실제 상세 불량 파일이 존재할 경우 실시간 로드 및 매핑
    if detail_csv_files and os.path.exists(detail_csv_files[0]):
        # parser.py가 수집한 상세 불량 내역 개방
        df_detail = pd.read_csv(detail_csv_files[0], encoding='utf-8-sig')

        if not df_detail.empty:
            # 사용자가 선택한 불량 카테고리 행들만 정밀 필터링
            df_filtered_detail = df_detail[df_detail['category'] == selected_cat]

            if not df_filtered_detail.empty:
                log_lines = []
                for idx, row in df_filtered_detail.iterrows():
                    # [소스 파일명] 에러 메시지 조합하여 실제 하드웨어 원문 로그 복원 스트리밍
                    log_lines.append(f"[{row['file']}] {row['msg']}")
                real_log_text = "\n".join(log_lines)
            else:
                real_log_text = f"[알림] {selected_session} 회차에서 [{selected_cat}] 관련 검출 불량 로그가 없습니다."
        else:
            real_log_text = "[알림] 해당 회차에 분석할 에러 데이터가 존재하지 않습니다. (ALL PASS)"
    else:
        real_log_text = f"[경고] 상세 불량 분석 파일이 누락되었거나 경로를 찾을 수 없습니다.\n대상 경로: {detail_csv_pattern}"

    # 8-4. 터미널 스타일의 화면 패널에 진짜 날것의 장비 로그 사출
    st.text_area(
        label=f"[{selected_cat}] 분석 파트 실시간 검증 로그 원문 (RAW LOG)",
        value=real_log_text,
        height=200,
        disabled=False  # 프리랜서/엔지니어가 즉시 복사하여 FA 진행할 수 있게 활성화
    )


else:
    st.warning(f"대시보드에 표시할 데이터 파일({target_file})이 존재하지 않습니다. 먼저 분석기(parser.py)를 구동하여 이력을 쌓아주세요")

