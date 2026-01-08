# AnalysisAgent/src/results/store.py
"""
Result Store

Storage and retrieval of analysis results.
Supports caching, history tracking, and querying.
"""

import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from collections import OrderedDict

from ..models.result import AnalysisResult, ResultSummary

logger = logging.getLogger(__name__)


class ResultStore:
    """
    In-memory store for analysis results.
    
    Features:
    - Cache by query_hash for quick lookups
    - History tracking with max size
    - TTL-based cache expiration
    - Query by various criteria
    
    Usage:
        store = ResultStore(max_size=100, cache_ttl_minutes=60)
        
        # Store a result
        store.save(result)
        
        # Check cache
        cached = store.get_cached(query, input_summary)
        
        # Get recent results
        recent = store.get_recent(limit=10)
    """
    
    def __init__(
        self,
        max_size: int = 100,
        cache_ttl_minutes: int = 60,
        enable_cache: bool = True,
    ):
        """
        Args:
            max_size: Maximum number of results to store
            cache_ttl_minutes: Cache TTL in minutes (0 = no expiration)
            enable_cache: Whether to enable cache lookups
        """
        self.max_size = max_size
        self.cache_ttl = timedelta(minutes=cache_ttl_minutes) if cache_ttl_minutes > 0 else None
        self.enable_cache = enable_cache
        
        # Storage: OrderedDict for LRU-like behavior
        self._results: OrderedDict[str, AnalysisResult] = OrderedDict()
        
        # Cache index: query_hash -> result_id
        self._cache_index: Dict[str, str] = {}
        
        logger.debug(f"ResultStore initialized (max_size={max_size}, ttl={cache_ttl_minutes}m)")
    
    def save(self, result: AnalysisResult) -> str:
        """
        Save a result to the store.
        
        Args:
            result: Result to save
        
        Returns:
            Result ID
        """
        # Evict if at capacity
        while len(self._results) >= self.max_size:
            self._evict_oldest()
        
        # Store result
        self._results[result.id] = result
        
        # Update cache index (only for successful results)
        if result.status == "success" and result.query_hash:
            self._cache_index[result.query_hash] = result.id
        
        logger.debug(f"Saved result {result.id} (hash={result.query_hash[:8]}...)")
        return result.id
    
    def get(self, result_id: str) -> Optional[AnalysisResult]:
        """Get result by ID"""
        return self._results.get(result_id)
    
    def get_cached(
        self,
        query: str,
        input_summary: Optional[Dict[str, Any]] = None,
    ) -> Optional[AnalysisResult]:
        """
        Get cached result for a query.
        
        Args:
            query: Query string
            input_summary: Input context summary for cache key
        
        Returns:
            Cached result if found and valid, None otherwise
        """
        if not self.enable_cache:
            return None
        
        # Compute hash
        temp_result = AnalysisResult(query=query, input_summary=input_summary or {})
        query_hash = temp_result.query_hash
        
        # Lookup
        result_id = self._cache_index.get(query_hash)
        if not result_id:
            logger.debug(f"Cache miss for hash {query_hash[:8]}...")
            return None
        
        result = self._results.get(result_id)
        if not result:
            # Stale index entry
            del self._cache_index[query_hash]
            return None
        
        # Check TTL
        if self.cache_ttl and self._is_expired(result):
            logger.debug(f"Cache expired for {result_id}")
            return None
        
        logger.info(f"Cache hit for hash {query_hash[:8]}... (result={result_id})")
        return result
    
    def _is_expired(self, result: AnalysisResult) -> bool:
        """Check if result is expired based on TTL"""
        if not self.cache_ttl:
            return False
        return datetime.now() - result.created_at > self.cache_ttl
    
    def _evict_oldest(self) -> None:
        """Evict oldest result (LRU)"""
        if not self._results:
            return
        
        # Get oldest (first item in OrderedDict)
        oldest_id = next(iter(self._results))
        oldest = self._results[oldest_id]
        
        # Remove from cache index
        if oldest.query_hash in self._cache_index:
            if self._cache_index[oldest.query_hash] == oldest_id:
                del self._cache_index[oldest.query_hash]
        
        # Remove from storage
        del self._results[oldest_id]
        logger.debug(f"Evicted oldest result {oldest_id}")
    
    def get_recent(self, limit: int = 10) -> List[AnalysisResult]:
        """
        Get most recent results.
        
        Args:
            limit: Maximum number of results to return
        
        Returns:
            List of results, most recent first
        """
        results = list(self._results.values())
        results.reverse()  # Most recent first
        return results[:limit]
    
    def get_recent_summaries(self, limit: int = 10) -> List[ResultSummary]:
        """Get summaries of recent results"""
        results = self.get_recent(limit)
        return [ResultSummary.from_result(r) for r in results]
    
    def get_by_status(self, status: str) -> List[AnalysisResult]:
        """Get results by status"""
        return [r for r in self._results.values() if r.status == status]
    
    def get_by_query_pattern(self, pattern: str) -> List[AnalysisResult]:
        """
        Get results matching a query pattern (case-insensitive substring).
        
        Args:
            pattern: Substring to match in query
        
        Returns:
            Matching results
        """
        pattern_lower = pattern.lower()
        return [
            r for r in self._results.values()
            if pattern_lower in r.query.lower()
        ]
    
    def get_history_for_context(self, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Get recent successful results formatted for AnalysisContext.
        
        Returns format suitable for `previous_results` in AnalysisContext.
        """
        results = self.get_recent(limit * 2)  # Get more to filter
        
        history = []
        for r in results:
            if r.status == "success":
                history.append({
                    "query": r.query,
                    "result_type": r.final_result_type,
                    "result_preview": str(r.final_result)[:100],
                    "created_at": r.created_at.isoformat(),
                })
                if len(history) >= limit:
                    break
        
        return history
    
    def clear(self) -> int:
        """
        Clear all stored results.
        
        Returns:
            Number of results cleared
        """
        count = len(self._results)
        self._results.clear()
        self._cache_index.clear()
        logger.info(f"Cleared {count} results from store")
        return count
    
    def clear_cache(self) -> int:
        """
        Clear only the cache index (results remain in history).
        
        Returns:
            Number of cache entries cleared
        """
        count = len(self._cache_index)
        self._cache_index.clear()
        logger.info(f"Cleared {count} cache entries")
        return count
    
    def clear_expired(self) -> int:
        """
        Remove expired results.
        
        Returns:
            Number of results removed
        """
        if not self.cache_ttl:
            return 0
        
        expired_ids = [
            rid for rid, result in self._results.items()
            if self._is_expired(result)
        ]
        
        for rid in expired_ids:
            result = self._results[rid]
            if result.query_hash in self._cache_index:
                if self._cache_index[result.query_hash] == rid:
                    del self._cache_index[result.query_hash]
            del self._results[rid]
        
        if expired_ids:
            logger.info(f"Cleared {len(expired_ids)} expired results")
        return len(expired_ids)
    
    def stats(self) -> Dict[str, Any]:
        """Get store statistics"""
        status_counts = {}
        for r in self._results.values():
            status_counts[r.status] = status_counts.get(r.status, 0) + 1
        
        return {
            "total_results": len(self._results),
            "cache_entries": len(self._cache_index),
            "max_size": self.max_size,
            "cache_enabled": self.enable_cache,
            "cache_ttl_minutes": self.cache_ttl.total_seconds() / 60 if self.cache_ttl else None,
            "status_counts": status_counts,
        }
    
    def __len__(self) -> int:
        return len(self._results)
    
    def __contains__(self, result_id: str) -> bool:
        return result_id in self._results


# Global store instance
_global_store: Optional[ResultStore] = None


def get_result_store(
    max_size: int = 100,
    cache_ttl_minutes: int = 60,
    enable_cache: bool = True,
) -> ResultStore:
    """
    Get the global result store.
    
    Creates one if it doesn't exist.
    """
    global _global_store
    if _global_store is None:
        _global_store = ResultStore(
            max_size=max_size,
            cache_ttl_minutes=cache_ttl_minutes,
            enable_cache=enable_cache,
        )
    return _global_store


def reset_global_store() -> None:
    """Reset the global store (for testing)"""
    global _global_store
    _global_store = None
