# src/result_exporter.py
"""
결과 추출기

쿼리 결과를 다양한 형식으로 저장합니다.
"""

from typing import Dict, Any, Optional
import pandas as pd
import json
import os
from pathlib import Path


class ResultExporter:
    """결과 추출기"""
    
    def __init__(self, output_dir: str = "output"):
        """
        Args:
            output_dir: 출력 디렉토리 경로
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def save_csv(self, data: pd.DataFrame, filename: str) -> str:
        """
        CSV 파일로 저장
        
        Args:
            data: 저장할 DataFrame
            filename: 파일명 (확장자 포함 또는 제외 가능)
        
        Returns:
            저장된 파일 경로
        """
        if not filename.endswith(".csv"):
            filename += ".csv"
        
        filepath = self.output_dir / filename
        data.to_csv(filepath, index=False, encoding='utf-8-sig')
        
        return str(filepath)
    
    def save_json(self, data: pd.DataFrame, filename: str, orient: str = "records") -> str:
        """
        JSON 파일로 저장
        
        Args:
            data: 저장할 DataFrame
            filename: 파일명
            orient: JSON 형식 ("records", "index", "values", "table", "split")
        
        Returns:
            저장된 파일 경로
        """
        if not filename.endswith(".json"):
            filename += ".json"
        
        filepath = self.output_dir / filename
        
        data_dict = data.to_dict(orient=orient)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data_dict, f, indent=2, ensure_ascii=False, default=str)
        
        return str(filepath)
    
    def save_excel(self, data: pd.DataFrame, filename: str, sheet_name: str = "Sheet1") -> str:
        """
        Excel 파일로 저장
        
        Args:
            data: 저장할 DataFrame
            filename: 파일명
            sheet_name: 시트명
        
        Returns:
            저장된 파일 경로
        """
        if not filename.endswith(".xlsx"):
            filename += ".xlsx"
        
        filepath = self.output_dir / filename
        
        with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
            data.to_excel(writer, sheet_name=sheet_name, index=False)
        
        return str(filepath)
    
    def save_parquet(self, data: pd.DataFrame, filename: str) -> str:
        """
        Parquet 파일로 저장 (대용량 데이터에 적합)
        
        Args:
            data: 저장할 DataFrame
            filename: 파일명
        
        Returns:
            저장된 파일 경로
        """
        if not filename.endswith(".parquet"):
            filename += ".parquet"
        
        filepath = self.output_dir / filename
        data.to_parquet(filepath, index=False)
        
        return str(filepath)
    
    def save_multiple_formats(
        self,
        data: pd.DataFrame,
        base_filename: str,
        formats: list = ["csv", "json"]
    ) -> Dict[str, str]:
        """
        여러 형식으로 동시에 저장
        
        Args:
            data: 저장할 DataFrame
            base_filename: 기본 파일명 (확장자 제외)
            formats: 저장할 형식 리스트 ["csv", "json", "excel", "parquet"]
        
        Returns:
            {format: filepath} 딕셔너리
        """
        saved_files = {}
        
        if "csv" in formats:
            saved_files["csv"] = self.save_csv(data, base_filename)
        
        if "json" in formats:
            saved_files["json"] = self.save_json(data, base_filename)
        
        if "excel" in formats:
            saved_files["excel"] = self.save_excel(data, base_filename)
        
        if "parquet" in formats:
            saved_files["parquet"] = self.save_parquet(data, base_filename)
        
        return saved_files

