"""
Logging configuration for the IRO system.
"""

import json
import logging
import logging.config
import sys
from datetime import datetime
from typing import Dict, Any


class JSONFormatter(logging.Formatter):
    """
    Custom JSON formatter for structured logging.
    """
    
    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        log_entry = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno
        }
        
        # Add exception info if present
        if record.exc_info:
            log_entry['exception'] = self.formatException(record.exc_info)
        
        # Add extra fields
        for key, value in record.__dict__.items():
            if key not in ('name', 'msg', 'args', 'levelname', 'levelno', 'pathname',
                          'filename', 'module', 'lineno', 'funcName', 'created', 'msecs',
                          'relativeCreated', 'thread', 'threadName', 'processName',
                          'process', 'exc_info', 'exc_text', 'stack_info', 'getMessage'):
                log_entry[key] = value
        
        return json.dumps(log_entry, default=str)


def setup_logging(log_level: str = "INFO", log_format: str = "json") -> None:
    """
    Setup logging configuration for the IRO system.
    
    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
        log_format: Format type ("json" or "text")
    """
    
    # Convert string level to logging constant
    level = getattr(logging, log_level.upper(), logging.INFO)
    
    if log_format.lower() == "json":
        formatter = JSONFormatter()
    else:
        formatter = logging.Formatter(
            fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    
    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Add console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # Set specific logger levels
    logging.getLogger('kubernetes').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('aiohttp').setLevel(logging.WARNING)
    
    # Log startup message
    logging.info("Logging configured", extra={
        'log_level': log_level,
        'log_format': log_format
    })


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger with the given name.
    
    Args:
        name: Logger name
        
    Returns:
        Configured logger instance
    """
    return logging.getLogger(name)


class StructuredLogger:
    """
    Wrapper for structured logging with additional context.
    """
    
    def __init__(self, name: str, context: Dict[str, Any] = None):
        self.logger = logging.getLogger(name)
        self.context = context or {}
    
    def _log(self, level: int, message: str, **kwargs) -> None:
        """Log with structured context."""
        extra = {**self.context, **kwargs}
        self.logger.log(level, message, extra=extra)
    
    def debug(self, message: str, **kwargs) -> None:
        """Log debug message."""
        self._log(logging.DEBUG, message, **kwargs)
    
    def info(self, message: str, **kwargs) -> None:
        """Log info message."""
        self._log(logging.INFO, message, **kwargs)
    
    def warning(self, message: str, **kwargs) -> None:
        """Log warning message."""
        self._log(logging.WARNING, message, **kwargs)
    
    def error(self, message: str, **kwargs) -> None:
        """Log error message."""
        self._log(logging.ERROR, message, **kwargs)
    
    def critical(self, message: str, **kwargs) -> None:
        """Log critical message."""
        self._log(logging.CRITICAL, message, **kwargs)
    
    def with_context(self, **context) -> 'StructuredLogger':
        """Create new logger with additional context."""
        new_context = {**self.context, **context}
        return StructuredLogger(self.logger.name, new_context)


def log_function_call(func):
    """
    Decorator to log function calls with parameters and results.
    """
    def wrapper(*args, **kwargs):
        logger = logging.getLogger(func.__module__)
        
        # Log function entry
        logger.debug(f"Calling {func.__name__}", extra={
            'function': func.__name__,
            'args': str(args),
            'kwargs': str(kwargs),
            'event': 'function_entry'
        })
        
        try:
            result = func(*args, **kwargs)
            
            # Log successful completion
            logger.debug(f"Completed {func.__name__}", extra={
                'function': func.__name__,
                'event': 'function_exit',
                'success': True
            })
            
            return result
            
        except Exception as e:
            # Log exception
            logger.error(f"Error in {func.__name__}: {e}", extra={
                'function': func.__name__,
                'event': 'function_error',
                'error': str(e),
                'success': False
            })
            raise
    
    return wrapper


async def log_async_function_call(func):
    """
    Decorator to log async function calls with parameters and results.
    """
    async def wrapper(*args, **kwargs):
        logger = logging.getLogger(func.__module__)
        
        # Log function entry
        logger.debug(f"Calling async {func.__name__}", extra={
            'function': func.__name__,
            'args': str(args),
            'kwargs': str(kwargs),
            'event': 'async_function_entry'
        })
        
        try:
            result = await func(*args, **kwargs)
            
            # Log successful completion
            logger.debug(f"Completed async {func.__name__}", extra={
                'function': func.__name__,
                'event': 'async_function_exit',
                'success': True
            })
            
            return result
            
        except Exception as e:
            # Log exception
            logger.error(f"Error in async {func.__name__}: {e}", extra={
                'function': func.__name__,
                'event': 'async_function_error',
                'error': str(e),
                'success': False
            })
            raise
    
    return wrapper


class LogContext:
    """
    Context manager for adding structured logging context.
    """
    
    def __init__(self, logger_name: str, **context):
        self.logger_name = logger_name
        self.context = context
        self.original_logger_class = None
    
    def __enter__(self):
        # Store original logger class
        self.original_logger_class = logging.getLoggerClass()
        
        # Create custom logger class with context
        class ContextLogger(logging.Logger):
            def __init__(self, name):
                super().__init__(name)
                self._context = context
            
            def _log(self, level, msg, args, exc_info=None, extra=None, stack_info=False):
                if extra is None:
                    extra = {}
                extra.update(self._context)
                super()._log(level, msg, args, exc_info, extra, stack_info)
        
        # Set new logger class
        logging.setLoggerClass(ContextLogger)
        
        return logging.getLogger(self.logger_name)
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        # Restore original logger class
        logging.setLoggerClass(self.original_logger_class)