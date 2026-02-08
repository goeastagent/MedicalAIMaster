#!/bin/bash
# import_db.sh
# IndexingAgent 결과물 Import 스크립트
# export_db.sh로 내보낸 dump 파일을 복원
#
# 사용법: ./scripts/import_db.sh <archive_file_or_directory>
# 예시:   ./scripts/import_db.sh ./db_export/indexing_agent_export_20240101_120000.tar.gz
#         ./scripts/import_db.sh ./db_export/indexing_agent_export_20240101_120000/

set -e

# ===========================================
# Configuration (환경변수 또는 기본값)
# ===========================================
POSTGRES_HOST=${POSTGRES_HOST:-localhost}
POSTGRES_PORT=${POSTGRES_PORT:-5432}
POSTGRES_USER=${POSTGRES_USER:-postgres}
POSTGRES_DB=${POSTGRES_DB:-medical_data}

NEO4J_URI=${NEO4J_URI:-bolt://localhost:7687}
NEO4J_USER=${NEO4J_USER:-neo4j}
NEO4J_PASSWORD=${NEO4J_PASSWORD:-password}
NEO4J_DATABASE=${NEO4J_DATABASE:-neo4j}

# Input validation
if [ -z "$1" ]; then
    echo "Usage: $0 <archive_file_or_directory>"
    echo "Example: $0 ./db_export/indexing_agent_export_20240101_120000.tar.gz"
    exit 1
fi

INPUT_PATH="$1"

echo "=========================================="
echo "📥 IndexingAgent Database Import"
echo "=========================================="
echo ""

# ===========================================
# 0. Extract archive if needed
# ===========================================
if [ -f "$INPUT_PATH" ] && [[ "$INPUT_PATH" == *.tar.gz ]]; then
    echo "0️⃣  Extracting archive..."
    EXTRACT_DIR=$(dirname "$INPUT_PATH")
    tar -xzvf "$INPUT_PATH" -C "$EXTRACT_DIR" > /dev/null
    
    # Get the extracted directory name
    EXPORT_DIR="$EXTRACT_DIR/$(tar -tzf "$INPUT_PATH" | head -1 | cut -d'/' -f1)"
    echo "✅ Extracted to: $EXPORT_DIR"
elif [ -d "$INPUT_PATH" ]; then
    EXPORT_DIR="$INPUT_PATH"
    echo "📁 Using directory: $EXPORT_DIR"
else
    echo "❌ Invalid input: $INPUT_PATH"
    echo "   Must be a .tar.gz file or a directory"
    exit 1
fi

# Verify required files exist
PG_DUMP_FILE="$EXPORT_DIR/postgres_dump.sql"
NEO4J_DUMP_FILE="$EXPORT_DIR/neo4j_dump.cypher"
METADATA_FILE="$EXPORT_DIR/metadata.json"

if [ ! -f "$PG_DUMP_FILE" ]; then
    echo "❌ PostgreSQL dump not found: $PG_DUMP_FILE"
    exit 1
fi

echo ""
echo "📋 Import source:"
echo "   - PostgreSQL: $PG_DUMP_FILE"
echo "   - Neo4j: $NEO4J_DUMP_FILE"
if [ -f "$METADATA_FILE" ]; then
    echo "   - Metadata: $METADATA_FILE"
    echo ""
    echo "📅 Export info:"
    cat "$METADATA_FILE" | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'   - Timestamp: {d.get(\"export_timestamp\", \"unknown\")}')"
fi
echo ""

# ===========================================
# 1. PostgreSQL Import
# ===========================================
echo "1️⃣  Importing PostgreSQL..."

# Check if PostgreSQL is accessible
if ! pg_isready -h $POSTGRES_HOST -p $POSTGRES_PORT > /dev/null 2>&1; then
    echo "❌ PostgreSQL is not running at $POSTGRES_HOST:$POSTGRES_PORT"
    echo ""
    echo "📝 To start PostgreSQL:"
    echo "   Option 1: ./IndexingAgent/run_postgres_neo4j.sh"
    echo "   Option 2: docker run -d -p 5432:5432 -e POSTGRES_PASSWORD=postgres postgres:16"
    exit 1
fi

# Check if database exists, create if not
if psql -h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER -lqt | cut -d \| -f 1 | grep -qw $POSTGRES_DB; then
    echo "   ⚠️  Database '$POSTGRES_DB' already exists"
    read -p "   Drop and recreate? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "   - Dropping existing database..."
        psql -h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER -c "DROP DATABASE IF EXISTS $POSTGRES_DB;"
        psql -h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER -c "CREATE DATABASE $POSTGRES_DB;"
        echo "   ✅ Database recreated"
    else
        echo "   - Proceeding with existing database (may cause errors if schema conflicts)"
    fi
else
    echo "   - Creating database '$POSTGRES_DB'..."
    psql -h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER -c "CREATE DATABASE $POSTGRES_DB;"
fi

# Import dump
echo "   - Importing data..."
psql -h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER -d $POSTGRES_DB -f "$PG_DUMP_FILE" > /dev/null 2>&1 || {
    echo "   ⚠️  Some warnings during import (this is often normal)"
}

# Verify import
TABLE_COUNT=$(psql -h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER -d $POSTGRES_DB -tAc "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public';")
echo "✅ PostgreSQL imported: $TABLE_COUNT tables"

# Show table row counts
echo ""
echo "   📊 Table row counts:"
psql -h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER -d $POSTGRES_DB << 'SQL'
SELECT 
    schemaname || '.' || tablename as table_name,
    n_tup_ins as rows
FROM pg_stat_user_tables
WHERE schemaname = 'public'
ORDER BY tablename;
SQL

# ===========================================
# 2. Neo4j Import
# ===========================================
echo ""
echo "2️⃣  Importing Neo4j..."

# Check if Neo4j dump file has content
if [ ! -s "$NEO4J_DUMP_FILE" ] || grep -q "Neo4j was not running" "$NEO4J_DUMP_FILE" 2>/dev/null; then
    echo "⚠️  Neo4j dump is empty or was not exported"
    echo "   Skipping Neo4j import..."
else
    # Check if Neo4j is accessible
    if ! nc -z localhost 7687 2>/dev/null; then
        echo "⚠️  Neo4j is not running at port 7687"
        echo ""
        echo "📝 To start Neo4j:"
        echo "   Option 1: ./IndexingAgent/run_postgres_neo4j.sh"
        echo "   Option 2: docker run -d -p 7474:7474 -p 7687:7687 -e NEO4J_AUTH=neo4j/password neo4j:5"
        echo ""
        echo "   Skipping Neo4j import..."
    else
        # Check if cypher-shell is available
        if command -v cypher-shell &> /dev/null; then
            echo "   - Clearing existing data..."
            cypher-shell -u "$NEO4J_USER" -p "$NEO4J_PASSWORD" -d "$NEO4J_DATABASE" \
                "MATCH (n) DETACH DELETE n" 2>/dev/null || true
            
            echo "   - Importing data..."
            cypher-shell -u "$NEO4J_USER" -p "$NEO4J_PASSWORD" -d "$NEO4J_DATABASE" \
                -f "$NEO4J_DUMP_FILE" 2>/dev/null || {
                echo "   ⚠️  Some errors during Neo4j import"
            }
            
            # Verify
            NODE_COUNT=$(cypher-shell -u "$NEO4J_USER" -p "$NEO4J_PASSWORD" -d "$NEO4J_DATABASE" \
                "MATCH (n) RETURN count(n)" 2>/dev/null | tail -1 || echo "unknown")
            echo "✅ Neo4j imported: $NODE_COUNT nodes"
        else
            # Try Python import
            echo "   - cypher-shell not found, using Python..."
            python3 << EOF
try:
    from neo4j import GraphDatabase
    
    driver = GraphDatabase.driver("$NEO4J_URI", auth=("$NEO4J_USER", "$NEO4J_PASSWORD"))
    
    with driver.session(database="$NEO4J_DATABASE") as session:
        # Clear existing data
        session.run("MATCH (n) DETACH DELETE n")
        
        # Read and execute cypher statements
        with open("$NEO4J_DUMP_FILE", "r") as f:
            statements = f.read().split(";")
            for stmt in statements:
                stmt = stmt.strip()
                if stmt and not stmt.startswith("//"):
                    try:
                        session.run(stmt)
                    except Exception as e:
                        pass  # Skip errors for now
        
        # Count nodes
        result = session.run("MATCH (n) RETURN count(n) as count").single()
        print(f"✅ Neo4j imported: {result['count']} nodes")
    
    driver.close()
except ImportError:
    print("⚠️  neo4j Python package not installed")
except Exception as e:
    print(f"⚠️  Neo4j import failed: {e}")
EOF
        fi
    fi
fi

# ===========================================
# 3. Verification
# ===========================================
echo ""
echo "3️⃣  Verifying import..."

# Check key tables exist
EXPECTED_TABLES=("directory_catalog" "file_catalog" "column_metadata" "parameter" "file_group")
MISSING_TABLES=()

for table in "${EXPECTED_TABLES[@]}"; do
    EXISTS=$(psql -h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER -d $POSTGRES_DB -tAc \
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = '$table');")
    if [ "$EXISTS" != "t" ]; then
        MISSING_TABLES+=("$table")
    fi
done

if [ ${#MISSING_TABLES[@]} -eq 0 ]; then
    echo "✅ All expected tables present"
else
    echo "⚠️  Missing tables: ${MISSING_TABLES[*]}"
fi

# ===========================================
# Summary
# ===========================================
echo ""
echo "=========================================="
echo "✅ Import Complete!"
echo "=========================================="
echo ""
echo "📊 PostgreSQL: $POSTGRES_HOST:$POSTGRES_PORT/$POSTGRES_DB"
echo "🧠 Neo4j: $NEO4J_URI"
echo ""
echo "🚀 You can now use the agents:"
echo "   - AnalysisAgent"
echo "   - ExtractionAgent"
echo "   - OrchestrationAgent"
echo ""
echo "📝 Example:"
echo "   cd OrchestrationAgent"
echo "   python test_e2e_hr_mean.py"
echo ""
