"""
Circuit breaker pattern implementation for fault tolerance.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, Callable, Any


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing, blocking requests
    HALF_OPEN = "half_open"  # Testing if service recovered


class CircuitBreaker:
    """
    Circuit breaker implementation for preventing cascade failures.
    """
    
    def __init__(
        self,
        failure_threshold: int = 5,
        reset_timeout: int = 60,
        success_threshold: int = 2,
        name: str = "circuit_breaker"
    ):
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.success_threshold = success_threshold
        self.name = name
        
        # State
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: Optional[datetime] = None
        
        # Logging
        self.logger = logging.getLogger(f"{__name__}.{name}")
    
    def can_execute(self) -> bool:
        """Check if execution is allowed."""
        if self.state == CircuitState.CLOSED:
            return True
        
        elif self.state == CircuitState.OPEN:
            # Check if reset timeout has passed
            if (self.last_failure_time and 
                datetime.now() - self.last_failure_time >= timedelta(seconds=self.reset_timeout)):
                self._transition_to_half_open()
                return True
            return False
        
        elif self.state == CircuitState.HALF_OPEN:
            return True
        
        return False
    
    def record_success(self) -> None:
        """Record a successful execution."""
        if self.state == CircuitState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.success_threshold:
                self._transition_to_closed()
        elif self.state == CircuitState.CLOSED:
            # Reset failure count on success
            self.failure_count = 0
    
    def record_failure(self) -> None:
        """Record a failed execution."""
        self.failure_count += 1
        self.last_failure_time = datetime.now()
        
        if self.state == CircuitState.CLOSED:
            if self.failure_count >= self.failure_threshold:
                self._transition_to_open()
        elif self.state == CircuitState.HALF_OPEN:
            self._transition_to_open()
    
    async def execute(self, func: Callable, *args, **kwargs) -> Any:
        """Execute a function through the circuit breaker."""
        if not self.can_execute():
            raise CircuitBreakerOpenError(f"Circuit breaker '{self.name}' is open")
        
        try:
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)
            
            self.record_success()
            return result
            
        except Exception as e:
            self.record_failure()
            raise
    
    def _transition_to_closed(self) -> None:
        """Transition to CLOSED state."""
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.logger.info(f"Circuit breaker '{self.name}' transitioned to CLOSED")
    
    def _transition_to_open(self) -> None:
        """Transition to OPEN state."""
        self.state = CircuitState.OPEN
        self.success_count = 0
        self.logger.warning(f"Circuit breaker '{self.name}' transitioned to OPEN")
    
    def _transition_to_half_open(self) -> None:
        """Transition to HALF_OPEN state."""
        self.state = CircuitState.HALF_OPEN
        self.success_count = 0
        self.logger.info(f"Circuit breaker '{self.name}' transitioned to HALF_OPEN")
    
    def get_metrics(self) -> dict:
        """Get circuit breaker metrics."""
        return {
            'name': self.name,
            'state': self.state.value,
            'failure_count': self.failure_count,
            'success_count': self.success_count,
            'last_failure_time': self.last_failure_time.isoformat() if self.last_failure_time else None,
            'failure_threshold': self.failure_threshold,
            'reset_timeout': self.reset_timeout,
            'success_threshold': self.success_threshold
        }


class CircuitBreakerOpenError(Exception):
    """Exception raised when circuit breaker is open."""
    pass


class AsyncCircuitBreaker(CircuitBreaker):
    """
    Async-first circuit breaker with additional features.
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._lock = asyncio.Lock()
    
    async def can_execute_async(self) -> bool:
        """Thread-safe check if execution is allowed."""
        async with self._lock:
            return self.can_execute()
    
    async def record_success_async(self) -> None:
        """Thread-safe record success."""
        async with self._lock:
            self.record_success()
    
    async def record_failure_async(self) -> None:
        """Thread-safe record failure."""
        async with self._lock:
            self.record_failure()
    
    async def execute_async(self, func: Callable, *args, **kwargs) -> Any:
        """Execute function with async-safe state management."""
        if not await self.can_execute_async():
            raise CircuitBreakerOpenError(f"Circuit breaker '{self.name}' is open")
        
        try:
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = await asyncio.to_thread(func, *args, **kwargs)
            
            await self.record_success_async()
            return result
            
        except Exception as e:
            await self.record_failure_async()
            raise


def circuit_breaker(
    failure_threshold: int = 5,
    reset_timeout: int = 60,
    success_threshold: int = 2,
    name: Optional[str] = None
):
    """
    Decorator for applying circuit breaker pattern to functions.
    """
    def decorator(func: Callable) -> Callable:
        cb_name = name or f"{func.__module__}.{func.__name__}"
        cb = AsyncCircuitBreaker(
            failure_threshold=failure_threshold,
            reset_timeout=reset_timeout,
            success_threshold=success_threshold,
            name=cb_name
        )
        
        if asyncio.iscoroutinefunction(func):
            async def async_wrapper(*args, **kwargs):
                return await cb.execute_async(func, *args, **kwargs)
            return async_wrapper
        else:
            def sync_wrapper(*args, **kwargs):
                return asyncio.run(cb.execute_async(func, *args, **kwargs))
            return sync_wrapper
    
    return decorator