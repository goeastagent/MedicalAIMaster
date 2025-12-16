#!/bin/bash
# run_with_postgres.sh
# PostgreSQL 서버 관리 스크립트
# 
# 실행: PostgreSQL 시작 및 대기
# Ctrl-C: PostgreSQL 종료

set -e  # 에러 시 중단

echo "=========================================="
echo "🐘 PostgreSQL 서버 관리"
echo "=========================================="

# PostgreSQL 설정
PG_DATA_DIR="./data/postgres_data"
PG_LOG_FILE="./data/postgres.log"
PG_PORT=5432
PG_PID_FILE="./data/postgres.pid"

# Cleanup 함수 (Ctrl-C 시 호출)
cleanup() {
    echo ""
    echo "=========================================="
    echo "🛑 종료 신호 감지 (Ctrl-C)"
    echo "=========================================="
    
    # PostgreSQL 종료
    if [ -f "$PG_PID_FILE" ]; then
        PG_PID=$(cat $PG_PID_FILE)
        
        if kill -0 $PG_PID 2>/dev/null; then
            echo "🐘 PostgreSQL 종료 중 (PID: $PG_PID)..."
            
            # SIGTERM 전송 (정상 종료)
            kill -TERM $PG_PID
            
            # 종료 대기 (최대 10초)
            for i in {1..10}; do
                if ! kill -0 $PG_PID 2>/dev/null; then
                    echo "✅ PostgreSQL 정상 종료됨"
                    break
                fi
                sleep 1
            done
            
            # 아직 살아있으면 강제 종료
            if kill -0 $PG_PID 2>/dev/null; then
                echo "⚠️  응답 없음 - 강제 종료 중..."
                kill -9 $PG_PID
                sleep 1
                echo "✅ PostgreSQL 강제 종료됨"
            fi
        else
            echo "⚠️  PostgreSQL 프로세스가 이미 종료되었습니다."
        fi
        
        rm -f $PG_PID_FILE
    else
        echo "⚠️  PID 파일 없음 (PostgreSQL이 실행 중이 아닐 수 있습니다)"
    fi
    
    echo "✅ 종료 완료"
    exit 0
}

# 시그널 트랩 설정 (Ctrl-C 감지)
trap cleanup SIGINT SIGTERM

# ==========================================
# 1. PostgreSQL 초기화 및 시작
# ==========================================

echo ""
echo "1️⃣  PostgreSQL 초기화 중..."

# 데이터 디렉토리가 없으면 생성
if [ ! -d "$PG_DATA_DIR" ]; then
    echo "📦 PostgreSQL 데이터 디렉토리 생성 중..."
    mkdir -p $(dirname $PG_DATA_DIR)
    
    # initdb (PostgreSQL 초기화)
    initdb -D $PG_DATA_DIR -U postgres --no-locale --encoding=UTF8
    
    echo "✅ 초기화 완료"
else
    echo "✅ 데이터 디렉토리 존재: $PG_DATA_DIR"
fi

echo ""
echo "2️⃣  PostgreSQL 시작 중..."

# PostgreSQL 시작 (포그라운드 아님, 백그라운드)
postgres -D $PG_DATA_DIR -p $PG_PORT > $PG_LOG_FILE 2>&1 &
PG_PID=$!

# PID 저장
echo $PG_PID > $PG_PID_FILE

echo "✅ PostgreSQL 시작됨 (PID: $PG_PID)"
echo "   - Port: $PG_PORT"
echo "   - Log: $PG_LOG_FILE"

# 시작 대기 (최대 10초)
echo "   - 시작 대기 중..."

for i in {1..10}; do
    if pg_isready -p $PG_PORT > /dev/null 2>&1; then
        echo "✅ PostgreSQL 준비 완료"
        break
    fi
    sleep 1
done

if ! pg_isready -p $PG_PORT > /dev/null 2>&1; then
    echo "❌ PostgreSQL 시작 실패"
    echo "로그 확인: cat $PG_LOG_FILE"
    cleanup
    exit 1
fi

# ==========================================
# 3. 데이터베이스 생성
# ==========================================

echo ""
echo "3️⃣  데이터베이스 생성 중..."

DB_NAME="medical_data"

# 데이터베이스 존재 확인
if psql -U postgres -p $PG_PORT -lqt | cut -d \| -f 1 | grep -qw $DB_NAME; then
    echo "✅ 데이터베이스 '$DB_NAME' 존재"
else
    echo "📦 데이터베이스 '$DB_NAME' 생성 중..."
    createdb -U postgres -p $PG_PORT $DB_NAME
    echo "✅ 데이터베이스 생성 완료"
fi

# ==========================================
# 4. .env 파일 설정
# ==========================================

echo ""
echo "4️⃣  환경변수 설정 중..."

# .env 파일 생성/업데이트
cat > .env.postgres << EOF
# PostgreSQL 설정
POSTGRES_HOST=localhost
POSTGRES_PORT=$PG_PORT
POSTGRES_DB=$DB_NAME
POSTGRES_USER=postgres
POSTGRES_PASSWORD=

# LLM 설정 (기존 .env에서 복사)
EOF

# 기존 .env에서 LLM 설정 복사
if [ -f ".env" ]; then
    grep "LLM_PROVIDER\|API_KEY" .env >> .env.postgres 2>/dev/null || true
fi

# .env 백업 후 교체
if [ -f ".env" ]; then
    mv .env .env.backup
    echo "   - 기존 .env 백업: .env.backup"
fi

mv .env.postgres .env
echo "✅ .env 파일 설정 완료"

# ==========================================
# 5. 대기 (Ctrl-C로 종료할 때까지)
# ==========================================

echo ""
echo "=========================================="
echo "✅ PostgreSQL 실행 중"
echo "=========================================="
echo ""
echo "📊 연결 정보:"
echo "   - Host: localhost"
echo "   - Port: $PG_PORT"
echo "   - Database: $DB_NAME"
echo "   - User: postgres"
echo ""
echo "🔌 Agent 실행 방법:"
echo "   python test_agent_with_interrupt.py"
echo ""
echo "🛑 종료 방법:"
echo "   Ctrl-C를 누르면 PostgreSQL이 종료됩니다."
echo ""
echo "----------------------------------------"
echo "대기 중... (Ctrl-C로 종료)"
echo "----------------------------------------"

# 무한 대기 (Ctrl-C까지)
while true; do
    # PostgreSQL이 살아있는지 체크
    if ! kill -0 $PG_PID 2>/dev/null; then
        echo ""
        echo "❌ PostgreSQL 프로세스가 예기치 않게 종료되었습니다."
        echo "로그 확인: cat $PG_LOG_FILE"
        cleanup
        exit 1
    fi
    
    sleep 2
done

# 여기까지 도달하지 않음 (Ctrl-C → cleanup 호출)

