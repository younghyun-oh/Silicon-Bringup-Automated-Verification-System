#!/bin/bash
echo "=================================================="
echo "  D-IC Automated Verification System (Linux Mode) "
echo "=================================================="

# 1. 리눅스 환경 가상환경(.venv) 존재 여부 검증 및 활성화
if [ -d ".venv" ]; then
    source .venv/bin/activate
    echo "-> 가상환경(.venv) 활성화 완료."
else
    echo "[경고] .venv 폴더가 없습니다. 시스템 기본 python3으로 실행을 시도합니다."
fi

# 2. 통합 총사령관 스크립트 실행
python3 main.py

# 3. 세션 유지용 대기 코드
echo ""
echo "Press [Enter] key to close..."
read