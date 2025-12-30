#!/usr/bin/env python3
"""
모든 DB 테이블 내용을 출력하는 스크립트
파이프라인 실행 없이 현재 DB 상태만 출력
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime


def get_conn():
    """DB 연결"""
    from src.database.connection import get_db_manager
    conn = get_db_manager().get_connection()
    try:
        conn.rollback()
    except:
        pass
    return conn


def print_file_catalog(limit=20):
    """file_catalog 출력"""
    conn = get_conn()
    cur = conn.cursor()
    
    print("\n" + "="*100)
    print("📁 file_catalog")
    print("="*100)
    
    try:
        cur.execute("SELECT COUNT(*) FROM file_catalog")
        total = cur.fetchone()[0]
        
        cur.execute("""
            SELECT file_id, file_name, processor_type, is_metadata, semantic_type,
                   file_size_mb, primary_entity
            FROM file_catalog
            ORDER BY file_name
            LIMIT %s
        """, (limit,))
        
        print(f"\n{'ID':<10} {'File Name':<30} {'Processor':<10} {'Meta':<5} {'Semantic':<15} {'Size(MB)':<10} {'Entity'}")
        print("-"*110)
        
        for row in cur.fetchall():
            fid, fname, proc, meta, sem, size, entity = row
            print(f"{str(fid)[:8]:<10} {fname[:28]:<30} {(proc or '-')[:8]:<10} {'✓' if meta else '-':<5} {(sem or '-')[:13]:<15} {(size or 0):<10.2f} {(entity or '-')}")
        
        print(f"\n[Total: {total}]")
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Error: {e}")


def print_column_metadata(limit=20):
    """column_metadata 출력"""
    conn = get_conn()
    cur = conn.cursor()
    
    print("\n" + "="*100)
    print("📊 column_metadata")
    print("="*100)
    
    try:
        cur.execute("SELECT COUNT(*) FROM column_metadata")
        total = cur.fetchone()[0]
        
        cur.execute("""
            SELECT fc.file_name, cm.original_name, cm.column_type, 
                   cm.semantic_name, cm.concept_category, cm.unit, 
                   cm.dict_match_status, cm.match_confidence
            FROM column_metadata cm
            JOIN file_catalog fc ON cm.file_id = fc.file_id
            ORDER BY fc.file_name, cm.col_id
            LIMIT %s
        """, (limit,))
        
        print(f"\n{'File':<22} {'Column':<15} {'Type':<12} {'Semantic':<20} {'Category':<15} {'Unit':<8} {'Match':<10} {'Conf'}")
        print("-"*120)
        
        for row in cur.fetchall():
            fname, col, dtype, sem, cat, unit, match, conf = row
            conf_str = f"{conf:.2f}" if conf else "-"
            print(f"{fname[:20]:<22} {(col or '-')[:13]:<15} {(dtype or '-')[:10]:<12} {(sem or '-')[:18]:<20} {(cat or '-')[:13]:<15} {(unit or '-')[:6]:<8} {(match or '-')[:8]:<10} {conf_str}")
        
        print(f"\n[Total: {total}]")
        
        # 통계
        cur.execute("SELECT dict_match_status, COUNT(*) FROM column_metadata GROUP BY dict_match_status")
        print("\nMatch Status:")
        for s, c in cur.fetchall():
            print(f"   {s or 'null'}: {c}")
        
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Error: {e}")


def print_data_dictionary(limit=20):
    """data_dictionary 출력"""
    conn = get_conn()
    cur = conn.cursor()
    
    print("\n" + "="*100)
    print("📖 data_dictionary")
    print("="*100)
    
    try:
        cur.execute("SELECT COUNT(*) FROM data_dictionary")
        total = cur.fetchone()[0]
        
        cur.execute("""
            SELECT source_file_name, parameter_key, parameter_desc, parameter_unit, llm_confidence
            FROM data_dictionary
            ORDER BY source_file_name, parameter_key
            LIMIT %s
        """, (limit,))
        
        print(f"\n{'Source':<25} {'Key':<20} {'Description':<40} {'Unit':<10} {'Conf'}")
        print("-"*110)
        
        for row in cur.fetchall():
            src, key, desc, unit, conf = row
            conf_str = f"{conf:.2f}" if conf else "-"
            desc_short = (desc or '-')[:38] + ".." if desc and len(desc) > 40 else (desc or '-')
            print(f"{(src or '-')[:23]:<25} {(key or '-')[:18]:<20} {desc_short:<40} {(unit or '-')[:8]:<10} {conf_str}")
        
        print(f"\n[Total: {total}]")
        
        cur.execute("SELECT source_file_name, COUNT(*) FROM data_dictionary GROUP BY source_file_name")
        print("\nBy Source:")
        for f, c in cur.fetchall():
            print(f"   {f}: {c}")
        
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Error: {e}")


def print_table_entities(limit=20):
    """table_entities 출력"""
    conn = get_conn()
    cur = conn.cursor()
    
    print("\n" + "="*100)
    print("🏷️  table_entities")
    print("="*100)
    
    try:
        cur.execute("SELECT COUNT(*) FROM table_entities")
        total = cur.fetchone()[0]
        
        # LEFT JOIN으로 file_name이 없어도 출력
        cur.execute("""
            SELECT COALESCE(fc.file_name, te.file_id::text) as fname, 
                   te.row_represents, te.entity_identifier, 
                   te.confidence, te.reasoning
            FROM table_entities te
            LEFT JOIN file_catalog fc ON te.file_id = fc.file_id
            ORDER BY te.confidence DESC
            LIMIT %s
        """, (limit,))
        
        print(f"\n{'File/ID':<40} {'Row Represents':<18} {'Identifier':<15} {'Conf':<8} {'Reasoning'}")
        print("-"*115)
        
        for row in cur.fetchall():
            fname, row_rep, ident, conf, reason = row
            reason_short = (reason or '-')[:30] + ".." if reason and len(reason) > 32 else (reason or '-')
            print(f"{fname[:38]:<40} {(row_rep or '-')[:16]:<18} {(ident or '(none)')[:13]:<15} {conf:.2f}    {reason_short}")
        
        print(f"\n[Total: {total}]")
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Error: {e}")


def print_table_relationships(limit=20):
    """table_relationships 출력"""
    conn = get_conn()
    cur = conn.cursor()
    
    print("\n" + "="*100)
    print("🔗 table_relationships")
    print("="*100)
    
    try:
        cur.execute("SELECT COUNT(*) FROM table_relationships")
        total = cur.fetchone()[0]
        
        # LEFT JOIN으로 file_name이 없어도 출력
        cur.execute("""
            SELECT COALESCE(fc1.file_name, tr.source_file_id::text) as src_name,
                   COALESCE(fc2.file_name, tr.target_file_id::text) as tgt_name,
                   tr.source_column, tr.target_column, 
                   tr.relationship_type, tr.cardinality, 
                   tr.confidence, tr.reasoning
            FROM table_relationships tr
            LEFT JOIN file_catalog fc1 ON tr.source_file_id = fc1.file_id
            LEFT JOIN file_catalog fc2 ON tr.target_file_id = fc2.file_id
            ORDER BY tr.confidence DESC
            LIMIT %s
        """, (limit,))
        
        rows = cur.fetchall()
        
        if not rows:
            print("\n(No relationships)")
        else:
            print(f"\n{'Source':<30} {'Target':<30} {'Src Col':<12} {'Tgt Col':<12} {'Type':<12} {'Card':<6} {'Conf'}")
            print("-"*115)
            
            for row in rows:
                src, tgt, scol, tcol, rtype, card, conf, reason = row
                print(f"{src[:28]:<30} {tgt[:28]:<30} {(scol or '-')[:10]:<12} {(tcol or '-')[:10]:<12} {(rtype or '-')[:10]:<12} {(card or '-'):<6} {conf:.2f}")
        
        print(f"\n[Total: {total}]")
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Error: {e}")


def print_ontology_subcategories(limit=20):
    """ontology_subcategories 출력"""
    conn = get_conn()
    cur = conn.cursor()
    
    print("\n" + "="*100)
    print("📂 ontology_subcategories (ontology_enhancement)")
    print("="*100)
    
    try:
        cur.execute("SELECT COUNT(*) FROM ontology_subcategories")
        total = cur.fetchone()[0]
        
        cur.execute("""
            SELECT parent_category, subcategory_name, confidence, reasoning
            FROM ontology_subcategories
            ORDER BY parent_category, subcategory_name
            LIMIT %s
        """, (limit,))
        
        rows = cur.fetchall()
        
        if not rows:
            print("\n(No subcategories)")
        else:
            print(f"\n{'Parent Category':<30} {'Subcategory':<35} {'Conf':<8} {'Reasoning'}")
            print("-"*110)
            
            for row in rows:
                parent, subcat, conf, reason = row
                reason_short = (reason or '-')[:30] + ".." if reason and len(reason) > 32 else (reason or '-')
                print(f"{(parent or '-')[:28]:<30} {(subcat or '-')[:33]:<35} {conf:.2f}    {reason_short}")
        
        print(f"\n[Total: {total}]")
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Error: {e}")


def print_semantic_edges(limit=20):
    """semantic_edges 출력"""
    conn = get_conn()
    cur = conn.cursor()
    
    print("\n" + "="*100)
    print("🔗 semantic_edges (ontology_enhancement)")
    print("="*100)
    
    try:
        cur.execute("SELECT COUNT(*) FROM semantic_edges")
        total = cur.fetchone()[0]
        
        cur.execute("""
            SELECT source_parameter, target_parameter, relationship_type, confidence, reasoning
            FROM semantic_edges
            ORDER BY confidence DESC
            LIMIT %s
        """, (limit,))
        
        rows = cur.fetchall()
        
        if not rows:
            print("\n(No semantic edges)")
        else:
            print(f"\n{'Source':<20} {'Relation':<15} {'Target':<20} {'Conf':<8} {'Reasoning'}")
            print("-"*100)
            
            for row in rows:
                src, tgt, rel, conf, reason = row
                reason_short = (reason or '-')[:30] + ".." if reason and len(reason) > 32 else (reason or '-')
                print(f"{(src or '-')[:18]:<20} {(rel or '-')[:13]:<15} {(tgt or '-')[:18]:<20} {conf:.2f}    {reason_short}")
        
        print(f"\n[Total: {total}]")
        
        cur.execute("SELECT relationship_type, COUNT(*) FROM semantic_edges GROUP BY relationship_type")
        print("\nBy Type:")
        for t, c in cur.fetchall():
            print(f"   {t}: {c}")
        
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Error: {e}")


def print_medical_term_mappings(limit=20):
    """medical_term_mappings 출력"""
    conn = get_conn()
    cur = conn.cursor()
    
    print("\n" + "="*100)
    print("🏥 medical_term_mappings (ontology_enhancement)")
    print("="*100)
    
    try:
        cur.execute("SELECT COUNT(*) FROM medical_term_mappings")
        total = cur.fetchone()[0]
        
        cur.execute("""
            SELECT parameter_key, snomed_code, snomed_name, loinc_code, loinc_name, confidence
            FROM medical_term_mappings
            ORDER BY confidence DESC
            LIMIT %s
        """, (limit,))
        
        rows = cur.fetchall()
        
        if not rows:
            print("\n(No medical mappings)")
        else:
            print(f"\n{'Parameter':<18} {'SNOMED Code':<15} {'SNOMED Name':<30} {'LOINC':<12} {'LOINC Name':<20} {'Conf'}")
            print("-"*115)
            
            for row in rows:
                param, sc, sn, lc, ln, conf = row
                print(f"{(param or '-')[:16]:<18} {(sc or '-')[:13]:<15} {(sn or '-')[:28]:<30} {(lc or '-')[:10]:<12} {(ln or '-')[:18]:<20} {conf:.2f}")
        
        print(f"\n[Total: {total}]")
        
        cur.execute("""
            SELECT COUNT(*), COUNT(snomed_code), COUNT(loinc_code)
            FROM medical_term_mappings
        """)
        t, s, l = cur.fetchone()
        if t > 0:
            print(f"\nCoverage: SNOMED {s}/{t} ({s/t*100:.1f}%), LOINC {l}/{t} ({l/t*100:.1f}%)")
        
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Error: {e}")


def print_cross_table_semantics(limit=20):
    """cross_table_semantics 출력"""
    conn = get_conn()
    cur = conn.cursor()
    
    print("\n" + "="*100)
    print("🔄 cross_table_semantics (ontology_enhancement)")
    print("="*100)
    
    try:
        cur.execute("SELECT COUNT(*) FROM cross_table_semantics")
        total = cur.fetchone()[0]
        
        # LEFT JOIN으로 file_name이 없어도 출력
        cur.execute("""
            SELECT COALESCE(fc1.file_name, cts.source_file_id::text) as src_name,
                   cts.source_column,
                   COALESCE(fc2.file_name, cts.target_file_id::text) as tgt_name,
                   cts.target_column, cts.relationship_type, cts.confidence, cts.reasoning
            FROM cross_table_semantics cts
            LEFT JOIN file_catalog fc1 ON cts.source_file_id = fc1.file_id
            LEFT JOIN file_catalog fc2 ON cts.target_file_id = fc2.file_id
            ORDER BY cts.confidence DESC
            LIMIT %s
        """, (limit,))
        
        rows = cur.fetchall()
        
        if not rows:
            print("\n(No cross-table semantics)")
        else:
            print(f"\n{'Source File/ID':<30} {'Src Col':<12} {'Target File/ID':<30} {'Tgt Col':<12} {'Type':<15} {'Conf'}")
            print("-"*115)
            
            for row in rows:
                sf, sc, tf, tc, rel, conf, reason = row
                print(f"{sf[:28]:<30} {(sc or '-')[:10]:<12} {tf[:28]:<30} {(tc or '-')[:10]:<12} {(rel or '-')[:13]:<15} {conf:.2f}")
        
        print(f"\n[Total: {total}]")
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Error: {e}")


def print_neo4j_stats():
    """Neo4j 통계"""
    try:
        from neo4j import GraphDatabase
        from src.config import Neo4jConfig
        
        driver = GraphDatabase.driver(
            Neo4jConfig.URI, auth=(Neo4jConfig.USER, Neo4jConfig.PASSWORD)
        )
        driver.verify_connectivity()
        
        print("\n" + "="*100)
        print("📊 Neo4j Knowledge Graph")
        print("="*100)
        
        with driver.session(database=Neo4jConfig.DATABASE) as session:
            print("\n🔵 Nodes:")
            for label in ['RowEntity', 'ConceptCategory', 'SubCategory', 'Parameter', 'MedicalTerm']:
                r = session.run(f"MATCH (n:{label}) RETURN count(n) as c")
                print(f"   {label:<18} {r.single()['c']:>5}")
            
            print("\n🔗 Relationships:")
            for rel in ['LINKS_TO', 'HAS_CONCEPT', 'HAS_SUBCATEGORY', 'CONTAINS', 'HAS_COLUMN', 'DERIVED_FROM', 'RELATED_TO', 'MAPS_TO']:
                r = session.run(f"MATCH ()-[r:{rel}]->() RETURN count(r) as c")
                print(f"   {rel:<18} {r.single()['c']:>5}")
        
        driver.close()
    except Exception as e:
        print(f"\n⚠️ Neo4j: {e}")


def print_summary():
    """요약 통계"""
    conn = get_conn()
    cur = conn.cursor()
    
    print("\n" + "="*100)
    print("📈 Summary")
    print("="*100)
    
    tables = [
        ('file_catalog', 'Files'),
        ('column_metadata', 'Columns'),
        ('data_dictionary', 'Dictionary'),
        ('table_entities', 'Entities'),
        ('table_relationships', 'Relationships'),
        ('ontology_subcategories', 'Subcategories'),
        ('semantic_edges', 'Semantic Edges'),
        ('medical_term_mappings', 'Medical Terms'),
        ('cross_table_semantics', 'Cross-table'),
    ]
    
    print(f"\n{'Table':<25} {'Count':>10}")
    print("-"*40)
    
    for tbl, name in tables:
        try:
            cur.execute(f"SELECT COUNT(*) FROM {tbl}")
            print(f"{name:<25} {cur.fetchone()[0]:>10}")
        except:
            conn.rollback()
            print(f"{name:<25} {'ERROR':>10}")


def main():
    print("="*100)
    print("📋 All Database Tables Viewer")
    print(f"   Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*100)
    
    LIMIT = 20
    
    print_summary()
    print_file_catalog(LIMIT)
    print_column_metadata(LIMIT)
    print_data_dictionary(LIMIT)
    print_table_entities(LIMIT)
    print_table_relationships(LIMIT)
    print_ontology_subcategories(LIMIT)
    print_semantic_edges(LIMIT)
    print_medical_term_mappings(LIMIT)
    print_cross_table_semantics(LIMIT)
    print_neo4j_stats()
    
    print("\n" + "="*100)
    print("✅ Done!")
    print("="*100)


if __name__ == "__main__":
    main()

