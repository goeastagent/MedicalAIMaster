#!/usr/bin/env python3
# view_ontology.py
"""
온톨로지 DB 확인 스크립트 (Enhanced Version)

Neo4j에 구축된 온톨로지 지식 그래프의 요약 및 상세 정보를 출력합니다.
"""

import sys
import os
import logging
from collections import defaultdict
from datetime import datetime

# 로깅 설정 (라이브러리 로그는 경고 이상만)
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("view_ontology")
logger.setLevel(logging.INFO)

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.utils.ontology_manager import get_ontology_manager
from src.database.neo4j_connection import Neo4jConnection


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
    MAGENTA = '\033[35m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    END = '\033[0m'


def c(text, color):
    """색상 적용"""
    return f"{color}{text}{Colors.END}"


def print_header(title, emoji="🧠"):
    """큰 섹션 헤더"""
    print(f"\n{c('═' * 80, Colors.MAGENTA)}")
    print(f"{c(f'  {emoji}  {title}', Colors.BOLD + Colors.MAGENTA)}")
    print(f"{c('═' * 80, Colors.MAGENTA)}")


def print_subheader(title, emoji="▶"):
    """작은 섹션 헤더"""
    print(f"\n{c(f'{emoji} {title}', Colors.CYAN + Colors.BOLD)}")
    print(c("─" * 60, Colors.CYAN))


def print_box(lines, title=None, width=76):
    """박스 형태로 출력"""
    print(f"┌{'─' * width}┐")
    if title:
        print(f"│ {c(title, Colors.BOLD):<{width + 8}} │")
        print(f"├{'─' * width}┤")
    for line in lines:
        print(f"│ {line:<{width - 2}} │")
    print(f"└{'─' * width}┘")


# =============================================================================
# Analysis Functions
# =============================================================================

def analyze_ontology(ontology):
    """온톨로지 분석 및 통계"""
    analysis = {
        'definitions_count': len(ontology.get('definitions', {})),
        'relationships_count': len(ontology.get('relationships', [])),
        'hierarchy_count': len(ontology.get('hierarchy', [])),
        'file_tags_count': len(ontology.get('file_tags', {})),
        'column_metadata_count': 0,
        'datasets': set(),
        'metadata_files': [],
        'data_files': [],
        'relationship_types': defaultdict(int),
        'entity_levels': defaultdict(list),
        'columns_per_table': defaultdict(int)
    }
    
    # 파일 분류
    for path, info in ontology.get('file_tags', {}).items():
        file_type = info.get('type', 'unknown')
        if file_type == 'metadata':
            analysis['metadata_files'].append(path)
        else:
            analysis['data_files'].append(path)
        
        # 데이터셋 추출
        if 'dataset_id' in info:
            analysis['datasets'].add(info['dataset_id'])
    
    # 관계 유형
    for rel in ontology.get('relationships', []):
        rel_type = rel.get('relation_type', 'unknown')
        analysis['relationship_types'][rel_type] += 1
    
    # Entity 계층
    for h in ontology.get('hierarchy', []):
        level = h.get('level', 0)
        analysis['entity_levels'][level].append(h.get('entity_name', 'Unknown'))
    
    # 컬럼 메타데이터
    column_metadata = ontology.get('column_metadata', {})
    for table, columns in column_metadata.items():
        analysis['columns_per_table'][table] = len(columns)
        analysis['column_metadata_count'] += len(columns)
    
    return analysis


def print_executive_summary(ontology, analysis):
    """Executive Summary 출력"""
    print_header("ONTOLOGY KNOWLEDGE GRAPH SUMMARY", "🧠")
    
    # 기본 통계
    lines = [
        f"📖 용어 정의 (Definitions): {c(str(analysis['definitions_count']), Colors.GREEN + Colors.BOLD)}개",
        f"🔗 테이블 관계 (Relationships): {c(str(analysis['relationships_count']), Colors.GREEN + Colors.BOLD)}개",
        f"🏗️  Entity 계층 (Hierarchy): {c(str(analysis['hierarchy_count']), Colors.GREEN + Colors.BOLD)}개",
        f"📁 파일 태그 (File Tags): {c(str(analysis['file_tags_count']), Colors.GREEN + Colors.BOLD)}개",
        f"📊 컬럼 메타데이터: {c(str(analysis['column_metadata_count']), Colors.GREEN + Colors.BOLD)}개",
        f"",
        f"🗂️  처리된 파일:",
        f"   • 메타데이터 파일: {len(analysis['metadata_files'])}개",
        f"   • 데이터 파일: {len(analysis['data_files'])}개"
    ]
    
    if analysis['datasets']:
        lines.append(f"")
        lines.append(f"📦 데이터셋: {', '.join(analysis['datasets'])}")
    
    print_box(lines, "Quick Overview")


def print_definitions_summary(ontology):
    """용어 정의 요약"""
    print_subheader("용어 정의 (Definitions)", "📖")
    
    definitions = ontology.get('definitions', {})
    
    if not definitions:
        print("   (정의된 용어가 없습니다)")
        return
    
    # ID 관련 용어
    id_terms = {k: v for k, v in definitions.items() 
                if any(kw in k.lower() for kw in ['id', 'key', 'no', 'num'])}
    
    # 의료 관련 용어 (일반적인 의료 키워드)
    medical_keywords = ['patient', 'case', 'diagnosis', 'medication', 'lab', 'vital', 
                       'blood', 'heart', 'rate', 'pressure', 'temperature', 'oxygen']
    medical_terms = {k: v for k, v in definitions.items() 
                    if any(kw in k.lower() for kw in medical_keywords)}
    
    # 기타 용어
    other_terms = {k: v for k, v in definitions.items() 
                   if k not in id_terms and k not in medical_terms}
    
    print(f"\n   총 {len(definitions)}개 용어 정의됨\n")
    
    # ID 관련 용어
    if id_terms:
        print(f"   {c('🔑 ID/Key 관련 용어:', Colors.YELLOW + Colors.BOLD)}")
        for i, (term, definition) in enumerate(sorted(id_terms.items())[:5], 1):
            def_preview = definition[:60] + "..." if len(str(definition)) > 60 else definition
            print(f"   {i}. {c(term, Colors.BOLD)}")
            print(f"      └─ {def_preview}")
        if len(id_terms) > 5:
            print(f"      ... 외 {len(id_terms) - 5}개")
        print()
    
    # 의료 관련 용어
    if medical_terms:
        print(f"   {c('🏥 의료 관련 용어:', Colors.GREEN + Colors.BOLD)}")
        for i, (term, definition) in enumerate(sorted(medical_terms.items())[:5], 1):
            def_preview = definition[:60] + "..." if len(str(definition)) > 60 else definition
            print(f"   {i}. {c(term, Colors.BOLD)}")
            print(f"      └─ {def_preview}")
        if len(medical_terms) > 5:
            print(f"      ... 외 {len(medical_terms) - 5}개")
        print()
    
    # 기타 용어 (처음 5개만)
    if other_terms:
        print(f"   {c('📝 기타 용어:', Colors.BLUE + Colors.BOLD)}")
        for i, (term, definition) in enumerate(sorted(other_terms.items())[:3], 1):
            def_preview = definition[:60] + "..." if len(str(definition)) > 60 else definition
            print(f"   {i}. {c(term, Colors.BOLD)}")
            print(f"      └─ {def_preview}")
        if len(other_terms) > 3:
            print(f"      ... 외 {len(other_terms) - 3}개")


def print_relationships_summary(ontology, analysis):
    """테이블 관계 요약"""
    print_subheader("테이블 관계 (Relationships)", "🔗")
    
    relationships = ontology.get('relationships', [])
    
    if not relationships:
        print("   (정의된 관계가 없습니다)")
        return
    
    # 관계 유형별 통계
    print(f"\n   {c('관계 유형별 분포:', Colors.BOLD)}")
    for rel_type, count in sorted(analysis['relationship_types'].items(), key=lambda x: -x[1]):
        bar = "█" * min(count * 2, 30)
        print(f"   {rel_type:<8} {bar} ({count}개)")
    
    print(f"\n   {c('테이블 연결 그래프:', Colors.BOLD)}")
    
    # 테이블별 연결 정리
    connections = defaultdict(list)
    for rel in relationships:
        source = rel.get('source_table', 'Unknown')
        target = rel.get('target_table', 'Unknown')
        rel_type = rel.get('relation_type', '?')
        source_col = rel.get('source_column', '?')
        target_col = rel.get('target_column', '?')
        confidence = rel.get('confidence', 0)
        
        connections[source].append({
            'target': target,
            'type': rel_type,
            'on': f"{source_col} = {target_col}",
            'confidence': confidence
        })
    
    # 그래프 출력
    for source, targets in sorted(connections.items()):
        print(f"\n   📁 {c(source, Colors.BOLD + Colors.CYAN)}")
        for t in targets:
            conf_color = Colors.GREEN if t['confidence'] > 0.8 else (Colors.YELLOW if t['confidence'] > 0.5 else Colors.RED)
            conf_str = c(f"{t['confidence']:.0%}", conf_color)
            print(f"      │")
            print(f"      ├─[{t['type']}]──▶ {c(t['target'], Colors.BLUE)} (on: {t['on']}) [{conf_str}]")


def print_hierarchy_summary(ontology, analysis):
    """Entity 계층 구조 요약"""
    print_subheader("Entity 계층 구조 (Hierarchy)", "🏗️")
    
    hierarchy = ontology.get('hierarchy', [])
    
    if not hierarchy:
        print("   (Entity 계층이 정의되지 않았습니다)")
        return
    
    # 레벨별 출력 (트리 형태)
    print(f"\n   {c('Entity 계층 트리:', Colors.BOLD)}")
    
    sorted_hierarchy = sorted(hierarchy, key=lambda x: x.get('level', 0))
    
    for h in sorted_hierarchy:
        level = h.get('level', 0)
        entity = h.get('entity_name', 'Unknown')
        anchor = h.get('anchor_column', 'N/A')
        confidence = h.get('confidence', 0)
        
        # 들여쓰기 (레벨 기반)
        indent = "   " * level
        prefix = "└─" if level > 1 else "●"
        
        conf_color = Colors.GREEN if confidence > 0.8 else (Colors.YELLOW if confidence > 0.5 else Colors.RED)
        
        print(f"   {indent}{prefix} {c(f'Level {level}:', Colors.BOLD)} {c(entity, Colors.CYAN)}")
        print(f"   {indent}   Anchor: {anchor} | Confidence: {c(f'{confidence:.0%}', conf_color)}")


def print_file_tags_summary(ontology, analysis):
    """파일 태그 요약"""
    print_subheader("파일 분류 결과 (File Tags)", "📁")
    
    file_tags = ontology.get('file_tags', {})
    
    if not file_tags:
        print("   (파일 태그가 없습니다)")
        return
    
    # 메타데이터 파일
    if analysis['metadata_files']:
        print(f"\n   {c('📖 메타데이터 파일:', Colors.YELLOW + Colors.BOLD)} ({len(analysis['metadata_files'])}개)")
        for path in analysis['metadata_files'][:5]:
            filename = os.path.basename(path)
            info = file_tags.get(path, {})
            role = info.get('role', 'unknown')
            print(f"      • {filename} [{role}]")
        if len(analysis['metadata_files']) > 5:
            print(f"      ... 외 {len(analysis['metadata_files']) - 5}개")
    
    # 데이터 파일
    if analysis['data_files']:
        print(f"\n   {c('📊 데이터 파일:', Colors.GREEN + Colors.BOLD)} ({len(analysis['data_files'])}개)")
        for path in analysis['data_files'][:10]:
            filename = os.path.basename(path)
            info = file_tags.get(path, {})
            anchor_col = info.get('anchor_column', 'N/A')
            is_time_series = info.get('is_time_series', False)
            ts_mark = "⏱️" if is_time_series else ""
            
            print(f"      • {filename} [anchor: {anchor_col}] {ts_mark}")
        if len(analysis['data_files']) > 10:
            print(f"      ... 외 {len(analysis['data_files']) - 10}개")


def print_column_metadata_summary(ontology):
    """컬럼 메타데이터 요약"""
    print_subheader("컬럼 메타데이터 (Column Metadata)", "📊")
    
    column_metadata = ontology.get('column_metadata', {})
    
    if not column_metadata:
        print("   (컬럼 메타데이터가 없습니다)")
        return
    
    total_columns = sum(len(cols) for cols in column_metadata.values())
    print(f"\n   총 {len(column_metadata)}개 테이블, {total_columns}개 컬럼 메타데이터\n")
    
    # 테이블별 출력
    for table_name, columns in sorted(column_metadata.items())[:5]:
        print(f"   {c(f'📁 {table_name}', Colors.BOLD)} ({len(columns)}개 컬럼)")
        
        for col_name, col_info in sorted(columns.items())[:5]:
            full_name = col_info.get('full_name', col_name)
            data_type = col_info.get('data_type', 'Unknown')
            unit = col_info.get('unit', '')
            is_pii = col_info.get('is_pii', False)
            
            pii_mark = c(" [PII]", Colors.RED) if is_pii else ""
            unit_mark = f" ({unit})" if unit else ""
            
            print(f"      • {col_name}: {full_name}{unit_mark}{pii_mark}")
            
            # 한글 설명이 있으면 출력
            desc_kr = col_info.get('description_kr')
            if desc_kr:
                print(f"        └─ {desc_kr[:50]}...")
        
        if len(columns) > 5:
            print(f"      ... 외 {len(columns) - 5}개 컬럼")
        print()
    
    if len(column_metadata) > 5:
        print(f"   ... 외 {len(column_metadata) - 5}개 테이블")


def print_neo4j_direct_query(neo4j_conn):
    """Neo4j 직접 쿼리 결과"""
    print_subheader("Neo4j 직접 조회", "🔍")
    
    try:
        with neo4j_conn.get_session() as session:
            # 노드 통계
            result = session.run("""
                MATCH (n)
                RETURN labels(n)[0] as label, count(*) as cnt
                ORDER BY cnt DESC
            """)
            node_stats = [(record['label'], record['cnt']) for record in result]
            
            # 관계 통계
            result = session.run("""
                MATCH ()-[r]->()
                RETURN type(r) as rel_type, count(*) as cnt
                ORDER BY cnt DESC
            """)
            rel_stats = [(record['rel_type'], record['cnt']) for record in result]
            
            print(f"\n   {c('노드 타입별 개수:', Colors.BOLD)}")
            for label, cnt in node_stats[:10]:
                print(f"      • {label}: {cnt}개")
            
            print(f"\n   {c('관계 타입별 개수:', Colors.BOLD)}")
            for rel_type, cnt in rel_stats[:10]:
                print(f"      • {rel_type}: {cnt}개")
            
    except Exception as e:
        print(f"   ⚠️ Neo4j 쿼리 실패: {e}")


def interactive_menu(ontology, neo4j_conn):
    """대화형 메뉴"""
    while True:
        print(f"\n{c('─' * 50, Colors.CYAN)}")
        print(f"{c('🔍 상세 조회 메뉴:', Colors.BOLD)}")
        print("1. Definitions (용어 사전) 전체 보기")
        print("2. Relationships (관계) 전체 보기")
        print("3. Hierarchy (계층 구조) 전체 보기")
        print("4. File Tags (파일 분류) 전체 보기")
        print("5. Column Metadata (컬럼 정보) 전체 보기")
        print("6. Neo4j Cypher 쿼리 실행")
        print("q. 종료")
        print(c("─" * 50, Colors.CYAN))
        
        choice = input("선택 >>> ").strip().lower()
        
        if choice == 'q':
            break
            
        elif choice == '1':
            print_header("Definitions (전체)", "📖")
            definitions = ontology.get('definitions', {})
            for i, (key, val) in enumerate(sorted(definitions.items()), 1):
                print(f"\n{i}. {c(key, Colors.BOLD)}")
                print(f"   {val}")
            print(f"\n총 {len(definitions)}개 용어")

        elif choice == '2':
            print_header("Relationships (전체)", "🔗")
            relationships = ontology.get('relationships', [])
            for i, rel in enumerate(relationships, 1):
                print(f"\n{i}. {rel.get('source_table')} → {rel.get('target_table')}")
                print(f"   Type: {rel.get('relation_type')}")
                print(f"   On: {rel.get('source_column', '')} = {rel.get('target_column', '')}")
                print(f"   Confidence: {rel.get('confidence', 0):.0%}")
            print(f"\n총 {len(relationships)}개 관계")

        elif choice == '3':
            print_header("Hierarchy (전체)", "🏗️")
            hierarchy = ontology.get('hierarchy', [])
            for h in sorted(hierarchy, key=lambda x: x.get('level', 0)):
                print(f"\nLevel {h.get('level', 0)}: {c(h.get('entity_name'), Colors.BOLD)}")
                print(f"  - Anchor: {h.get('anchor_column', 'N/A')}")
                print(f"  - Mapping Table: {h.get('mapping_table', 'N/A')}")
                print(f"  - Confidence: {h.get('confidence', 0):.0%}")
            print(f"\n총 {len(hierarchy)}개 Entity")

        elif choice == '4':
            print_header("File Tags (전체)", "📁")
            file_tags = ontology.get('file_tags', {})
            for i, (path, info) in enumerate(sorted(file_tags.items()), 1):
                filename = os.path.basename(path)
                file_type = info.get('type', 'unknown')
                print(f"\n{i}. {c(filename, Colors.BOLD)} [{file_type}]")
                for k, v in info.items():
                    if k != 'type':
                        print(f"   • {k}: {str(v)[:60]}...")
            print(f"\n총 {len(file_tags)}개 파일")

        elif choice == '5':
            print_header("Column Metadata (전체)", "📊")
            column_metadata = ontology.get('column_metadata', {})
            for table, columns in sorted(column_metadata.items()):
                print(f"\n{c(table, Colors.BOLD + Colors.CYAN)} ({len(columns)}개 컬럼)")
                for col_name, col_info in sorted(columns.items()):
                    print(f"   • {col_name}")
                    for k, v in col_info.items():
                        print(f"     - {k}: {v}")

        elif choice == '6':
            print_header("Neo4j Cypher Query", "🔍")
            print("Cypher 쿼리를 입력하세요 (빈 줄로 종료)")
            
            while True:
                query = input("Cypher> ").strip()
                if not query:
                    break
                
                try:
                    with neo4j_conn.get_session() as session:
                        result = session.run(query)
                        records = list(result)
                        
                        if records:
                            print(f"\n결과: {len(records)}행")
                            for i, record in enumerate(records[:20], 1):
                                print(f"{i}. {dict(record)}")
                            if len(records) > 20:
                                print(f"... 외 {len(records) - 20}행")
                        else:
                            print("결과 없음")
                except Exception as e:
                    print(f"❌ 쿼리 에러: {e}")


def main():
    """메인 함수"""
    print(c("\n" + "═" * 80, Colors.MAGENTA + Colors.BOLD))
    print(c("  🧠  ONTOLOGY KNOWLEDGE GRAPH VIEWER (Enhanced)", Colors.MAGENTA + Colors.BOLD))
    print(c("═" * 80, Colors.MAGENTA + Colors.BOLD))
    
    # 1. Neo4j 연결 확인
    print("\n🔌 Neo4j 연결 확인 중...")
    try:
        neo4j_conn = Neo4jConnection()
        neo4j_conn.connect()
        print("✅ Neo4j 연결 성공")
    except Exception as e:
        print(f"\n❌ Neo4j 연결 실패: {e}")
        print("----------------------------------------------------------------")
        print("💡 Tip: .env 파일의 NEO4J_USER, NEO4J_PASSWORD 설정을 확인하세요.")
        print("        또는 run_postgres_neo4j.sh 스크립트가 실행 중인지 확인하세요.")
        print("----------------------------------------------------------------")
        return

    # 2. 온톨로지 로드
    print("📥 온톨로지 데이터 로드 중...")
    try:
        manager = get_ontology_manager()
        ontology = manager.load()
    except Exception as e:
        print(f"❌ 데이터 로드 중 오류 발생: {e}")
        return
    
    # 3. 데이터 검증
    definitions = ontology.get("definitions", {})
    relationships = ontology.get("relationships", [])
    file_tags = ontology.get("file_tags", {})
    
    if not definitions and not relationships and not file_tags:
        print("\n⚠️  온톨로지가 비어있습니다 (데이터 없음).")
        print("   먼저 test_agent_with_interrupt.py를 실행하여 데이터를 인덱싱하세요.")
        return
    
    # 4. 분석
    analysis = analyze_ontology(ontology)
    
    # 5. 요약 출력
    print_executive_summary(ontology, analysis)
    print_definitions_summary(ontology)
    print_relationships_summary(ontology, analysis)
    print_hierarchy_summary(ontology, analysis)
    print_file_tags_summary(ontology, analysis)
    print_column_metadata_summary(ontology)
    print_neo4j_direct_query(neo4j_conn)
    
    # 6. 대화형 메뉴
    interactive_menu(ontology, neo4j_conn)
    
    print(c("\n👋 종료합니다.\n", Colors.GREEN + Colors.BOLD))


if __name__ == "__main__":
    main()
