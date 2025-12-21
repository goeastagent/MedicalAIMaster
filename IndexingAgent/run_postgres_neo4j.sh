#!/bin/bash
# run_postgres_neo4j.sh
# PostgreSQL + Neo4j 서비스 관리 스크립트
#
# 실행: PostgreSQL 및 Neo4j 시작 후 대기
# Ctrl-C: 두 서비스 모두 종료

set -e  # 에러 시 중단

echo "=========================================="
echo "🗄️  PostgreSQL & 🧠 Neo4j 서비스 관리"
echo "=========================================="

# PostgreSQL 설정
PG_DATA_DIR="./data/postgres_data"
PG_LOG_FILE="./data/postgres.log"
PG_PORT=5432
PG_PID_FILE="./data/postgres.pid"

# Neo4j 설정 (NEO4J_ENABLED=0 이면 비활성화)
NEO4J_ENABLED=${NEO4J_ENABLED:-1}
NEO4J_BIN=${NEO4J_BIN:-neo4j}
NEO4J_PID_FILE="./data/neo4j.pid"
NEO4J_LOG_FILE="./data/neo4j.log"

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

    # Neo4j 종료 (neo4j stop 명령어 사용)
    if lsof -i :7687 >/dev/null 2>&1 || [ -f "$NEO4J_PID_FILE" ]; then
        echo "🧠 Neo4j 종료 중..."
        
        # 1. neo4j stop 명령어로 정상 종료 시도
        if command -v "$NEO4J_BIN" >/dev/null 2>&1; then
            "$NEO4J_BIN" stop 2>/dev/null || true
            sleep 3
        fi
        
        # 2. 아직 실행 중이면 pkill로 모든 Neo4j 관련 프로세스 종료
        if lsof -i :7687 >/dev/null 2>&1; then
            echo "   - neo4j stop 실패, pkill 시도..."
            pkill -f "org.neo4j" 2>/dev/null || true
            sleep 2
        fi
        
        # 3. 그래도 실행 중이면 강제 종료
        if lsof -i :7687 >/dev/null 2>&1; then
            echo "   - 강제 종료 (SIGKILL)..."
            pkill -9 -f "org.neo4j" 2>/dev/null || true
            sleep 1
        fi
        
        # 최종 확인
        if lsof -i :7687 >/dev/null 2>&1; then
            echo "⚠️  Neo4j 종료 실패 - 수동 종료 필요"
        else
            echo "✅ Neo4j 종료됨"
        fi
        
        rm -f $NEO4J_PID_FILE
    else
        echo "⚠️  Neo4j가 실행 중이 아닙니다."
    fi
    
    echo "✅ 종료 완료"
    exit 0
}

# 시그널 트랩 설정 (Ctrl-C 감지)
trap cleanup SIGINT SIGTERM

# ==========================================
# 0. 기존 실행 중인 서비스 종료
# ==========================================

echo ""
echo "0️⃣  기존 실행 중인 서비스 확인 및 종료..."

# PostgreSQL 종료 (포트 체크)
if lsof -i :$PG_PORT >/dev/null 2>&1; then
    echo "⚠️  PostgreSQL이 이미 실행 중입니다 (Port: $PG_PORT). 종료 중..."
    
    # PID 파일이 있으면 해당 PID로 종료 시도
    if [ -f "$PG_PID_FILE" ]; then
        OLD_PG_PID=$(cat $PG_PID_FILE)
        if [[ "$OLD_PG_PID" =~ ^[0-9]+$ ]] && kill -0 $OLD_PG_PID 2>/dev/null; then
            kill -TERM $OLD_PG_PID 2>/dev/null || true
            sleep 2
        fi
    fi
    
    # 아직 실행 중이면 pkill로 강제 종료
    if lsof -i :$PG_PORT >/dev/null 2>&1; then
        pkill -f "postgres.*-p.*$PG_PORT" 2>/dev/null || true
        sleep 2
    fi
    
    # 최종 확인
    if lsof -i :$PG_PORT >/dev/null 2>&1; then
        echo "❌ PostgreSQL 종료 실패. 수동으로 종료해주세요."
        exit 1
    fi
    
    echo "✅ 기존 PostgreSQL 종료됨"
    rm -f $PG_PID_FILE
else
    echo "✅ PostgreSQL: 실행 중인 인스턴스 없음"
fi

# Neo4j 종료 (포트 체크)
if [ "$NEO4J_ENABLED" != "0" ]; then
    if lsof -i :7687 >/dev/null 2>&1; then
        echo "⚠️  Neo4j가 이미 실행 중입니다 (Port: 7687). 종료 중..."
        
        # 1. neo4j stop 명령어로 정상 종료 시도 (가장 안전)
        if command -v "$NEO4J_BIN" >/dev/null 2>&1; then
            "$NEO4J_BIN" stop 2>/dev/null || true
            sleep 3
        fi
        
        # 2. 아직 실행 중이면 pkill로 모든 Neo4j Java 프로세스 종료
        if lsof -i :7687 >/dev/null 2>&1; then
            echo "   - neo4j stop 실패, pkill 시도..."
            pkill -f "org.neo4j" 2>/dev/null || true
            sleep 2
        fi
        
        # 3. 그래도 실행 중이면 강제 종료 (SIGKILL)
        if lsof -i :7687 >/dev/null 2>&1; then
            echo "   - 강제 종료 (SIGKILL)..."
            pkill -9 -f "org.neo4j" 2>/dev/null || true
            sleep 1
        fi
        
        # 최종 확인
        if lsof -i :7687 >/dev/null 2>&1; then
            echo "❌ Neo4j 종료 실패. 수동으로 종료해주세요."
            exit 1
        fi
        
        echo "✅ 기존 Neo4j 종료됨"
        rm -f $NEO4J_PID_FILE
    else
        echo "✅ Neo4j: 실행 중인 인스턴스 없음"
    fi
fi

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
echo "2️⃣a PostgreSQL 시작 중..."

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
# 2.5 Neo4j 시작 (옵션)
# ==========================================
if [ "$NEO4J_ENABLED" != "0" ]; then
    echo ""
    echo "2️⃣b Neo4j 시작 중..."
    
    # 기존 Neo4j 프로세스 정리 (안전장치)
    pkill -f "neo4j" 2>/dev/null || true
    
    if ! command -v "$NEO4J_BIN" >/dev/null 2>&1; then
        echo "⚠️  Neo4j 실행 파일을 찾을 수 없습니다 (NEO4J_BIN=$NEO4J_BIN)."
        echo "    Neo4j는 건너뜁니다."
    else
        mkdir -p "$(dirname "$NEO4J_LOG_FILE")"
        
        # Neo4j 시작
        "$NEO4J_BIN" console > "$NEO4J_LOG_FILE" 2>&1 &
        NEO4J_PID=$!
        echo $NEO4J_PID > $NEO4J_PID_FILE
        
        # 시작 대기 (포트 리스닝 확인)
        echo "   - Neo4j 시작 대기 중..."
        for i in {1..30}; do
            if lsof -i :7687 >/dev/null 2>&1; then
                echo "✅ Neo4j 시작됨 (PID: $NEO4J_PID, Port: 7687)"
                break
            fi
            if ! kill -0 $NEO4J_PID 2>/dev/null; then
                 echo "❌ Neo4j 시작 실패 (프로세스 종료됨). 로그 확인: $NEO4J_LOG_FILE"
                 break
            fi
            sleep 1
        done
        
        echo "   - Log: $NEO4J_LOG_FILE"
    fi
else
    echo ""
    echo "2️⃣b Neo4j 시작 스킵 (NEO4J_ENABLED=0)"
fi

# ==========================================
# 3. 데이터베이스 생성
# ==========================================

echo ""
echo "3️⃣  PostgreSQL 데이터베이스 생성/확인 중..."

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
echo "✅ 서비스 실행 중 (PostgreSQL & Neo4j)"
echo "=========================================="
echo ""
echo "📊 PostgreSQL 연결 정보:"
echo "   - Host: localhost"
echo "   - Port: $PG_PORT"
echo "   - Database: $DB_NAME"
echo "   - User: postgres"
if [ "$NEO4J_ENABLED" != "0" ] && [ -f "$NEO4J_PID_FILE" ]; then
echo ""
echo "🧠 Neo4j 정보:"
echo "   - PID 파일: $NEO4J_PID_FILE"
echo "   - 로그: $NEO4J_LOG_FILE"
echo "   - 명령: $NEO4J_BIN console"
fi
echo ""
echo "🔌 Agent 실행 방법:"
echo "   python test_agent_with_interrupt.py"
echo ""
echo "🛑 종료 방법:"
echo "   Ctrl-C를 누르면 PostgreSQL과 Neo4j가 함께 종료됩니다."
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
    # Neo4j가 켜진 경우 상태 체크
    if [ "$NEO4J_ENABLED" != "0" ] && [ -f "$NEO4J_PID_FILE" ]; then
        NEO4J_PID=$(cat $NEO4J_PID_FILE)
        if ! kill -0 $NEO4J_PID 2>/dev/null; then
            echo ""
            echo "⚠️  Neo4j 프로세스가 종료되었습니다. 로그 확인: $NEO4J_LOG_FILE"
            rm -f $NEO4J_PID_FILE
        fi
    fi
    
    sleep 2
done
