#!/usr/bin/env python3
"""
모든 DB 테이블 자동 탐지 및 출력 스크립트

- 모든 테이블을 자동으로 탐지
- 각 테이블당 20개의 레코드 출력
- 테이블 스키마 정보 표시
"""

import sys
import os
from datetime import datetime

# tabulate는 optional
try:
    from tabulate import tabulate
    HAS_TABULATE = True
except ImportError:
    HAS_TABULATE = False

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# =============================================================================
# ANSI Colors
# =============================================================================
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    END = '\033[0m'


def c(text, color):
    return f"{color}{text}{Colors.END}"


# =============================================================================
# Database Functions
# =============================================================================
def get_connection():
    """PostgreSQL 연결"""
    from src.database.connection import get_db_manager
    conn = get_db_manager().get_connection()
    try:
        conn.rollback()
    except:
        pass
    return conn


def get_all_tables(conn):
    """모든 테이블 목록 조회"""
    cur = conn.cursor()
    cur.execute("""
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema = 'public' 
        AND table_type = 'BASE TABLE'
        ORDER BY table_name
    """)
    tables = [row[0] for row in cur.fetchall()]
    return tables


def get_table_columns(conn, table_name):
    """테이블 컬럼 정보 조회"""
    cur = conn.cursor()
    cur.execute("""
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_name = %s
        ORDER BY ordinal_position
    """, (table_name,))
    return cur.fetchall()


def get_table_row_count(conn, table_name):
    """테이블 행 수 조회"""
    cur = conn.cursor()
    try:
        cur.execute(f'SELECT COUNT(*) FROM "{table_name}"')
        return cur.fetchone()[0]
    except Exception as e:
        conn.rollback()
        return f"Error: {e}"


def get_table_sample(conn, table_name, limit=20):
    """테이블 샘플 데이터 조회"""
    cur = conn.cursor()
    try:
        # 컬럼명 조회
        cur.execute(f'SELECT * FROM "{table_name}" LIMIT 0')
        column_names = [desc[0] for desc in cur.description]
        
        # 데이터 조회
        cur.execute(f'SELECT * FROM "{table_name}" LIMIT %s', (limit,))
        rows = cur.fetchall()
        conn.commit()
        
        return column_names, rows
    except Exception as e:
        conn.rollback()
        return None, f"Error: {e}"


def truncate_value(value, max_len=50):
    """값 truncate"""
    if value is None:
        return "NULL"
    s = str(value)
    if len(s) > max_len:
        return s[:max_len-2] + ".."
    return s


# =============================================================================
# Display Functions
# =============================================================================
def print_header(title, emoji="📊"):
    """섹션 헤더 출력"""
    print(f"\n{c('═' * 100, Colors.CYAN)}")
    print(f"{c(f'  {emoji}  {title}', Colors.BOLD + Colors.CYAN)}")
    print(f"{c('═' * 100, Colors.CYAN)}")


def print_table_info(conn, table_name, limit=20):
    """단일 테이블 정보 출력"""
    # 테이블 헤더
    row_count = get_table_row_count(conn, table_name)
    print(f"\n{c('─' * 100, Colors.YELLOW)}")
    print(f"{c(f'📋 {table_name}', Colors.BOLD + Colors.YELLOW)}  ({c(f'{row_count} rows', Colors.GREEN)})")
    print(f"{c('─' * 100, Colors.YELLOW)}")
    
    # 컬럼 스키마 정보
    columns_info = get_table_columns(conn, table_name)
    if columns_info:
        print(f"\n  {c('Columns:', Colors.BOLD)}")
        col_list = []
        for col_name, data_type, nullable in columns_info:
            null_mark = "" if nullable == "YES" else " (NOT NULL)"
            col_list.append(f"{col_name} [{data_type}{null_mark}]")
        
        # 3열로 출력
        for i in range(0, len(col_list), 3):
            chunk = col_list[i:i+3]
            print(f"    {', '.join(chunk)}")
    
    # 샘플 데이터
    column_names, rows = get_table_sample(conn, table_name, limit)
    
    if column_names is None:
        print(f"\n  {c(f'Error: {rows}', Colors.RED)}")
        return
    
    if not rows:
        print(f"\n  {c('(Empty table)', Colors.YELLOW)}")
        return
    
    # 데이터를 truncate해서 표시
    display_rows = []
    for row in rows:
        display_row = [truncate_value(v, 40) for v in row]
        display_rows.append(display_row)
    
    # 컬럼명도 truncate
    display_columns = [col[:25] for col in column_names]
    
    print(f"\n  {c('Sample Data:', Colors.BOLD)} (showing {len(rows)} of {row_count})")
    
    # tabulate로 테이블 형식 출력
    if HAS_TABULATE:
        try:
            table_str = tabulate(display_rows, headers=display_columns, tablefmt="simple", maxcolwidths=40)
            # 들여쓰기 추가
            for line in table_str.split('\n'):
                print(f"  {line}")
        except Exception:
            # tabulate 실패 시 간단한 출력
            _print_simple_table(display_columns, display_rows, limit)
    else:
        _print_simple_table(display_columns, display_rows, limit)


def _print_simple_table(columns, rows, limit):
    """간단한 테이블 출력 (tabulate 없을 때)"""
    # 각 컬럼별 최대 너비 계산
    col_widths = []
    for i, col in enumerate(columns):
        max_width = len(col)
        for row in rows[:limit]:
            if i < len(row):
                max_width = max(max_width, len(str(row[i])))
        col_widths.append(min(max_width, 25))  # 최대 25자
    
    # 헤더 출력
    header = " | ".join(col[:col_widths[i]].ljust(col_widths[i]) for i, col in enumerate(columns))
    print(f"  {header}")
    print(f"  {'-' * len(header)}")
    
    # 데이터 출력
    for row in rows[:limit]:
        row_str = " | ".join(str(v)[:col_widths[i]].ljust(col_widths[i]) for i, v in enumerate(row))
        print(f"  {row_str}")


def print_summary(conn, tables):
    """요약 정보 출력"""
    print_header("DATABASE SUMMARY", "🗄️")
    
    total_rows = 0
    table_stats = []
    
    for table in tables:
        count = get_table_row_count(conn, table)
        if isinstance(count, int):
            total_rows += count
            table_stats.append((table, count))
        else:
            table_stats.append((table, "Error"))
    
    # 통계 출력
    print(f"\n  {c('Total Tables:', Colors.BOLD)} {len(tables)}")
    print(f"  {c('Total Rows:', Colors.BOLD)} {total_rows:,}")
    
    # 테이블별 행 수
    print(f"\n  {c('Table Row Counts:', Colors.BOLD)}")
    
    # 데이터 테이블과 시스템 테이블 분리
    data_tables = [(t, c) for t, c in table_stats if not t.startswith('_')]
    system_tables = [(t, c) for t, c in table_stats if t.startswith('_')]
    
    if data_tables:
        print(f"\n  {c('📊 Data Tables:', Colors.CYAN)}")
        for table, count in sorted(data_tables, key=lambda x: x[0]):
            count_str = f"{count:,}" if isinstance(count, int) else count
            status = c("✓", Colors.GREEN) if count and count != "Error" else c("○", Colors.YELLOW)
            print(f"    {status} {table:<45} {count_str:>10}")
    
    if system_tables:
        print(f"\n  {c('⚙️  System Tables:', Colors.CYAN)}")
        for table, count in sorted(system_tables, key=lambda x: x[0]):
            count_str = f"{count:,}" if isinstance(count, int) else count
            status = c("✓", Colors.GREEN) if count and count != "Error" else c("○", Colors.YELLOW)
            print(f"    {status} {table:<45} {count_str:>10}")


# =============================================================================
# Main
# =============================================================================
def main():
    LIMIT = 20  # 각 테이블당 표시할 레코드 수
    
    print(c("\n" + "═" * 100, Colors.CYAN + Colors.BOLD))
    print(c("  🗄️  ALL DATABASE TABLES VIEWER", Colors.CYAN + Colors.BOLD))
    print(c(f"     Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", Colors.CYAN))
    print(c("═" * 100, Colors.CYAN + Colors.BOLD))
    
    # DB 연결
    try:
        conn = get_connection()
        print(f"\n{c('✅ PostgreSQL 연결 성공', Colors.GREEN)}")
    except Exception as e:
        print(f"\n{c(f'❌ PostgreSQL 연결 실패: {e}', Colors.RED)}")
        print("\n확인 사항:")
        print("  1. PostgreSQL이 실행 중인가? (./run_postgres_neo4j.sh)")
        print("  2. .env 파일의 POSTGRES_* 설정이 올바른가?")
        return
    
    # 모든 테이블 조회
    tables = get_all_tables(conn)
    
    if not tables:
        print(f"\n{c('⚠️  테이블이 없습니다.', Colors.YELLOW)}")
        return
    
    # 요약 출력
    print_summary(conn, tables)
    
    # 각 테이블 상세 출력
    print_header(f"ALL TABLES DETAIL (Limit {LIMIT} rows each)", "📋")
    
    for table in tables:
        print_table_info(conn, table, LIMIT)
    
    # 완료
    print(f"\n{c('═' * 100, Colors.GREEN)}")
    print(f"{c('✅ Done! Displayed all tables.', Colors.GREEN + Colors.BOLD)}")
    print(f"{c('═' * 100, Colors.GREEN)}")


if __name__ == "__main__":
    main()

