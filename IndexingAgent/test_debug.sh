#!/bin/bash
# test_debug.sh
# 디버그 모드로 테스트 실행

echo "=========================================="
echo "🐛 디버그 모드 테스트"
echo "=========================================="

# 1. 캐시 클리어 (깨끗한 상태)
echo ""
echo "🗑️  캐시 클리어..."
rm -rf data/cache/llm/*
rm -rf data/processed/ontology_db.json

echo "✅ 클리어 완료"

# 2. PostgreSQL 초기화 (테이블 삭제)
echo ""
echo "🐘 PostgreSQL 테이블 클리어..."

psql -U postgres -d medical_data -c "DROP TABLE IF EXISTS clinical_data_table CASCADE;" 2>/dev/null
psql -U postgres -d medical_data -c "DROP TABLE IF EXISTS lab_data_table CASCADE;" 2>/dev/null

echo "✅ 테이블 클리어 완료"

# 3. 테스트 실행
echo ""
echo "▶️  Agent 실행 (디버그 로그 포함)..."
echo ""

python test_agent_with_interrupt.py

# 4. 결과 확인
echo ""
echo "=========================================="
echo "📊 결과 확인"
echo "=========================================="

echo ""
echo "1️⃣  PostgreSQL 테이블:"
psql -U postgres -d medical_data -c "\dt"

echo ""
echo "2️⃣  테이블별 행 개수:"
psql -U postgres -d medical_data -c "SELECT 'clinical_data_table' as table_name, COUNT(*) as row_count FROM clinical_data_table UNION ALL SELECT 'lab_data_table', COUNT(*) FROM lab_data_table;" 2>/dev/null || echo "⚠️  일부 테이블 누락"

echo ""
echo "3️⃣  온톨로지:"
python view_ontology.py | head -30

echo ""
echo "=========================================="
echo "✅ 디버그 테스트 완료"
echo "=========================================="

