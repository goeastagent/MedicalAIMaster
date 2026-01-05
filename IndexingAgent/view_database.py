#!/usr/bin/env python3
# view_database.py
"""
PostgreSQL DB 확인 스크립트 (Enhanced Version)

생성된 테이블, 행 개수, FK, 인덱스, 버전 관리 등의 요약 정보를 출력합니다.
"""

import sys
import os
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.database import get_db_manager


# =============================================================================
# ANSI Colors (터미널 출력용)
# =============================================================================
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    END = '\033[0m'


def c(text, color):
    """색상 적용"""
    return f"{color}{text}{Colors.END}"


def print_header(title, emoji="📊"):
    """큰 섹션 헤더"""
    print(f"\n{c('═' * 80, Colors.CYAN)}")
    print(f"{c(f'  {emoji}  {title}', Colors.BOLD + Colors.CYAN)}")
    print(f"{c('═' * 80, Colors.CYAN)}")


def print_subheader(title, emoji="▶"):
    """작은 섹션 헤더"""
    print(f"\n{c(f'{emoji} {title}', Colors.YELLOW + Colors.BOLD)}")
    print(c("─" * 60, Colors.YELLOW))


def print_box(lines, title=None, width=76):
    """박스 형태로 출력"""
    print(f"┌{'─' * width}┐")
    if title:
        print(f"│ {c(title, Colors.BOLD):<{width + 8}} │")
        print(f"├{'─' * width}┤")
    for line in lines:
        # ANSI 코드가 포함되어 있으면 실제 길이 조정 필요
        print(f"│ {line:<{width - 2}} │")
    print(f"└{'─' * width}┘")


# =============================================================================
# Main Functions
# =============================================================================

def get_summary_stats(cursor):
    """전체 통계 요약"""
    stats = {}
    
    # 테이블 목록
    cursor.execute("""
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema = 'public' 
        AND table_type = 'BASE TABLE'
        ORDER BY table_name
    """)
    stats['tables'] = [row[0] for row in cursor.fetchall()]
    
    # 시스템 테이블과 데이터 테이블 분리
    stats['system_tables'] = [t for t in stats['tables'] if t.startswith('_')]
    stats['data_tables'] = [t for t in stats['tables'] if not t.startswith('_')]
    
    # 데이터셋별 테이블 분류
    stats['datasets'] = defaultdict(list)
    for table in stats['data_tables']:
        parts = table.split('_')
        if len(parts) >= 2:
            dataset_prefix = parts[0]
            stats['datasets'][dataset_prefix].append(table)
        else:
            stats['datasets']['other'].append(table)
    
    # 총 행 수 계산
    stats['total_rows'] = 0
    stats['table_rows'] = {}
    for table in stats['tables']:
        try:
            cursor.execute(f'SELECT COUNT(*) FROM "{table}"')
            count = cursor.fetchone()[0]
            stats['table_rows'][table] = count
            stats['total_rows'] += count
        except:
            stats['table_rows'][table] = 0
    
    return stats


def print_executive_summary(cursor, stats):
    """핵심 요약 출력 (Executive Summary)"""
    print_header("DATABASE SUMMARY", "🗄️")
    
    # 기본 통계
    total_rows_str = f"{stats['total_rows']:,}"
    lines = [
        f"📁 총 테이블: {c(str(len(stats['tables'])), Colors.GREEN + Colors.BOLD)}개",
        f"   • 데이터 테이블: {len(stats['data_tables'])}개",
        f"   • 시스템 테이블: {len(stats['system_tables'])}개",
        "",
        f"📊 총 레코드: {c(total_rows_str, Colors.GREEN + Colors.BOLD)}개",
        "",
        f"🗂️  데이터셋: {c(str(len(stats['datasets'])), Colors.BLUE + Colors.BOLD)}개"
    ]
    
    for dataset, tables in stats['datasets'].items():
        dataset_rows = sum(stats['table_rows'].get(t, 0) for t in tables)
        lines.append(f"   • {dataset}: {len(tables)}개 테이블, {dataset_rows:,}행")
    
    print_box(lines, "Quick Overview")


def print_version_info(cursor):
    """버전 관리 정보 출력"""
    # _table_versions 테이블 확인
    cursor.execute("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_name = '_table_versions'
        )
    """)
    
    if not cursor.fetchone()[0]:
        print("\n⚠️  버전 관리 테이블(_table_versions)이 없습니다.")
        return
    
    print_subheader("버전 관리 히스토리", "📜")
    
    cursor.execute("""
        SELECT 
            table_id,
            dataset_id,
            table_name,
            original_filename,
            row_count,
            column_count,
            version,
            indexed_at,
            is_current
        FROM _table_versions
        ORDER BY indexed_at DESC
        LIMIT 15
    """)
    
    versions = cursor.fetchall()
    
    if not versions:
        print("   (버전 기록이 없습니다)")
        return
    
    print(f"\n{'No':<3} {'Table ID':<40} {'Ver':<4} {'Rows':>10} {'Cols':>5} {'Current':<8} {'Indexed At':<20}")
    print("─" * 100)
    
    for i, (table_id, dataset_id, table_name, filename, rows, cols, version, indexed_at, is_current) in enumerate(versions, 1):
        current_mark = c("✓", Colors.GREEN) if is_current else ""
        indexed_str = indexed_at.strftime("%Y-%m-%d %H:%M") if indexed_at else "N/A"
        
        # Table ID 축약
        display_id = table_id[:38] + ".." if len(str(table_id)) > 40 else table_id
        
        print(f"{i:<3} {display_id:<40} v{version:<3} {rows or 0:>10,} {cols or 0:>5} {current_mark:<8} {indexed_str:<20}")
    
    # 통계
    cursor.execute("""
        SELECT 
            COUNT(*) as total_versions,
            COUNT(DISTINCT table_id) as unique_tables,
            MAX(indexed_at) as last_indexed
        FROM _table_versions
    """)
    total_versions, unique_tables, last_indexed = cursor.fetchone()
    
    print(f"\n📈 통계: {unique_tables}개 테이블, 총 {total_versions}개 버전 기록")
    if last_indexed:
        print(f"   마지막 인덱싱: {last_indexed.strftime('%Y-%m-%d %H:%M:%S')}")


def print_table_relationships(cursor):
    """테이블 관계 시각화"""
    print_subheader("테이블 관계 (Foreign Keys)", "🔗")
    
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
    
    fks = cursor.fetchall()
    
    if not fks:
        print("   (Foreign Key 관계가 없습니다)")
        return
    
    print(f"\n   발견된 FK 관계: {len(fks)}개\n")
    
    # 관계 그래프 시각화
    relationships = defaultdict(list)
    for table, col, ref_table, ref_col in fks:
        relationships[table].append((col, ref_table, ref_col))
    
    for table, refs in relationships.items():
        print(f"   📁 {c(table, Colors.BOLD)}")
        for col, ref_table, ref_col in refs:
            print(f"      └─ {col} ──▶ {c(ref_table, Colors.BLUE)}.{ref_col}")
        print()


def print_data_tables_summary(cursor, stats):
    """데이터 테이블 요약"""
    print_subheader("데이터 테이블 상세", "📋")
    
    if not stats['data_tables']:
        print("   (데이터 테이블이 없습니다)")
        return
    
    # 헤더
    print(f"\n{'No':<3} {'Table Name':<45} {'Rows':>12} {'Columns':>8} {'Dataset':<15}")
    print("─" * 90)
    
    for i, table in enumerate(sorted(stats['data_tables']), 1):
        # 컬럼 수 조회
        cursor.execute("""
            SELECT COUNT(*) 
            FROM information_schema.columns
            WHERE table_name = %s
        """, (table,))
        col_count = cursor.fetchone()[0]
        
        rows = stats['table_rows'].get(table, 0)
        
        # 데이터셋 추출
        parts = table.split('_')
        dataset = parts[0] if len(parts) >= 2 else 'other'
        
        # 색상 (rows 기준)
        row_str = f"{rows:,}"
        if rows > 10000:
            row_str = c(row_str, Colors.GREEN + Colors.BOLD)
        elif rows > 1000:
            row_str = c(row_str, Colors.YELLOW)
        elif rows == 0:
            row_str = c(row_str, Colors.RED)
        
        # 이름이 길면 축약
        display_name = table[:43] + ".." if len(table) > 45 else table
        
        print(f"{i:<3} {display_name:<45} {row_str:>12} {col_count:>8} {dataset:<15}")
    
    print(f"\n   총 {len(stats['data_tables'])}개 데이터 테이블")


def print_column_analysis(cursor, stats):
    """주요 컬럼 분석"""
    print_subheader("주요 컬럼 분석", "🔍")
    
    # 모든 테이블에서 공통 컬럼 찾기
    column_frequency = defaultdict(int)
    column_tables = defaultdict(list)
    
    for table in stats['data_tables'][:20]:  # 처음 20개 테이블만
        cursor.execute("""
            SELECT column_name 
            FROM information_schema.columns
            WHERE table_name = %s
        """, (table,))
        
        for (col,) in cursor.fetchall():
            column_frequency[col] += 1
            column_tables[col].append(table)
    
    # 자주 나오는 컬럼 (2개 이상 테이블에 존재)
    common_columns = [(col, freq) for col, freq in column_frequency.items() if freq >= 2]
    common_columns.sort(key=lambda x: -x[1])
    
    if common_columns:
        print("\n   📊 공통 컬럼 (2개 이상 테이블에 존재):")
        print(f"   {'Column Name':<30} {'출현 횟수':>10} {'테이블 예시':<30}")
        print("   " + "─" * 70)
        
        for col, freq in common_columns[:15]:
            tables_example = ', '.join(column_tables[col][:2])
            if len(column_tables[col]) > 2:
                tables_example += f" +{len(column_tables[col])-2}개"
            print(f"   {col:<30} {freq:>10}회    {tables_example:<30}")
    
    # 잠재적 ID 컬럼 (caseid, subjectid 등)
    id_keywords = ['id', 'key', 'no', 'num', 'code']
    potential_ids = [col for col in column_frequency.keys() 
                     if any(kw in col.lower() for kw in id_keywords)]
    
    if potential_ids:
        print(f"\n   🔑 잠재적 ID/Key 컬럼:")
        print(f"   {', '.join(sorted(potential_ids)[:10])}")
        if len(potential_ids) > 10:
            print(f"   ... 외 {len(potential_ids) - 10}개")


def print_signal_metadata(cursor):
    """Signal 파일 메타데이터 확인"""
    print_subheader("Signal 파일 메타데이터", "📡")
    
    # signal_files_metadata 테이블 확인
    cursor.execute("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_name = 'signal_files_metadata'
        )
    """)
    
    if not cursor.fetchone()[0]:
        print("   (signal_files_metadata 테이블이 없습니다)")
        return
    
    cursor.execute("""
        SELECT 
            file_path,
            file_format,
            caseid,
            sample_rate,
            num_channels,
            duration_seconds,
            indexed_at
        FROM signal_files_metadata
        ORDER BY indexed_at DESC
        LIMIT 10
    """)
    
    signals = cursor.fetchall()
    
    if not signals:
        print("   (Signal 파일이 없습니다)")
        return
    
    print(f"\n   발견된 Signal 파일: {len(signals)}개\n")
    
    print(f"   {'Case ID':<15} {'Format':<10} {'Channels':>10} {'Sample Rate':>12} {'Duration':>12}")
    print("   " + "─" * 65)
    
    for path, fmt, caseid, sr, channels, duration, indexed_at in signals:
        duration_str = f"{duration:.1f}s" if duration else "N/A"
        sr_str = f"{sr:,}Hz" if sr else "N/A"
        
        print(f"   {caseid or 'N/A':<15} {fmt or 'N/A':<10} {channels or 0:>10} {sr_str:>12} {duration_str:>12}")


def check_database():
    """PostgreSQL DB 상태 확인 (Enhanced)"""
    
    print(c("\n" + "═" * 80, Colors.CYAN + Colors.BOLD))
    print(c("  🗄️  POSTGRESQL DATABASE VIEWER (Enhanced)", Colors.CYAN + Colors.BOLD))
    print(c("═" * 80, Colors.CYAN + Colors.BOLD))
    
    # DB 연결
    try:
        db_manager = get_db_manager()
        conn = db_manager.connect()
        cursor = conn.cursor()
        
        print(f"\n✅ PostgreSQL 연결 성공")
        print(f"   {c('Host:', Colors.BOLD)} {db_manager.db_host}:{db_manager.db_port}")
        print(f"   {c('Database:', Colors.BOLD)} {db_manager.db_name}")
        print(f"   {c('User:', Colors.BOLD)} {db_manager.db_user}")
        
    except Exception as e:
        print(f"\n❌ PostgreSQL 연결 실패: {e}")
        print("\n확인 사항:")
        print("  1. PostgreSQL이 실행 중인가? (./run_postgres_neo4j.sh)")
        print("  2. .env 파일의 POSTGRES_* 설정이 올바른가?")
        return
    
    # 통계 수집
    stats = get_summary_stats(cursor)
    
    if not stats['tables']:
        print("\n⚠️  테이블이 없습니다.")
        print("   먼저 test_agent_with_interrupt.py를 실행하여 데이터를 인덱싱하세요.")
        conn.close()
        return
    
    # 1. Executive Summary
    print_executive_summary(cursor, stats)
    
    # 2. 데이터 테이블 상세
    print_data_tables_summary(cursor, stats)
    
    # 3. 컬럼 분석
    print_column_analysis(cursor, stats)
    
    # 4. 테이블 관계
    print_table_relationships(cursor)
    
    # 5. 버전 관리 정보
    print_version_info(cursor)
    
    # 6. Signal 메타데이터
    print_signal_metadata(cursor)
    
    # 최종 안내
    print_header("사용 안내", "💡")
    print(f"""
   📝 SQL 쿼리 실행:
      psql -U postgres -d {db_manager.db_name}
      
   🔍 예시 쿼리:
      SELECT * FROM _table_versions WHERE is_current = TRUE;
      SELECT table_name, COUNT(*) FROM information_schema.columns GROUP BY table_name;
      
   🚀 대화형 모드:
      python view_database.py --interactive
""")
    
    conn.close()
    
    print(c("\n✅ DB 확인 완료\n", Colors.GREEN + Colors.BOLD))


def interactive_query():
    """대화형 SQL 쿼리 (PostgreSQL)"""
    
    try:
        db_manager = get_db_manager()
        conn = db_manager.connect()
        cursor = conn.cursor()
        
        print_header("Interactive SQL Query Mode", "🔍")
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
            conn.rollback()
    
    conn.close()
    print("\n✅ 종료")


def main():
    """메인 함수"""
    import argparse
    
    parser = argparse.ArgumentParser(description="PostgreSQL DB 확인 (Enhanced)")
    parser.add_argument('--interactive', '-i', action='store_true', help="대화형 쿼리 모드")
    
    args = parser.parse_args()
    
    if args.interactive:
        interactive_query()
    else:
        check_database()


if __name__ == "__main__":
    main()
