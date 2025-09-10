"""
Test suite for the incident detector.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from src.iro.config import MonitoringConfig
from src.iro.monitoring.detector import IncidentDetector, AnomalyDetector
from src.iro.core.models import ServiceMetrics, Anomaly, SeverityLevel
from src.iro.utils.events import EventBus


@pytest.fixture
def config():
    """Create test monitoring configuration."""
    return MonitoringConfig(
        interval_seconds=10,
        cpu_threshold=0.8,
        memory_threshold=0.9,
        restart_threshold=3,
        services=["test-service", "another-service"]
    )


@pytest.fixture
async def event_bus():
    """Create test event bus."""
    bus = EventBus()
    await bus.start()
    yield bus
    await bus.stop()


@pytest.fixture
async def detector(config, event_bus):
    """Create test detector with mocked Kubernetes client."""
    with patch('src.iro.monitoring.detector.K8sClientManager') as mock_k8s:
        # Setup mock Kubernetes client
        mock_client_manager = AsyncMock()
        mock_k8s.return_value = mock_client_manager
        
        detector = IncidentDetector(config, event_bus)
        detector.k8s_manager = mock_client_manager
        detector.v1_core = AsyncMock()
        detector.v1_metrics = AsyncMock()
        
        yield detector


class TestIncidentDetector:
    """Test cases for IncidentDetector."""
    
    @pytest.mark.asyncio
    async def test_start_stop(self, detector):
        """Test detector startup and shutdown."""
        # Test start
        await detector.start()
        assert detector.running is True
        
        # Test stop
        await detector.stop()
        assert detector.running is False
    
    @pytest.mark.asyncio
    async def test_health_check(self, detector):
        """Test health check functionality."""
        # Setup mock
        detector.v1_core.list_namespace = AsyncMock()
        
        # Test healthy state
        health = await detector.health_check()
        assert health.healthy is True
        
        # Test unhealthy state
        detector.v1_core.list_namespace.side_effect = Exception("Connection failed")
        health = await detector.health_check()
        assert health.healthy is False
    
    @pytest.mark.asyncio
    async def test_collect_service_metrics(self, detector):
        """Test service metrics collection."""
        # Setup mock data
        mock_pod = MagicMock()
        mock_pod.metadata.name = "test-pod"
        mock_pod.status.phase = "Running"
        mock_pod.status.conditions = [
            MagicMock(type="Ready", status="True")
        ]
        mock_pod.status.container_statuses = [
            MagicMock(restart_count=1)
        ]
        
        mock_pods_response = MagicMock()
        mock_pods_response.items = [mock_pod]
        
        # Configure mocks
        detector.v1_core.list_namespaced_pod = AsyncMock(return_value=mock_pods_response)
        detector._get_pod_metrics = AsyncMock(return_value={'cpu': 0.5, 'memory': 1024*1024*100})  # 100MB
        detector._get_application_metrics = AsyncMock(return_value={
            'request_rate': 10.0,
            'error_rate': 0.01,
            'latency_p99': 200.0
        })
        
        # Test metrics collection
        metrics = await detector._collect_service_metrics("test-service")
        
        assert metrics is not None
        assert metrics.service == "test-service"
        assert metrics.pod_count == 1
        assert metrics.ready_pods == 1
        assert metrics.cpu_usage == 0.5
        assert metrics.request_rate == 10.0
    
    @pytest.mark.asyncio
    async def test_collect_all_metrics(self, detector):
        """Test collection of all service metrics."""
        # Mock collect_service_metrics to return test data
        test_metrics = ServiceMetrics(
            service="test-service",
            namespace="default",
            cpu_usage=0.7,
            memory_usage=0.6
        )
        
        detector._collect_service_metrics = AsyncMock(return_value=test_metrics)
        
        # Test collection
        all_metrics = await detector._collect_all_metrics()
        
        assert len(all_metrics) == len(detector.config.services)
        assert all(isinstance(m, ServiceMetrics) for m in all_metrics)
    
    def test_detect_anomalies(self, detector):
        """Test anomaly detection."""
        # Create test metrics
        current_metrics = [
            ServiceMetrics(
                service="test-service",
                namespace="default",
                cpu_usage=0.95,  # Above threshold
                memory_usage=0.5,
                restart_count=5   # Above threshold
            )
        ]
        
        # Test detection
        anomalies = detector._detect_anomalies(current_metrics)
        
        # Should detect CPU and restart anomalies
        assert len(anomalies) >= 2
        anomaly_types = [a.anomaly_type for a in anomalies]
        assert 'high_cpu' in anomaly_types
        assert 'high_restart_count' in anomaly_types
    
    @pytest.mark.asyncio
    async def test_process_anomaly(self, detector, event_bus):
        """Test anomaly processing and incident creation."""
        # Create test anomaly
        anomaly = Anomaly(
            service="test-service",
            anomaly_type="high_cpu",
            description="CPU usage too high",
            current_value=0.95,
            threshold=0.8,
            confidence=0.9
        )
        
        # Setup event capture
        published_events = []
        
        async def capture_event(data):
            published_events.append(data)
        
        event_bus.subscribe('incident.detected', capture_event)
        
        # Process anomaly
        await detector._process_anomaly(anomaly)
        
        # Wait for event processing
        await asyncio.sleep(0.1)
        
        # Verify incident was created and published
        assert len(published_events) == 1
        incident_data = published_events[0]['incident']
        assert incident_data['service'] == "test-service"
        assert incident_data['type'] == "high_cpu"


class TestAnomalyDetector:
    """Test cases for AnomalyDetector."""
    
    def setup_method(self):
        """Setup test data."""
        self.detector = AnomalyDetector()
    
    def test_detect_cpu_anomaly_threshold(self):
        """Test CPU anomaly detection with threshold."""
        # Test case: CPU above threshold
        current = ServiceMetrics(
            service="test-service",
            namespace="default",
            cpu_usage=0.95
        )
        
        anomaly = self.detector.detect_cpu_anomaly(current, [], 0.8)
        
        assert anomaly is not None
        assert anomaly.anomaly_type == "high_cpu"
        assert anomaly.current_value == 0.95
        assert anomaly.threshold == 0.8
    
    def test_detect_cpu_anomaly_statistical(self):
        """Test CPU anomaly detection with statistical analysis."""
        # Create historical data with normal CPU usage
        history = [
            ServiceMetrics(service="test", namespace="default", cpu_usage=0.3 + i * 0.01)
            for i in range(20)
        ]
        
        # Test case: CPU significantly above normal
        current = ServiceMetrics(
            service="test-service",
            namespace="default",
            cpu_usage=0.9  # Much higher than historical average
        )
        
        anomaly = self.detector.detect_cpu_anomaly(current, history, 1.0)  # High threshold
        
        assert anomaly is not None
        assert anomaly.anomaly_type == "cpu_anomaly"
        assert abs(anomaly.deviation) > 3.0  # Should be >3 standard deviations
    
    def test_detect_memory_anomaly(self):
        """Test memory anomaly detection."""
        current = ServiceMetrics(
            service="test-service",
            namespace="default",
            memory_usage=0.95
        )
        
        anomaly = self.detector.detect_memory_anomaly(current, [], 0.9)
        
        assert anomaly is not None
        assert anomaly.anomaly_type == "high_memory"
        assert anomaly.current_value == 0.95
    
    def test_detect_restart_anomaly(self):
        """Test restart anomaly detection."""
        current = ServiceMetrics(
            service="test-service",
            namespace="default",
            restart_count=5
        )
        
        anomaly = self.detector.detect_restart_anomaly(current, [], 3)
        
        assert anomaly is not None
        assert anomaly.anomaly_type == "high_restart_count"
        assert anomaly.current_value == 5.0
    
    def test_detect_error_rate_anomaly(self):
        """Test error rate anomaly detection."""
        current = ServiceMetrics(
            service="test-service",
            namespace="default",
            error_rate=0.1  # 10% error rate
        )
        
        anomaly = self.detector.detect_error_rate_anomaly(current, [])
        
        assert anomaly is not None
        assert anomaly.anomaly_type == "high_error_rate"
        assert anomaly.current_value == 0.1
    
    def test_no_anomaly_detected(self):
        """Test case where no anomaly should be detected."""
        current = ServiceMetrics(
            service="test-service",
            namespace="default",
            cpu_usage=0.3,
            memory_usage=0.4,
            restart_count=1,
            error_rate=0.01
        )
        
        # Test all detection methods
        cpu_anomaly = self.detector.detect_cpu_anomaly(current, [], 0.8)
        memory_anomaly = self.detector.detect_memory_anomaly(current, [], 0.9)
        restart_anomaly = self.detector.detect_restart_anomaly(current, [], 3)
        error_anomaly = self.detector.detect_error_rate_anomaly(current, [])
        
        # No anomalies should be detected
        assert cpu_anomaly is None
        assert memory_anomaly is None
        assert restart_anomaly is None
        assert error_anomaly is None


@pytest.mark.asyncio
async def test_monitoring_loop_integration(config, event_bus):
    """Test the complete monitoring loop."""
    with patch('src.iro.monitoring.detector.K8sClientManager') as mock_k8s:
        # Setup mocks
        mock_client_manager = AsyncMock()
        mock_k8s.return_value = mock_client_manager
        
        detector = IncidentDetector(config, event_bus)
        detector.k8s_manager = mock_client_manager
        detector.v1_core = AsyncMock()
        detector.v1_metrics = AsyncMock()
        
        # Mock metrics collection to return anomalous data
        detector._collect_all_metrics = AsyncMock(return_value=[
            ServiceMetrics(
                service="test-service",
                namespace="default",
                cpu_usage=0.95,  # Will trigger anomaly
                memory_usage=0.5
            )
        ])
        
        # Setup event capture
        detected_incidents = []
        
        async def capture_incident(data):
            detected_incidents.append(data)
        
        event_bus.subscribe('incident.detected', capture_incident)
        
        # Start detector briefly
        await detector.start()
        
        # Wait for one monitoring cycle
        await asyncio.sleep(0.1)
        
        await detector.stop()
        
        # Should have detected at least one incident
        assert len(detected_incidents) > 0


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__])