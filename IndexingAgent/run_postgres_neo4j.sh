#!/bin/bash
# run_postgres_neo4j.sh
# PostgreSQL + Neo4j Service Management Script
#
# Run: Start PostgreSQL and Neo4j, then wait
# Ctrl-C: Terminate both services

set -e  # Stop on error

# PostgreSQL version configuration (upgraded to 18)
export PATH="/opt/homebrew/opt/postgresql@18/bin:$PATH"
export LDFLAGS="-L/opt/homebrew/opt/postgresql@18/lib"
export CPPFLAGS="-I/opt/homebrew/opt/postgresql@18/include"
export LC_ALL="en_US.UTF-8"  # Prevent PostgreSQL multithread issue

echo "=========================================="
echo "🗄️  PostgreSQL & 🧠 Neo4j Service Manager"
echo "=========================================="

# PostgreSQL configuration
PG_DATA_DIR="./data/postgres_data"
PG_LOG_FILE="./data/postgres.log"
PG_PORT=5432
PG_PID_FILE="./data/postgres.pid"

# Neo4j configuration (set NEO4J_ENABLED=0 to disable)
NEO4J_ENABLED=${NEO4J_ENABLED:-1}
NEO4J_BIN=${NEO4J_BIN:-neo4j}
NEO4J_PID_FILE="./data/neo4j.pid"
NEO4J_LOG_FILE="./data/neo4j.log"

# Cleanup function (called on Ctrl-C)
cleanup() {
    echo ""
    echo "=========================================="
    echo "🛑 Shutdown signal detected (Ctrl-C)"
    echo "=========================================="
    
    # Stop PostgreSQL
    if [ -f "$PG_PID_FILE" ]; then
        PG_PID=$(cat $PG_PID_FILE)
        
        if kill -0 $PG_PID 2>/dev/null; then
            echo "🐘 Stopping PostgreSQL (PID: $PG_PID)..."
            
            # Send SIGTERM (graceful shutdown)
            kill -TERM $PG_PID
            
            # Wait for shutdown (max 10 seconds)
            for i in {1..10}; do
                if ! kill -0 $PG_PID 2>/dev/null; then
                    echo "✅ PostgreSQL stopped gracefully"
                    break
                fi
                sleep 1
            done
            
            # Force kill if still running
            if kill -0 $PG_PID 2>/dev/null; then
                echo "⚠️  No response - forcing shutdown..."
                kill -9 $PG_PID
                sleep 1
                echo "✅ PostgreSQL force stopped"
            fi
        else
            echo "⚠️  PostgreSQL process already terminated."
        fi
        
        rm -f $PG_PID_FILE
    else
        echo "⚠️  PID file not found (PostgreSQL may not be running)"
    fi

    # Stop Neo4j (using neo4j stop command)
    if lsof -i :7687 >/dev/null 2>&1 || [ -f "$NEO4J_PID_FILE" ]; then
        echo "🧠 Stopping Neo4j..."
        
        # 1. Try graceful shutdown with neo4j stop
        if command -v "$NEO4J_BIN" >/dev/null 2>&1; then
            "$NEO4J_BIN" stop 2>/dev/null || true
            sleep 3
        fi
        
        # 2. If still running, use pkill
        if lsof -i :7687 >/dev/null 2>&1; then
            echo "   - neo4j stop failed, trying pkill..."
            pkill -f "org.neo4j" 2>/dev/null || true
            sleep 2
        fi
        
        # 3. Force kill if still running
        if lsof -i :7687 >/dev/null 2>&1; then
            echo "   - Force kill (SIGKILL)..."
            pkill -9 -f "org.neo4j" 2>/dev/null || true
            sleep 1
        fi
        
        # Final check
        if lsof -i :7687 >/dev/null 2>&1; then
            echo "⚠️  Failed to stop Neo4j - manual intervention required"
        else
            echo "✅ Neo4j stopped"
        fi
        
        rm -f $NEO4J_PID_FILE
    else
        echo "⚠️  Neo4j is not running."
    fi
    
    echo "✅ Shutdown complete"
    exit 0
}

# Set signal trap (detect Ctrl-C)
trap cleanup SIGINT SIGTERM

# ==========================================
# 0. Stop existing running services
# ==========================================

echo ""
echo "0️⃣  Checking and stopping existing services..."

# Stop PostgreSQL (port check)
if lsof -i :$PG_PORT >/dev/null 2>&1; then
    echo "⚠️  PostgreSQL is already running (Port: $PG_PORT). Stopping..."
    
    # Try to stop using PID file
    if [ -f "$PG_PID_FILE" ]; then
        OLD_PG_PID=$(cat $PG_PID_FILE)
        if [[ "$OLD_PG_PID" =~ ^[0-9]+$ ]] && kill -0 $OLD_PG_PID 2>/dev/null; then
            kill -TERM $OLD_PG_PID 2>/dev/null || true
            sleep 2
        fi
    fi
    
    # Force kill if still running
    if lsof -i :$PG_PORT >/dev/null 2>&1; then
        # Try multiple patterns (port-based or data directory-based)
        pkill -f "postgres.*-p.*$PG_PORT" 2>/dev/null || true
        pkill -f "postgres.*-D.*postgres_data" 2>/dev/null || true
        sleep 2
    fi
    
    # Final check
    if lsof -i :$PG_PORT >/dev/null 2>&1; then
        echo "❌ Failed to stop PostgreSQL. Please stop it manually."
        exit 1
    fi
    
    echo "✅ Existing PostgreSQL stopped"
    rm -f $PG_PID_FILE
else
    echo "✅ PostgreSQL: No running instance found"
fi

# Stop Neo4j (port check)
if [ "$NEO4J_ENABLED" != "0" ]; then
    if lsof -i :7687 >/dev/null 2>&1; then
        echo "⚠️  Neo4j is already running (Port: 7687). Stopping..."
        
        # 1. Try graceful shutdown with neo4j stop
        if command -v "$NEO4J_BIN" >/dev/null 2>&1; then
            "$NEO4J_BIN" stop 2>/dev/null || true
            sleep 3
        fi
        
        # 2. If still running, use pkill
        if lsof -i :7687 >/dev/null 2>&1; then
            echo "   - neo4j stop failed, trying pkill..."
            pkill -f "org.neo4j" 2>/dev/null || true
            sleep 2
        fi
        
        # 3. Force kill (SIGKILL) if still running
        if lsof -i :7687 >/dev/null 2>&1; then
            echo "   - Force kill (SIGKILL)..."
            pkill -9 -f "org.neo4j" 2>/dev/null || true
            sleep 1
        fi
        
        # Final check
        if lsof -i :7687 >/dev/null 2>&1; then
            echo "❌ Failed to stop Neo4j. Please stop it manually."
            exit 1
        fi
        
        echo "✅ Existing Neo4j stopped"
        rm -f $NEO4J_PID_FILE
    else
        echo "✅ Neo4j: No running instance found"
    fi
fi

# ==========================================
# 1. Initialize and start PostgreSQL
# ==========================================

echo ""
echo "1️⃣  Initializing PostgreSQL..."

# Create data directory if not exists
if [ ! -d "$PG_DATA_DIR" ]; then
    echo "📦 Creating PostgreSQL data directory..."
    mkdir -p $(dirname $PG_DATA_DIR)
    
    # initdb (PostgreSQL initialization)
    initdb -D $PG_DATA_DIR -U postgres --no-locale --encoding=UTF8
    
    echo "✅ Initialization complete"
else
    echo "✅ Data directory exists: $PG_DATA_DIR"
fi

echo ""
echo "2️⃣a Starting PostgreSQL..."

# Start PostgreSQL (background)
postgres -D $PG_DATA_DIR -p $PG_PORT > $PG_LOG_FILE 2>&1 &
PG_PID=$!

# Save PID
echo $PG_PID > $PG_PID_FILE

echo "✅ PostgreSQL started (PID: $PG_PID)"
echo "   - Port: $PG_PORT"
echo "   - Log: $PG_LOG_FILE"

# Wait for startup (max 10 seconds)
echo "   - Waiting for startup..."

for i in {1..10}; do
    if pg_isready -p $PG_PORT > /dev/null 2>&1; then
        echo "✅ PostgreSQL ready"
        break
    fi
    sleep 1
done

if ! pg_isready -p $PG_PORT > /dev/null 2>&1; then
    echo "❌ PostgreSQL startup failed"
    echo "Check log: cat $PG_LOG_FILE"
    cleanup
    exit 1
fi

# ==========================================
# 2.5 Start Neo4j (optional)
# ==========================================
if [ "$NEO4J_ENABLED" != "0" ]; then
    echo ""
    echo "2️⃣b Starting Neo4j..."
    
    # Clean up existing Neo4j processes (safety)
    pkill -f "neo4j" 2>/dev/null || true
    
    if ! command -v "$NEO4J_BIN" >/dev/null 2>&1; then
        echo "⚠️  Neo4j executable not found (NEO4J_BIN=$NEO4J_BIN)."
        echo "    Skipping Neo4j."
    else
        mkdir -p "$(dirname "$NEO4J_LOG_FILE")"
        
        # Start Neo4j
        "$NEO4J_BIN" console > "$NEO4J_LOG_FILE" 2>&1 &
        NEO4J_PID=$!
        echo $NEO4J_PID > $NEO4J_PID_FILE
        
        # Wait for startup (check port listening)
        echo "   - Waiting for Neo4j startup..."
        for i in {1..30}; do
            if lsof -i :7687 >/dev/null 2>&1; then
                echo "✅ Neo4j started (PID: $NEO4J_PID, Port: 7687)"
                break
            fi
            if ! kill -0 $NEO4J_PID 2>/dev/null; then
                 echo "❌ Neo4j startup failed (process terminated). Check log: $NEO4J_LOG_FILE"
                 break
            fi
            sleep 1
        done
        
        echo "   - Log: $NEO4J_LOG_FILE"
    fi
else
    echo ""
    echo "2️⃣b Neo4j startup skipped (NEO4J_ENABLED=0)"
fi

# ==========================================
# 3. Create database
# ==========================================

echo ""
echo "3️⃣  Creating/checking PostgreSQL database..."

DB_NAME="medical_data"

# Check if database exists
if psql -U postgres -p $PG_PORT -lqt | cut -d \| -f 1 | grep -qw $DB_NAME; then
    echo "✅ Database '$DB_NAME' exists"
else
    echo "📦 Creating database '$DB_NAME'..."
    createdb -U postgres -p $PG_PORT $DB_NAME
    echo "✅ Database created"
fi

# ==========================================
# 3.5 Check pgvector extension (auto-install in Python)
# ==========================================

echo ""
echo "3️⃣.5 Checking pgvector extension..."

# Only check - actual installation is done by VectorStore.initialize()
PGVECTOR_INSTALLED=$(psql -U postgres -p $PG_PORT -d $DB_NAME -tAc "SELECT 1 FROM pg_extension WHERE extname='vector'" 2>/dev/null || echo "0")

if [ "$PGVECTOR_INSTALLED" = "1" ]; then
    echo "✅ pgvector extension installed"
else
    echo "ℹ️  pgvector extension not installed - will be auto-installed by VectorStore"
    echo "   (Pre-install: brew install pgvector or apt install postgresql-XX-pgvector)"
fi

# ==========================================
# 4. Configure .env file
# ==========================================

echo ""
echo "4️⃣  Configuring environment variables..."

# Create/update .env file
cat > .env.postgres << EOF
# PostgreSQL Configuration
POSTGRES_HOST=localhost
POSTGRES_PORT=$PG_PORT
POSTGRES_DB=$DB_NAME
POSTGRES_USER=postgres
POSTGRES_PASSWORD=

# LLM Configuration (copied from existing .env)
EOF

# Copy LLM settings from existing .env
if [ -f ".env" ]; then
    grep "LLM_PROVIDER\|API_KEY" .env >> .env.postgres 2>/dev/null || true
fi

# Backup and replace .env
if [ -f ".env" ]; then
    mv .env .env.backup
    echo "   - Existing .env backed up: .env.backup"
fi

mv .env.postgres .env
echo "✅ .env file configured"

# ==========================================
# 5. Wait (until Ctrl-C)
# ==========================================

echo ""
echo "=========================================="
echo "✅ Services running (PostgreSQL & Neo4j)"
echo "=========================================="
echo ""
echo "📊 PostgreSQL Connection Info:"
echo "   - Host: localhost"
echo "   - Port: $PG_PORT"
echo "   - Database: $DB_NAME"
echo "   - User: postgres"
if [ "$NEO4J_ENABLED" != "0" ] && [ -f "$NEO4J_PID_FILE" ]; then
echo ""
echo "🧠 Neo4j Info:"
echo "   - PID file: $NEO4J_PID_FILE"
echo "   - Log: $NEO4J_LOG_FILE"
echo "   - Command: $NEO4J_BIN console"
fi
echo ""
echo "🔌 Run Agent:"
echo "   python test_agent_with_interrupt.py"
echo ""
echo "🛑 To stop:"
echo "   Press Ctrl-C to stop both PostgreSQL and Neo4j."
echo ""
echo "----------------------------------------"
echo "Waiting... (Press Ctrl-C to stop)"
echo "----------------------------------------"

# Infinite wait (until Ctrl-C)
while true; do
    # Check if PostgreSQL is alive
    if ! kill -0 $PG_PID 2>/dev/null; then
        echo ""
        echo "❌ PostgreSQL process terminated unexpectedly."
        echo "Check log: cat $PG_LOG_FILE"
        cleanup
        exit 1
    fi
    # Check Neo4j status if enabled
    if [ "$NEO4J_ENABLED" != "0" ] && [ -f "$NEO4J_PID_FILE" ]; then
        NEO4J_PID=$(cat $NEO4J_PID_FILE)
        if ! kill -0 $NEO4J_PID 2>/dev/null; then
            echo ""
            echo "⚠️  Neo4j process terminated. Check log: $NEO4J_LOG_FILE"
            rm -f $NEO4J_PID_FILE
        fi
    fi
    
    sleep 2
done
