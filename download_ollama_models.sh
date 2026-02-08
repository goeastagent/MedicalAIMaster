#!/bin/bash
# ============================================================
# Ollama 모델 다운로드 스크립트
# ============================================================
# 멀티모델 비교 테스트를 위한 모든 모델을 다운로드합니다.
# 
# 사용법:
#   chmod +x download_ollama_models.sh
#   ./download_ollama_models.sh
#
# 총 용량 예상: ~120GB (모든 모델 다운로드 시)
# ============================================================

set -e

echo "============================================================"
echo "🚀 Ollama 모델 다운로드 시작"
echo "============================================================"
echo ""

# Ollama 실행 확인
if ! command -v ollama &> /dev/null; then
    echo "❌ Ollama가 설치되어 있지 않습니다."
    echo "   brew install ollama 로 설치해주세요."
    exit 1
fi

# Ollama 서버 실행 확인
if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "⚠️  Ollama 서버가 실행 중이지 않습니다."
    echo "   다른 터미널에서 'ollama serve' 를 실행해주세요."
    echo ""
    read -p "서버 실행 후 Enter를 눌러 계속하세요..."
fi

# ============================================================
# 다운로드할 모델 목록
# ============================================================

# 코딩 특화 모델
CODING_MODELS=(
    "qwen2.5-coder:7b"
    "qwen2.5-coder:14b"
    "codestral:22b"
    "deepseek-coder-v2:16b"
    "starcoder2:7b"
    "codellama:7b"
)

# 범용 모델
GENERAL_MODELS=(
    "qwen2.5:7b"
    "qwen2.5:14b"
    "qwen2.5:32b"
    "llama3.1:8b"
    "mistral:7b"
    "mixtral:8x7b"
)

# 전체 모델 목록
ALL_MODELS=("${CODING_MODELS[@]}" "${GENERAL_MODELS[@]}")

echo "📋 다운로드할 모델 목록 (총 ${#ALL_MODELS[@]}개):"
echo ""
echo "=== 코딩 특화 모델 ==="
for model in "${CODING_MODELS[@]}"; do
    echo "  - $model"
done
echo ""
echo "=== 범용 모델 ==="
for model in "${GENERAL_MODELS[@]}"; do
    echo "  - $model"
done
echo ""
echo "============================================================"
echo ""

# 사용자 확인
read -p "모든 모델을 다운로드하시겠습니까? (y/n): " confirm
if [[ $confirm != "y" && $confirm != "Y" ]]; then
    echo "취소되었습니다."
    exit 0
fi

echo ""

# ============================================================
# 다운로드 실행
# ============================================================

SUCCESS_COUNT=0
FAIL_COUNT=0
FAILED_MODELS=()

for model in "${ALL_MODELS[@]}"; do
    echo "------------------------------------------------------------"
    echo "📥 다운로드 중: $model"
    echo "------------------------------------------------------------"
    
    if ollama pull "$model"; then
        echo "✅ 완료: $model"
        ((SUCCESS_COUNT++))
    else
        echo "❌ 실패: $model"
        ((FAIL_COUNT++))
        FAILED_MODELS+=("$model")
    fi
    
    echo ""
done

# ============================================================
# 결과 요약
# ============================================================

echo "============================================================"
echo "📊 다운로드 완료"
echo "============================================================"
echo "✅ 성공: $SUCCESS_COUNT 개"
echo "❌ 실패: $FAIL_COUNT 개"

if [ $FAIL_COUNT -gt 0 ]; then
    echo ""
    echo "실패한 모델:"
    for model in "${FAILED_MODELS[@]}"; do
        echo "  - $model"
    done
fi

echo ""
echo "============================================================"
echo "📋 설치된 모델 목록:"
echo "============================================================"
ollama list

echo ""
echo "🎉 완료! 이제 compare_models.py를 실행할 수 있습니다."
