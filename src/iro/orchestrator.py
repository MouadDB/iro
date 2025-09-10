"""
Main orchestrator for the Incident Response Orchestrator (IRO) system.
Coordinates monitoring, analysis, remediation, and dashboard components.
"""

import asyncio
import logging
from typing import Dict, List, Optional
from datetime import datetime, timezone
import uuid

from .config import Config
from .core.models import Incident, IncidentState, SeverityLevel
from .monitoring.detector import IncidentDetector
from .analysis.analyzer import IncidentAnalyzer
from .remediation.executor import RemediationExecutor
from .dashboard.server import DashboardServer
from .utils.events import EventBus
from .utils.circuit_breaker import CircuitBreaker


class IncidentOrchestrator:
    """
    Main orchestrator that coordinates all IRO components.
    """
    
    def __init__(self, config: Config):
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        # Component initialization
        self.event_bus = EventBus()
        self.detector = IncidentDetector(config.monitoring, self.event_bus)
        self.analyzer = IncidentAnalyzer(config.analysis, self.event_bus)
        self.executor = RemediationExecutor(config.remediation, self.event_bus)
        self.dashboard = DashboardServer(config.dashboard, self.event_bus)
        
        # State management
        self.incidents: Dict[str, Incident] = {}
        self.running = False
        
        # Circuit breakers for external dependencies
        self.circuit_breakers = {
            'kubernetes': CircuitBreaker(
                failure_threshold=5,
                reset_timeout=60,
                name='kubernetes'
            ),
            'gemini': CircuitBreaker(
                failure_threshold=3,
                reset_timeout=30,
                name='gemini'
            )
        }
        
        # Setup event handlers
        self._setup_event_handlers()
        
    async def start(self) -> None:
        """Start the orchestrator and all components."""
        self.logger.info("Starting Incident Response Orchestrator")
        
        try:
            # Start components
            await self.detector.start()
            await self.analyzer.start()
            await self.executor.start()
            await self.dashboard.start()
            
            self.running = True
            self.logger.info("IRO started successfully")
            
            # Start main orchestration loop
            asyncio.create_task(self._orchestration_loop())
            
        except Exception as e:
            self.logger.error(f"Failed to start IRO: {e}")
            await self.stop()
            raise
    
    async def stop(self) -> None:
        """Stop the orchestrator and all components."""
        self.logger.info("Stopping Incident Response Orchestrator")
        self.running = False
        
        # Stop components gracefully
        await asyncio.gather(
            self.detector.stop(),
            self.analyzer.stop(),
            self.executor.stop(),
            self.dashboard.stop(),
            return_exceptions=True
        )
        
        self.logger.info("IRO stopped")
    
    def _setup_event_handlers(self) -> None:
        """Setup event handlers for inter-component communication."""
        
        # Incident detected -> Start analysis
        self.event_bus.subscribe('incident.detected', self._handle_incident_detected)
        
        # Analysis completed -> Start remediation
        self.event_bus.subscribe('analysis.completed', self._handle_analysis_completed)
        
        # Remediation completed -> Update incident
        self.event_bus.subscribe('remediation.completed', self._handle_remediation_completed)
        
        # Health checks
        self.event_bus.subscribe('health.check', self._handle_health_check)
        
    async def _handle_incident_detected(self, event: dict) -> None:
        """Handle new incident detection."""
        try:
            incident_data = event['incident']
            incident = Incident(**incident_data)
            
            self.logger.info(f"New incident detected: {incident.id} - {incident.service}")
            
            # Store incident
            self.incidents[incident.id] = incident
            
            # Update incident state
            incident.state = IncidentState.ANALYZING
            incident.updated_at = datetime.now(timezone.utc)
            
            # Broadcast to dashboard
            await self.event_bus.publish('dashboard.incident_update', {
                'incident': incident.to_dict()
            })
            
            # Trigger analysis with circuit breaker
            if self.circuit_breakers['gemini'].can_execute():
                try:
                    await self.event_bus.publish('analysis.request', {
                        'incident': incident.to_dict()
                    })
                    self.circuit_breakers['gemini'].record_success()
                except Exception as e:
                    self.circuit_breakers['gemini'].record_failure()
                    self.logger.error(f"Analysis request failed: {e}")
                    # Fallback to basic remediation
                    await self._handle_analysis_fallback(incident)
            else:
                self.logger.warning("Gemini circuit breaker open, using fallback analysis")
                await self._handle_analysis_fallback(incident)
                
        except Exception as e:
            self.logger.error(f"Error handling incident detection: {e}")
    
    async def _handle_analysis_completed(self, event: dict) -> None:
        """Handle completed incident analysis."""
        try:
            incident_id = event['incident_id']
            analysis = event['analysis']
            
            incident = self.incidents.get(incident_id)
            if not incident:
                self.logger.warning(f"Unknown incident ID: {incident_id}")
                return
            
            self.logger.info(f"Analysis completed for incident {incident_id}")
            
            # Update incident with analysis
            incident.root_cause = analysis
            incident.state = IncidentState.REMEDIATING
            incident.updated_at = datetime.now(timezone.utc)
            
            # Broadcast update
            await self.event_bus.publish('dashboard.incident_update', {
                'incident': incident.to_dict()
            })
            
            # Check if remediation is needed and safe
            if self._should_remediate(incident, analysis):
                await self.event_bus.publish('remediation.request', {
                    'incident': incident.to_dict(),
                    'analysis': analysis
                })
            else:
                # Mark as resolved if no remediation needed
                incident.state = IncidentState.RESOLVED
                incident.resolved_at = datetime.now(timezone.utc)
                await self.event_bus.publish('dashboard.incident_update', {
                    'incident': incident.to_dict()
                })
                
        except Exception as e:
            self.logger.error(f"Error handling analysis completion: {e}")
    
    async def _handle_remediation_completed(self, event: dict) -> None:
        """Handle completed remediation."""
        try:
            incident_id = event['incident_id']
            success = event['success']
            result = event.get('result', {})
            
            incident = self.incidents.get(incident_id)
            if not incident:
                self.logger.warning(f"Unknown incident ID: {incident_id}")
                return
            
            if success:
                self.logger.info(f"Remediation successful for incident {incident_id}")
                incident.state = IncidentState.RESOLVED
                incident.resolved_at = datetime.now(timezone.utc)
            else:
                self.logger.error(f"Remediation failed for incident {incident_id}")
                incident.state = IncidentState.FAILED
            
            incident.remediation_result = result
            incident.updated_at = datetime.now(timezone.utc)
            
            # Broadcast final update
            await self.event_bus.publish('dashboard.incident_update', {
                'incident': incident.to_dict()
            })
            
        except Exception as e:
            self.logger.error(f"Error handling remediation completion: {e}")
    
    async def _handle_analysis_fallback(self, incident: Incident) -> None:
        """Handle analysis fallback when Gemini is unavailable."""
        self.logger.info(f"Using fallback analysis for incident {incident.id}")
        
        # Simple rule-based analysis
        basic_analysis = {
            'summary': f"Basic analysis for {incident.type} in {incident.service}",
            'confidence': 0.6,
            'causes': [{
                'description': self._get_basic_cause(incident),
                'probability': 0.8,
                'category': 'resource'
            }],
            'recommended_actions': self._get_basic_remediation(incident)
        }
        
        await self._handle_analysis_completed({
            'incident_id': incident.id,
            'analysis': basic_analysis
        })
    
    def _get_basic_cause(self, incident: Incident) -> str:
        """Get basic cause description based on incident type."""
        causes = {
            'high_cpu': 'High CPU usage detected, likely due to increased load or inefficient processing',
            'high_memory': 'High memory usage detected, possible memory leak or insufficient resources',
            'pod_restart': 'Pod restart detected, likely due to health check failure or resource constraints',
            'high_error_rate': 'High error rate detected, possible application or dependency issues',
            'high_latency': 'High latency detected, possible network or performance issues'
        }
        return causes.get(incident.type, f'Issue detected with {incident.type}')
    
    def _get_basic_remediation(self, incident: Incident) -> List[dict]:
        """Get basic remediation actions based on incident type."""
        actions = {
            'high_cpu': [
                {'action': 'scale_replicas', 'priority': 'high', 'params': {'replicas': '+1'}},
                {'action': 'check_cpu_limits', 'priority': 'medium'}
            ],
            'high_memory': [
                {'action': 'restart_pod', 'priority': 'high'},
                {'action': 'check_memory_limits', 'priority': 'medium'}
            ],
            'pod_restart': [
                {'action': 'check_pod_logs', 'priority': 'high'},
                {'action': 'verify_health_checks', 'priority': 'medium'}
            ]
        }
        return actions.get(incident.type, [
            {'action': 'investigate_manually', 'priority': 'medium'}
        ])
    
    def _should_remediate(self, incident: Incident, analysis: dict) -> bool:
        """Determine if remediation should be attempted."""
        # Don't remediate if dry run mode
        if self.config.remediation.dry_run:
            self.logger.info(f"Dry run mode - skipping remediation for {incident.id}")
            return False
        
        # Don't remediate low severity incidents automatically
        if incident.severity in [SeverityLevel.INFO, SeverityLevel.WARNING]:
            return False
        
        # Don't remediate if confidence is too low
        confidence = analysis.get('confidence', 0)
        if confidence < 0.7:
            self.logger.info(f"Analysis confidence too low ({confidence}) for {incident.id}")
            return False
        
        # Check if approval is required
        if self.config.remediation.require_approval:
            self.logger.info(f"Approval required for remediation of {incident.id}")
            return False
        
        return True
    
    async def _handle_health_check(self, event: dict) -> None:
        """Handle health check requests."""
        health_status = {
            'status': 'healthy' if self.running else 'unhealthy',
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'components': {
                'detector': await self.detector.health_check(),
                'analyzer': await self.analyzer.health_check(),
                'executor': await self.executor.health_check(),
                'dashboard': await self.dashboard.health_check()
            },
            'circuit_breakers': {
                name: {
                    'state': cb.state.value,
                    'failure_count': cb.failure_count,
                    'last_failure': cb.last_failure_time.isoformat() if cb.last_failure_time else None
                }
                for name, cb in self.circuit_breakers.items()
            },
            'incidents': {
                'active': len([i for i in self.incidents.values() 
                             if i.state not in [IncidentState.RESOLVED, IncidentState.FAILED]]),
                'total': len(self.incidents)
            }
        }
        
        await self.event_bus.publish('health.response', health_status)
    
    async def _orchestration_loop(self) -> None:
        """Main orchestration loop for periodic tasks."""
        while self.running:
            try:
                await asyncio.sleep(60)  # Run every minute
                
                # Cleanup old resolved incidents
                await self._cleanup_old_incidents()
                
                # Check circuit breaker states
                await self._check_circuit_breakers()
                
                # Emit health check
                await self.event_bus.publish('health.check', {})
                
            except Exception as e:
                self.logger.error(f"Error in orchestration loop: {e}")
    
    async def _cleanup_old_incidents(self) -> None:
        """Clean up old resolved incidents."""
        cutoff_time = datetime.now(timezone.utc)
        cutoff_time = cutoff_time.replace(hour=cutoff_time.hour - 24)  # 24 hours ago
        
        to_remove = []
        for incident_id, incident in self.incidents.items():
            if (incident.state in [IncidentState.RESOLVED, IncidentState.FAILED] and
                incident.updated_at < cutoff_time):
                to_remove.append(incident_id)
        
        for incident_id in to_remove:
            del self.incidents[incident_id]
            
        if to_remove:
            self.logger.info(f"Cleaned up {len(to_remove)} old incidents")
    
    async def _check_circuit_breakers(self) -> None:
        """Check and log circuit breaker states."""
        for name, cb in self.circuit_breakers.items():
            if cb.state.name != 'CLOSED':
                self.logger.warning(f"Circuit breaker '{name}' is {cb.state.name}")