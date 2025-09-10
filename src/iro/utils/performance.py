"""
Performance monitoring and profiling utilities for IRO system.
"""

import asyncio
import functools
import logging
import psutil
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Dict, List, Optional, Callable, Any
import threading
from collections import deque


@dataclass
class PerformanceMetrics:
    """Performance metrics data structure."""
    cpu_percent: float
    memory_percent: float
    memory_mb: float
    disk_io_read_mb: float
    disk_io_write_mb: float
    network_sent_mb: float
    network_recv_mb: float
    open_files: int
    thread_count: int
    timestamp: float


@dataclass
class FunctionMetrics:
    """Function performance metrics."""
    name: str
    call_count: int
    total_time: float
    avg_time: float
    min_time: float
    max_time: float
    error_count: int
    last_called: float


class PerformanceMonitor:
    """
    System performance monitoring with historical tracking.
    """
    
    def __init__(self, history_size: int = 100):
        self.history_size = history_size
        self.metrics_history: deque = deque(maxlen=history_size)
        self.logger = logging.getLogger(__name__)
        self.process = psutil.Process()
        self._lock = threading.Lock()
        
        # Initial network/disk IO counters for delta calculation
        self._last_net_io = psutil.net_io_counters()
        self._last_disk_io = psutil.disk_io_counters()
        self._last_update = time.time()
    
    def collect_metrics(self) -> PerformanceMetrics:
        """Collect current system performance metrics."""
        try:
            with self._lock:
                current_time = time.time()
                time_delta = current_time - self._last_update
                
                # CPU and Memory
                cpu_percent = self.process.cpu_percent()
                memory_info = self.process.memory_info()
                memory_percent = self.process.memory_percent()
                
                # Network IO (delta since last call)
                current_net_io = psutil.net_io_counters()
                net_sent_mb = 0
                net_recv_mb = 0
                
                if self._last_net_io and time_delta > 0:
                    net_sent_mb = (current_net_io.bytes_sent - self._last_net_io.bytes_sent) / (1024 * 1024)
                    net_recv_mb = (current_net_io.bytes_recv - self._last_net_io.bytes_recv) / (1024 * 1024)
                
                # Disk IO (delta since last call)
                current_disk_io = psutil.disk_io_counters()
                disk_read_mb = 0
                disk_write_mb = 0
                
                if self._last_disk_io and time_delta > 0:
                    disk_read_mb = (current_disk_io.read_bytes - self._last_disk_io.read_bytes) / (1024 * 1024)
                    disk_write_mb = (current_disk_io.write_bytes - self._last_disk_io.write_bytes) / (1024 * 1024)
                
                # Process info
                open_files = len(self.process.open_files())
                thread_count = self.process.num_threads()
                
                metrics = PerformanceMetrics(
                    cpu_percent=cpu_percent,
                    memory_percent=memory_percent,
                    memory_mb=memory_info.rss / (1024 * 1024),
                    disk_io_read_mb=disk_read_mb,
                    disk_io_write_mb=disk_write_mb,
                    network_sent_mb=net_sent_mb,
                    network_recv_mb=net_recv_mb,
                    open_files=open_files,
                    thread_count=thread_count,
                    timestamp=current_time
                )
                
                # Update last values
                self._last_net_io = current_net_io
                self._last_disk_io = current_disk_io
                self._last_update = current_time
                
                # Store in history
                self.metrics_history.append(metrics)
                
                return metrics
                
        except Exception as e:
            self.logger.error(f"Failed to collect performance metrics: {e}")
            # Return default metrics on error
            return PerformanceMetrics(
                cpu_percent=0, memory_percent=0, memory_mb=0,
                disk_io_read_mb=0, disk_io_write_mb=0,
                network_sent_mb=0, network_recv_mb=0,
                open_files=0, thread_count=0, timestamp=time.time()
            )
    
    def get_metrics_history(self, minutes: int = 10) -> List[PerformanceMetrics]:
        """Get metrics history for the last N minutes."""
        cutoff_time = time.time() - (minutes * 60)
        with self._lock:
            return [m for m in self.metrics_history if m.timestamp >= cutoff_time]
    
    def get_average_metrics(self, minutes: int = 5) -> Optional[PerformanceMetrics]:
        """Get average metrics over the last N minutes."""
        history = self.get_metrics_history(minutes)
        
        if not history:
            return None
        
        return PerformanceMetrics(
            cpu_percent=sum(m.cpu_percent for m in history) / len(history),
            memory_percent=sum(m.memory_percent for m in history) / len(history),
            memory_mb=sum(m.memory_mb for m in history) / len(history),
            disk_io_read_mb=sum(m.disk_io_read_mb for m in history),
            disk_io_write_mb=sum(m.disk_io_write_mb for m in history),
            network_sent_mb=sum(m.network_sent_mb for m in history),
            network_recv_mb=sum(m.network_recv_mb for m in history),
            open_files=int(sum(m.open_files for m in history) / len(history)),
            thread_count=int(sum(m.thread_count for m in history) / len(history)),
            timestamp=time.time()
        )
    
    def detect_performance_issues(self) -> List[str]:
        """Detect potential performance issues."""
        issues = []
        current = self.collect_metrics()
        avg_5min = self.get_average_metrics(5)
        
        if not avg_5min:
            return issues
        
        # High CPU usage
        if current.cpu_percent > 80:
            issues.append(f"High CPU usage: {current.cpu_percent:.1f}%")
        
        # High memory usage
        if current.memory_percent > 85:
            issues.append(f"High memory usage: {current.memory_percent:.1f}%")
        
        # Memory leak detection (memory consistently increasing)
        recent_history = self.get_metrics_history(10)
        if len(recent_history) >= 10:
            memory_trend = recent_history[-1].memory_mb - recent_history[0].memory_mb
            if memory_trend > 100:  # 100MB increase in 10 minutes
                issues.append(f"Potential memory leak: +{memory_trend:.1f}MB in 10 minutes")
        
        # Too many open files
        if current.open_files > 1000:
            issues.append(f"High open file count: {current.open_files}")
        
        # Excessive thread count
        if current.thread_count > 100:
            issues.append(f"High thread count: {current.thread_count}")
        
        return issues


class FunctionProfiler:
    """
    Function-level performance profiling.
    """
    
    def __init__(self):
        self.function_metrics: Dict[str, FunctionMetrics] = {}
        self._lock = threading.Lock()
        self.logger = logging.getLogger(__name__)
    
    def record_function_call(self, function_name: str, duration: float, error: bool = False) -> None:
        """Record a function call performance."""
        with self._lock:
            if function_name not in self.function_metrics:
                self.function_metrics[function_name] = FunctionMetrics(
                    name=function_name,
                    call_count=0,
                    total_time=0.0,
                    avg_time=0.0,
                    min_time=float('inf'),
                    max_time=0.0,
                    error_count=0,
                    last_called=0.0
                )
            
            metrics = self.function_metrics[function_name]
            metrics.call_count += 1
            metrics.total_time += duration
            metrics.avg_time = metrics.total_time / metrics.call_count
            metrics.min_time = min(metrics.min_time, duration)
            metrics.max_time = max(metrics.max_time, duration)
            metrics.last_called = time.time()
            
            if error:
                metrics.error_count += 1
    
    def get_function_metrics(self, function_name: str) -> Optional[FunctionMetrics]:
        """Get metrics for a specific function."""
        with self._lock:
            return self.function_metrics.get(function_name)
    
    def get_all_metrics(self) -> Dict[str, FunctionMetrics]:
        """Get all function metrics."""
        with self._lock:
            return self.function_metrics.copy()
    
    def get_top_functions(self, by: str = "total_time", limit: int = 10) -> List[FunctionMetrics]:
        """Get top functions by specified metric."""
        with self._lock:
            metrics_list = list(self.function_metrics.values())
            
        if by == "total_time":
            metrics_list.sort(key=lambda x: x.total_time, reverse=True)
        elif by == "avg_time":
            metrics_list.sort(key=lambda x: x.avg_time, reverse=True)
        elif by == "call_count":
            metrics_list.sort(key=lambda x: x.call_count, reverse=True)
        elif by == "error_count":
            metrics_list.sort(key=lambda x: x.error_count, reverse=True)
        
        return metrics_list[:limit]
    
    def reset_metrics(self) -> None:
        """Reset all function metrics."""
        with self._lock:
            self.function_metrics.clear()


# Global instances
performance_monitor = PerformanceMonitor()
function_profiler = FunctionProfiler()


def profile_function(function_name: Optional[str] = None):
    """Decorator to profile function performance."""
    def decorator(func: Callable) -> Callable:
        name = function_name or f"{func.__module__}.{func.__name__}"
        
        if asyncio.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                start_time = time.time()
                error_occurred = False
                try:
                    result = await func(*args, **kwargs)
                    return result
                except Exception as e:
                    error_occurred = True
                    raise
                finally:
                    duration = time.time() - start_time
                    function_profiler.record_function_call(name, duration, error_occurred)
            
            return async_wrapper
        else:
            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                start_time = time.time()
                error_occurred = False
                try:
                    result = func(*args, **kwargs)
                    return result
                except Exception as e:
                    error_occurred = True
                    raise
                finally:
                    duration = time.time() - start_time
                    function_profiler.record_function_call(name, duration, error_occurred)
            
            return sync_wrapper
    
    return decorator


@asynccontextmanager
async def performance_context(name: str):
    """Async context manager for measuring performance."""
    start_time = time.time()
    error_occurred = False
    try:
        yield
    except Exception as e:
        error_occurred = True
        raise
    finally:
        duration = time.time() - start_time
        function_profiler.record_function_call(name, duration, error_occurred)


class PerformanceReporter:
    """
    Generate performance reports.
    """
    
    def __init__(self, monitor: PerformanceMonitor, profiler: FunctionProfiler):
        self.monitor = monitor
        self.profiler = profiler
    
    def generate_system_report(self) -> Dict[str, Any]:
        """Generate system performance report."""
        current_metrics = self.monitor.collect_metrics()
        avg_metrics = self.monitor.get_average_metrics(10)
        issues = self.monitor.detect_performance_issues()
        
        return {
            "current_metrics": {
                "cpu_percent": current_metrics.cpu_percent,
                "memory_percent": current_metrics.memory_percent,
                "memory_mb": current_metrics.memory_mb,
                "open_files": current_metrics.open_files,
                "thread_count": current_metrics.thread_count
            },
            "average_metrics_10min": {
                "cpu_percent": avg_metrics.cpu_percent if avg_metrics else 0,
                "memory_percent": avg_metrics.memory_percent if avg_metrics else 0,
                "memory_mb": avg_metrics.memory_mb if avg_metrics else 0
            } if avg_metrics else None,
            "performance_issues": issues,
            "timestamp": current_metrics.timestamp
        }
    
    def generate_function_report(self) -> Dict[str, Any]:
        """Generate function performance report."""
        top_by_time = self.profiler.get_top_functions("total_time", 10)
        top_by_calls = self.profiler.get_top_functions("call_count", 10)
        top_by_errors = self.profiler.get_top_functions("error_count", 10)
        
        return {
            "top_functions_by_time": [
                {
                    "name": f.name,
                    "total_time": f.total_time,
                    "avg_time": f.avg_time,
                    "call_count": f.call_count
                }
                for f in top_by_time
            ],
            "top_functions_by_calls": [
                {
                    "name": f.name,
                    "call_count": f.call_count,
                    "total_time": f.total_time,
                    "avg_time": f.avg_time
                }
                for f in top_by_calls
            ],
            "functions_with_errors": [
                {
                    "name": f.name,
                    "error_count": f.error_count,
                    "call_count": f.call_count,
                    "error_rate": f.error_count / f.call_count if f.call_count > 0 else 0
                }
                for f in top_by_errors if f.error_count > 0
            ]
        }
    
    def generate_full_report(self) -> Dict[str, Any]:
        """Generate comprehensive performance report."""
        return {
            "system": self.generate_system_report(),
            "functions": self.generate_function_report(),
            "report_timestamp": time.time()
        }


# Global performance reporter
performance_reporter = PerformanceReporter(performance_monitor, function_profiler)


def start_performance_monitoring(interval_seconds: int = 60) -> None:
    """Start background performance monitoring."""
    async def monitor_loop():
        while True:
            try:
                performance_monitor.collect_metrics()
                await asyncio.sleep(interval_seconds)
            except Exception as e:
                logging.error(f"Performance monitoring error: {e}")
                await asyncio.sleep(interval_seconds)
    
    # Start monitoring task
    asyncio.create_task(monitor_loop())