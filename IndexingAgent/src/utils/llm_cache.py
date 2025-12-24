# src/utils/llm_cache.py
"""
LLM Response Cache using diskcache

Provides persistent caching for LLM responses to reduce API costs.
"""

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Optional

from diskcache import Cache

# Default cache directory
CACHE_DIR = Path("data/cache/llm_disk")


class LLMCache:
    """
    LLM 응답 캐시 (diskcache 기반)
    
    Features:
    - Persistent disk-based caching
    - Automatic key generation from prompt/context
    - TTL support
    - Cache statistics
    """
    
    def __init__(self, cache_dir: Path = None, size_limit: int = 1024 * 1024 * 500):
        """
        Initialize cache
        
        Args:
            cache_dir: Cache directory path
            size_limit: Max cache size in bytes (default 500MB)
        """
        self.cache_dir = cache_dir or CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        self.cache = Cache(
            str(self.cache_dir),
            size_limit=size_limit,
            eviction_policy='least-recently-used'
        )
        
        # Statistics
        self._hits = 0
        self._misses = 0
    
    def _generate_key(self, operation: str, context: Any) -> str:
        """Generate a unique cache key from operation and context"""
        context_str = json.dumps(context, sort_keys=True, default=str)
        combined = f"{operation}:{context_str}"
        return hashlib.md5(combined.encode()).hexdigest()
    
    def get(self, operation: str, context: Any) -> Optional[Dict[str, Any]]:
        """
        Get cached response
        
        Args:
            operation: Operation type (e.g., "metadata_detection")
            context: Context dict used for key generation
        
        Returns:
            Cached response or None if not found
        """
        key = self._generate_key(operation, context)
        result = self.cache.get(key)
        
        if result is not None:
            self._hits += 1
            return result
        
        self._misses += 1
        return None
    
    def set(
        self, 
        operation: str, 
        context: Any, 
        value: Dict[str, Any],
        expire: int = None
    ) -> bool:
        """
        Store response in cache
        
        Args:
            operation: Operation type
            context: Context dict
            value: Response to cache
            expire: TTL in seconds (optional)
        
        Returns:
            True if successfully stored
        """
        key = self._generate_key(operation, context)
        return self.cache.set(key, value, expire=expire)
    
    def invalidate(self, operation: str, context: Any) -> bool:
        """
        Invalidate specific cache entry
        
        Args:
            operation: Operation type
            context: Context dict
        
        Returns:
            True if entry was found and removed
        """
        key = self._generate_key(operation, context)
        return self.cache.delete(key)
    
    def invalidate_for_file(self, filename: str) -> int:
        """
        Invalidate all cache entries related to a specific file
        
        Note: This performs a full scan, which may be slow for large caches.
        Consider using tags for better performance.
        
        Args:
            filename: Filename to invalidate
        
        Returns:
            Number of entries invalidated
        """
        count = 0
        keys_to_delete = []
        
        for key in self.cache.iterkeys():
            # Try to get the value and check if it contains the filename
            try:
                value = self.cache.peek(key)
                if value and isinstance(value, dict):
                    # Check if filename appears in the cached data
                    value_str = json.dumps(value, default=str)
                    if filename in value_str:
                        keys_to_delete.append(key)
            except Exception:
                continue
        
        for key in keys_to_delete:
            if self.cache.delete(key):
                count += 1
        
        return count
    
    def invalidate_for_file_extension(self, extension: str) -> int:
        """
        Invalidate all cache entries for files with specific extension
        
        Args:
            extension: File extension (e.g., ".vital")
        
        Returns:
            Number of entries invalidated
        """
        if not extension.startswith('.'):
            extension = f'.{extension}'
        
        count = 0
        keys_to_delete = []
        
        for key in self.cache.iterkeys():
            try:
                value = self.cache.peek(key)
                if value and isinstance(value, dict):
                    value_str = json.dumps(value, default=str)
                    if extension in value_str:
                        keys_to_delete.append(key)
            except Exception:
                continue
        
        for key in keys_to_delete:
            if self.cache.delete(key):
                count += 1
        
        return count
    
    def clear(self) -> int:
        """
        Clear all cache entries
        
        Returns:
            Number of entries cleared
        """
        count = len(self.cache)
        self.cache.clear()
        self._hits = 0
        self._misses = 0
        return count
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        total = self._hits + self._misses
        hit_rate = self._hits / total if total > 0 else 0.0
        
        return {
            "hits": self._hits,
            "misses": self._misses,
            "total_requests": total,
            "hit_rate": f"{hit_rate:.1%}",
            "cache_size": len(self.cache),
            "cache_volume": self.cache.volume(),
        }
    
    def print_stats(self):
        """Print cache statistics to console"""
        stats = self.get_stats()
        print("\n" + "="*50)
        print("📊 LLM Cache Statistics")
        print("="*50)
        print(f"   Hits: {stats['hits']}")
        print(f"   Misses: {stats['misses']}")
        print(f"   Total Requests: {stats['total_requests']}")
        print(f"   Hit Rate: {stats['hit_rate']}")
        print(f"   Cache Size: {stats['cache_size']} entries")
        print(f"   Cache Volume: {stats['cache_volume']} bytes")
        print("="*50)
    
    def __len__(self) -> int:
        """Return number of cached entries"""
        return len(self.cache)
    
    def close(self):
        """Close the cache"""
        self.cache.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# Global cache instance
_global_cache: Optional[LLMCache] = None


def get_llm_cache() -> LLMCache:
    """Get global LLM cache instance (singleton)"""
    global _global_cache
    if _global_cache is None:
        _global_cache = LLMCache()
    return _global_cache


def reset_llm_cache():
    """Reset the global cache instance"""
    global _global_cache
    if _global_cache is not None:
        _global_cache.close()
        _global_cache = None
