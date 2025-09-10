"""
Configuration management for IRO system.
"""

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import yaml


@dataclass
class MonitoringConfig:
    """Configuration for monitoring functionality."""
    interval_seconds: int = 30
    cpu_threshold: float = 0.8
    memory_threshold: float = 0.9
    restart_threshold: int = 3
    namespace: str = "default"
    services: List[str] = field(default_factory=lambda: [
        "frontend", "userservice", "contacts", 
        "balancereader", "ledgerwriter", "transactionhistory"
    ])


@dataclass
class AnalysisConfig:
    """Configuration for AI analysis."""
    model_name: str = "gemini-1.5-flash"
    temperature: float = 0.7
    max_tokens: int = 2048
    timeout_seconds: int = 120
    cache_ttl_minutes: int = 15


@dataclass
class RemediationConfig:
    """Configuration for remediation actions."""
    dry_run: bool = False
    require_approval: bool = False
    max_concurrent: int = 3
    timeout_seconds: int = 300
    enable_rollback: bool = True
    max_blast_radius: float = 0.8


@dataclass
class DashboardConfig:
    """Configuration for dashboard/web interface."""
    host: str = "0.0.0.0"
    port: int = 8080
    enable_websocket: bool = True
    static_files_path: str = "web/static"


@dataclass
class Config:
    """Main configuration for IRO system."""
    version: str = "1.0.0"
    environment: str = "development"
    
    # Cloud configuration
    gcp_project: str = ""
    gcp_region: str = "us-central1"
    
    # Kubernetes configuration
    kubeconfig_path: Optional[str] = None
    cluster_name: str = "bank-of-anthos"
    
    # Component configurations
    monitoring: MonitoringConfig = field(default_factory=MonitoringConfig)
    analysis: AnalysisConfig = field(default_factory=AnalysisConfig)
    remediation: RemediationConfig = field(default_factory=RemediationConfig)
    dashboard: DashboardConfig = field(default_factory=DashboardConfig)
    
    # Logging
    log_level: str = "INFO"
    log_format: str = "json"


def load_config(config_path: Optional[str] = None) -> Config:
    """Load configuration from file and environment variables."""
    config = Config()
    
    # Load from file if provided
    if config_path and os.path.exists(config_path):
        with open(config_path, 'r') as f:
            config_data = yaml.safe_load(f)
            _update_config_from_dict(config, config_data)
    
    # Override with environment variables
    _load_from_env(config)
    
    return config


def _load_from_env(config: Config) -> None:
    """Load configuration values from environment variables."""
    env_mapping = {
        'IRO_VERSION': lambda v: setattr(config, 'version', v),
        'IRO_ENVIRONMENT': lambda v: setattr(config, 'environment', v),
        'GCP_PROJECT': lambda v: setattr(config, 'gcp_project', v),
        'GCP_REGION': lambda v: setattr(config, 'gcp_region', v),
        'KUBECONFIG': lambda v: setattr(config, 'kubeconfig_path', v),
        'CLUSTER_NAME': lambda v: setattr(config, 'cluster_name', v),
        'LOG_LEVEL': lambda v: setattr(config, 'log_level', v),
        
        # Monitoring
        'MONITORING_INTERVAL': lambda v: setattr(config.monitoring, 'interval_seconds', int(v)),
        'CPU_THRESHOLD': lambda v: setattr(config.monitoring, 'cpu_threshold', float(v)),
        'MEMORY_THRESHOLD': lambda v: setattr(config.monitoring, 'memory_threshold', float(v)),
        
        # Analysis
        'GEMINI_MODEL': lambda v: setattr(config.analysis, 'model_name', v),
        'ANALYSIS_TIMEOUT': lambda v: setattr(config.analysis, 'timeout_seconds', int(v)),
        
        # Remediation
        'REMEDIATION_DRY_RUN': lambda v: setattr(config.remediation, 'dry_run', v.lower() == 'true'),
        'REQUIRE_APPROVAL': lambda v: setattr(config.remediation, 'require_approval', v.lower() == 'true'),
        
        # Dashboard
        'DASHBOARD_PORT': lambda v: setattr(config.dashboard, 'port', int(v)),
        'DASHBOARD_HOST': lambda v: setattr(config.dashboard, 'host', v),
    }
    
    for env_var, setter in env_mapping.items():
        value = os.getenv(env_var)
        if value is not None:
            try:
                setter(value)
            except (ValueError, AttributeError) as e:
                print(f"Warning: Invalid value for {env_var}: {value} ({e})")


def _update_config_from_dict(config: Config, data: dict) -> None:
    """Update config object from dictionary data."""
    for key, value in data.items():
        if hasattr(config, key):
            if isinstance(value, dict):
                sub_config = getattr(config, key)
                for sub_key, sub_value in value.items():
                    if hasattr(sub_config, sub_key):
                        setattr(sub_config, sub_key, sub_value)
            else:
                setattr(config, key, value)