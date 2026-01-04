# src/database/schemas/file_group.py
"""
File Group DDL

파일 그룹 테이블 정의:
- file_group: 대량의 유사 파일들을 그룹으로 관리 (예: 6,388개 .vital 파일)

Workflow:
1. [250] file_grouping_candidate: 후보 그룹 생성 (status='candidate')
2. [350] file_grouping_validation: LLM 검증 후 확정 (status='confirmed') 또는 거부 (status='rejected')
3. 이후 노드들: confirmed 그룹만 활용

그룹 레벨에서 관리되는 정보:
- 그룹핑 기준 (확장자, 패턴 등)
- 검증 상태 (candidate → confirmed/rejected)
- Entity 정보 (row_represents, entity_identifier)
- 관련 메타데이터 파일과의 관계

개별 파일은 file_catalog.group_id로 연결됩니다 (confirmed 그룹만).
"""

# ═══════════════════════════════════════════════════════════════════════════════
# file_group 테이블
# ═══════════════════════════════════════════════════════════════════════════════

CREATE_FILE_GROUP_SQL = """
CREATE TABLE IF NOT EXISTS file_group (
    -- ═══════════════════════════════════════════════════════════════
    -- 식별자
    -- ═══════════════════════════════════════════════════════════════
    group_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    group_name VARCHAR(255) NOT NULL,
    
    -- ═══════════════════════════════════════════════════════════════
    -- 그룹핑 기준 (JSONB로 유연하게 관리)
    -- ═══════════════════════════════════════════════════════════════
    grouping_criteria JSONB NOT NULL DEFAULT '{}'::jsonb,
    /*
    예시:
    {
        "extensions": [".vital"],
        "pattern": "{caseid}.vital",
        "pattern_key": "caseid",
        "pattern_regex": "(\\d+)\\.vital"
    }
    
    또는 복수 확장자:
    {
        "extensions": [".hea", ".dat"],
        "pattern": "{record_id}.{ext}",
        "pattern_key": "record_id",
        "file_pairing": "by_basename"
    }
    */
    
    -- ═══════════════════════════════════════════════════════════════
    -- 통계 (캐시, 필요시 재계산)
    -- ═══════════════════════════════════════════════════════════════
    file_count INT NOT NULL DEFAULT 0,
    
    -- ═══════════════════════════════════════════════════════════════
    -- 그룹 상태 (Workflow 관리)
    -- ═══════════════════════════════════════════════════════════════
    status VARCHAR(20) NOT NULL DEFAULT 'candidate',
    -- 'candidate': 후보 (Rule-based로 생성, LLM 검증 전)
    -- 'confirmed': 확정 (LLM 검증 통과, 파일에 group_id 배정됨)
    -- 'rejected': 거부 (LLM 검증 실패, 그룹화하지 않음)
    -- 'needs_human_review': 사람 검토 필요 (LLM 불확실 또는 패턴 검증 실패)
    
    validation_reasoning TEXT,
    -- LLM 검증 결과 설명 (왜 확정/거부되었는지)
    
    validated_at TIMESTAMP,
    -- LLM 검증 완료 시간
    
    -- ═══════════════════════════════════════════════════════════════
    -- Human Review 정보 (status='needs_human_review'일 때)
    -- ═══════════════════════════════════════════════════════════════
    review_type VARCHAR(50),
    -- 'pattern_validation_failed': 패턴 검증 실패
    -- 'low_confidence': LLM 신뢰도 낮음
    -- 'ambiguous_grouping': 그룹핑 기준 모호
    -- 'complex_pattern': 복잡한 패턴으로 자동 처리 불가
    
    review_context JSONB,
    -- 리뷰에 필요한 추가 정보 (실패 원인, 샘플 등)
    /*
    예시:
    {
        "failed_samples": ["file1.vital", "file2.vital"],
        "expected_values": {"caseid": "123"},
        "actual_values": {"caseid": "abc"},
        "llm_suggestion": "..."
    }
    */
    
    reviewed_by VARCHAR(100),
    -- 리뷰 완료한 사용자
    
    reviewed_at TIMESTAMP,
    -- 리뷰 완료 시간
    
    -- ═══════════════════════════════════════════════════════════════
    -- Entity 정보 (LLM 분석 결과, [800] entity_identification)
    -- ═══════════════════════════════════════════════════════════════
    row_represents VARCHAR(255),
    -- 예: 'surgical_case_vital_signs', 'waveform_record'
    
    entity_identifier_source VARCHAR(50),
    -- 예: 'filename', 'content', 'directory'
    
    entity_identifier_key VARCHAR(100),
    -- 예: 'caseid', 'record_id', 'subject_id'
    
    -- ═══════════════════════════════════════════════════════════════
    -- 분석 결과
    -- ═══════════════════════════════════════════════════════════════
    confidence REAL,
    -- LLM 분석 신뢰도 (0.0 ~ 1.0)
    
    reasoning TEXT,
    -- LLM 판단 근거
    
    llm_analyzed_at TIMESTAMP,
    -- LLM 분석 완료 시간
    
    -- ═══════════════════════════════════════════════════════════════
    -- 관계 정보 (메타데이터 파일과의 관계)
    -- ═══════════════════════════════════════════════════════════════
    related_files JSONB,
    /*
    예시:
    [
        {
            "file_id": "uuid-of-clinical_data.csv",
            "relationship_key": "caseid",
            "relationship_type": "1:1"
        }
    ]
    */
    
    -- ═══════════════════════════════════════════════════════════════
    -- 샘플 정보 (분석에 사용된 샘플 파일들)
    -- ═══════════════════════════════════════════════════════════════
    sample_file_ids UUID[],
    -- 대표 분석에 사용된 샘플 파일 IDs
    
    verification_file_ids UUID[],
    -- 검증에 사용된 샘플 파일 IDs
    
    -- ═══════════════════════════════════════════════════════════════
    -- 메타데이터
    -- ═══════════════════════════════════════════════════════════════
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_file_group_name ON file_group (group_name);
CREATE INDEX IF NOT EXISTS idx_file_group_status ON file_group (status);
CREATE INDEX IF NOT EXISTS idx_file_group_criteria ON file_group USING GIN (grouping_criteria);
CREATE INDEX IF NOT EXISTS idx_file_group_extensions ON file_group 
    USING GIN ((grouping_criteria->'extensions'));
CREATE INDEX IF NOT EXISTS idx_file_group_entity_key ON file_group (entity_identifier_key);
CREATE INDEX IF NOT EXISTS idx_file_group_confidence ON file_group (confidence);

-- 자주 사용되는 쿼리를 위한 복합 인덱스
CREATE INDEX IF NOT EXISTS idx_file_group_status_validated ON file_group (status, validated_at);
CREATE INDEX IF NOT EXISTS idx_file_group_review_type ON file_group (review_type) WHERE status = 'needs_human_review';
"""

# ═══════════════════════════════════════════════════════════════════════════════
# file_catalog.group_id에 FK 제약조건 추가
# (컬럼은 catalog.py에서 이미 생성, file_group 테이블 생성 후 FK만 추가)
# ═══════════════════════════════════════════════════════════════════════════════

ADD_FILE_CATALOG_GROUP_FK_SQL = """
-- file_catalog.group_id에 FK 제약조건 추가
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints 
        WHERE constraint_name = 'file_catalog_group_id_fkey'
    ) THEN
        ALTER TABLE file_catalog 
        ADD CONSTRAINT file_catalog_group_id_fkey 
        FOREIGN KEY (group_id) REFERENCES file_group(group_id) ON DELETE SET NULL;
    END IF;
END $$;
"""

# ═══════════════════════════════════════════════════════════════════════════════
# parameter.group_id에 FK 제약조건 추가
# (컬럼은 parameter.py에서 이미 생성, file_group 테이블 생성 후 FK만 추가)
# ═══════════════════════════════════════════════════════════════════════════════

ADD_PARAMETER_GROUP_FK_SQL = """
-- parameter.group_id에 FK 제약조건 추가
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints 
        WHERE constraint_name = 'parameter_group_id_fkey'
    ) THEN
        ALTER TABLE parameter 
        ADD CONSTRAINT parameter_group_id_fkey 
        FOREIGN KEY (group_id) REFERENCES file_group(group_id) ON DELETE SET NULL;
    END IF;
END $$;
"""

# ═══════════════════════════════════════════════════════════════════════════════
# updated_at 트리거
# ═══════════════════════════════════════════════════════════════════════════════

CREATE_FILE_GROUP_UPDATE_TRIGGER_SQL = """
-- file_group 테이블 updated_at 트리거
DROP TRIGGER IF EXISTS update_file_group_updated_at ON file_group;
CREATE TRIGGER update_file_group_updated_at
    BEFORE UPDATE ON file_group
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
"""

