"""
Incident detection module for monitoring Kubernetes services.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional
import statistics

from kubernetes import client, config
from kubernetes.client.rest import ApiException

from ..config import MonitoringConfig
from ..core.models import ServiceMetrics, Anomaly, HealthStatus
from ..utils.events import EventBus
from ..utils.k8s_client import K8sClientManager


class IncidentDetector:
    """
    Detects incidents by monitoring Kubernetes services and metrics.
    """
    
    def __init__(self, config: MonitoringConfig, event_bus: EventBus):
        self.config = config
        self.event_bus = event_bus
        self.logger = logging.getLogger(__name__)
        
        # Kubernetes client
        self.k8s_manager = K8sClientManager()
        self.v1_core = None
        self.v1_metrics = None
        
        # State management
        self.running = False
        self.metrics_history: Dict[str, List[ServiceMetrics]] = {}
        self.anomaly_detector = AnomalyDetector()
        
        # Monitoring task
        self._monitor_task: Optional[asyncio.Task] = None
    
    async def start(self) -> None:
        """Start the incident detector."""
        self.logger.info("Starting incident detector")
        
        try:
            # Initialize Kubernetes clients
            await self.k8s_manager.initialize()
            self.v1_core = self.k8s_manager.core_v1
            self.v1_metrics = self.k8s_manager.metrics_v1
            
            self.running = True
            
            # Start monitoring loop
            self._monitor_task = asyncio.create_task(self._monitoring_loop())
            
            self.logger.info("Incident detector started")
            
        except Exception as e:
            self.logger.error(f"Failed to start incident detector: {e}")
            raise
    
    async def stop(self) -> None:
        """Stop the incident detector."""
        self.logger.info("Stopping incident detector")
        self.running = False
        
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        
        self.logger.info("Incident detector stopped")
    
    async def health_check(self) -> HealthStatus:
        """Perform health check."""
        try:
            # Test Kubernetes connectivity
            await asyncio.to_thread(self.v1_core.list_namespace)
            
            return HealthStatus(
                healthy=True,
                message="Detector running normally",
                details={
                    'services_monitored': len(self.config.services),
                    'metrics_history_size': len(self.metrics_history)
                }
            )
        except Exception as e:
            return HealthStatus(
                healthy=False,
                message=f"Health check failed: {e}",
                details={'error': str(e)}
            )
    
    async def _monitoring_loop(self) -> None:
        """Main monitoring loop."""
        self.logger.info(f"Starting monitoring loop with {self.config.interval_seconds}s interval")
        
        while self.running:
            try:
                start_time = datetime.now()
                
                # Collect metrics for all services
                all_metrics = await self._collect_all_metrics()
                
                # Detect anomalies
                anomalies = self._detect_anomalies(all_metrics)
                
                # Process detected anomalies
                for anomaly in anomalies:
                    await self._process_anomaly(anomaly)
                
                # Store metrics history
                self._store_metrics_history(all_metrics)
                
                duration = (datetime.now() - start_time).total_seconds()
                self.logger.debug(f"Monitoring cycle completed in {duration:.2f}s")
                
                # Wait for next interval
                await asyncio.sleep(max(0, self.config.interval_seconds - duration))
                
            except Exception as e:
                self.logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(10)  # Error backoff
    
    async def _collect_all_metrics(self) -> List[ServiceMetrics]:
        """Collect metrics for all monitored services."""
        metrics = []
        
        for service_name in self.config.services:
            try:
                service_metrics = await self._collect_service_metrics(service_name)
                if service_metrics:
                    metrics.append(service_metrics)
            except Exception as e:
                self.logger.warning(f"Failed to collect metrics for {service_name}: {e}")
        
        return metrics
    
    async def _collect_service_metrics(self, service_name: str) -> Optional[ServiceMetrics]:
        """Collect metrics for a specific service."""
        try:
            # Get pods for the service
            pods = await asyncio.to_thread(
                self.v1_core.list_namespaced_pod,
                namespace=self.config.namespace,
                label_selector=f"app={service_name}"
            )
            
            if not pods.items:
                self.logger.debug(f"No pods found for service {service_name}")
                return None
            
            # Initialize metrics
            metrics = ServiceMetrics(
                service=service_name,
                namespace=self.config.namespace,
                pod_count=len(pods.items)
            )
            
            # Collect pod-level metrics
            total_cpu = 0.0
            total_memory = 0.0
            ready_pods = 0
            total_restarts = 0
            
            for pod in pods.items:
                if pod.status.phase == "Running":
                    # Check if pod is ready
                    if pod.status.conditions:
                        for condition in pod.status.conditions:
                            if condition.type == "Ready" and condition.status == "True":
                                ready_pods += 1
                                break
                    
                    # Get restart count
                    if pod.status.container_statuses:
                        for container_status in pod.status.container_statuses:
                            total_restarts += container_status.restart_count
                    
                    # Try to get resource metrics
                    try:
                        pod_metrics = await self._get_pod_metrics(pod.metadata.name)
                        if pod_metrics:
                            total_cpu += pod_metrics.get('cpu', 0)
                            total_memory += pod_metrics.get('memory', 0)
                    except Exception as e:
                        self.logger.debug(f"Could not get metrics for pod {pod.metadata.name}: {e}")
            
            # Calculate averages
            if ready_pods > 0:
                metrics.cpu_usage = total_cpu / ready_pods
                metrics.memory_usage = total_memory / ready_pods
            
            metrics.ready_pods = ready_pods
            metrics.restart_count = total_restarts
            
            # Try to get application metrics (this would be extended with Prometheus integration)
            app_metrics = await self._get_application_metrics(service_name)
            if app_metrics:
                metrics.request_rate = app_metrics.get('request_rate', 0.0)
                metrics.error_rate = app_metrics.get('error_rate', 0.0)
                metrics.latency_p99 = app_metrics.get('latency_p99', 0.0)
            
            return metrics
            
        except Exception as e:
            self.logger.error(f"Error collecting metrics for {service_name}: {e}")
            return None
    
    async def _get_pod_metrics(self, pod_name: str) -> Optional[Dict[str, float]]:
        """Get resource metrics for a specific pod."""
        try:
            if not self.v1_metrics:
                return None
            
            # Get pod metrics from metrics server
            pod_metrics = await asyncio.to_thread(
                self.v1_metrics.get_namespaced_pod_metrics,
                name=pod_name,
                namespace=self.config.namespace
            )
            
            metrics = {}
            for container in pod_metrics.containers:
                # Parse CPU (convert from nano cores)
                cpu_str = container.usage.get('cpu', '0n')
                if cpu_str.endswith('n'):
                    cpu_nano = float(cpu_str[:-1])
                    metrics['cpu'] = cpu_nano / 1_000_000_000  # Convert to cores
                
                # Parse memory (convert from bytes)
                memory_str = container.usage.get('memory', '0Ki')
                if memory_str.endswith('Ki'):
                    memory_ki = float(memory_str[:-2])
                    metrics['memory'] = memory_ki * 1024  # Convert to bytes
                elif memory_str.endswith('Mi'):
                    memory_mi = float(memory_str[:-2])
                    metrics['memory'] = memory_mi * 1024 * 1024
            
            return metrics
            
        except Exception as e:
            self.logger.debug(f"Failed to get pod metrics for {pod_name}: {e}")
            return None
    
    async def _get_application_metrics(self, service_name: str) -> Optional[Dict[str, float]]:
        """Get application-level metrics (placeholder for Prometheus integration)."""
        # This would integrate with Prometheus or other monitoring systems
        # For now, return mock data based on service behavior patterns
        return {
            'request_rate': 10.0,  # requests/second
            'error_rate': 0.01,    # 1% error rate
            'latency_p99': 200.0   # 200ms
        }
    
    def _detect_anomalies(self, current_metrics: List[ServiceMetrics]) -> List[Anomaly]:
        """Detect anomalies in current metrics compared to historical data."""
        anomalies = []
        
        for metrics in current_metrics:
            service_history = self.metrics_history.get(metrics.service, [])
            
            # CPU anomaly detection
            cpu_anomaly = self.anomaly_detector.detect_cpu_anomaly(
                metrics, service_history, self.config.cpu_threshold
            )
            if cpu_anomaly:
                anomalies.append(cpu_anomaly)
            
            # Memory anomaly detection
            memory_anomaly = self.anomaly_detector.detect_memory_anomaly(
                metrics, service_history, self.config.memory_threshold
            )
            if memory_anomaly:
                anomalies.append(memory_anomaly)
            
            # Restart anomaly detection
            restart_anomaly = self.anomaly_detector.detect_restart_anomaly(
                metrics, service_history, self.config.restart_threshold
            )
            if restart_anomaly:
                anomalies.append(restart_anomaly)
            
            # Error rate anomaly detection
            error_anomaly = self.anomaly_detector.detect_error_rate_anomaly(
                metrics, service_history
            )
            if error_anomaly:
                anomalies.append(error_anomaly)
        
        return anomalies
    
    async def _process_anomaly(self, anomaly: Anomaly) -> None:
        """Process a detected anomaly by creating an incident."""
        incident = anomaly.to_incident()
        
        self.logger.warning(
            f"Anomaly detected: {anomaly.anomaly_type} in {anomaly.service} "
            f"(confidence: {anomaly.confidence:.2f})"
        )
        
        # Publish incident detected event
        await self.event_bus.publish('incident.detected', {
            'incident': incident.to_dict(),
            'anomaly': {
                'id': anomaly.id,
                'type': anomaly.anomaly_type,
                'confidence': anomaly.confidence,
                'deviation': anomaly.deviation
            }
        })
    
    def _store_metrics_history(self, metrics: List[ServiceMetrics]) -> None:
        """Store metrics in history for trend analysis."""
        for metric in metrics:
            if metric.service not in self.metrics_history:
                self.metrics_history[metric.service] = []
            
            history = self.metrics_history[metric.service]
            history.append(metric)
            
            # Keep only last 100 data points (configurable)
            if len(history) > 100:
                history.pop(0)


class AnomalyDetector:
    """Statistical anomaly detection for service metrics."""
    
    def detect_cpu_anomaly(
        self, 
        current: ServiceMetrics, 
        history: List[ServiceMetrics], 
        threshold: float
    ) -> Optional[Anomaly]:
        """Detect CPU usage anomalies."""
        
        # Threshold-based detection
        if current.cpu_usage > threshold:
            confidence = min(1.0, current.cpu_usage / threshold)
            
            return Anomaly(
                service=current.service,
                namespace=current.namespace,
                metric_name="cpu_usage",
                anomaly_type="high_cpu",
                description=f"CPU usage {current.cpu_usage:.1%} exceeds threshold {threshold:.1%}",
                current_value=current.cpu_usage,
                threshold=threshold,
                confidence=confidence,
                deviation=(current.cpu_usage - threshold) / threshold
            )
        
        # Statistical anomaly detection if we have history
        if len(history) >= 10:
            cpu_values = [m.cpu_usage for m in history[-30:]]  # Last 30 measurements
            mean_cpu = statistics.mean(cpu_values)
            stdev_cpu = statistics.stdev(cpu_values) if len(cpu_values) > 1 else 0
            
            if stdev_cpu > 0:
                z_score = (current.cpu_usage - mean_cpu) / stdev_cpu
                
                if abs(z_score) > 3.0:  # 3 standard deviations
                    return Anomaly(
                        service=current.service,
                        namespace=current.namespace,
                        metric_name="cpu_usage",
                        anomaly_type="cpu_anomaly",
                        description=f"CPU usage {current.cpu_usage:.1%} is unusual (z-score: {z_score:.2f})",
                        current_value=current.cpu_usage,
                        expected_value=mean_cpu,
                        confidence=min(1.0, abs(z_score) / 3.0),
                        deviation=z_score
                    )
        
        return None
    
    def detect_memory_anomaly(
        self, 
        current: ServiceMetrics, 
        history: List[ServiceMetrics], 
        threshold: float
    ) -> Optional[Anomaly]:
        """Detect memory usage anomalies."""
        
        if current.memory_usage > threshold:
            confidence = min(1.0, current.memory_usage / threshold)
            
            return Anomaly(
                service=current.service,
                namespace=current.namespace,
                metric_name="memory_usage",
                anomaly_type="high_memory",
                description=f"Memory usage {current.memory_usage:.1%} exceeds threshold {threshold:.1%}",
                current_value=current.memory_usage,
                threshold=threshold,
                confidence=confidence,
                deviation=(current.memory_usage - threshold) / threshold
            )
        
        return None
    
    def detect_restart_anomaly(
        self, 
        current: ServiceMetrics, 
        history: List[ServiceMetrics], 
        threshold: int
    ) -> Optional[Anomaly]:
        """Detect pod restart anomalies."""
        
        if current.restart_count > threshold:
            return Anomaly(
                service=current.service,
                namespace=current.namespace,
                metric_name="restart_count",
                anomaly_type="high_restart_count",
                description=f"Pod restart count {current.restart_count} exceeds threshold {threshold}",
                current_value=float(current.restart_count),
                threshold=float(threshold),
                confidence=0.9,
                deviation=float(current.restart_count - threshold)
            )
        
        return None
    
    def detect_error_rate_anomaly(
        self, 
        current: ServiceMetrics, 
        history: List[ServiceMetrics]
    ) -> Optional[Anomaly]:
        """Detect error rate anomalies."""
        
        # Simple threshold for error rate
        if current.error_rate > 0.05:  # 5% error rate
            return Anomaly(
                service=current.service,
                namespace=current.namespace,
                metric_name="error_rate",
                anomaly_type="high_error_rate",
                description=f"Error rate {current.error_rate:.2%} is too high",
                current_value=current.error_rate,
                threshold=0.05,
                confidence=0.8,
                deviation=current.error_rate - 0.05
            )
        
        return None