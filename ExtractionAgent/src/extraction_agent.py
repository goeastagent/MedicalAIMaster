# src/extraction_agent.py
"""
ExtractionAgent - 메인 에이전트 클래스

사용자의 자연어 질의를 SQL로 변환하고 데이터를 추출합니다.
"""

from typing import Dict, Any, Optional
from datetime import datetime

from .nl_to_sql import NLToSQLConverter
from .query_executor import QueryExecutor
from .result_exporter import ResultExporter


class ExtractionAgent:
    """데이터 추출 에이전트"""
    
    def __init__(self, output_dir: str = "output"):
        """
        Args:
            output_dir: 결과 파일 저장 디렉토리
        """
        self.nl_to_sql = NLToSQLConverter()
        self.query_executor = QueryExecutor()
        self.result_exporter = ResultExporter(output_dir=output_dir)
    
    def extract(
        self,
        query: str,
        max_tables: int = 20,
        result_limit: int = 10000,
        auto_save: bool = False,
        save_format: str = "csv"
    ) -> Dict[str, Any]:
        """
        자연어 질의를 처리하여 데이터 추출
        
        Args:
            query: 자연어 질의
            max_tables: 프롬프트에 포함할 최대 테이블 수
            result_limit: 결과 행 수 제한
            auto_save: 자동 저장 여부
            save_format: 저장 형식 ("csv", "json", "excel", "parquet")
        
        Returns:
            {
                "success": True/False,
                "sql": "생성된 SQL",
                "explanation": "SQL 설명",
                "data": DataFrame or None,
                "row_count": int,
                "columns": List[str],
                "saved_files": Dict[str, str] or None,
                "error": None or error message
            }
        """
        print("\n" + "=" * 80)
        print("🔍 ExtractionAgent 시작")
        print("=" * 80)
        print(f"\n📝 사용자 질의: {query}")
        print()
        
        # 1. 자연어 → SQL 변환
        print("🤖 [Step 1] 자연어 → SQL 변환 중...")
        conversion_result = self.nl_to_sql.convert(query, max_tables=max_tables)
        
        if conversion_result.get("error"):
            print(f"❌ 변환 실패: {conversion_result['error']}")
            return {
                "success": False,
                "sql": None,
                "explanation": None,
                "data": None,
                "row_count": 0,
                "columns": [],
                "saved_files": None,
                "error": conversion_result["error"]
            }
        
        sql = conversion_result["sql"]
        explanation = conversion_result["explanation"]
        confidence = conversion_result["confidence"]
        tables_used = conversion_result["tables_used"]
        
        print(f"✅ SQL 생성 완료 (confidence: {confidence:.2%})")
        print(f"\n📊 생성된 SQL:")
        print("-" * 80)
        print(sql)
        print("-" * 80)
        print(f"\n💡 설명: {explanation}")
        if tables_used:
            print(f"📋 사용된 테이블: {', '.join(tables_used)}")
        
        # 2. SQL 검증
        print(f"\n🔍 [Step 2] SQL 검증 중...")
        validation = self.nl_to_sql.validate_sql(sql)
        
        if not validation["valid"]:
            print(f"❌ SQL 검증 실패: {validation['error']}")
            return {
                "success": False,
                "sql": sql,
                "explanation": explanation,
                "data": None,
                "row_count": 0,
                "columns": [],
                "saved_files": None,
                "error": validation["error"]
            }
        
        print("✅ SQL 검증 통과")
        
        # 3. SQL 실행
        print(f"\n⚡ [Step 3] SQL 실행 중...")
        execution_result = self.query_executor.execute(sql, limit=result_limit)
        
        if not execution_result["success"]:
            print(f"❌ 실행 실패: {execution_result['error']}")
            return {
                "success": False,
                "sql": sql,
                "explanation": explanation,
                "data": None,
                "row_count": 0,
                "columns": [],
                "saved_files": None,
                "error": execution_result["error"]
            }
        
        data = execution_result["data"]
        row_count = execution_result["row_count"]
        columns = execution_result["columns"]
        
        print(f"✅ 실행 완료: {row_count:,}행 반환")
        print(f"📋 컬럼: {', '.join(columns[:5])}{'...' if len(columns) > 5 else ''}")
        
        # 4. 결과 저장 (옵션)
        saved_files = None
        if auto_save and data is not None and len(data) > 0:
            print(f"\n💾 [Step 4] 결과 저장 중...")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            base_filename = f"extracted_{timestamp}"
            
            if save_format == "csv":
                filepath = self.result_exporter.save_csv(data, base_filename)
                saved_files = {"csv": filepath}
            elif save_format == "json":
                filepath = self.result_exporter.save_json(data, base_filename)
                saved_files = {"json": filepath}
            elif save_format == "excel":
                filepath = self.result_exporter.save_excel(data, base_filename)
                saved_files = {"excel": filepath}
            elif save_format == "parquet":
                filepath = self.result_exporter.save_parquet(data, base_filename)
                saved_files = {"parquet": filepath}
            else:
                # 여러 형식으로 저장
                saved_files = self.result_exporter.save_multiple_formats(
                    data, base_filename, formats=["csv", "json"]
                )
            
            print(f"✅ 저장 완료: {list(saved_files.values())}")
        
        print("\n" + "=" * 80)
        print("✅ ExtractionAgent 완료")
        print("=" * 80)
        
        return {
            "success": True,
            "sql": sql,
            "explanation": explanation,
            "confidence": confidence,
            "tables_used": tables_used,
            "data": data,
            "row_count": row_count,
            "columns": columns,
            "saved_files": saved_files,
            "error": None
        }
    
    def extract_and_save(
        self,
        query: str,
        filename: str,
        format: str = "csv",
        max_tables: int = 20,
        result_limit: int = 10000
    ) -> Dict[str, Any]:
        """
        자연어 질의를 처리하고 결과를 파일로 저장
        
        Args:
            query: 자연어 질의
            filename: 저장할 파일명 (확장자 제외 가능)
            format: 저장 형식 ("csv", "json", "excel", "parquet")
            max_tables: 프롬프트에 포함할 최대 테이블 수
            result_limit: 결과 행 수 제한
        
        Returns:
            extract()와 동일한 형식
        """
        result = self.extract(
            query=query,
            max_tables=max_tables,
            result_limit=result_limit,
            auto_save=False  # 수동으로 저장
        )
        
        if result["success"] and result["data"] is not None:
            data = result["data"]
            
            if format == "csv":
                filepath = self.result_exporter.save_csv(data, filename)
            elif format == "json":
                filepath = self.result_exporter.save_json(data, filename)
            elif format == "excel":
                filepath = self.result_exporter.save_excel(data, filename)
            elif format == "parquet":
                filepath = self.result_exporter.save_parquet(data, filename)
            else:
                filepath = self.result_exporter.save_csv(data, filename)
            
            result["saved_files"] = {format: filepath}
        
        return result
    
    def preview_sql(self, query: str, max_tables: int = 20) -> Dict[str, Any]:
        """
        SQL만 생성하고 실행하지 않음 (미리보기용)
        
        Args:
            query: 자연어 질의
            max_tables: 프롬프트에 포함할 최대 테이블 수
        
        Returns:
            {
                "sql": "생성된 SQL",
                "explanation": "SQL 설명",
                "confidence": 0.0-1.0,
                "tables_used": List[str],
                "error": None or error message
            }
        """
        conversion_result = self.nl_to_sql.convert(query, max_tables=max_tables)
        
        return {
            "sql": conversion_result.get("sql"),
            "explanation": conversion_result.get("explanation"),
            "confidence": conversion_result.get("confidence"),
            "tables_used": conversion_result.get("tables_used", []),
            "error": conversion_result.get("error")
        }

