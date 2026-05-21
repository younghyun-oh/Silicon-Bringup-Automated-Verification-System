@echo off
chcp 65001 >nul
title HW Verification Automation System
echo ==========================================
echo   HW 검증 및 리포트 자동화 시스템 가동
echo ==========================================

:: 1. 가상환경 내의 파이썬 경로 설정 (본인의 프로젝트 경로에 맞춰 수정하세요)
set PYTHON_EXE="C:\Users\오영현\PycharmProjects\YH_PP\.venv\Scripts\python.exe"

:: 2. 테스트 실행 (runner.py)
echo [STEP 1] 검증 시나리오 실행 중...
%PYTHON_EXE% "C:\Users\오영현\PycharmProjects\YH_PP\runner.py"

:: 3. 데이터 분석 및 리포트 생성 (parser.py)
echo [STEP 2] 데이터 분석 및 리포트 생성 중...
%PYTHON_EXE% "C:\Users\오영현\PycharmProjects\YH_PP\parser.py"

echo ==========================================
echo   모든 작업이 완료되었습니다.
echo ==========================================
pause