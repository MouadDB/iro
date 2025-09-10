"""
AI-powered incident analysis using Google Gemini.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

import google.generativeai as genai
from google.generativeai import GenerativeModel

from ..config import AnalysisConfig
from ..core.models import Incident, HealthStatus
from ..utils.events import EventBus


class IncidentAnalyzer:
    """
    Analyzes incidents using Google Gemini AI to provide root cause analysis
    and remediation recommendations.
    """
    
    def __init__(self, config: AnalysisConfig, event_bus: EventBus):
        self.config = config
        self.event_bus = event_bus
        self.logger = logging.getLogger(__name__)
        
        # Initialize Gemini client
        self.model: Optional[GenerativeModel] = None
        self.running = False
        
        # Analysis cache
        self.analysis_cache: Dict[str, Dict[str, Any]] = {}
        
        # Knowledge base for Bank of Anthos services
        self.service_knowledge = self._build_service_knowledge()
        
        # Setup event handlers
        self.event_bus.subscribe('analysis.request', self._handle_analysis_request)
    
    async def start(self) -> None:
        """Start the incident analyzer."""
        self.logger.info("Starting incident analyzer")
        
        try:
            # Initialize Gemini
            await self._initialize_gemini()
            self.running = True
            self.logger.info("Incident analyzer started")
            
        except Exception as e:
            self.logger.error(f"Failed to start incident analyzer: {e}")
            raise
    
    async def stop(self) -> None:
        """Stop the incident analyzer."""
        self.logger.info("Stopping incident analyzer")
        self.running = False
        self.logger.info("Incident analyzer stopped")
    
    async def health_check(self) -> HealthStatus:
        """Perform health check."""
        try:
            if not self.model:
                return HealthStatus(
                    healthy=False,
                    message="Gemini model not initialized"
                )
            
            # Test with a simple query
            test_prompt = "Respond with 'OK' if you can process this request."
            response = await asyncio.to_thread(
                self.model.generate_content,
                test_prompt
            )
            
            if "OK" in response.text:
                return HealthStatus(
                    healthy=True,
                    message="Analyzer running normally",
                    details={
                        'model': self.config.model_name,
                        'cache_size': len(self.analysis_cache)
                    }
                )
            else:
                return HealthStatus(
                    healthy=False,
                    message="Gemini model test failed"
                )
                
        except Exception as e:
            return HealthStatus(
                healthy=False,
                message=f"Health check failed: {e}",
                details={'error': str(e)}
            )
    
    async def _initialize_gemini(self) -> None:
        """Initialize the Gemini AI model."""
        try:
            # Configure Gemini
            genai.configure()  # Uses GOOGLE_API_KEY environment variable
            
            # Create model with configuration
            self.model = GenerativeModel(
                model_name=self.config.model_name,
                generation_config={
                    'temperature': self.config.temperature,
                    'max_output_tokens': self.config.max_tokens,
                    'response_mime_type': 'application/json'
                },
                system_instruction=self._get_system_instruction()
            )
            
            self.logger.info(f"Initialized Gemini model: {self.config.model_name}")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize Gemini: {e}")
            raise
    
    def _get_system_instruction(self) -> str:
        """Get the system instruction for Gemini."""
        return """You are an expert Kubernetes and distributed systems engineer specializing in the Bank of Anthos application. 

Your role is to analyze incidents, identify root causes, and recommend remediation strategies.

Bank of Anthos Architecture:
- Frontend: React-based web UI that calls all backend services
- User Service: Manages user accounts and authentication (critical service)
- Contacts Service: Stores user contacts for transfers
- Balance Reader: Reads account balances from ledger (read-heavy)
- Ledger Writer: Writes transactions to ledger (write-heavy, critical)
- Transaction History: Retrieves transaction history

Service Dependencies:
- Frontend → All backend services
- Balance Reader → Ledger database
- Ledger Writer → Ledger database
- Transaction History → Ledger database
- All services → User Service for authentication

Common Issues:
1. Memory leaks in Java services (especially Balance Reader)
2. Connection pool exhaustion to databases
3. CPU spikes during batch processing
4. Cascading failures when User Service is down
5. Ledger database lock contention

Always respond in valid JSON format with the structure specified in the prompt."""
    
    async def _handle_analysis_request(self, event: Dict[str, Any]) -> None:
        """Handle incident analysis requests."""
        try:
            incident_data = event['incident']
            incident = Incident.from_dict(incident_data)
            
            self.logger.info(f"Starting analysis for incident {incident.id}")
            
            # Check cache first
            cache_key = self._get_cache_key(incident)
            if cache_key in self.analysis_cache:
                cached_analysis = self.analysis_cache[cache_key]
                self.logger.info(f"Using cached analysis for {incident.id}")
                
                await self.event_bus.publish('analysis.completed', {
                    'incident_id': incident.id,
                    'analysis': cached_analysis
                })
                return
            
            # Perform analysis
            analysis = await self._analyze_incident(incident)
            
            # Cache result
            self.analysis_cache[cache_key] = analysis
            
            # Clean old cache entries
            self._cleanup_cache()
            
            # Publish result
            await self.event_bus.publish('analysis.completed', {
                'incident_id': incident.id,
                'analysis': analysis
            })
            
            self.logger.info(f"Analysis completed for incident {incident.id}")
            
        except Exception as e:
            self.logger.error(f"Error in analysis request: {e}")
    
    async def _analyze_incident(self, incident: Incident) -> Dict[str, Any]:
        """Perform detailed incident analysis using Gemini."""
        prompt = self._build_analysis_prompt(incident)
        
        try:
            # Make async call to Gemini
            response = await asyncio.wait_for(
                asyncio.to_thread(self.model.generate_content, prompt),
                timeout=self.config.timeout_seconds
            )
            
            # Parse JSON response
            analysis_json = response.text.strip()
            analysis = json.loads(analysis_json)
            
            # Add metadata
            analysis['timestamp'] = datetime.now(timezone.utc).isoformat()
            analysis['model_version'] = self.config.model_name
            analysis['incident_id'] = incident.id
            
            return analysis
            
        except asyncio.TimeoutError:
            self.logger.error(f"Analysis timeout for incident {incident.id}")
            return self._get_fallback_analysis(incident)
        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse Gemini response: {e}")
            return self._get_fallback_analysis(incident)
        except Exception as e:
            self.logger.error(f"Analysis failed for incident {incident.id}: {e}")
            return self._get_fallback_analysis(incident)
    
    def _build_analysis_prompt(self, incident: Incident) -> str:
        """Build the analysis prompt for Gemini."""
        service_info = self.service_knowledge.get(incident.service, {})
        
        prompt = f"""Analyze this Kubernetes incident and provide root cause analysis.

Incident Details:
- ID: {incident.id}
- Service: {incident.service}
- Type: {incident.type}
- Severity: {incident.severity.value}
- Description: {incident.description}
- Namespace: {incident.namespace}
- Timestamp: {incident.created_at.isoformat()}

Current Metrics:
{json.dumps(incident.metrics, indent=2)}

Service Information:
- Function: {service_info.get('function', 'Unknown')}
- Technology: {service_info.get('technology', 'Unknown')}
- Dependencies: {', '.join(service_info.get('dependencies', []))}
- Common Issues: {', '.join(service_info.get('common_issues', []))}

Analyze this incident considering:
1. The Bank of Anthos architecture and service dependencies
2. The specific service characteristics and common failure patterns
3. Current system metrics and thresholds
4. Potential cascade effects on dependent services

Provide your analysis in the following JSON format:
{{
  "summary": "Brief summary of the root cause",
  "confidence": 0.85,
  "causes": [
    {{
      "description": "Detailed description of this potential cause",
      "probability": 0.9,
      "evidence": ["Evidence point 1", "Evidence point 2"],
      "category": "resource|configuration|code|infrastructure"
    }}
  ],
  "evidence": [
    {{
      "type": "metric|log|trace|historical",
      "source": "Source system",
      "data": "Specific evidence data",
      "confidence": 0.95
    }}
  ],
  "impact_analysis": {{
    "affected_services": ["service1", "service2"],
    "user_impact": "Description of user impact",
    "business_impact": "Revenue/transaction impact",
    "cascade_risk": 0.7
  }},
  "recommended_actions": [
    {{
      "action": "Specific remediation action",
      "priority": "high|medium|low",
      "estimated_time": "5m",
      "risk": "low|medium|high",
      "parameters": {{}}
    }}
  ],
  "prevention_strategies": ["Strategy 1", "Strategy 2"]
}}"""
        
        return prompt
    
    def _get_fallback_analysis(self, incident: Incident) -> Dict[str, Any]:
        """Get fallback analysis when Gemini is unavailable."""
        service_info = self.service_knowledge.get(incident.service, {})
        
        # Rule-based analysis based on incident type
        analysis = {
            'summary': f'Basic analysis for {incident.type} in {incident.service}',
            'confidence': 0.6,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'model_version': 'fallback',
            'incident_id': incident.id,
            'causes': [{
                'description': self._get_fallback_cause(incident),
                'probability': 0.8,
                'evidence': [f'Incident type: {incident.type}', f'Service: {incident.service}'],
                'category': 'resource'
            }],
            'evidence': [{
                'type': 'metric',
                'source': 'monitoring',
                'data': json.dumps(incident.metrics),
                'confidence': 0.7
            }],
            'impact_analysis': {
                'affected_services': self._get_affected_services(incident.service),
                'user_impact': 'Potential service degradation',
                'business_impact': 'Transaction processing may be affected',
                'cascade_risk': 0.5
            },
            'recommended_actions': self._get_fallback_actions(incident),
            'prevention_strategies': service_info.get('prevention_strategies', [
                'Monitor resource usage', 'Implement circuit breakers'
            ])
        }
        
        return analysis
    
    def _get_fallback_cause(self, incident: Incident) -> str:
        """Get fallback cause based on incident type."""
        causes = {
            'high_cpu': 'High CPU usage detected, likely due to increased load or inefficient processing',
            'high_memory': 'High memory usage detected, possible memory leak or insufficient resources',
            'high_restart_count': 'High restart count detected, likely due to health check failures',
            'high_error_rate': 'High error rate detected, possible application or dependency issues'
        }
        return causes.get(incident.type, f'Issue detected with {incident.type}')
    
    def _get_fallback_actions(self, incident: Incident) -> List[Dict[str, Any]]:
        """Get fallback remediation actions."""
        actions = {
            'high_cpu': [
                {'action': 'scale_replicas', 'priority': 'high', 'estimated_time': '2m', 'risk': 'low', 'parameters': {'replicas': 2}},
                {'action': 'check_cpu_limits', 'priority': 'medium', 'estimated_time': '5m', 'risk': 'low', 'parameters': {}}
            ],
            'high_memory': [
                {'action': 'restart_pod', 'priority': 'high', 'estimated_time': '1m', 'risk': 'medium', 'parameters': {}},
                {'action': 'check_memory_limits', 'priority': 'medium', 'estimated_time': '5m', 'risk': 'low', 'parameters': {}}
            ],
            'high_restart_count': [
                {'action': 'check_pod_logs', 'priority': 'high', 'estimated_time': '5m', 'risk': 'low', 'parameters': {}},
                {'action': 'verify_health_checks', 'priority': 'medium', 'estimated_time': '10m', 'risk': 'low', 'parameters': {}}
            ]
        }
        
        return actions.get(incident.type, [
            {'action': 'investigate_manually', 'priority': 'medium', 'estimated_time': '15m', 'risk': 'low', 'parameters': {}}
        ])
    
    def _get_affected_services(self, service: str) -> List[str]:
        """Get services that could be affected by this service's issues."""
        dependencies = {
            'userservice': ['frontend', 'contacts', 'balancereader', 'ledgerwriter', 'transactionhistory'],
            'ledgerwriter': ['balancereader', 'transactionhistory', 'frontend'],
            'balancereader': ['frontend'],
            'frontend': [],
            'contacts': ['frontend'],
            'transactionhistory': ['frontend']
        }
        return dependencies.get(service, [])
    
    def _get_cache_key(self, incident: Incident) -> str:
        """Generate cache key for incident analysis."""
        # Cache based on service, type, and key metrics
        key_parts = [
            incident.service,
            incident.type,
            incident.severity.value
        ]
        
        # Add key metric values to cache key
        if 'cpu_usage' in incident.metrics:
            key_parts.append(f"cpu_{incident.metrics['cpu_usage']:.2f}")
        if 'memory_usage' in incident.metrics:
            key_parts.append(f"mem_{incident.metrics['memory_usage']:.2f}")
        
        return "_".join(key_parts)
    
    def _cleanup_cache(self) -> None:
        """Clean up old cache entries."""
        if len(self.analysis_cache) > 100:  # Keep last 100 entries
            oldest_keys = list(self.analysis_cache.keys())[:50]
            for key in oldest_keys:
                del self.analysis_cache[key]
    
    def _build_service_knowledge(self) -> Dict[str, Dict[str, Any]]:
        """Build knowledge base about Bank of Anthos services."""
        return {
            'frontend': {
                'function': 'Web UI for banking operations',
                'technology': 'React/Node.js',
                'dependencies': ['userservice', 'balancereader', 'ledgerwriter', 'transactionhistory', 'contacts'],
                'common_issues': ['High latency', 'Connection timeouts', 'Session issues'],
                'prevention_strategies': ['Connection pooling', 'Circuit breakers', 'Caching']
            },
            'userservice': {
                'function': 'User authentication and management',
                'technology': 'Python/Flask',
                'dependencies': ['database'],
                'common_issues': ['Database connection issues', 'Authentication failures', 'Memory leaks'],
                'prevention_strategies': ['Database connection pooling', 'Proper session management', 'Memory monitoring']
            },
            'balancereader': {
                'function': 'Read account balances',
                'technology': 'Java/Spring',
                'dependencies': ['ledger-db', 'userservice'],
                'common_issues': ['Memory leaks', 'Database lock contention', 'GC pressure'],
                'prevention_strategies': ['JVM tuning', 'Connection pooling', 'Read replicas']
            },
            'ledgerwriter': {
                'function': 'Write transactions to ledger',
                'technology': 'Java/Spring',
                'dependencies': ['ledger-db', 'userservice'],
                'common_issues': ['Database deadlocks', 'Transaction failures', 'High latency'],
                'prevention_strategies': ['Transaction optimization', 'Database tuning', 'Retry mechanisms']
            },
            'transactionhistory': {
                'function': 'Transaction history retrieval',
                'technology': 'Java/Spring',
                'dependencies': ['ledger-db', 'userservice'],
                'common_issues': ['Slow queries', 'Memory usage', 'Database timeouts'],
                'prevention_strategies': ['Query optimization', 'Proper indexing', 'Caching']
            },
            'contacts': {
                'function': 'User contacts management',
                'technology': 'Python/Flask',
                'dependencies': ['database', 'userservice'],
                'common_issues': ['Database connection issues', 'Slow responses'],
                'prevention_strategies': ['Database optimization', 'Connection pooling']
            }
        }