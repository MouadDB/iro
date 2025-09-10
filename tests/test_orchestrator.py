"""
Test suite for the main orchestrator functionality.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from src.iro.config import Config, MonitoringConfig, AnalysisConfig, RemediationConfig, DashboardConfig
from src.iro.orchestrator import IncidentOrchestrator
from src.iro.core.models import Incident, IncidentState, SeverityLevel
from src.iro.utils.events import EventBus


@pytest.fixture
async def config():
    """Create test configuration."""
    return Config(
        version="test",
        environment="test",
        gcp_project="test-project",
        monitoring=MonitoringConfig(
            interval_seconds=10,
            services=["test-service"]
        ),
        analysis=AnalysisConfig(
            model_name="test-model",
            timeout_seconds=30
        ),
        remediation=RemediationConfig(
            dry_run=True,
            max_concurrent=1
        ),
        dashboard=DashboardConfig(
            port=8081
        )
    )


@pytest.fixture
async def event_bus():
    """Create test event bus."""
    bus = EventBus()
    await bus.start()
    yield bus
    await bus.stop()


@pytest.fixture
async def orchestrator(config, event_bus):
    """Create test orchestrator."""
    with patch('src.iro.orchestrator.IncidentDetector'), \
         patch('src.iro.orchestrator.IncidentAnalyzer'), \
         patch('src.iro.orchestrator.RemediationExecutor'), \
         patch('src.iro.orchestrator.DashboardServer'):
        
        orchestrator = IncidentOrchestrator(config)
        
        # Mock component methods
        orchestrator.detector.start = AsyncMock()
        orchestrator.detector.stop = AsyncMock()
        orchestrator.detector.health_check = AsyncMock(return_value=MagicMock(healthy=True))
        
        orchestrator.analyzer.start = AsyncMock()
        orchestrator.analyzer.stop = AsyncMock()
        orchestrator.analyzer.health_check = AsyncMock(return_value=MagicMock(healthy=True))
        
        orchestrator.executor.start = AsyncMock()
        orchestrator.executor.stop = AsyncMock()
        orchestrator.executor.health_check = AsyncMock(return_value=MagicMock(healthy=True))
        
        orchestrator.dashboard.start = AsyncMock()
        orchestrator.dashboard.stop = AsyncMock()
        orchestrator.dashboard.health_check = AsyncMock(return_value=MagicMock(healthy=True))
        
        yield orchestrator


class TestIncidentOrchestrator:
    """Test cases for IncidentOrchestrator."""
    
    @pytest.mark.asyncio
    async def test_start_stop(self, orchestrator):
        """Test orchestrator startup and shutdown."""
        # Test start
        await orchestrator.start()
        assert orchestrator.running is True
        
        # Verify components were started
        orchestrator.detector.start.assert_called_once()
        orchestrator.analyzer.start.assert_called_once()
        orchestrator.executor.start.assert_called_once()
        orchestrator.dashboard.start.assert_called_once()
        
        # Test stop
        await orchestrator.stop()
        assert orchestrator.running is False
        
        # Verify components were stopped
        orchestrator.detector.stop.assert_called_once()
        orchestrator.analyzer.stop.assert_called_once()
        orchestrator.executor.stop.assert_called_once()
        orchestrator.dashboard.stop.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_handle_incident_detected(self, orchestrator):
        """Test incident detection handling."""
        # Create test incident
        incident = Incident(
            service="test-service",
            incident_type="high_cpu",
            severity=SeverityLevel.WARNING,
            description="Test incident"
        )
        
        # Start orchestrator
        await orchestrator.start()
        
        # Simulate incident detection
        await orchestrator._handle_incident_detected({
            'incident': incident.to_dict()
        })
        
        # Verify incident was stored
        assert incident.id in orchestrator.incidents
        stored_incident = orchestrator.incidents[incident.id]
        assert stored_incident.state == IncidentState.ANALYZING
    
    @pytest.mark.asyncio
    async def test_handle_analysis_completed(self, orchestrator):
        """Test analysis completion handling."""
        # Create test incident
        incident = Incident(
            service="test-service",
            incident_type="high_cpu",
            severity=SeverityLevel.CRITICAL,
            description="Test incident"
        )
        
        # Store incident
        orchestrator.incidents[incident.id] = incident
        
        # Create test analysis
        analysis = {
            'summary': 'Test analysis',
            'confidence': 0.9,
            'causes': [{'description': 'Test cause', 'probability': 0.8}],
            'recommended_actions': [
                {'action': 'restart_pod', 'priority': 'high', 'estimated_time': '1m'}
            ]
        }
        
        # Start orchestrator
        await orchestrator.start()
        
        # Simulate analysis completion
        await orchestrator._handle_analysis_completed({
            'incident_id': incident.id,
            'analysis': analysis
        })
        
        # Verify incident was updated
        stored_incident = orchestrator.incidents[incident.id]
        assert stored_incident.state == IncidentState.REMEDIATING
        assert stored_incident.root_cause == analysis
    
    @pytest.mark.asyncio
    async def test_handle_remediation_completed(self, orchestrator):
        """Test remediation completion handling."""
        # Create test incident
        incident = Incident(
            service="test-service",
            incident_type="high_cpu",
            severity=SeverityLevel.ERROR,
            description="Test incident"
        )
        
        # Store incident
        orchestrator.incidents[incident.id] = incident
        
        # Start orchestrator
        await orchestrator.start()
        
        # Simulate successful remediation
        await orchestrator._handle_remediation_completed({
            'incident_id': incident.id,
            'success': True,
            'result': {'duration': 30}
        })
        
        # Verify incident was resolved
        stored_incident = orchestrator.incidents[incident.id]
        assert stored_incident.state == IncidentState.RESOLVED
        assert stored_incident.resolved_at is not None
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_fallback(self, orchestrator):
        """Test circuit breaker fallback behavior."""
        # Create test incident
        incident = Incident(
            service="test-service",
            incident_type="high_cpu",
            severity=SeverityLevel.WARNING,
            description="Test incident"
        )
        
        # Open Gemini circuit breaker
        orchestrator.circuit_breakers['gemini'].state = orchestrator.circuit_breakers['gemini'].state.OPEN
        
        # Start orchestrator
        await orchestrator.start()
        
        # Simulate incident detection
        await orchestrator._handle_incident_detected({
            'incident': incident.to_dict()
        })
        
        # Wait for fallback analysis
        await asyncio.sleep(0.1)
        
        # Verify fallback analysis was used
        stored_incident = orchestrator.incidents[incident.id]
        assert stored_incident.root_cause is not None
        assert stored_incident.root_cause['model_version'] == 'fallback'
    
    @pytest.mark.asyncio
    async def test_should_remediate_logic(self, orchestrator):
        """Test remediation decision logic."""
        # Test cases for remediation decisions
        test_cases = [
            # (severity, confidence, dry_run, require_approval, expected)
            (SeverityLevel.INFO, 0.9, False, False, False),  # Low severity
            (SeverityLevel.CRITICAL, 0.5, False, False, False),  # Low confidence
            (SeverityLevel.CRITICAL, 0.9, True, False, False),  # Dry run mode
            (SeverityLevel.CRITICAL, 0.9, False, True, False),  # Requires approval
            (SeverityLevel.CRITICAL, 0.9, False, False, True),  # Should remediate
        ]
        
        for severity, confidence, dry_run, require_approval, expected in test_cases:
            # Update config
            orchestrator.config.remediation.dry_run = dry_run
            orchestrator.config.remediation.require_approval = require_approval
            
            # Create test incident
            incident = Incident(
                service="test-service",
                severity=severity,
                description="Test incident"
            )
            
            # Create test analysis
            analysis = {'confidence': confidence}
            
            # Test decision
            result = orchestrator._should_remediate(incident, analysis)
            assert result == expected, f"Failed for case: {test_cases}"
    
    @pytest.mark.asyncio
    async def test_health_check_handler(self, orchestrator):
        """Test health check event handling."""
        # Start orchestrator
        await orchestrator.start()
        
        # Create test incident
        incident = Incident(service="test-service")
        orchestrator.incidents[incident.id] = incident
        
        # Trigger health check
        await orchestrator._handle_health_check({})
        
        # Wait for processing
        await asyncio.sleep(0.1)
        
        # Health check should complete without errors
        assert orchestrator.running is True
    
    def test_get_basic_cause(self, orchestrator):
        """Test basic cause generation."""
        test_cases = [
            ('high_cpu', 'High CPU usage detected'),
            ('high_memory', 'High memory usage detected'),
            ('unknown_type', 'Issue detected with unknown_type')
        ]
        
        for incident_type, expected_substring in test_cases:
            incident = Incident(incident_type=incident_type)
            cause = orchestrator._get_basic_cause(incident)
            assert expected_substring in cause
    
    def test_get_basic_remediation(self, orchestrator):
        """Test basic remediation action generation."""
        test_cases = [
            'high_cpu',
            'high_memory',
            'high_restart_count',
            'unknown_type'
        ]
        
        for incident_type in test_cases:
            incident = Incident(incident_type=incident_type)
            actions = orchestrator._get_basic_remediation(incident)
            assert len(actions) > 0
            assert all('action' in action for action in actions)
            assert all('priority' in action for action in actions)
    
    def test_get_affected_services(self, orchestrator):
        """Test affected services determination."""
        test_cases = [
            ('userservice', ['frontend', 'contacts', 'balancereader', 'ledgerwriter', 'transactionhistory']),
            ('frontend', []),
            ('unknown_service', [])
        ]
        
        for service, expected_affected in test_cases:
            affected = orchestrator._get_affected_services(service)
            assert affected == expected_affected


@pytest.mark.asyncio
async def test_integration_flow(config):
    """Test full integration flow from detection to resolution."""
    # This test would require more setup and might be better as an integration test
    # For now, it's a placeholder showing how to structure such a test
    
    # Setup real event bus
    event_bus = EventBus()
    await event_bus.start()
    
    try:
        # Mock external dependencies
        with patch('src.iro.orchestrator.IncidentDetector'), \
             patch('src.iro.orchestrator.IncidentAnalyzer'), \
             patch('src.iro.orchestrator.RemediationExecutor'), \
             patch('src.iro.orchestrator.DashboardServer'):
            
            orchestrator = IncidentOrchestrator(config)
            
            # Setup mock responses
            orchestrator.detector.start = AsyncMock()
            orchestrator.detector.stop = AsyncMock()
            
            # Start orchestrator
            await orchestrator.start()
            
            # Simulate complete flow
            incident = Incident(
                service="test-service",
                incident_type="high_cpu",
                severity=SeverityLevel.CRITICAL
            )
            
            # Detection
            await event_bus.publish('incident.detected', {
                'incident': incident.to_dict()
            })
            
            # Wait for processing
            await asyncio.sleep(0.1)
            
            # Verify incident was processed
            assert incident.id in orchestrator.incidents
            
            await orchestrator.stop()
    
    finally:
        await event_bus.stop()


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__])