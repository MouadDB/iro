"""
Automated remediation executor for Kubernetes incidents.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

from kubernetes import client
from kubernetes.client.rest import ApiException

from ..config import RemediationConfig
from ..core.models import (
    Incident, RemediationPlan, RemediationStep, RemediationStrategy, 
    HealthStatus
)
from ..utils.events import EventBus
from ..utils.k8s_client import K8sClientManager


class RemediationExecutor:
    """
    Executes automated remediation actions for Kubernetes incidents.
    """
    
    def __init__(self, config: RemediationConfig, event_bus: EventBus):
        self.config = config
        self.event_bus = event_bus
        self.logger = logging.getLogger(__name__)
        
        # Kubernetes client
        self.k8s_manager = K8sClientManager()
        self.v1_core = None
        self.v1_apps = None
        
        # State management
        self.running = False
        self.active_executions: Dict[str, RemediationPlan] = {}
        
        # Execution queue
        self.execution_queue = asyncio.Queue(maxsize=self.config.max_concurrent)
        self.execution_tasks: List[asyncio.Task] = []
        
        # Action handlers
        self.action_handlers = self._register_action_handlers()
        
        # Setup event handlers
        self.event_bus.subscribe('remediation.request', self._handle_remediation_request)
    
    async def start(self) -> None:
        """Start the remediation executor."""
        self.logger.info("Starting remediation executor")
        
        try:
            # Initialize Kubernetes clients
            await self.k8s_manager.initialize()
            self.v1_core = self.k8s_manager.core_v1
            self.v1_apps = self.k8s_manager.apps_v1
            
            self.running = True
            
            # Start execution workers
            for i in range(self.config.max_concurrent):
                task = asyncio.create_task(self._execution_worker(i))
                self.execution_tasks.append(task)
            
            self.logger.info(f"Remediation executor started with {self.config.max_concurrent} workers")
            
        except Exception as e:
            self.logger.error(f"Failed to start remediation executor: {e}")
            raise
    
    async def stop(self) -> None:
        """Stop the remediation executor."""
        self.logger.info("Stopping remediation executor")
        self.running = False
        
        # Cancel all execution tasks
        for task in self.execution_tasks:
            task.cancel()
        
        # Wait for tasks to complete
        if self.execution_tasks:
            await asyncio.gather(*self.execution_tasks, return_exceptions=True)
        
        self.logger.info("Remediation executor stopped")
    
    async def health_check(self) -> HealthStatus:
        """Perform health check."""
        try:
            # Test Kubernetes connectivity
            await asyncio.to_thread(self.v1_core.list_namespace)
            
            return HealthStatus(
                healthy=True,
                message="Executor running normally",
                details={
                    'active_executions': len(self.active_executions),
                    'queue_size': self.execution_queue.qsize(),
                    'workers': len(self.execution_tasks)
                }
            )
        except Exception as e:
            return HealthStatus(
                healthy=False,
                message=f"Health check failed: {e}",
                details={'error': str(e)}
            )
    
    async def _handle_remediation_request(self, event: Dict[str, Any]) -> None:
        """Handle remediation requests."""
        try:
            incident_data = event['incident']
            analysis = event['analysis']
            
            incident = Incident.from_dict(incident_data)
            
            self.logger.info(f"Creating remediation plan for incident {incident.id}")
            
            # Create remediation plan
            plan = await self._create_remediation_plan(incident, analysis)
            
            if not plan.steps:
                self.logger.warning(f"No remediation steps created for incident {incident.id}")
                return
            
            # Queue for execution
            try:
                await self.execution_queue.put((incident, plan))
                self.logger.info(f"Queued remediation plan {plan.id} for execution")
            except asyncio.QueueFull:
                self.logger.warning(f"Execution queue full, skipping remediation for {incident.id}")
                
        except Exception as e:
            self.logger.error(f"Error handling remediation request: {e}")
    
    async def _create_remediation_plan(
        self, 
        incident: Incident, 
        analysis: Dict[str, Any]
    ) -> RemediationPlan:
        """Create a remediation plan based on incident and analysis."""
        
        plan = RemediationPlan(
            incident_id=incident.id,
            strategy=RemediationStrategy.IMMEDIATE
        )
        
        # Get recommended actions from analysis
        recommended_actions = analysis.get('recommended_actions', [])
        
        if not recommended_actions:
            self.logger.warning(f"No recommended actions in analysis for {incident.id}")
            return plan
        
        # Convert analysis actions to remediation steps
        for i, action in enumerate(recommended_actions):
            step = RemediationStep(
                name=action.get('action', f'step_{i}'),
                description=f"Execute {action.get('action', 'unknown action')}",
                action_type=action.get('action', 'unknown'),
                parameters=action.get('parameters', {}),
                timeout_seconds=self._parse_time_estimate(action.get('estimated_time', '5m')),
                continue_on_error=(action.get('priority') != 'high')
            )
            plan.steps.append(step)
        
        # Calculate risk score and metadata
        plan.risk_score = self._calculate_risk_score(incident, analysis)
        plan.estimated_duration = sum(step.timeout_seconds for step in plan.steps)
        plan.approval_required = self._should_require_approval(plan, incident)
        
        return plan
    
    async def _execution_worker(self, worker_id: int) -> None:
        """Worker that executes remediation plans."""
        self.logger.info(f"Remediation worker {worker_id} started")
        
        while self.running:
            try:
                # Get next execution from queue
                incident, plan = await asyncio.wait_for(
                    self.execution_queue.get(), 
                    timeout=1.0
                )
                
                await self._execute_remediation_plan(incident, plan)
                
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                self.logger.error(f"Error in remediation worker {worker_id}: {e}")
        
        self.logger.info(f"Remediation worker {worker_id} stopped")
    
    async def _execute_remediation_plan(
        self, 
        incident: Incident, 
        plan: RemediationPlan
    ) -> None:
        """Execute a complete remediation plan."""
        
        plan.execution_state = "executing"
        plan.started_at = datetime.now(timezone.utc)
        self.active_executions[plan.id] = plan
        
        self.logger.info(f"Starting execution of plan {plan.id} for incident {incident.id}")
        
        success = True
        error_message = None
        
        try:
            # Check if dry run mode
            if self.config.dry_run:
                await self._dry_run_execution(plan)
                self.logger.info(f"Dry run completed for plan {plan.id}")
            else:
                # Execute each step
                for step in plan.steps:
                    step_success = await self._execute_step(incident, step)
                    
                    if not step_success and not step.continue_on_error:
                        success = False
                        error_message = f"Step '{step.name}' failed: {step.error_message}"
                        break
        
        except Exception as e:
            success = False
            error_message = str(e)
            self.logger.error(f"Execution failed for plan {plan.id}: {e}")
        
        finally:
            # Update plan status
            plan.execution_state = "completed" if success else "failed"
            plan.completed_at = datetime.now(timezone.utc)
            plan.success = success
            
            # Remove from active executions
            self.active_executions.pop(plan.id, None)
            
            # Publish completion event
            await self.event_bus.publish('remediation.completed', {
                'incident_id': incident.id,
                'plan_id': plan.id,
                'success': success,
                'error': error_message,
                'result': {
                    'execution_state': plan.execution_state,
                    'steps_completed': len([s for s in plan.steps if s.success]),
                    'total_steps': len(plan.steps),
                    'duration': (plan.completed_at - plan.started_at).total_seconds() if plan.completed_at else 0
                }
            })
            
            self.logger.info(
                f"Remediation plan {plan.id} {'completed successfully' if success else 'failed'}"
            )
    
    async def _execute_step(self, incident: Incident, step: RemediationStep) -> bool:
        """Execute a single remediation step."""
        
        step.started_at = datetime.now(timezone.utc)
        
        self.logger.info(f"Executing step '{step.name}' ({step.action_type})")
        
        try:
            # Get action handler
            handler = self.action_handlers.get(step.action_type)
            if not handler:
                raise ValueError(f"Unknown action type: {step.action_type}")
            
            # Execute with timeout
            result = await asyncio.wait_for(
                handler(incident, step),
                timeout=step.timeout_seconds
            )
            
            step.success = True
            step.output = result or "Action completed successfully"
            
            self.logger.info(f"Step '{step.name}' completed successfully")
            return True
            
        except asyncio.TimeoutError:
            step.success = False
            step.error_message = f"Step timed out after {step.timeout_seconds} seconds"
            self.logger.error(f"Step '{step.name}' timed out")
            return False
            
        except Exception as e:
            step.success = False
            step.error_message = str(e)
            self.logger.error(f"Step '{step.name}' failed: {e}")
            return False
            
        finally:
            step.completed_at = datetime.now(timezone.utc)
    
    async def _dry_run_execution(self, plan: RemediationPlan) -> None:
        """Perform dry run of remediation plan."""
        for step in plan.steps:
            step.started_at = datetime.now(timezone.utc)
            step.success = True
            step.output = f"DRY RUN: Would execute {step.action_type} with parameters {step.parameters}"
            step.completed_at = datetime.now(timezone.utc)
            
            self.logger.info(f"DRY RUN: {step.output}")
            await asyncio.sleep(0.1)  # Simulate execution time
    
    def _register_action_handlers(self) -> Dict[str, callable]:
        """Register action handlers for different remediation actions."""
        return {
            'scale_replicas': self._handle_scale_replicas,
            'restart_pod': self._handle_restart_pod,
            'check_pod_logs': self._handle_check_pod_logs,
            'check_cpu_limits': self._handle_check_cpu_limits,
            'check_memory_limits': self._handle_check_memory_limits,
            'verify_health_checks': self._handle_verify_health_checks,
            'investigate_manually': self._handle_investigate_manually
        }
    
    async def _handle_scale_replicas(self, incident: Incident, step: RemediationStep) -> str:
        """Handle scaling deployment replicas."""
        try:
            replicas = step.parameters.get('replicas', 2)
            
            # Get current deployment
            deployment = await asyncio.to_thread(
                self.v1_apps.read_namespaced_deployment,
                name=incident.service,
                namespace=incident.namespace
            )
            
            current_replicas = deployment.spec.replicas
            
            # Update replicas
            deployment.spec.replicas = replicas
            
            await asyncio.to_thread(
                self.v1_apps.patch_namespaced_deployment,
                name=incident.service,
                namespace=incident.namespace,
                body=deployment
            )
            
            return f"Scaled {incident.service} from {current_replicas} to {replicas} replicas"
            
        except ApiException as e:
            raise Exception(f"Failed to scale deployment: {e}")
    
    async def _handle_restart_pod(self, incident: Incident, step: RemediationStep) -> str:
        """Handle restarting pods."""
        try:
            # Get pods for the service
            pods = await asyncio.to_thread(
                self.v1_core.list_namespaced_pod,
                namespace=incident.namespace,
                label_selector=f"app={incident.service}"
            )
            
            if not pods.items:
                raise Exception(f"No pods found for service {incident.service}")
            
            # Delete the first pod to trigger restart
            pod_to_restart = pods.items[0]
            
            await asyncio.to_thread(
                self.v1_core.delete_namespaced_pod,
                name=pod_to_restart.metadata.name,
                namespace=incident.namespace
            )
            
            return f"Restarted pod {pod_to_restart.metadata.name}"
            
        except ApiException as e:
            raise Exception(f"Failed to restart pod: {e}")
    
    async def _handle_check_pod_logs(self, incident: Incident, step: RemediationStep) -> str:
        """Handle checking pod logs."""
        try:
            # Get pods for the service
            pods = await asyncio.to_thread(
                self.v1_core.list_namespaced_pod,
                namespace=incident.namespace,
                label_selector=f"app={incident.service}"
            )
            
            if not pods.items:
                return f"No pods found for service {incident.service}"
            
            # Get logs from the first pod
            pod = pods.items[0]
            
            logs = await asyncio.to_thread(
                self.v1_core.read_namespaced_pod_log,
                name=pod.metadata.name,
                namespace=incident.namespace,
                tail_lines=50
            )
            
            # Look for error patterns
            error_patterns = ['ERROR', 'Exception', 'FATAL', 'OutOfMemoryError']
            errors_found = []
            
            for line in logs.split('\n'):
                for pattern in error_patterns:
                    if pattern in line:
                        errors_found.append(line.strip())
                        break
            
            result = f"Checked logs for {pod.metadata.name}"
            if errors_found:
                result += f". Found {len(errors_found)} error lines."
            else:
                result += ". No obvious errors found."
            
            return result
            
        except ApiException as e:
            raise Exception(f"Failed to check pod logs: {e}")
    
    async def _handle_check_cpu_limits(self, incident: Incident, step: RemediationStep) -> str:
        """Handle checking CPU limits."""
        try:
            # Get deployment
            deployment = await asyncio.to_thread(
                self.v1_apps.read_namespaced_deployment,
                name=incident.service,
                namespace=incident.namespace
            )
            
            containers = deployment.spec.template.spec.containers
            
            results = []
            for container in containers:
                resources = container.resources
                cpu_limit = None
                cpu_request = None
                
                if resources.limits:
                    cpu_limit = resources.limits.get('cpu')
                if resources.requests:
                    cpu_request = resources.requests.get('cpu')
                
                results.append(f"Container {container.name}: "
                             f"CPU limit={cpu_limit or 'none'}, "
                             f"CPU request={cpu_request or 'none'}")
            
            return f"CPU limits check completed. {'; '.join(results)}"
            
        except ApiException as e:
            raise Exception(f"Failed to check CPU limits: {e}")
    
    async def _handle_check_memory_limits(self, incident: Incident, step: RemediationStep) -> str:
        """Handle checking memory limits."""
        try:
            # Get deployment
            deployment = await asyncio.to_thread(
                self.v1_apps.read_namespaced_deployment,
                name=incident.service,
                namespace=incident.namespace
            )
            
            containers = deployment.spec.template.spec.containers
            
            results = []
            for container in containers:
                resources = container.resources
                memory_limit = None
                memory_request = None
                
                if resources.limits:
                    memory_limit = resources.limits.get('memory')
                if resources.requests:
                    memory_request = resources.requests.get('memory')
                
                results.append(f"Container {container.name}: "
                             f"Memory limit={memory_limit or 'none'}, "
                             f"Memory request={memory_request or 'none'}")
            
            return f"Memory limits check completed. {'; '.join(results)}"
            
        except ApiException as e:
            raise Exception(f"Failed to check memory limits: {e}")
    
    async def _handle_verify_health_checks(self, incident: Incident, step: RemediationStep) -> str:
        """Handle verifying health checks."""
        try:
            # Get deployment
            deployment = await asyncio.to_thread(
                self.v1_apps.read_namespaced_deployment,
                name=incident.service,
                namespace=incident.namespace
            )
            
            containers = deployment.spec.template.spec.containers
            
            results = []
            for container in containers:
                liveness_probe = container.liveness_probe
                readiness_probe = container.readiness_probe
                
                status = f"Container {container.name}: "
                
                if liveness_probe:
                    status += f"Liveness probe configured, "
                else:
                    status += "No liveness probe, "
                
                if readiness_probe:
                    status += "Readiness probe configured"
                else:
                    status += "No readiness probe"
                
                results.append(status)
            
            return f"Health checks verification completed. {'; '.join(results)}"
            
        except ApiException as e:
            raise Exception(f"Failed to verify health checks: {e}")
    
    async def _handle_investigate_manually(self, incident: Incident, step: RemediationStep) -> str:
        """Handle manual investigation placeholder."""
        return (f"Manual investigation required for {incident.service}. "
                f"Incident type: {incident.type}, Severity: {incident.severity.value}")
    
    def _calculate_risk_score(self, incident: Incident, analysis: Dict[str, Any]) -> float:
        """Calculate risk score for remediation plan."""
        score = 0.0
        
        # Service criticality
        critical_services = {'userservice': 0.9, 'ledgerwriter': 0.9, 'balancereader': 0.7}
        service_criticality = critical_services.get(incident.service, 0.5)
        score += service_criticality * 0.4
        
        # Incident severity
        severity_weights = {
            'emergency': 1.0, 'critical': 0.8, 'error': 0.6, 'warning': 0.4, 'info': 0.2
        }
        severity_score = severity_weights.get(incident.severity.value, 0.5)
        score += severity_score * 0.3
        
        # Analysis confidence (lower confidence = higher risk)
        confidence = analysis.get('confidence', 0.5)
        confidence_risk = 1.0 - confidence
        score += confidence_risk * 0.3
        
        return min(score, 1.0)
    
    def _should_require_approval(self, plan: RemediationPlan, incident: Incident) -> bool:
        """Determine if approval is required for this plan."""
        if self.config.require_approval:
            return True
        
        if plan.risk_score > self.config.max_blast_radius:
            return True
        
        # Always require approval for production during business hours
        current_hour = datetime.now().hour
        if 9 <= current_hour <= 17:  # Business hours
            return True
        
        return False
    
    def _parse_time_estimate(self, time_str: str) -> int:
        """Parse time estimate string to seconds."""
        time_str = time_str.lower().strip()
        
        if time_str.endswith('s'):
            return int(time_str[:-1])
        elif time_str.endswith('m'):
            return int(time_str[:-1]) * 60
        elif time_str.endswith('h'):
            return int(time_str[:-1]) * 3600
        else:
            return 300  # Default 5 minutes