#!/bin/bash
set -euo pipefail

# Incident Response Orchestrator (IRO) Deployment Script

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
VERSION=${VERSION:-"latest"}
PROJECT_ID=${GCP_PROJECT:-""}
CLUSTER_NAME=${CLUSTER_NAME:-"bank-of-anthos"}
ZONE=${ZONE:-"us-central1-a"}
NAMESPACE="incident-response"
REGISTRY=${REGISTRY:-"gcr.io/${PROJECT_ID}"}
IMAGE_NAME="iro"

# Functions
log_info() {
    echo -e "${BLUE}INFO:${NC} $1"
}

log_success() {
    echo -e "${GREEN}SUCCESS:${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}WARNING:${NC} $1"
}

log_error() {
    echo -e "${RED}ERROR:${NC} $1"
}

check_prerequisites() {
    log_info "Checking prerequisites..."
    
    # Check required tools
    for tool in kubectl docker gcloud; do
        if ! command -v $tool &> /dev/null; then
            log_error "$tool is not installed or not in PATH"
            exit 1
        fi
    done
    
    # Check GCP project
    if [[ -z "$PROJECT_ID" ]]; then
        log_error "GCP_PROJECT environment variable is not set"
        exit 1
    fi
    
    # Check kubectl context
    current_context=$(kubectl config current-context 2>/dev/null || echo "none")
    log_info "Current kubectl context: $current_context"
    
    log_success "Prerequisites check passed"
}

build_image() {
    log_info "Building Docker image..."
    
    local image_tag="${REGISTRY}/${IMAGE_NAME}:${VERSION}"
    
    # Build image
    docker build -t "$image_tag" .
    
    # Tag as latest if version is not latest
    if [[ "$VERSION" != "latest" ]]; then
        docker tag "$image_tag" "${REGISTRY}/${IMAGE_NAME}:latest"
    fi
    
    log_success "Docker image built: $image_tag"
}

push_image() {
    log_info "Pushing Docker image to registry..."
    
    # Configure Docker for GCR
    gcloud auth configure-docker --quiet
    
    # Push image
    docker push "${REGISTRY}/${IMAGE_NAME}:${VERSION}"
    
    if [[ "$VERSION" != "latest" ]]; then
        docker push "${REGISTRY}/${IMAGE_NAME}:latest"
    fi
    
    log_success "Docker image pushed to registry"
}

create_namespace() {
    log_info "Creating namespace..."
    
    if kubectl get namespace "$NAMESPACE" &> /dev/null; then
        log_warning "Namespace $NAMESPACE already exists"
    else
        kubectl create namespace "$NAMESPACE"
        log_success "Namespace $NAMESPACE created"
    fi
}

create_secrets() {
    log_info "Creating secrets..."
    
    # Check if Google Cloud service account key exists
    if [[ ! -f "service-account-key.json" ]]; then
        log_warning "service-account-key.json not found. Please create a service account key and place it in the current directory."
        log_info "You can create it with: gcloud iam service-accounts keys create service-account-key.json --iam-account=YOUR_SERVICE_ACCOUNT@${PROJECT_ID}.iam.gserviceaccount.com"
        return
    fi
    
    # Create Google Cloud key secret
    kubectl create secret generic google-cloud-key \
        --from-file=key.json=service-account-key.json \
        --namespace="$NAMESPACE" \
        --dry-run=client -o yaml | kubectl apply -f -
    
    log_success "Secrets created"
}

update_deployment_config() {
    log_info "Updating deployment configuration..."
    
    # Create temporary deployment file
    local temp_deployment="/tmp/iro-deployment.yaml"
    cp k8s/deployment.yaml "$temp_deployment"
    
    # Replace placeholders
    sed -i "s|your-project-id|${PROJECT_ID}|g" "$temp_deployment"
    sed -i "s|your-registry/iro:latest|${REGISTRY}/${IMAGE_NAME}:${VERSION}|g" "$temp_deployment"
    
    log_success "Deployment configuration updated"
    echo "$temp_deployment"
}

deploy_to_kubernetes() {
    log_info "Deploying to Kubernetes..."
    
    local deployment_file
    deployment_file=$(update_deployment_config)
    
    # Apply deployment
    kubectl apply -f "$deployment_file"
    
    # Wait for deployment to be ready
    log_info "Waiting for deployment to be ready..."
    kubectl wait --for=condition=available --timeout=300s \
        deployment/iro-orchestrator -n "$NAMESPACE"
    
    log_success "Deployment completed successfully"
    
    # Clean up temp file
    rm -f "$deployment_file"
}

check_deployment() {
    log_info "Checking deployment status..."
    
    # Get pod status
    echo ""
    echo "Pod Status:"
    kubectl get pods -n "$NAMESPACE" -l app=iro-orchestrator
    
    # Get service status
    echo ""
    echo "Service Status:"
    kubectl get services -n "$NAMESPACE"
    
    # Get ingress status
    echo ""
    echo "Ingress Status:"
    kubectl get ingress -n "$NAMESPACE" 2>/dev/null || echo "No ingress found"
    
    # Get service URL
    local service_ip
    service_ip=$(kubectl get service iro-service -n "$NAMESPACE" \
        -o jsonpath='{.status.loadBalancer.ingress[0].ip}' 2>/dev/null || echo "pending")
    
    echo ""
    if [[ "$service_ip" != "pending" && -n "$service_ip" ]]; then
        log_success "IRO Dashboard is accessible at: http://${service_ip}"
    else
        log_info "Service external IP is still pending. Check back in a few minutes."
        log_info "You can check the status with: kubectl get service iro-service -n $NAMESPACE"
    fi
}

show_logs() {
    log_info "Recent logs from IRO:"
    echo ""
    kubectl logs -n "$NAMESPACE" -l app=iro-orchestrator --tail=20
}

cleanup() {
    log_info "Cleaning up deployment..."
    
    kubectl delete namespace "$NAMESPACE" --ignore-not-found=true
    
    log_success "Cleanup completed"
}

show_help() {
    echo "Usage: $0 [COMMAND]"
    echo ""
    echo "Commands:"
    echo "  deploy    - Build, push and deploy IRO (default)"
    echo "  build     - Build Docker image only"
    echo "  push      - Push Docker image only"
    echo "  k8s       - Deploy to Kubernetes only"
    echo "  status    - Check deployment status"
    echo "  logs      - Show application logs"
    echo "  cleanup   - Remove deployment"
    echo "  help      - Show this help"
    echo ""
    echo "Environment Variables:"
    echo "  GCP_PROJECT    - Google Cloud Project ID (required)"
    echo "  VERSION        - Image version tag (default: latest)"
    echo "  CLUSTER_NAME   - Kubernetes cluster name (default: bank-of-anthos)"
    echo "  ZONE           - GCP zone (default: us-central1-a)"
    echo "  REGISTRY       - Container registry (default: gcr.io/\$GCP_PROJECT)"
}

# Main execution
main() {
    local command=${1:-"deploy"}
    
    case $command in
        "deploy")
            check_prerequisites
            build_image
            push_image
            create_namespace
            create_secrets
            deploy_to_kubernetes
            check_deployment
            ;;
        "build")
            check_prerequisites
            build_image
            ;;
        "push")
            check_prerequisites
            push_image
            ;;
        "k8s")
            check_prerequisites
            create_namespace
            create_secrets
            deploy_to_kubernetes
            check_deployment
            ;;
        "status")
            check_deployment
            ;;
        "logs")
            show_logs
            ;;
        "cleanup")
            cleanup
            ;;
        "help"|"-h"|"--help")
            show_help
            ;;
        *)
            log_error "Unknown command: $command"
            show_help
            exit 1
            ;;
    esac
}

# Script entry point
log_info "Starting IRO deployment script..."
main "$@"
log_success "Script completed successfully!"