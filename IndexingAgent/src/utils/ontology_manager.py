# src/utils/ontology_manager.py
"""
온톨로지 저장/로드/병합 관리자

온톨로지를 JSON 파일로 영구 저장하고, 증분 업데이트 지원
"""

import json
from pathlib import Path
from typing import Dict, Any, List
from datetime import datetime


class OntologyManager:
    """온톨로지 지식 베이스 관리자"""
    
    def __init__(self, db_path: str = "data/processed/ontology_db.json"):
        self.db_path = Path(db_path)
        self.ontology = None
    
    def load(self) -> Dict[str, Any]:
        """
        기존 온톨로지 로드
        
        Returns:
            온톨로지 딕셔너리 (없으면 빈 구조 생성)
        """
        if self.db_path.exists():
            try:
                with open(self.db_path, 'r', encoding='utf-8') as f:
                    self.ontology = json.load(f)
                
                print(f"✅ [Ontology] 기존 온톨로지 로드: {self.db_path}")
                print(f"   - 용어: {len(self.ontology.get('definitions', {}))}개")
                print(f"   - 관계: {len(self.ontology.get('relationships', []))}개")
                print(f"   - 계층: {len(self.ontology.get('hierarchy', []))}개")
                print(f"   - 마지막 업데이트: {self.ontology.get('last_updated', 'N/A')}")
                
                return self.ontology
            except Exception as e:
                print(f"⚠️  [Ontology] 로드 실패: {e}")
                return self._create_empty_ontology()
        else:
            print("📝 [Ontology] 새 온톨로지 생성")
            return self._create_empty_ontology()
    
    def save(self, ontology: Dict[str, Any]):
        """
        온톨로지 저장
        
        Args:
            ontology: 저장할 온톨로지 딕셔너리
        """
        # 디렉토리 생성
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 메타데이터 업데이트
        ontology["last_updated"] = datetime.now().isoformat()
        if "metadata" not in ontology:
            ontology["metadata"] = {}
        
        ontology["metadata"]["total_tables"] = len(ontology.get("file_tags", {}))
        ontology["metadata"]["total_definitions"] = len(ontology.get("definitions", {}))
        ontology["metadata"]["total_relationships"] = len(ontology.get("relationships", []))
        
        # 저장
        try:
            with open(self.db_path, 'w', encoding='utf-8') as f:
                json.dump(ontology, f, indent=2, ensure_ascii=False)
            
            print(f"💾 [Ontology] 저장 완료: {self.db_path}")
            
        except Exception as e:
            print(f"❌ [Ontology] 저장 실패: {e}")
        
        self.ontology = ontology
    
    def merge(self, new_knowledge: Dict[str, Any]) -> Dict[str, Any]:
        """
        기존 온톨로지 + 새 지식 병합 (증분 업데이트)
        
        Args:
            new_knowledge: 새로 추가할 지식
        
        Returns:
            병합된 온톨로지
        """
        if not self.ontology:
            self.ontology = self._create_empty_ontology()
        
        # 1. Definitions 병합 (중복 시 덮어쓰기)
        if "definitions" in new_knowledge:
            self.ontology["definitions"].update(new_knowledge["definitions"])
        
        # 2. Relationships 병합 (중복 제거)
        if "relationships" in new_knowledge:
            existing_rels = {
                self._rel_key(r): r 
                for r in self.ontology.get("relationships", [])
            }
            
            for new_rel in new_knowledge["relationships"]:
                key = self._rel_key(new_rel)
                if key not in existing_rels:
                    existing_rels[key] = new_rel
                else:
                    # 기존 관계 업데이트 (confidence 높은 것 우선)
                    if new_rel.get("confidence", 0) > existing_rels[key].get("confidence", 0):
                        existing_rels[key] = new_rel
            
            self.ontology["relationships"] = list(existing_rels.values())
        
        # 3. Hierarchy 병합
        if "hierarchy" in new_knowledge:
            self._merge_hierarchy(new_knowledge["hierarchy"])
        
        # 4. File Tags 병합
        if "file_tags" in new_knowledge:
            if "file_tags" not in self.ontology:
                self.ontology["file_tags"] = {}
            self.ontology["file_tags"].update(new_knowledge["file_tags"])
        
        return self.ontology
    
    def _rel_key(self, relationship: Dict) -> tuple:
        """관계 중복 체크를 위한 키 생성"""
        return (
            relationship.get("source_table", ""),
            relationship.get("target_table", ""),
            relationship.get("source_column", ""),
            relationship.get("target_column", "")
        )
    
    def _merge_hierarchy(self, new_hierarchy: List[Dict]):
        """
        계층 구조 병합 (충돌 해결)
        """
        if "hierarchy" not in self.ontology:
            self.ontology["hierarchy"] = []
        
        existing_entities = {h["entity_name"]: h for h in self.ontology["hierarchy"]}
        
        # 새 계층 업데이트
        for new_level in new_hierarchy:
            entity = new_level["entity_name"]
            
            # 기존에 없으면 추가
            if entity not in existing_entities:
                self.ontology["hierarchy"].append(new_level)
                existing_entities[entity] = new_level
            else:
                # 있으면 confidence 높은 것 우선
                if new_level.get("confidence", 0) > existing_entities[entity].get("confidence", 0):
                    # 기존 것 제거하고 새 것 추가
                    self.ontology["hierarchy"] = [
                        h for h in self.ontology["hierarchy"]
                        if h["entity_name"] != entity
                    ]
                    self.ontology["hierarchy"].append(new_level)
        
        # 레벨 번호로 정렬
        self.ontology["hierarchy"].sort(key=lambda x: x.get("level", 99))
    
    def _create_empty_ontology(self) -> Dict[str, Any]:
        """빈 온톨로지 구조 생성"""
        return {
            "version": "1.0",
            "created_at": datetime.now().isoformat(),
            "last_updated": datetime.now().isoformat(),
            "definitions": {},
            "relationships": [],
            "hierarchy": [],
            "file_tags": {},
            "metadata": {
                "total_tables": 0,
                "total_definitions": 0,
                "total_relationships": 0
            }
        }
    
    def export_summary(self) -> str:
        """
        온톨로지 요약 출력 (디버깅용)
        
        Returns:
            요약 문자열
        """
        if not self.ontology:
            return "온톨로지 없음"
        
        summary = []
        summary.append("\n" + "="*60)
        summary.append("📚 Ontology Summary")
        summary.append("="*60)
        
        # Definitions
        defs = self.ontology.get("definitions", {})
        summary.append(f"\n🔤 Definitions: {len(defs)}개")
        if defs:
            for i, (key, val) in enumerate(list(defs.items())[:3]):
                summary.append(f"   {i+1}. {key}: {val[:50]}...")
            if len(defs) > 3:
                summary.append(f"   ... and {len(defs) - 3} more")
        
        # Relationships
        rels = self.ontology.get("relationships", [])
        summary.append(f"\n🔗 Relationships: {len(rels)}개")
        if rels:
            for i, rel in enumerate(rels[:3]):
                summary.append(
                    f"   {i+1}. {rel['source_table']}.{rel['source_column']} "
                    f"→ {rel['target_table']}.{rel['target_column']} ({rel['relation_type']})"
                )
            if len(rels) > 3:
                summary.append(f"   ... and {len(rels) - 3} more")
        
        # Hierarchy
        hier = self.ontology.get("hierarchy", [])
        summary.append(f"\n🏗️  Hierarchy: {len(hier)}개 레벨")
        if hier:
            for h in hier:
                summary.append(
                    f"   L{h['level']}: {h['entity_name']} ({h['anchor_column']})"
                )
        
        summary.append("="*60)
        
        return "\n".join(summary)


# 전역 싱글톤 인스턴스
_global_ontology_manager = None

def get_ontology_manager() -> OntologyManager:
    """전역 온톨로지 매니저 반환"""
    global _global_ontology_manager
    if _global_ontology_manager is None:
        _global_ontology_manager = OntologyManager()
    return _global_ontology_manager

