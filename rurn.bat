@echo off
title D-IC Automated Verification System
echo ==================================================
echo   D-IC Automated Verification System Starting...
echo ==================================================

:: 1. 가상환경 자동 활성화 (.venv 폴더 환경 기준)
call .venv\Scripts\activate

:: 2. 총사령관 스크립트 실행 (테스트 -> 파싱 -> 대시보드 자동 연결)
python main.py

pause