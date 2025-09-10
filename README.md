# Incident Response Orchestrator (IRO)

🚨 **Automated incident detection and remediation for Kubernetes environments**

IRO is a Python-based system that automatically detects, analyzes, and remediates incidents in Kubernetes clusters using AI-powered analysis and intelligent automation.

## Features

- **🔍 Intelligent Monitoring**: Real-time detection of anomalies using statistical analysis and threshold-based monitoring
- **🤖 AI-Powered Analysis**: Root cause analysis using Google Gemini AI with contextual understanding of your services
- **⚡ Automated Remediation**: Safe, configurable remediation actions with rollback capabilities
- **📊 Real-time Dashboard**: Web-based dashboard with WebSocket updates for live incident tracking
- **🛡️ Safety First**: Circuit breakers, dry-run mode, and approval workflows for production safety
- **📈 Bank of Anthos Ready**: Pre-configured for Google's Bank of Anthos microservices demo

## Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Monitoring    │    │    Analysis     │    │   Remediation   │
│    Detector     │───▶│    Analyzer     │───▶│    Executor     │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         │              ┌─────────────────┐              │
         └──────────────▶│   Dashboard     │◀─────────────┘
                        │     Server      │
                        └─────────────────┘
                                 │
                        ┌─────────────────┐
                        │   Event Bus     │
                        └─────────────────┘
```

## Quick Start

### Prerequisites

- Python 3.9+
- Kubernetes cluster with Bank of Anthos deployed
- Google Cloud Project with Vertex AI API enabled
- kubectl configured for your cluster

### Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/MouadDB/iro.git
   cd iro
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   pip install -e .
   ```

3. **Configure environment**:
   ```bash
   export GCP_PROJECT="your-project-id"
   export GOOGLE_APPLICATION_CREDENTIALS="path/to/service-account-key.json"
   ```

4. **Run IRO**:
   ```bash
   python -m iro.main
   ```

5. **Access Dashboard**:
   Open http://localhost:8080 in your browser

### Docker Deployment

1. **Build and run with Docker**:
   ```bash
   docker build -t iro:latest .
   docker run -p 8080:8080 \
     -e GCP_PROJECT="your-project-id" \
     -e GOOGLE_APPLICATION_CREDENTIALS="/app/key.json" \
     -v /path/to/key.json:/app/key.json \
     iro:latest
   ```

### Kubernetes Deployment

1. **Deploy using the provided script**:
   ```bash
   export GCP_PROJECT="your-project-id"
   ./scripts/deploy.sh deploy
   ```

2. **Check deployment status**:
   ```bash
   ./scripts/deploy.sh status
   ```

## Configuration

IRO can be configured through YAML files or environment variables:

```yaml
# config/default.yaml
monitoring:
  interval_seconds: 30
  cpu_threshold: 0.8
  memory_threshold: 0.9
  services:
    - "frontend"
    - "userservice"
    - "balancereader"

analysis:
  model_name: "gemini-1.5-flash"
  temperature: 0.7
  timeout_seconds: 120

remediation:
  dry_run: false
  require_approval: true
  max_concurrent: 3
```

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `GCP_PROJECT` | Google Cloud Project ID | Required |
| `LOG_LEVEL` | Logging level | INFO |
| `MONITORING_INTERVAL` | Monitoring interval in seconds | 30 |
| `REMEDIATION_DRY_RUN` | Enable dry-run mode | false |

## How It Works

### 1. Monitoring & Detection

IRO continuously monitors your Kubernetes services for:
- **Resource anomalies**: CPU/memory usage spikes
- **Pod health issues**: Restarts, crashes, stuck states
- **Application metrics**: Error rates, latency issues

### 2. AI-Powered Analysis

When an incident is detected, IRO uses Google Gemini AI to:
- Analyze the incident context and symptoms
- Identify potential root causes
- Assess impact on dependent services
- Recommend specific remediation actions

### 3. Safe Remediation

IRO can automatically execute remediation actions such as:
- Scaling deployments up/down
- Restarting problematic pods
- Adjusting resource limits
- Triggering circuit breakers

### 4. Real-time Monitoring

The web dashboard provides:
- Live incident feed with WebSocket updates
- System health status
- Remediation progress tracking
- Historical incident analytics

## Example Incident Flow

1. **Detection**: High CPU usage detected on `balancereader` service
2. **Analysis**: AI determines memory leak as root cause with 85% confidence
3. **Recommendation**: Restart pod and increase memory limits
4. **Execution**: Pod restart initiated with health monitoring
5. **Verification**: Service returns to normal operation
6. **Learning**: Pattern stored for future similar incidents

## Safety Features

- **Circuit Breakers**: Prevent cascade failures in external dependencies
- **Dry Run Mode**: Test remediation actions without executing them
- **Approval Workflows**: Require human approval for high-risk actions
- **Rollback Capabilities**: Automatic rollback on remediation failure
- **Blast Radius Limits**: Prevent actions affecting too many services

## API Reference

### REST Endpoints

- `GET /api/health` - System health check
- `GET /api/incidents` - List all incidents
- `GET /api/incidents/{id}` - Get specific incident
- `GET /api/metrics` - Current system metrics
- `GET /api/stats` - System statistics

### WebSocket Events

- `incident_update` - Real-time incident updates
- `health_update` - System health changes
- `metrics_update` - Live metrics feed

## Development

### Running Tests

```bash
# Unit tests
pytest tests/unit/

# Integration tests
pytest tests/integration/

# Coverage report
pytest --cov=src tests/
```

### Code Quality

```bash
# Format code
black src/ tests/

# Lint code
flake8 src/ tests/

# Type checking
mypy src/
```

### Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Run quality checks
6. Submit a pull request

## Monitoring & Observability

IRO provides comprehensive observability:

- **Structured JSON logging** for easy log aggregation
- **Prometheus metrics** (optional) for monitoring
- **Health check endpoints** for load balancer integration
- **Distributed tracing** support for complex workflows

## Security Considerations

- **RBAC**: Minimal required Kubernetes permissions
- **Service Account**: Dedicated service account with limited scope
- **Secrets Management**: Secure handling of API keys and credentials
- **Network Policies**: Recommended network isolation
- **Audit Logging**: Complete audit trail of all actions

## Troubleshooting

### Common Issues

1. **Gemini API Errors**:
   ```bash
   # Check API key and project configuration
   gcloud auth application-default login
   export GOOGLE_APPLICATION_CREDENTIALS="path/to/key.json"
   ```

2. **Kubernetes Permission Errors**:
   ```bash
   # Verify RBAC configuration
   kubectl auth can-i list pods --as=system:serviceaccount:incident-response:iro-service-account
   ```

3. **Dashboard Not Accessible**:
   ```bash
   # Check service and ingress status
   kubectl get service iro-service -n incident-response
   kubectl get ingress iro-ingress -n incident-response
   ```

### Debug Mode

Enable debug logging for troubleshooting:

```bash
export LOG_LEVEL=DEBUG
python -m iro.main
```

## License

This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- Built for Google Cloud's Bank of Anthos microservices demo
- Powered by Google Gemini AI for intelligent analysis
- Inspired by Site Reliability Engineering practices
- Kubernetes community for excellent tooling and APIs

## Support

- 📖 [Documentation](https://iro.readthedocs.io/)
- 🐛 [Issue Tracker](https://github.com/MouadDB/iro/issues)
- 💬 [Discussions](https://github.com/MouadDB/iro/discussions)
- 📧 [Email Support](mailto:support@yourorg.com)

---

**Made with ❤️ for reliable Kubernetes operations**