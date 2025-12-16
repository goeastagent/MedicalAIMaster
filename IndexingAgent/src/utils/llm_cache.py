# src/utils/llm_cache.py
"""
LLM 응답 캐싱 시스템 (비용 절감)

동일한 프롬프트 + 컨텍스트 조합은 캐시에서 재사용
"""

import hashlib
import json
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime


class LLMCache:
    """LLM 응답 캐싱 (비용 절감 및 속도 향상)"""
    
    def __init__(self, cache_dir: str = "data/cache/llm"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.hit_count = 0
        self.miss_count = 0
    
    def _get_key(self, prompt: str, context: Dict[str, Any]) -> str:
        """
        프롬프트 + 컨텍스트로 고유 키 생성
        
        Args:
            prompt: LLM 프롬프트 문자열
            context: 컨텍스트 딕셔너리 (파일명, 컬럼 등)
        
        Returns:
            MD5 해시 키
        """
        # 컨텍스트를 정렬된 JSON으로 변환 (순서 독립성)
        context_str = json.dumps(context, sort_keys=True)
        content = f"{prompt}::{context_str}"
        return hashlib.md5(content.encode('utf-8')).hexdigest()
    
    def get(self, prompt: str, context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        캐시 조회
        
        Returns:
            캐시된 결과 또는 None
        """
        key = self._get_key(prompt, context)
        cache_file = self.cache_dir / f"{key}.json"
        
        if cache_file.exists():
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    cached_data = json.load(f)
                    self.hit_count += 1
                    # 캐시된 결과에서 실제 result 추출
                    result = cached_data.get("result") if isinstance(cached_data, dict) and "result" in cached_data else cached_data
                    print(f"✅ [Cache Hit] 캐시 사용 (총 {self.hit_count}회 절약)")
                    return result
            except Exception as e:
                print(f"⚠️  [Cache Error] 캐시 읽기 실패: {e}")
                self.miss_count += 1
                return None
        
        self.miss_count += 1
        return None
    
    def set(self, prompt: str, context: Dict[str, Any], result: Dict[str, Any]):
        """
        캐시 저장
        
        Args:
            prompt: LLM 프롬프트
            context: 컨텍스트
            result: LLM 응답
        """
        key = self._get_key(prompt, context)
        cache_file = self.cache_dir / f"{key}.json"
        
        # 메타데이터 추가
        cached_data = {
            "result": result,
            "prompt_hash": key,
            "cached_at": datetime.now().isoformat(),
            "context_summary": {
                "filename": context.get("filename", "unknown"),
                "num_columns": context.get("num_columns", 0)
            }
        }
        
        try:
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(cached_data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"⚠️  [Cache Error] 캐시 저장 실패: {e}")
    
    def clear(self):
        """캐시 전체 삭제"""
        import shutil
        if self.cache_dir.exists():
            shutil.rmtree(self.cache_dir)
            self.cache_dir.mkdir(parents=True)
        
        self.hit_count = 0
        self.miss_count = 0
        print("🗑️  캐시 클리어 완료")
    
    def stats(self) -> Dict[str, Any]:
        """
        캐시 통계
        
        Returns:
            hits, misses, hit_rate, estimated_savings
        """
        total = self.hit_count + self.miss_count
        hit_rate = self.hit_count / total if total > 0 else 0
        
        return {
            "hits": self.hit_count,
            "misses": self.miss_count,
            "total_calls": total,
            "hit_rate": round(hit_rate, 2),
            "estimated_savings_usd": round(self.hit_count * 0.03, 2)  # $0.03/call 가정
        }
    
    def print_stats(self):
        """캐시 통계 출력"""
        stats = self.stats()
        print("\n" + "="*60)
        print("📊 LLM Cache Statistics")
        print("="*60)
        print(f"  Cache Hits:     {stats['hits']}")
        print(f"  Cache Misses:   {stats['misses']}")
        print(f"  Total Calls:    {stats['total_calls']}")
        print(f"  Hit Rate:       {stats['hit_rate']:.1%}")
        print(f"  Estimated Savings: ${stats['estimated_savings_usd']:.2f}")
        print("="*60)


# 전역 싱글톤 인스턴스
_global_cache = None

def get_llm_cache() -> LLMCache:
    """전역 LLM 캐시 인스턴스 반환"""
    global _global_cache
    if _global_cache is None:
        _global_cache = LLMCache()
    return _global_cache

