# src/agents/context/schema_context_builder.py
"""
SchemaContextBuilder - 동적 스키마 컨텍스트 생성

PostgreSQL 메타데이터 테이블을 쿼리하여 LLM 프롬프트용 컨텍스트를 생성합니다.

데이터 소스:
- file_catalog + table_entities: Cohort 소스 정보
- file_group: Signal 그룹 정보  
- column_metadata: 필터링 가능한 컬럼
- parameter: 파라미터 목록 (카테고리별)
- table_relationships: 테이블 간 관계

Output:
{
    "cohort_sources": [...],
    "signal_groups": [...],
    "parameters": {...},
    "relationships": [...],
    "context_text": "LLM 프롬프트용 텍스트"
}
"""

import sys
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

# shared 패키지 경로 추가
project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from shared.database.connection import get_db_manager
from shared.database.repositories import (
    FileRepository,
    FileGroupRepository,
    EntityRepository,
    ParameterRepository,
    ColumnRepository,
)


@dataclass
class SchemaContext:
    """스키마 컨텍스트 데이터 클래스"""
    cohort_sources: List[Dict[str, Any]] = field(default_factory=list)
    signal_groups: List[Dict[str, Any]] = field(default_factory=list)
    parameters: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)
    parameter_examples: List[Dict[str, Any]] = field(default_factory=list)  # 소스별 예시
    relationships: List[Dict[str, Any]] = field(default_factory=list)
    context_text: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "cohort_sources": self.cohort_sources,
            "signal_groups": self.signal_groups,
            "parameters": self.parameters,
            "parameter_examples": self.parameter_examples,
            "relationships": self.relationships,
            "context_text": self.context_text,
        }


class SchemaContextBuilder:
    """
    동적 스키마 컨텍스트 빌더
    
    PostgreSQL 메타데이터를 쿼리하여 LLM이 데이터 구조를 이해할 수 있는
    컨텍스트를 생성합니다.
    
    Usage:
        builder = SchemaContextBuilder()
        context = builder.build_context()
        
        # 또는 개별 메서드 사용
        cohort_sources = builder.get_cohort_sources()
        signal_groups = builder.get_signal_groups()
    """
    
    def __init__(self, db_manager=None):
        """
        Args:
            db_manager: DatabaseManager 인스턴스 (None이면 자동 생성)
        """
        self.db = db_manager or get_db_manager()
        
        # Repositories
        self._file_repo = None
        self._group_repo = None
        self._entity_repo = None
        self._param_repo = None
        self._column_repo = None
    
    @property
    def file_repo(self) -> FileRepository:
        if self._file_repo is None:
            self._file_repo = FileRepository(self.db)
        return self._file_repo
    
    @property
    def group_repo(self) -> FileGroupRepository:
        if self._group_repo is None:
            self._group_repo = FileGroupRepository(self.db)
        return self._group_repo
    
    @property
    def entity_repo(self) -> EntityRepository:
        if self._entity_repo is None:
            self._entity_repo = EntityRepository(self.db)
        return self._entity_repo
    
    @property
    def param_repo(self) -> ParameterRepository:
        if self._param_repo is None:
            self._param_repo = ParameterRepository(self.db)
        return self._param_repo
    
    @property
    def column_repo(self) -> ColumnRepository:
        if self._column_repo is None:
            self._column_repo = ColumnRepository(self.db)
        return self._column_repo
    
    # =========================================================================
    # Main Entry Point
    # =========================================================================
    
    def build_context(self, max_parameters: int = 100) -> Dict[str, Any]:
        """
        전체 스키마 컨텍스트 빌드
        
        Args:
            max_parameters: 컨텍스트에 포함할 최대 파라미터 수
        
        Returns:
            {
                "cohort_sources": [...],
                "signal_groups": [...],
                "parameters": {...},
                "relationships": [...],
                "context_text": "..."
            }
        """
        context = SchemaContext()
        
        # 1. Cohort 소스 조회
        context.cohort_sources = self.get_cohort_sources()
        
        # 2. Signal 그룹 조회
        context.signal_groups = self.get_signal_groups()
        
        # 3. 파라미터 조회 (카테고리별)
        context.parameters = self.get_parameter_summary(limit=max_parameters)
        
        # 4. 파라미터 예시 조회 (소스별)
        context.parameter_examples = self.get_parameter_examples(examples_per_source=3)
        
        # 5. 관계 조회
        context.relationships = self.get_relationships()
        
        # 6. LLM 프롬프트용 텍스트 생성
        context.context_text = self.build_context_text(context)
        
        return context.to_dict()
    
    # =========================================================================
    # Individual Query Methods
    # =========================================================================
    
    def get_cohort_sources(self) -> List[Dict[str, Any]]:
        """
        Cohort 소스 정보 조회
        
        file_catalog + table_entities를 조인하여 cohort 정보를 가져옵니다.
        is_metadata=false이고 table_entities에 entity 정보가 있는 파일들.
        
        Returns:
            [
                {
                    "file_id": "uuid-...",
                    "file_name": "clinical_data.csv",
                    "row_represents": "surgical_case",
                    "entity_identifier": "caseid",
                    "row_count": 6388,
                    "filterable_columns": [...],
                    "temporal_columns": [...]
                }
            ]
        """
        try:
            # table_entities에서 Entity 정보가 있는 파일들 조회
            tables = self.entity_repo.get_tables_with_entities(include_semantic=True)
            
            cohort_sources = []
            for table in tables:
                # Signal group에 속한 파일은 제외 (group_id가 있으면 signal source)
                if table.get("group_id"):
                    continue
                
                file_id = table["file_id"]
                
                # 필터링 가능한 컬럼 조회
                columns = self.column_repo.get_columns_with_semantic(file_id)
                
                filterable_columns = []
                temporal_columns = []
                
                for col in columns:
                    col_role = col.get("column_role", "")
                    col_name = col.get("original_name", "")
                    semantic_name = col.get("semantic_name", col_name)
                    
                    # 필터링 가능한 컬럼 (identifier, metadata 등)
                    if col_role in ("identifier", "metadata", "categorical"):
                        filterable_columns.append({
                            "column_name": col_name,
                            "semantic_name": semantic_name,
                            "role": col_role
                        })
                    
                    # 시간 관련 컬럼
                    if col_role == "timestamp" or "time" in col_name.lower() or "date" in col_name.lower():
                        temporal_columns.append({
                            "column_name": col_name,
                            "semantic_name": semantic_name
                        })
                
                cohort_sources.append({
                    "file_id": file_id,
                    "file_name": table["file_name"],
                    "row_represents": table.get("row_represents"),
                    "entity_identifier": table.get("entity_identifier"),
                    "row_count": table.get("row_count", 0),
                    "filterable_columns": filterable_columns,
                    "temporal_columns": temporal_columns
                })
            
            return cohort_sources
            
        except Exception as e:
            print(f"[SchemaContextBuilder] Error getting cohort sources: {e}")
            try:
                self.db.rollback()
            except:
                pass
            return []
    
    def get_signal_groups(self) -> List[Dict[str, Any]]:
        """
        Signal 그룹 정보 조회
        
        status='confirmed'인 file_group 조회
        
        Returns:
            [
                {
                    "group_id": "uuid-...",
                    "group_name": "vital_case_records",
                    "file_count": 6388,
                    "file_pattern": "*.vital",
                    "entity_identifier_key": "caseid",
                    "row_represents": "surgical_case_vital_signs"
                }
            ]
        """
        try:
            groups = self.group_repo.get_all_groups(status="confirmed")
            
            signal_groups = []
            for group in groups:
                criteria = group.get("grouping_criteria", {})
                
                signal_groups.append({
                    "group_id": group["group_id"],
                    "group_name": group["group_name"],
                    "file_count": group.get("file_count", 0),
                    "file_pattern": criteria.get("pattern", criteria.get("extensions", [])),
                    "entity_identifier_key": group.get("entity_identifier_key"),
                    "entity_identifier_source": group.get("entity_identifier_source"),
                    "row_represents": group.get("row_represents")
                })
            
            return signal_groups
            
        except Exception as e:
            print(f"[SchemaContextBuilder] Error getting signal groups: {e}")
            try:
                self.db.rollback()
            except:
                pass
            return []
    
    def get_filterable_columns(self, file_id: str) -> List[Dict[str, Any]]:
        """
        특정 파일의 필터링 가능한 컬럼 조회
        
        column_role이 'identifier', 'metadata', 'categorical'인 컬럼
        
        Returns:
            [
                {
                    "column_name": "diagnosis",
                    "semantic_name": "Diagnosis",
                    "data_type": "text",
                    "role": "metadata"
                }
            ]
        """
        try:
            columns = self.column_repo.get_columns_with_semantic(file_id)
            
            filterable = []
            for col in columns:
                role = col.get("column_role", "")
                if role in ("identifier", "metadata", "categorical"):
                    filterable.append({
                        "column_name": col.get("original_name"),
                        "semantic_name": col.get("semantic_name"),
                        "role": role
                    })
            
            return filterable
            
        except Exception as e:
            print(f"[SchemaContextBuilder] Error getting filterable columns: {e}")
            try:
                self.db.rollback()
            except:
                pass
            return []
    
    def get_parameter_summary(self, limit: int = 100) -> Dict[str, List[Dict[str, Any]]]:
        """
        파라미터 요약 조회 (카테고리별 그룹핑)
        
        Returns:
            {
                "Vital Signs": [
                    {"param_key": "Solar8000/HR", "semantic_name": "Heart Rate", "unit": "bpm"},
                    ...
                ],
                "Laboratory": [...],
                ...
            }
        """
        try:
            # 카테고리별 파라미터 조회
            params_by_concept = self.param_repo.get_parameters_by_concept()
            
            # 각 카테고리별로 limit 적용
            result = {}
            total_count = 0
            
            for category, params in params_by_concept.items():
                if total_count >= limit:
                    break
                
                remaining = limit - total_count
                category_params = params[:remaining]
                
                result[category] = [
                    {
                        "param_key": p.get("key"),
                        "semantic_name": p.get("name"),
                        "unit": p.get("unit")
                    }
                    for p in category_params
                ]
                
                total_count += len(category_params)
            
            return result
            
        except Exception as e:
            print(f"[SchemaContextBuilder] Error getting parameters: {e}")
            try:
                self.db.rollback()
            except:
                pass
            return {}
    
    def get_parameter_examples(self, examples_per_source: int = 3) -> List[Dict[str, Any]]:
        """
        소스별 파라미터 예시 조회 (프롬프트용)
        
        Args:
            examples_per_source: 각 소스(장비)별 가져올 예시 수
        
        Returns:
            [
                {
                    "source": "Solar8000",
                    "source_type": "device",
                    "param_key": "Solar8000/HR",
                    "semantic_name": "Heart Rate",
                    "unit": "/min",
                    "category": "Vital Signs"
                },
                ...
            ]
        """
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            # Note: %% is escaped to % for psycopg2
            query = """
                WITH ranked AS (
                    SELECT 
                        param_key, 
                        semantic_name, 
                        unit, 
                        concept_category,
                        CASE 
                            WHEN param_key LIKE '%%/%%' THEN split_part(param_key, '/', 1)
                            ELSE 'clinical_lab'
                        END as source,
                        CASE 
                            WHEN param_key LIKE '%%/%%' THEN 'device'
                            ELSE 'clinical'
                        END as source_type,
                        ROW_NUMBER() OVER (
                            PARTITION BY CASE 
                                WHEN param_key LIKE '%%/%%' THEN split_part(param_key, '/', 1)
                                ELSE 'clinical_lab'
                            END 
                            ORDER BY param_id
                        ) as rn
                    FROM parameter
                    WHERE semantic_name IS NOT NULL
                )
                SELECT source, source_type, param_key, semantic_name, unit, concept_category
                FROM ranked
                WHERE rn <= %s
                ORDER BY source, rn
            """
            
            cursor.execute(query, (examples_per_source,))
            rows = cursor.fetchall()
            conn.commit()
            
            examples = []
            for row in rows:
                source, source_type, param_key, sem_name, unit, category = row
                examples.append({
                    "source": source,
                    "source_type": source_type,
                    "param_key": param_key,
                    "semantic_name": sem_name,
                    "unit": unit,
                    "category": category
                })
            
            return examples
            
        except Exception as e:
            print(f"[SchemaContextBuilder] Error getting parameter examples: {e}")
            try:
                self.db.rollback()
            except:
                pass
            return []
    
    def get_relationships(self) -> List[Dict[str, Any]]:
        """
        테이블 간 관계 조회
        
        Returns:
            [
                {
                    "from_table": "clinical_data.csv",
                    "to_table": "vital_files",
                    "from_column": "caseid",
                    "to_column": "filename_values.caseid",
                    "cardinality": "1:N"
                }
            ]
        """
        try:
            relationships = self.entity_repo.get_relationships()
            
            result = []
            for rel in relationships:
                result.append({
                    "from_table": rel.get("source_name"),
                    "to_table": rel.get("target_name"),
                    "from_column": rel.get("source_column"),
                    "to_column": rel.get("target_column"),
                    "cardinality": rel.get("cardinality"),
                    "relationship_type": rel.get("relationship_type")
                })
            
            return result
            
        except Exception as e:
            print(f"[SchemaContextBuilder] Error getting relationships: {e}")
            # 트랜잭션 롤백
            try:
                self.db.rollback()
            except:
                pass
            return []
    
    # =========================================================================
    # Context Text Generation
    # =========================================================================
    
    def build_context_text(self, context: SchemaContext) -> str:
        """
        LLM 프롬프트용 컨텍스트 텍스트 생성
        
        Args:
            context: SchemaContext 객체
        
        Returns:
            마크다운 형식의 컨텍스트 텍스트
        """
        lines = []
        
        # 1. Cohort Sources
        lines.append("## 데이터 소스")
        lines.append("")
        
        if context.cohort_sources:
            lines.append("### Cohort (환자/케이스 메타데이터)")
            for cs in context.cohort_sources:
                lines.append(f"- **{cs['file_name']}**")
                lines.append(f"  - 행의 의미: {cs.get('row_represents', 'N/A')}")
                lines.append(f"  - 식별자 컬럼: {cs.get('entity_identifier', 'N/A')}")
                lines.append(f"  - 행 수: {cs.get('row_count', 'N/A')}")
                
                if cs.get('filterable_columns'):
                    filter_cols = [c['column_name'] for c in cs['filterable_columns'][:5]]
                    lines.append(f"  - 필터 가능 컬럼: {', '.join(filter_cols)}")
                
                if cs.get('temporal_columns'):
                    temp_cols = [c['column_name'] for c in cs['temporal_columns'][:3]]
                    lines.append(f"  - 시간 컬럼: {', '.join(temp_cols)}")
            lines.append("")
        
        # 2. Signal Groups
        if context.signal_groups:
            lines.append("### Signal Groups (시계열 데이터)")
            for sg in context.signal_groups:
                lines.append(f"- **{sg['group_name']}**")
                lines.append(f"  - 파일 수: {sg.get('file_count', 'N/A')}")
                lines.append(f"  - 패턴: {sg.get('file_pattern', 'N/A')}")
                lines.append(f"  - 식별자 키: {sg.get('entity_identifier_key', 'N/A')}")
                lines.append(f"  - 행의 의미: {sg.get('row_represents', 'N/A')}")
            lines.append("")
        
        # 3. Parameters
        if context.parameters:
            lines.append("## 측정 파라미터")
            lines.append("")
            
            for category, params in context.parameters.items():
                if not params:
                    continue
                    
                lines.append(f"### {category}")
                param_strs = []
                for p in params[:10]:  # 카테고리당 최대 10개
                    name = p.get('semantic_name') or p.get('param_key')
                    unit = p.get('unit')
                    if unit:
                        param_strs.append(f"{name} ({unit})")
                    else:
                        param_strs.append(name)
                
                lines.append(f"- {', '.join(param_strs)}")
                
                if len(params) > 10:
                    lines.append(f"  - ... 외 {len(params) - 10}개")
            lines.append("")
        
        # 4. Relationships
        if context.relationships:
            lines.append("## 데이터 관계")
            lines.append("")
            
            for rel in context.relationships:
                lines.append(
                    f"- {rel['from_table']}.{rel['from_column']} → "
                    f"{rel['to_table']}.{rel['to_column']} ({rel.get('cardinality', 'N/A')})"
                )
            lines.append("")
        
        return "\n".join(lines)
    
    # =========================================================================
    # Utility Methods
    # =========================================================================
    
    def get_group_parameters(self, group_id: str) -> List[Dict[str, Any]]:
        """
        특정 그룹의 파라미터 목록 조회
        
        Args:
            group_id: 파일 그룹 ID
        
        Returns:
            파라미터 목록
        """
        try:
            return self.group_repo.get_group_parameters(group_id)
        except Exception as e:
            print(f"[SchemaContextBuilder] Error getting group parameters: {e}")
            try:
                self.db.rollback()
            except:
                pass
            return []
    
    def get_stats(self) -> Dict[str, int]:
        """
        컨텍스트 통계 조회
        
        Returns:
            {
                "cohort_source_count": n,
                "signal_group_count": n,
                "parameter_count": n,
                "relationship_count": n
            }
        """
        try:
            cohort_sources = self.get_cohort_sources()
            signal_groups = self.get_signal_groups()
            relationships = self.get_relationships()
            param_count = self.param_repo.get_parameter_count()
            
            return {
                "cohort_source_count": len(cohort_sources),
                "signal_group_count": len(signal_groups),
                "parameter_count": param_count,
                "relationship_count": len(relationships)
            }
        except Exception as e:
            print(f"[SchemaContextBuilder] Error getting stats: {e}")
            try:
                self.db.rollback()
            except:
                pass
            return {}

