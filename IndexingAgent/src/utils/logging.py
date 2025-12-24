# src/utils/logging.py
"""
Logging configuration using loguru

Provides structured, colored logging with file rotation.
"""

import sys
from pathlib import Path
from loguru import logger

# Default log directory
LOG_DIR = Path("data/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)


def setup_logging(
    level: str = "INFO",
    log_file: str = "indexing.log",
    rotation: str = "10 MB",
    retention: str = "7 days",
    console: bool = True
):
    """
    Configure loguru logger
    
    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR)
        log_file: Log file name
        rotation: When to rotate (e.g., "10 MB", "1 day")
        retention: How long to keep logs
        console: Whether to log to console
    """
    # Remove default handler
    logger.remove()
    
    # Console handler with colors
    if console:
        logger.add(
            sys.stdout,
            level=level,
            format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>",
            colorize=True
        )
    
    # File handler with rotation
    logger.add(
        LOG_DIR / log_file,
        level=level,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        rotation=rotation,
        retention=retention,
        compression="zip"
    )
    
    return logger


def get_logger(name: str = None):
    """
    Get a logger instance with optional name binding
    
    Args:
        name: Module name for context
    
    Returns:
        Bound logger instance
    """
    if name:
        return logger.bind(name=name)
    return logger


# Convenience shortcuts
def info(message: str, **kwargs):
    """Log info message"""
    logger.info(message, **kwargs)


def debug(message: str, **kwargs):
    """Log debug message"""
    logger.debug(message, **kwargs)


def warning(message: str, **kwargs):
    """Log warning message"""
    logger.warning(message, **kwargs)


def error(message: str, **kwargs):
    """Log error message"""
    logger.error(message, **kwargs)


def success(message: str, **kwargs):
    """Log success message (info with success marker)"""
    logger.success(message, **kwargs)


# Node-specific formatters
def node_start(node_name: str, file_path: str = None):
    """Log node start"""
    if file_path:
        logger.info(f"🚀 [{node_name}] Starting - {Path(file_path).name}")
    else:
        logger.info(f"🚀 [{node_name}] Starting")


def node_complete(node_name: str, details: str = None):
    """Log node completion"""
    if details:
        logger.success(f"✅ [{node_name}] Complete - {details}")
    else:
        logger.success(f"✅ [{node_name}] Complete")


def node_error(node_name: str, error_msg: str):
    """Log node error"""
    logger.error(f"❌ [{node_name}] Error: {error_msg}")


def phase_start(phase_name: str, count: int = None):
    """Log phase start"""
    if count is not None:
        logger.info(f"📋 [{phase_name}] Starting - {count} items")
    else:
        logger.info(f"📋 [{phase_name}] Starting")


def llm_call(operation: str, cached: bool = False):
    """Log LLM call"""
    if cached:
        logger.debug(f"🧠 [LLM] {operation} (cached)")
    else:
        logger.debug(f"🧠 [LLM] {operation}")


def human_review_required(question_type: str):
    """Log human review requirement"""
    logger.warning(f"🛑 [Human Review] Required: {question_type}")


def separator(char: str = "=", length: int = 60):
    """Print separator line"""
    logger.info(char * length)


# Initialize with defaults on import
setup_logging()

