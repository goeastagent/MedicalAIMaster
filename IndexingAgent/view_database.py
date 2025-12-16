#!/usr/bin/env python3
# view_database.py
"""
PostgreSQL DB 확인 스크립트

생성된 테이블, 행 개수, FK, 인덱스 등을 확인
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from database.connection import get_db_manager


def print_separator(title="", char="=", length=80):
    """구분선 출력"""
    if title:
        print(f"\n{char * length}")
        print(f" {title}")
        print(f"{char * length}")
    else:
        print(f"{char * length}")


def check_database():
    """PostgreSQL DB 상태 확인"""
    
    print_separator("🗄️  PostgreSQL Database Viewer", "=")
    
    # DB 연결
    try:
        db_manager = get_db_manager()
        conn = db_manager.connect()
        cursor = conn.cursor()
        
        print(f"\n✅ PostgreSQL 연결 성공")
        print(f"   - Host: {db_manager.db_host}")
        print(f"   - Port: {db_manager.db_port}")
        print(f"   - Database: {db_manager.db_name}")
        print(f"   - User: {db_manager.db_user}")
        
    except Exception as e:
        print(f"\n❌ PostgreSQL 연결 실패: {e}")
        print("\n확인 사항:")
        print("  1. PostgreSQL이 실행 중인가? (./run_with_postgres.sh)")
        print("  2. .env 파일의 POSTGRES_* 설정이 올바른가?")
        return
    
    # === 1. 테이블 목록 ===
    print_separator("📋 테이블 목록")
    
    cursor.execute("""
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema = 'public' 
        AND table_type = 'BASE TABLE'
        ORDER BY table_name
    """)
    tables = cursor.fetchall()
    
    if not tables:
        print("\n⚠️  테이블이 없습니다.")
        conn.close()
        return
    
    print(f"\n총 {len(tables)}개 테이블:")
    for i, (table_name,) in enumerate(tables, 1):
        print(f"   {i}. {table_name}")
    
    # === 2. 각 테이블 상세 정보 ===
    for (table_name,) in tables:
        print_separator(f"📊 Table: {table_name}")
        
        # 2-1. 컬럼 정보
        cursor.execute("""
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_name = %s
            ORDER BY ordinal_position
        """, (table_name,))
        columns = cursor.fetchall()
        
        print(f"\n🔹 컬럼 ({len(columns)}개):")
        
        # PK 정보 조회
        cursor.execute("""
            SELECT a.attname
            FROM pg_index i
            JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
            WHERE i.indrelid = %s::regclass AND i.indisprimary
        """, (table_name,))
        pk_cols = {row[0] for row in cursor.fetchall()}
        
        for idx, (col_name, data_type, is_nullable, default) in enumerate(columns[:10], 1):
            pk_mark = " 🔑" if col_name in pk_cols else ""
            nullable_mark = "" if is_nullable == 'YES' else " NOT NULL"
            print(f"   {idx}. {col_name} ({data_type}){pk_mark}{nullable_mark}")
        
        if len(columns) > 10:
            print(f"   ... and {len(columns) - 10} more columns")
        
        if pk_cols:
            print(f"\n   Primary Key: {', '.join(pk_cols)}")
        
        # 2-2. 행 개수
        cursor.execute(f'SELECT COUNT(*) FROM "{table_name}"')
        row_count = cursor.fetchone()[0]
        print(f"\n🔹 행 개수: {row_count:,}개")
        
        # 2-3. FK 제약조건 (PostgreSQL)
        cursor.execute("""
            SELECT
                kcu.column_name,
                ccu.table_name AS foreign_table_name,
                ccu.column_name AS foreign_column_name
            FROM information_schema.table_constraints AS tc
            JOIN information_schema.key_column_usage AS kcu
              ON tc.constraint_name = kcu.constraint_name
              AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage AS ccu
              ON ccu.constraint_name = tc.constraint_name
              AND ccu.table_schema = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_name = %s
        """, (table_name,))
        fks = cursor.fetchall()
        
        if fks:
            print(f"\n🔹 Foreign Keys ({len(fks)}개):")
            for from_col, target_table, to_col in fks:
                print(f"   • {from_col} → {target_table}({to_col})")
        else:
            print(f"\n🔹 Foreign Keys: 없음")
        
        # 2-4. 인덱스 (PostgreSQL)
        cursor.execute("""
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE tablename = %s
              AND schemaname = 'public'
            ORDER BY indexname
        """, (table_name,))
        indices = cursor.fetchall()
        
        # PK 자동 인덱스 제외
        manual_indices = [idx for idx in indices if not idx[0].endswith('_pkey')]
        
        if manual_indices:
            print(f"\n🔹 Indices ({len(manual_indices)}개):")
            for idx_name, idx_def in manual_indices:
                # 인덱스 정의에서 컬럼 추출
                print(f"   • {idx_name}")
                if idx_def:
                    # CREATE INDEX ... ON table(col) 형식에서 컬럼 추출
                    if '(' in idx_def and ')' in idx_def:
                        cols = idx_def[idx_def.index('(')+1:idx_def.index(')')].strip()
                        print(f"     ON ({cols})")
        else:
            print(f"\n🔹 Indices: 없음 (PK 인덱스 제외)")
        
        # 2-5. 샘플 데이터 (처음 3행)
        try:
            cursor.execute(f'SELECT * FROM "{table_name}" LIMIT 3')
            samples = cursor.fetchall()
            
            if samples:
                print(f"\n🔹 샘플 데이터 (처음 3행):")
                
                # 컬럼명 (PostgreSQL cursor.description 사용)
                col_names = [desc[0] for desc in cursor.description[:5]]
                print(f"   컬럼: {', '.join(col_names)}...")
                
                # 데이터
                for idx, row in enumerate(samples, 1):
                    row_preview = ', '.join(str(v) if v is not None else 'NULL' for v in row[:5])
                    print(f"   {idx}. {row_preview}...")
        except Exception as e:
            print(f"\n⚠️  샘플 데이터 조회 실패: {e}")
    
    # === 3. 전체 통계 ===
    print_separator("📊 전체 통계")
    
    total_rows = 0
    for (table_name,) in tables:
        cursor.execute(f'SELECT COUNT(*) FROM "{table_name}"')
        count = cursor.fetchone()[0]
        total_rows += count
    
    print(f"\n전체 행 개수: {total_rows:,}개")
    print(f"전체 테이블: {len(tables)}개")
    
    # FK 관계 그래프
    print(f"\n🔗 테이블 관계:")
    has_relationship = False
    
    cursor.execute("""
        SELECT
            tc.table_name,
            kcu.column_name,
            ccu.table_name AS foreign_table_name,
            ccu.column_name AS foreign_column_name
        FROM information_schema.table_constraints AS tc
        JOIN information_schema.key_column_usage AS kcu
          ON tc.constraint_name = kcu.constraint_name
        JOIN information_schema.constraint_column_usage AS ccu
          ON ccu.constraint_name = tc.constraint_name
        WHERE tc.constraint_type = 'FOREIGN KEY'
          AND tc.table_schema = 'public'
        ORDER BY tc.table_name
    """)
    all_fks = cursor.fetchall()
    
    for table_name, from_col, target_table, to_col in all_fks:
        print(f"   {table_name}.{from_col} → {target_table}.{to_col}")
        has_relationship = True
    
    if not has_relationship:
        print(f"   (관계 없음)")
    
    conn.close()
    
    print_separator()
    
    print("\n✅ DB 확인 완료")
    print(f"\n💡 PostgreSQL 쿼리 실행:")
    print(f"   psql -U postgres -d {db_manager.db_name}")
    print(f"   medical_data=> SELECT * FROM clinical_data_table LIMIT 5;")


def interactive_query():
    """대화형 SQL 쿼리 (PostgreSQL)"""
    
    try:
        db_manager = get_db_manager()
        conn = db_manager.connect()
        cursor = conn.cursor()
        
        print_separator("🔍 Interactive SQL Query Mode (PostgreSQL)")
        print(f"\n연결: {db_manager.db_user}@{db_manager.db_host}:{db_manager.db_port}/{db_manager.db_name}")
        print("SQL 쿼리를 입력하세요 (quit로 종료)")
        
    except Exception as e:
        print(f"❌ DB 연결 실패: {e}")
        return
    
    while True:
        print("\n" + "-"*80)
        query = input("SQL> ").strip()
        
        if not query:
            continue
        
        if query.lower() in ['quit', 'exit', 'q']:
            break
        
        try:
            cursor.execute(query)
            
            # SELECT 쿼리면 결과 출력
            if query.strip().upper().startswith('SELECT'):
                results = cursor.fetchall()
                
                if results:
                    # 컬럼명
                    col_names = [desc[0] for desc in cursor.description]
                    print(f"\n결과: {len(results)}행")
                    print("─"*80)
                    print(" | ".join(col_names[:10]))
                    print("─"*80)
                    
                    for row in results[:10]:
                        row_str = " | ".join(str(v) if v is not None else 'NULL' for v in row[:10])
                        print(row_str)
                    
                    if len(results) > 10:
                        print(f"... and {len(results) - 10} more rows")
                else:
                    print("결과 없음")
            else:
                # INSERT, UPDATE 등
                conn.commit()
                print(f"✅ 실행 완료 (affected: {cursor.rowcount}행)")
        
        except Exception as e:
            print(f"❌ 에러: {e}")
            conn.rollback()  # 에러 시 롤백
    
    conn.close()
    print("\n✅ 종료")


def main():
    """메인 함수"""
    import argparse
    
    parser = argparse.ArgumentParser(description="PostgreSQL DB 확인")
    parser.add_argument('--interactive', '-i', action='store_true', help="대화형 쿼리 모드")
    
    args = parser.parse_args()
    
    if args.interactive:
        interactive_query()
    else:
        check_database()


if __name__ == "__main__":
    main()

