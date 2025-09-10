"""
Metrics collection and export utilities for IRO system.
"""

import time
from typing import Dict, Optional, Counter as CounterType
from collections import defaultdict, Counter
import threading
import logging


class MetricsRegistry:
    """
    Simple metrics registry for collecting application metrics.
    """
    
    def __init__(self):
        self.counters: Dict[str, Counter] = {}
        self.gauges: Dict[str, Gauge] = {}
        self.histograms: Dict[str, Histogram] = {}
        self._lock = threading.Lock()
        self.logger = logging.getLogger(__name__)
    
    def counter(self, name: str, description: str = "", labels: Dict[str, str] = None) -> 'Counter':
        """Get or create a counter metric."""
        with self._lock:
            if name not in self.counters:
                self.counters[name] = Counter(name, description, labels or {})
            return self.counters[name]
    
    def gauge(self, name: str, description: str = "", labels: Dict[str, str] = None) -> 'Gauge':
        """Get or create a gauge metric."""
        with self._lock:
            if name not in self.gauges:
                self.gauges[name] = Gauge(name, description, labels or {})
            return self.gauges[name]
    
    def histogram(self, name: str, description: str = "", buckets: list = None, labels: Dict[str, str] = None) -> 'Histogram':
        """Get or create a histogram metric."""
        with self._lock:
            if name not in self.histograms:
                self.histograms[name] = Histogram(name, description, buckets or [0.1, 0.5, 1.0, 2.5, 5.0, 10.0], labels or {})
            return self.histograms[name]
    
    def collect_all(self) -> Dict[str, Dict]:
        """Collect all metrics."""
        with self._lock:
            metrics = {}
            
            for name, counter in self.counters.items():
                metrics[name] = counter.to_dict()
            
            for name, gauge in self.gauges.items():
                metrics[name] = gauge.to_dict()
            
            for name, histogram in self.histograms.items():
                metrics[name] = histogram.to_dict()
            
            return metrics


class Counter:
    """
    Counter metric that can only be incremented.
    """
    
    def __init__(self, name: str, description: str = "", labels: Dict[str, str] = None):
        self.name = name
        self.description = description
        self.labels = labels or {}
        self.value = 0
        self._lock = threading.Lock()
    
    def inc(self, amount: float = 1.0) -> None:
        """Increment the counter."""
        with self._lock:
            self.value += amount
    
    def get(self) -> float:
        """Get current counter value."""
        with self._lock:
            return self.value
    
    def to_dict(self) -> Dict:
        """Convert to dictionary representation."""
        return {
            'type': 'counter',
            'name': self.name,
            'description': self.description,
            'labels': self.labels,
            'value': self.get()
        }


class Gauge:
    """
    Gauge metric that can be set to arbitrary values.
    """
    
    def __init__(self, name: str, description: str = "", labels: Dict[str, str] = None):
        self.name = name
        self.description = description
        self.labels = labels or {}
        self.value = 0.0
        self._lock = threading.Lock()
    
    def set(self, value: float) -> None:
        """Set the gauge value."""
        with self._lock:
            self.value = value
    
    def inc(self, amount: float = 1.0) -> None:
        """Increment the gauge."""
        with self._lock:
            self.value += amount
    
    def dec(self, amount: float = 1.0) -> None:
        """Decrement the gauge."""
        with self._lock:
            self.value -= amount
    
    def get(self) -> float:
        """Get current gauge value."""
        with self._lock:
            return self.value
    
    def to_dict(self) -> Dict:
        """Convert to dictionary representation."""
        return {
            'type': 'gauge',
            'name': self.name,
            'description': self.description,
            'labels': self.labels,
            'value': self.get()
        }


class Histogram:
    """
    Histogram metric for measuring distributions.
    """
    
    def __init__(self, name: str, description: str = "", buckets: list = None, labels: Dict[str, str] = None):
        self.name = name
        self.description = description
        self.labels = labels or {}
        self.buckets = sorted(buckets or [0.1, 0.5, 1.0, 2.5, 5.0, 10.0])
        self.bucket_counts = {bucket: 0 for bucket in self.buckets}
        self.bucket_counts[float('inf')] = 0  # +Inf bucket
        self.count = 0
        self.sum = 0.0
        self._lock = threading.Lock()
    
    def observe(self, value: float) -> None:
        """Observe a value."""
        with self._lock:
            self.count += 1
            self.sum += value
            
            # Update bucket counts
            for bucket in self.buckets:
                if value <= bucket:
                    self.bucket_counts[bucket] += 1
            
            # Always update +Inf bucket
            self.bucket_counts[float('inf')] += 1
    
    def get_count(self) -> int:
        """Get total count of observations."""
        with self._lock:
            return self.count
    
    def get_sum(self) -> float:
        """Get sum of all observed values."""
        with self._lock:
            return self.sum
    
    def get_bucket_counts(self) -> Dict[float, int]:
        """Get bucket counts."""
        with self._lock:
            return self.bucket_counts.copy()
    
    def to_dict(self) -> Dict:
        """Convert to dictionary representation."""
        return {
            'type': 'histogram',
            'name': self.name,
            'description': self.description,
            'labels': self.labels,
            'count': self.get_count(),
            'sum': self.get_sum(),
            'buckets': self.get_bucket_counts()
        }


class Timer:
    """
    Context manager for timing operations.
    """
    
    def __init__(self, metric: Histogram):
        self.metric = metric
        self.start_time = None
    
    def __enter__(self):
        self.start_time = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.start_time:
            duration = time.time() - self.start_time
            self.metric.observe(duration)


# Global metrics registry
metrics_registry = MetricsRegistry()

# Standard IRO metrics
INCIDENT_COUNTER = metrics_registry.counter(
    'iro_incidents_total',
    'Total number of incidents detected',
    {'service': '', 'severity': ''}
)

INCIDENT_RESOLUTION_TIME = metrics_registry.histogram(
    'iro_incident_resolution_seconds',
    'Time taken to resolve incidents',
    [1, 5, 10, 30, 60, 300, 600, 1800],  # 1s to 30min buckets
    {'service': '', 'severity': ''}
)

REMEDIATION_SUCCESS_COUNTER = metrics_registry.counter(
    'iro_remediations_success_total',
    'Number of successful remediations',
    {'service': '', 'action': ''}
)

REMEDIATION_FAILURE_COUNTER = metrics_registry.counter(
    'iro_remediations_failure_total',
    'Number of failed remediations',
    {'service': '', 'action': ''}
)

ANALYSIS_DURATION = metrics_registry.histogram(
    'iro_analysis_duration_seconds',
    'Time taken for incident analysis',
    [0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
    {'service': ''}
)

COMPONENT_HEALTH = metrics_registry.gauge(
    'iro_component_health',
    'Health status of IRO components (1=healthy, 0=unhealthy)',
    {'component': ''}
)

ACTIVE_INCIDENTS = metrics_registry.gauge(
    'iro_active_incidents',
    'Number of currently active incidents'
)

WEBSOCKET_CONNECTIONS = metrics_registry.gauge(
    'iro_websocket_connections',
    'Number of active WebSocket connections'
)


def record_incident_detected(service: str, severity: str) -> None:
    """Record an incident detection."""
    counter = metrics_registry.counter(
        'iro_incidents_total',
        labels={'service': service, 'severity': severity}
    )
    counter.inc()


def record_incident_resolved(service: str, severity: str, duration_seconds: float) -> None:
    """Record an incident resolution."""
    histogram = metrics_registry.histogram(
        'iro_incident_resolution_seconds',
        labels={'service': service, 'severity': severity}
    )
    histogram.observe(duration_seconds)


def record_remediation_success(service: str, action: str) -> None:
    """Record a successful remediation."""
    counter = metrics_registry.counter(
        'iro_remediations_success_total',
        labels={'service': service, 'action': action}
    )
    counter.inc()


def record_remediation_failure(service: str, action: str) -> None:
    """Record a failed remediation."""
    counter = metrics_registry.counter(
        'iro_remediations_failure_total',
        labels={'service': service, 'action': action}
    )
    counter.inc()


def record_analysis_duration(service: str, duration_seconds: float) -> None:
    """Record analysis duration."""
    histogram = metrics_registry.histogram(
        'iro_analysis_duration_seconds',
        labels={'service': service}
    )
    histogram.observe(duration_seconds)


def set_component_health(component: str, healthy: bool) -> None:
    """Set component health status."""
    gauge = metrics_registry.gauge(
        'iro_component_health',
        labels={'component': component}
    )
    gauge.set(1.0 if healthy else 0.0)


def time_function(metric_name: str, labels: Dict[str, str] = None):
    """Decorator to time function execution."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            histogram = metrics_registry.histogram(metric_name, labels=labels or {})
            with Timer(histogram):
                return func(*args, **kwargs)
        return wrapper
    return decorator


async def time_async_function(metric_name: str, labels: Dict[str, str] = None):
    """Decorator to time async function execution."""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            histogram = metrics_registry.histogram(metric_name, labels=labels or {})
            start_time = time.time()
            try:
                result = await func(*args, **kwargs)
                return result
            finally:
                duration = time.time() - start_time
                histogram.observe(duration)
        return wrapper
    return decorator


class MetricsExporter:
    """
    Exports metrics in various formats.
    """
    
    def __init__(self, registry: MetricsRegistry):
        self.registry = registry
    
    def export_prometheus(self) -> str:
        """Export metrics in Prometheus format."""
        lines = []
        metrics = self.registry.collect_all()
        
        for name, metric in metrics.items():
            # Add HELP and TYPE comments
            lines.append(f"# HELP {name} {metric['description']}")
            lines.append(f"# TYPE {name} {metric['type']}")
            
            if metric['type'] == 'counter':
                label_str = self._format_labels(metric['labels'])
                lines.append(f"{name}{label_str} {metric['value']}")
            
            elif metric['type'] == 'gauge':
                label_str = self._format_labels(metric['labels'])
                lines.append(f"{name}{label_str} {metric['value']}")
            
            elif metric['type'] == 'histogram':
                base_labels = metric['labels']
                
                # Bucket lines
                for bucket, count in metric['buckets'].items():
                    bucket_labels = {**base_labels, 'le': str(bucket)}
                    label_str = self._format_labels(bucket_labels)
                    lines.append(f"{name}_bucket{label_str} {count}")
                
                # Count and sum
                label_str = self._format_labels(base_labels)
                lines.append(f"{name}_count{label_str} {metric['count']}")
                lines.append(f"{name}_sum{label_str} {metric['sum']}")
            
            lines.append("")  # Empty line between metrics
        
        return "\n".join(lines)
    
    def export_json(self) -> str:
        """Export metrics in JSON format."""
        import json
        metrics = self.registry.collect_all()
        return json.dumps(metrics, indent=2)
    
    def _format_labels(self, labels: Dict[str, str]) -> str:
        """Format labels for Prometheus export."""
        if not labels:
            return ""
        
        label_pairs = [f'{k}="{v}"' for k, v in labels.items()]
        return "{" + ",".join(label_pairs) + "}"


# Global metrics exporter
metrics_exporter = MetricsExporter(metrics_registry)