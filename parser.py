import json
import re
import os
import glob
from datetime import datetime
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import sys


class HWLogAnalyzer:
    """HW 검증 로그 분석 및 리포트 생성을 담당하는 메인 클래스"""

    def __init__(self, project_name="D-IC_Mobile"):
        # 1. 초기 설정: 경로 및 정규식 정의
        self.base_path = os.path.dirname(os.path.abspath(__file__))
        self.target_dir = os.path.join(self.base_path, f"{project_name}_Project_Results")
        self.error_map_file = os.path.join(self.base_path, "error_map.json")

        # 2. 정규식 패턴 교정 (0x와 0X 모두 허용 / FAILED와 FAIL 모두 허용)
        self.ERROR_PATTERN = re.compile(r"\[ERROR\] Code:\s*(?P<code>0[xX]\w+), \s*Message:\s*(?P<msg>.*)")
        self.FAIL_RESULT_PATTERN = re.compile(r"(Result:\s*FAILED|최종 결과:\s*FAIL)")

        # 3. 에러 맵 로드
        self.error_map_upper = self._load_error_map()

    def _load_error_map(self):
        """에러 정의 JSON 파일 대문자 변환 (내부 전용 함수)"""
        if os.path.exists(self.error_map_file):
            with open(self.error_map_file, 'r', encoding='utf-8') as f:
                raw_map = json.load(f)
                return {str(k).upper().strip(): v for k, v in raw_map.items()}
        return {}

    def scan_all_logs(self):
        """로그 파일 스캔 및 데이터 수집"""
        try:

            # 1. 해당 폴더의 모든 .log 파일 목록 가져오기
            log_files = glob.glob(os.path.join(self.target_dir, "*.log"))
            total_count = len(log_files)  # 파일 개수 저장

            if total_count == 0:
                print(f"[경고] {self.target_dir} 폴더에 .log 파일이 없습니다.")
                return pd.DataFrame(), 0

            print(f"---총 {total_count}개의 로그 파일 분석 시작 ---")

            results = []

            for file_path in log_files:
                file_name = os.path.basename(file_path)

                # 파일의 수정 시간 가져오기
                file_date = datetime.fromtimestamp(os.path.getmtime(file_path)).strftime('%Y-%m-%d')
                is_file_failed = False
                error_detected = False

                with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()
                    # 1차 검사 : 규격화된 에러 패턴 매칭
                    matches = self.ERROR_PATTERN.finditer(content)
                    for match in matches:
                        error_detected = True
                        err_code = match.group("code").upper().strip()
                        err_msg = match.group("msg").strip()

                        # 에러 맵 매칭
                        info = self.error_map_upper.get(err_code)
                        if info:
                            category = info.get('category', 'UNKNOWN').upper()
                            description = info.get('description', f"Undefined Code: {err_code}")
                        else:
                            category = "UNKNOWN"
                            description = f"Undefined Code: {err_code}"

                        # 발견되면 파일명과 함께 저장
                        results.append({
                            "file": file_name,
                            "code": err_code,
                            "msg": err_msg,
                            "date": file_date,
                            "category": category,
                            "description": description
                        })
                    # 2차 검사 : 파일 내부에 FAILED 문구가 있는데 1차 에러 매칭에서 누락된 경우 (방어용 맵핑)
                    if self.FAIL_RESULT_PATTERN.search(content) or "FAIL" in content:
                        is_file_failed = True

                # 에러 코드는 없지만 결과가 FAILED인 경우, 강제로 분석 데이터에 누적 생성
                if is_file_failed and not error_detected:
                    # 파일명이나 테스트 항목명에 맞춰 카테고리 임의 유추 유연성 부여
                    upper_name = file_name.upper()
                    if "VOLTAGE" in upper_name or "POWER" in upper_name:
                        category = "VOLTAGE"
                    elif "CLOCK" in upper_name or "FREQ" in upper_name:
                        category = "CLOCK"
                    elif "REG" in upper_name:
                        category = "REG"
                    else:
                        category = "SYSTEM"
                    results.append({
                        "file": file_name,
                        "code": "0XFAIL",
                        "msg": "Test sequence terminated with FAIL status",
                        "date": file_date,
                        "category": category,
                        "description": f"자동 검출된 하드웨어 불량 항목 ({file_name})"
                    })

            return pd.DataFrame(results), total_count



        except Exception as e:  # <--- 에러 발생 시 처리
            print(f"[오류] 로그 스캔 중 예상치 못한 에러 발생: {e}")
            import traceback
            traceback.print_exc()
            return pd.DataFrame(), 0  # 빈 데이터프레임을 반환해서 main이 멈추지 않게 함

    def save_and_visualize(self, df, total_count):
        """결과 저장, 히스토리 업데이트 및 시각화"""
        now_str = datetime.now().strftime("%Y%m%d_%H%M")
        report_name = f"Final_Analysis_{now_str}.csv"  # 버그 방지를 위하 최상단 변수 선언

        # 1. 에러가 있을 때만 상세 CSV 저장
        if not df.empty:
            report_name = f"Final_Analysis_{now_str}.csv"  # 실행할때마다 고유 리포트 생성
            df.to_csv(report_name, index=False, encoding='utf-8-sig')
            print(f"[알림] 상세 분석 결과가 {report_name}에 저장되었습니다.")
        else:
            # 빈 데이터프레임 구조라도 저장하여 에러 방지
            empty_df = pd.DataFrame(columns=["file", "code", "msg", "date", "category", "description"])
            empty_df.to_csv(report_name, index=False, encoding='utf-8-sig')
            print(f"[알림] 검증 성공 혹은 분석할 에러 데이터가 없어 빈 요약 파일({report_name})을 생성했습니다.")

        # 2. [핵심] 에러 통계 내기 (Failure Triage)
        if not df.empty:
            category_counts = df['category'].value_counts()

            print("\n" + "=" * 40)
            print("      FAILURE TRIAGE REPORT")
            print("=" * 44)
            print(category_counts.to_string())
            print("-" * 40)
        else:
            print("\n" + "=" * 40)
            print("      FAILURE TRIAGE REPORT (NO ERRORS FOUND)")
            print("=" * 44)
            print("검출된 카테고리별 에러가 없습니다.")
            print("-" * 40)

        # 3. 요약 히스토리 파일에 누적 기록 (그래프용)
        history_file = "verification_history.csv"
        summary = {
            "Date": now_str,
            "Total_Fail": len(df),
            "VOLTAGE": (df['category'] == 'VOLTAGE').sum() if not df.empty else 0,
            "POWER": (df['category'] == 'POWER').sum() if not df.empty else 0,
            "CLOCK": (df['category'] == 'CLOCK').sum() if not df.empty else 0,
            "PHY": (df['category'] == 'PHY').sum() if not df.empty else 0,
            "SYSTEM": (df['category'] == 'SYSTEM').sum() if not df.empty else 0,
            "REG": (df['category'] == 'REG').sum() if not df.empty else 0
        }

        pd.DataFrame([summary]).to_csv(history_file, mode='a', index=False,
                                       header=not os.path.exists(history_file), encoding='utf-8-sig')

        print(f"\n[알림] {now_str} 차수 분석 결과가 {report_name}에 저장되었습니다.")
        print(f"[알림] 히스토리 파일 ({history_file})에 요약 데이터가 누적되었습니다.")

        # 4. 시각화 실행 (함수로 호출)
        self._generate_plots(history_file)
        # 요약리포트 실행 (함수로 호출)
        self._write_text_report(df, total_count)

    def _generate_plots(self, history_file):
        if not os.path.exists(history_file):
            print("시각화할 데이터가 없습니다.")
            return

        # 1. 데이터 로드
        df_history = pd.read_csv(history_file)
        if len(df_history) < 2:
            return

        sns.set_theme(style="whitegrid")
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))
        # 1. 차수별 불량 발생 추이 (Line Chart) ---
        # 각 날짜 / 시간별로 누적된 불량 개수 변화 확인
        df_melted = df_history.melt(id_vars='Date', value_vars=['VOLTAGE', 'POWER', 'CLOCK', 'PHY', 'SYSTEM', 'REG'],
                                    var_name='Category', value_name='Count')

        sns.lineplot(data=df_melted, x='Date', y='Count', hue='Category', marker='o', ax=ax1)
        ax1.set_title('Failure Trend by Iteration', fontsize=14)
        ax1.tick_params(axis='x', rotation=45)

        # --- 그래프 2: 전체 누적 불량 분포 (Pareto Bar Chart) ---
        # 어떤 카테고리가 가장 큰 문제인지 확인
        total_failures = df_history[['VOLTAGE', 'POWER', 'CLOCK', 'PHY', 'SYSTEM', 'REG']].sum().sort_values(
            ascending=False)

        sns.barplot(x=total_failures.index, y=total_failures.values, hue=total_failures.index, palette='viridis',
                    ax=ax2, legend=False)
        ax2.set_title('Total Failure Distribution (Pareto)', fontsize=14)
        ax2.set_ylabel('Total Occurrence')

        plt.tight_layout()

        # 그래프 파일 저장
        report_img = "Verification_Report_Visual.png"
        plt.savefig(report_img)
        print(f"\n[시각화] 대시보드 그래프가 저장되었습니다: {report_img}")
        # plt.show()

    def _write_text_report(self, df, total_logs):
        """오늘의 분석 결과를 텍스트 리포트로 요약 저장"""
        total_fails = len(df)
        pass_rate = ((total_logs - total_fails) / total_logs) * 100 if total_logs > 0 else 0

        with open("Final_Summary_Report.txt", "w", encoding="utf-8") as f:
            f.write("=" * 50 + "\n")
            f.write(f" HW VERIFICATION SUMMARY REPORT ({datetime.now().strftime('%Y-%m-%d')})\n")
            f.write("=" * 50 + "\n\n")
            f.write(f"1. Total Test Logs Scanned : {total_logs}\n")
            f.write(f"2. Total Failures Detected : {total_fails}\n")
            f.write(f"3. Estimated Yield (Pass %) : {pass_rate:.2f}%\n\n")
            if total_fails > 0:
                f.write("-" * 30 + "\n [Failure Triage Ranking]\n" + "-" * 30 + "\n")

                # 카테고리별 순위 기록
                counts = df['category'].value_counts()
                for i, (cat, count) in enumerate(counts.items(), 1):
                    f.write(f" Rank {i}: {cat:<10} | {count} cases\n")
            else:
                f.write("\n[결과] 모든 항목 PASS - 시스템 안정성 확인됨\n")

            f.write("\n" + "=" * 50 + "\n")
            f.write(" Report Generated by Automated Verification System\n")
            f.write("=" * 50 + "\n")

        print("\n[리포트] 요약 문서 (Final_Summary_Report.txt)가 생성되었습니다.")


def main():
    analyzer = HWLogAnalyzer(project_name="D-IC_Mobile")
    df_results, total_logs = analyzer.scan_all_logs()

    # 1. 스캔된 로그 자체가 없는 경우 (폴더 경로 오류 등)

    if total_logs == 0:
        print("분석할 로그 파일이 없어 종료합니다.")
        sys.exit(1)  # 실패 코드로 종료

    # 2. 로그는 있는데 에러가 없는 경우(all pass)
    if df_results.empty:
        print("\n[알림] 모든 테스트 항목이 pass 되었습니다. all pass 리포트를 생성합니다.")
        analyzer.save_and_visualize(df_results, total_logs)

    # 3. 에러가 발견된 경우
    else:
        analyzer.save_and_visualize(df_results, total_logs)

    # 모든 작업이 끝나고 성공코드 9를 반환
    sys.exit(9)


if __name__ == "__main__":
    main()
