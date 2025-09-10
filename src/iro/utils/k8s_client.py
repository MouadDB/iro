"""
Kubernetes client manager for IRO system.
"""

import asyncio
import logging
import os
from typing import Optional

from kubernetes import client, config
from kubernetes.client.rest import ApiException


class K8sClientManager:
    """
    Manages Kubernetes client connections and provides high-level operations.
    """
    
    def __init__(self, kubeconfig_path: Optional[str] = None):
        self.kubeconfig_path = kubeconfig_path
        self.logger = logging.getLogger(__name__)
        
        # Client instances
        self.core_v1: Optional[client.CoreV1Api] = None
        self.apps_v1: Optional[client.AppsV1Api] = None
        self.metrics_v1: Optional[client.CustomObjectsApi] = None
        
        # Connection status
        self.connected = False
    
    async def initialize(self) -> None:
        """Initialize Kubernetes clients."""
        try:
            # Load Kubernetes configuration
            await self._load_config()
            
            # Create client instances
            self.core_v1 = client.CoreV1Api()
            self.apps_v1 = client.AppsV1Api()
            self.metrics_v1 = client.CustomObjectsApi()
            
            # Test connection
            await self._test_connection()
            
            self.connected = True
            self.logger.info("Kubernetes clients initialized successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize Kubernetes clients: {e}")
            raise
    
    async def _load_config(self) -> None:
        """Load Kubernetes configuration."""
        try:
            # Try in-cluster config first
            config.load_incluster_config()
            self.logger.info("Loaded in-cluster Kubernetes configuration")
        except config.ConfigException:
            try:
                # Fall back to kubeconfig file
                config_file = self.kubeconfig_path or os.path.expanduser("~/.kube/config")
                await asyncio.to_thread(config.load_kube_config, config_file=config_file)
                self.logger.info(f"Loaded Kubernetes configuration from {config_file}")
            except Exception as e:
                raise Exception(f"Failed to load Kubernetes configuration: {e}")
    
    async def _test_connection(self) -> None:
        """Test Kubernetes connection."""
        try:
            # Simple API call to test connection
            await asyncio.to_thread(self.core_v1.get_api_versions)
            self.logger.debug("Kubernetes connection test successful")
        except Exception as e:
            raise Exception(f"Kubernetes connection test failed: {e}")
    
    async def get_pod_metrics(self, name: str, namespace: str) -> Optional[dict]:
        """Get metrics for a specific pod."""
        try:
            metrics = await asyncio.to_thread(
                self.metrics_v1.get_namespaced_custom_object,
                group="metrics.k8s.io",
                version="v1beta1",
                namespace=namespace,
                plural="pods",
                name=name
            )
            return metrics
        except ApiException as e:
            if e.status == 404:
                self.logger.debug(f"Metrics not found for pod {name}")
                return None
            else:
                self.logger.error(f"Failed to get pod metrics: {e}")
                raise
    
    async def get_node_metrics(self, name: str) -> Optional[dict]:
        """Get metrics for a specific node."""
        try:
            metrics = await asyncio.to_thread(
                self.metrics_v1.get_cluster_custom_object,
                group="metrics.k8s.io",
                version="v1beta1",
                plural="nodes",
                name=name
            )
            return metrics
        except ApiException as e:
            if e.status == 404:
                self.logger.debug(f"Metrics not found for node {name}")
                return None
            else:
                self.logger.error(f"Failed to get node metrics: {e}")
                raise
    
    async def get_pods_by_service(self, service_name: str, namespace: str = "default") -> list:
        """Get all pods for a service."""
        try:
            pods = await asyncio.to_thread(
                self.core_v1.list_namespaced_pod,
                namespace=namespace,
                label_selector=f"app={service_name}"
            )
            return pods.items
        except ApiException as e:
            self.logger.error(f"Failed to get pods for service {service_name}: {e}")
            raise
    
    async def get_deployment(self, name: str, namespace: str = "default") -> Optional[client.V1Deployment]:
        """Get a deployment by name."""
        try:
            deployment = await asyncio.to_thread(
                self.apps_v1.read_namespaced_deployment,
                name=name,
                namespace=namespace
            )
            return deployment
        except ApiException as e:
            if e.status == 404:
                self.logger.debug(f"Deployment {name} not found")
                return None
            else:
                self.logger.error(f"Failed to get deployment {name}: {e}")
                raise
    
    async def scale_deployment(self, name: str, replicas: int, namespace: str = "default") -> bool:
        """Scale a deployment to specified replicas."""
        try:
            # Get current deployment
            deployment = await self.get_deployment(name, namespace)
            if not deployment:
                raise Exception(f"Deployment {name} not found")
            
            # Update replicas
            deployment.spec.replicas = replicas
            
            # Apply update
            await asyncio.to_thread(
                self.apps_v1.patch_namespaced_deployment,
                name=name,
                namespace=namespace,
                body=deployment
            )
            
            self.logger.info(f"Scaled deployment {name} to {replicas} replicas")
            return True
            
        except ApiException as e:
            self.logger.error(f"Failed to scale deployment {name}: {e}")
            raise
    
    async def delete_pod(self, name: str, namespace: str = "default", grace_period: int = 30) -> bool:
        """Delete a pod."""
        try:
            await asyncio.to_thread(
                self.core_v1.delete_namespaced_pod,
                name=name,
                namespace=namespace,
                grace_period_seconds=grace_period
            )
            
            self.logger.info(f"Deleted pod {name}")
            return True
            
        except ApiException as e:
            if e.status == 404:
                self.logger.debug(f"Pod {name} not found")
                return True  # Already deleted
            else:
                self.logger.error(f"Failed to delete pod {name}: {e}")
                raise
    
    async def get_pod_logs(
        self, 
        name: str, 
        namespace: str = "default", 
        tail_lines: int = 100,
        since_seconds: Optional[int] = None
    ) -> str:
        """Get logs from a pod."""
        try:
            logs = await asyncio.to_thread(
                self.core_v1.read_namespaced_pod_log,
                name=name,
                namespace=namespace,
                tail_lines=tail_lines,
                since_seconds=since_seconds
            )
            return logs
        except ApiException as e:
            self.logger.error(f"Failed to get logs for pod {name}: {e}")
            raise
    
    async def wait_for_pod_ready(
        self, 
        name: str, 
        namespace: str = "default", 
        timeout: int = 300
    ) -> bool:
        """Wait for a pod to become ready."""
        start_time = asyncio.get_event_loop().time()
        
        while asyncio.get_event_loop().time() - start_time < timeout:
            try:
                pod = await asyncio.to_thread(
                    self.core_v1.read_namespaced_pod,
                    name=name,
                    namespace=namespace
                )
                
                if pod.status.phase == "Running":
                    # Check if all containers are ready
                    if pod.status.conditions:
                        for condition in pod.status.conditions:
                            if condition.type == "Ready" and condition.status == "True":
                                return True
                
                await asyncio.sleep(5)
                
            except ApiException as e:
                if e.status == 404:
                    self.logger.debug(f"Pod {name} not found, continuing to wait")
                    await asyncio.sleep(5)
                else:
                    raise
        
        return False
    
    async def check_service_health(self, service_name: str, namespace: str = "default") -> dict:
        """Check overall health of a service."""
        try:
            pods = await self.get_pods_by_service(service_name, namespace)
            
            if not pods:
                return {
                    'healthy': False,
                    'reason': 'No pods found',
                    'pod_count': 0,
                    'ready_pods': 0
                }
            
            ready_pods = 0
            total_pods = len(pods)
            
            for pod in pods:
                if pod.status.phase == "Running":
                    if pod.status.conditions:
                        for condition in pod.status.conditions:
                            if condition.type == "Ready" and condition.status == "True":
                                ready_pods += 1
                                break
            
            health_ratio = ready_pods / total_pods if total_pods > 0 else 0
            healthy = health_ratio >= 0.5  # At least 50% of pods must be ready
            
            return {
                'healthy': healthy,
                'reason': f'{ready_pods}/{total_pods} pods ready',
                'pod_count': total_pods,
                'ready_pods': ready_pods,
                'health_ratio': health_ratio
            }
            
        except Exception as e:
            return {
                'healthy': False,
                'reason': f'Health check failed: {e}',
                'pod_count': 0,
                'ready_pods': 0
            }
    
    def is_connected(self) -> bool:
        """Check if clients are connected."""
        return self.connected and self.core_v1 is not None


class K8sResourceManager:
    """
    Higher-level Kubernetes resource management utilities.
    """
    
    def __init__(self, client_manager: K8sClientManager):
        self.client_manager = client_manager
        self.logger = logging.getLogger(__name__)
    
    async def get_resource_usage(self, namespace: str = "default") -> dict:
        """Get resource usage summary for a namespace."""
        try:
            # Get all pods in namespace
            pods = await asyncio.to_thread(
                self.client_manager.core_v1.list_namespaced_pod,
                namespace=namespace
            )
            
            total_cpu_requests = 0
            total_memory_requests = 0
            total_cpu_limits = 0
            total_memory_limits = 0
            
            for pod in pods.items:
                if pod.spec.containers:
                    for container in pod.spec.containers:
                        if container.resources:
                            # Parse CPU requests/limits
                            if container.resources.requests:
                                cpu_req = container.resources.requests.get('cpu', '0')
                                total_cpu_requests += self._parse_cpu(cpu_req)
                                
                                mem_req = container.resources.requests.get('memory', '0')
                                total_memory_requests += self._parse_memory(mem_req)
                            
                            if container.resources.limits:
                                cpu_limit = container.resources.limits.get('cpu', '0')
                                total_cpu_limits += self._parse_cpu(cpu_limit)
                                
                                mem_limit = container.resources.limits.get('memory', '0')
                                total_memory_limits += self._parse_memory(mem_limit)
            
            return {
                'namespace': namespace,
                'pod_count': len(pods.items),
                'cpu_requests': total_cpu_requests,
                'memory_requests': total_memory_requests,
                'cpu_limits': total_cpu_limits,
                'memory_limits': total_memory_limits
            }
            
        except Exception as e:
            self.logger.error(f"Failed to get resource usage: {e}")
            raise
    
    def _parse_cpu(self, cpu_str: str) -> float:
        """Parse CPU string to cores."""
        if not cpu_str or cpu_str == '0':
            return 0.0
        
        cpu_str = cpu_str.lower()
        if cpu_str.endswith('m'):
            return float(cpu_str[:-1]) / 1000  # millicores to cores
        else:
            return float(cpu_str)
    
    def _parse_memory(self, memory_str: str) -> int:
        """Parse memory string to bytes."""
        if not memory_str or memory_str == '0':
            return 0
        
        memory_str = memory_str.upper()
        multipliers = {
            'KI': 1024,
            'MI': 1024 ** 2,
            'GI': 1024 ** 3,
            'K': 1000,
            'M': 1000 ** 2,
            'G': 1000 ** 3
        }
        
        for suffix, multiplier in multipliers.items():
            if memory_str.endswith(suffix):
                return int(float(memory_str[:-len(suffix)]) * multiplier)
        
        return int(memory_str)  # Assume bytes if no suffix