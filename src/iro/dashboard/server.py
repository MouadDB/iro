"""
Web dashboard server for the IRO system.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any

from aiohttp import web, WSMsgType
from aiohttp.web_ws import WebSocketResponse
import aiohttp_cors

from ..config import DashboardConfig
from ..core.models import Incident, HealthStatus
from ..utils.events import EventBus


class DashboardServer:
    """
    Web dashboard server providing REST API and WebSocket interfaces.
    """
    
    def __init__(self, config: DashboardConfig, event_bus: EventBus):
        self.config = config
        self.event_bus = event_bus
        self.logger = logging.getLogger(__name__)
        
        # Web application
        self.app: Optional[web.Application] = None
        self.runner: Optional[web.AppRunner] = None
        self.site: Optional[web.TCPSite] = None
        
        # State management
        self.running = False
        self.incidents: Dict[str, Dict[str, Any]] = {}
        self.metrics: Dict[str, Any] = {}
        
        # WebSocket connections
        self.websockets: List[WebSocketResponse] = []
        
        # Setup event handlers
        self.event_bus.subscribe('dashboard.incident_update', self._handle_incident_update)
        self.event_bus.subscribe('health.response', self._handle_health_response)
    
    async def start(self) -> None:
        """Start the dashboard server."""
        self.logger.info("Starting dashboard server")
        
        try:
            # Create web application
            self.app = web.Application()
            
            # Setup CORS
            cors = aiohttp_cors.setup(self.app, defaults={
                "*": aiohttp_cors.ResourceOptions(
                    allow_credentials=True,
                    expose_headers="*",
                    allow_headers="*",
                    allow_methods="*"
                )
            })
            
            # Setup routes
            self._setup_routes()
            
            # Add CORS to all routes
            for route in list(self.app.router.routes()):
                cors.add(route)
            
            # Start server
            self.runner = web.AppRunner(self.app)
            await self.runner.setup()
            
            self.site = web.TCPSite(
                self.runner, 
                self.config.host, 
                self.config.port
            )
            await self.site.start()
            
            self.running = True
            
            self.logger.info(f"Dashboard server started on http://{self.config.host}:{self.config.port}")
            
        except Exception as e:
            self.logger.error(f"Failed to start dashboard server: {e}")
            raise
    
    async def stop(self) -> None:
        """Stop the dashboard server."""
        self.logger.info("Stopping dashboard server")
        self.running = False
        
        # Close WebSocket connections
        for ws in self.websockets[:]:
            await ws.close()
        
        # Stop server
        if self.site:
            await self.site.stop()
        
        if self.runner:
            await self.runner.cleanup()
        
        self.logger.info("Dashboard server stopped")
    
    async def health_check(self) -> HealthStatus:
        """Perform health check."""
        return HealthStatus(
            healthy=self.running,
            message="Dashboard running normally" if self.running else "Dashboard not running",
            details={
                'websocket_connections': len(self.websockets),
                'incidents_tracked': len(self.incidents),
                'port': self.config.port
            }
        )
    
    def _setup_routes(self) -> None:
        """Setup HTTP routes."""
        # API routes
        self.app.router.add_get('/api/health', self._handle_health)
        self.app.router.add_get('/api/incidents', self._handle_get_incidents)
        self.app.router.add_get('/api/incidents/{incident_id}', self._handle_get_incident)
        self.app.router.add_get('/api/metrics', self._handle_get_metrics)
        self.app.router.add_get('/api/stats', self._handle_get_stats)
        
        # WebSocket route
        if self.config.enable_websocket:
            self.app.router.add_get('/ws', self._handle_websocket)
        
        # Static files
        static_path = Path(self.config.static_files_path)
        if static_path.exists():
            self.app.router.add_static('/', static_path, name='static')
        else:
            # Serve a simple default page
            self.app.router.add_get('/', self._handle_index)
    
    async def _handle_health(self, request: web.Request) -> web.Response:
        """Handle health check endpoint."""
        health = await self.health_check()
        return web.json_response(health.to_dict())
    
    async def _handle_get_incidents(self, request: web.Request) -> web.Response:
        """Handle get all incidents endpoint."""
        # Parse query parameters
        state = request.query.get('state')
        service = request.query.get('service')
        severity = request.query.get('severity')
        limit = int(request.query.get('limit', 100))
        
        # Filter incidents
        filtered_incidents = list(self.incidents.values())
        
        if state:
            filtered_incidents = [i for i in filtered_incidents if i.get('state') == state]
        if service:
            filtered_incidents = [i for i in filtered_incidents if i.get('service') == service]
        if severity:
            filtered_incidents = [i for i in filtered_incidents if i.get('severity') == severity]
        
        # Sort by created_at descending
        filtered_incidents.sort(
            key=lambda x: x.get('created_at', ''), 
            reverse=True
        )
        
        # Apply limit
        filtered_incidents = filtered_incidents[:limit]
        
        return web.json_response({
            'incidents': filtered_incidents,
            'total': len(filtered_incidents),
            'filters': {
                'state': state,
                'service': service,
                'severity': severity,
                'limit': limit
            }
        })
    
    async def _handle_get_incident(self, request: web.Request) -> web.Response:
        """Handle get specific incident endpoint."""
        incident_id = request.match_info['incident_id']
        
        incident = self.incidents.get(incident_id)
        if not incident:
            return web.json_response(
                {'error': 'Incident not found'}, 
                status=404
            )
        
        return web.json_response(incident)
    
    async def _handle_get_metrics(self, request: web.Request) -> web.Response:
        """Handle get metrics endpoint."""
        return web.json_response(self.metrics)
    
    async def _handle_get_stats(self, request: web.Request) -> web.Response:
        """Handle get statistics endpoint."""
        stats = self._calculate_stats()
        return web.json_response(stats)
    
    async def _handle_index(self, request: web.Request) -> web.Response:
        """Handle index page."""
        html_content = self._get_default_html()
        return web.Response(text=html_content, content_type='text/html')
    
    async def _handle_websocket(self, request: web.Request) -> WebSocketResponse:
        """Handle WebSocket connections."""
        ws = WebSocketResponse()
        await ws.prepare(request)
        
        self.websockets.append(ws)
        self.logger.info(f"New WebSocket connection. Total: {len(self.websockets)}")
        
        try:
            # Send welcome message
            await self._send_websocket_message(ws, {
                'type': 'welcome',
                'data': {
                    'message': 'Connected to IRO Dashboard',
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }
            })
            
            # Send current incidents
            await self._send_websocket_message(ws, {
                'type': 'incidents_snapshot',
                'data': list(self.incidents.values())
            })
            
            # Handle incoming messages
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        await self._handle_websocket_message(ws, data)
                    except json.JSONDecodeError:
                        await self._send_websocket_message(ws, {
                            'type': 'error',
                            'data': {'message': 'Invalid JSON'}
                        })
                elif msg.type == WSMsgType.ERROR:
                    self.logger.error(f'WebSocket error: {ws.exception()}')
                    break
        
        except Exception as e:
            self.logger.error(f"WebSocket error: {e}")
        
        finally:
            if ws in self.websockets:
                self.websockets.remove(ws)
            self.logger.info(f"WebSocket disconnected. Total: {len(self.websockets)}")
        
        return ws
    
    async def _handle_websocket_message(self, ws: WebSocketResponse, data: Dict[str, Any]) -> None:
        """Handle incoming WebSocket messages."""
        msg_type = data.get('type')
        
        if msg_type == 'ping':
            await self._send_websocket_message(ws, {
                'type': 'pong',
                'data': {'timestamp': datetime.now(timezone.utc).isoformat()}
            })
        
        elif msg_type == 'subscribe':
            # Handle subscription requests (placeholder)
            await self._send_websocket_message(ws, {
                'type': 'subscribed',
                'data': {'topic': data.get('topic')}
            })
        
        else:
            await self._send_websocket_message(ws, {
                'type': 'error',
                'data': {'message': f'Unknown message type: {msg_type}'}
            })
    
    async def _send_websocket_message(self, ws: WebSocketResponse, message: Dict[str, Any]) -> None:
        """Send message to WebSocket client."""
        try:
            await ws.send_str(json.dumps(message))
        except Exception as e:
            self.logger.warning(f"Failed to send WebSocket message: {e}")
    
    async def _broadcast_websocket_message(self, message: Dict[str, Any]) -> None:
        """Broadcast message to all WebSocket clients."""
        if not self.websockets:
            return
        
        # Remove closed connections
        active_connections = []
        for ws in self.websockets[:]:
            if ws.closed:
                self.websockets.remove(ws)
            else:
                active_connections.append(ws)
        
        # Send to active connections
        if active_connections:
            tasks = [
                self._send_websocket_message(ws, message) 
                for ws in active_connections
            ]
            await asyncio.gather(*tasks, return_exceptions=True)
    
    async def _handle_incident_update(self, event: Dict[str, Any]) -> None:
        """Handle incident update events."""
        try:
            incident_data = event['incident']
            incident_id = incident_data['id']
            
            # Store incident
            self.incidents[incident_id] = incident_data
            
            # Broadcast to WebSocket clients
            await self._broadcast_websocket_message({
                'type': 'incident_update',
                'data': incident_data
            })
            
            self.logger.debug(f"Updated incident {incident_id}")
            
        except Exception as e:
            self.logger.error(f"Error handling incident update: {e}")
    
    async def _handle_health_response(self, event: Dict[str, Any]) -> None:
        """Handle health response events."""
        try:
            # Store health metrics
            self.metrics['health'] = event
            self.metrics['last_updated'] = datetime.now(timezone.utc).isoformat()
            
            # Broadcast to WebSocket clients
            await self._broadcast_websocket_message({
                'type': 'health_update',
                'data': event
            })
            
        except Exception as e:
            self.logger.error(f"Error handling health response: {e}")
    
    def _calculate_stats(self) -> Dict[str, Any]:
        """Calculate system statistics."""
        total_incidents = len(self.incidents)
        
        # Count by state
        states = {}
        severities = {}
        services = {}
        
        for incident in self.incidents.values():
            state = incident.get('state', 'unknown')
            severity = incident.get('severity', 'unknown')
            service = incident.get('service', 'unknown')
            
            states[state] = states.get(state, 0) + 1
            severities[severity] = severities.get(severity, 0) + 1
            services[service] = services.get(service, 0) + 1
        
        # Calculate resolution rate
        resolved = states.get('resolved', 0)
        failed = states.get('failed', 0)
        total_completed = resolved + failed
        resolution_rate = (resolved / total_completed * 100) if total_completed > 0 else 0
        
        return {
            'total_incidents': total_incidents,
            'by_state': states,
            'by_severity': severities,
            'by_service': services,
            'resolution_rate': round(resolution_rate, 2),
            'active_connections': len(self.websockets),
            'last_updated': datetime.now(timezone.utc).isoformat()
        }
    
    def _get_default_html(self) -> str:
        """Get default HTML page."""
        return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>IRO Dashboard</title>
    <style>
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            margin: 0;
            padding: 20px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            min-height: 100vh;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
            background: rgba(255, 255, 255, 0.1);
            border-radius: 15px;
            padding: 30px;
            backdrop-filter: blur(10px);
            box-shadow: 0 8px 32px 0 rgba(31, 38, 135, 0.37);
        }
        h1 {
            text-align: center;
            margin-bottom: 30px;
            font-size: 2.5em;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
        }
        .status {
            text-align: center;
            font-size: 1.2em;
            margin-bottom: 30px;
            padding: 15px;
            background: rgba(255, 255, 255, 0.2);
            border-radius: 10px;
        }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin-top: 30px;
        }
        .card {
            background: rgba(255, 255, 255, 0.15);
            border-radius: 10px;
            padding: 20px;
            backdrop-filter: blur(5px);
        }
        .card h3 {
            margin-top: 0;
            border-bottom: 2px solid rgba(255, 255, 255, 0.3);
            padding-bottom: 10px;
        }
        .incident {
            background: rgba(255, 255, 255, 0.1);
            border-radius: 8px;
            padding: 15px;
            margin: 10px 0;
            border-left: 4px solid;
        }
        .incident.critical { border-left-color: #ff4757; }
        .incident.error { border-left-color: #ff6b35; }
        .incident.warning { border-left-color: #ffa500; }
        .incident.info { border-left-color: #3742fa; }
        .timestamp {
            font-size: 0.9em;
            opacity: 0.8;
        }
        .api-info {
            background: rgba(255, 255, 255, 0.1);
            border-radius: 10px;
            padding: 20px;
            margin-top: 20px;
        }
        .api-info h4 {
            margin-top: 0;
        }
        .api-endpoint {
            background: rgba(0, 0, 0, 0.2);
            padding: 8px 12px;
            border-radius: 5px;
            font-family: monospace;
            margin: 5px 0;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🚨 Incident Response Orchestrator</h1>
        <div id="status" class="status">Connecting...</div>
        
        <div class="grid">
            <div class="card">
                <h3>📊 System Status</h3>
                <div id="system-status">Loading...</div>
            </div>
            
            <div class="card">
                <h3>🔥 Recent Incidents</h3>
                <div id="incidents">Loading...</div>
            </div>
            
            <div class="card">
                <h3>📈 Statistics</h3>
                <div id="stats">Loading...</div>
            </div>
        </div>
        
        <div class="api-info">
            <h4>🔗 API Endpoints</h4>
            <div class="api-endpoint">GET /api/health - System health check</div>
            <div class="api-endpoint">GET /api/incidents - List all incidents</div>
            <div class="api-endpoint">GET /api/incidents/{id} - Get specific incident</div>
            <div class="api-endpoint">GET /api/metrics - System metrics</div>
            <div class="api-endpoint">GET /api/stats - System statistics</div>
            <div class="api-endpoint">WebSocket /ws - Real-time updates</div>
        </div>
    </div>

    <script>
        let ws = null;
        let incidents = {};
        
        function connect() {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const wsUrl = `${protocol}//${window.location.host}/ws`;
            
            ws = new WebSocket(wsUrl);
            
            ws.onopen = () => {
                document.getElementById('status').innerHTML = '✅ Connected to IRO Dashboard';
                document.getElementById('status').style.background = 'rgba(46, 213, 115, 0.3)';
            };
            
            ws.onmessage = (event) => {
                const message = JSON.parse(event.data);
                handleMessage(message);
            };
            
            ws.onclose = () => {
                document.getElementById('status').innerHTML = '❌ Disconnected - Reconnecting...';
                document.getElementById('status').style.background = 'rgba(255, 71, 87, 0.3)';
                setTimeout(connect, 2000);
            };
            
            ws.onerror = (error) => {
                console.error('WebSocket error:', error);
            };
        }
        
        function handleMessage(message) {
            switch(message.type) {
                case 'welcome':
                    console.log('Connected to IRO Dashboard');
                    break;
                    
                case 'incidents_snapshot':
                    message.data.forEach(incident => {
                        incidents[incident.id] = incident;
                    });
                    updateIncidentsDisplay();
                    break;
                    
                case 'incident_update':
                    incidents[message.data.id] = message.data;
                    updateIncidentsDisplay();
                    break;
                    
                case 'health_update':
                    updateSystemStatus(message.data);
                    break;
                    
                default:
                    console.log('Unknown message type:', message.type);
            }
        }
        
        function updateIncidentsDisplay() {
            const container = document.getElementById('incidents');
            const incidentList = Object.values(incidents)
                .sort((a, b) => new Date(b.created_at) - new Date(a.created_at))
                .slice(0, 5);
            
            if (incidentList.length === 0) {
                container.innerHTML = '<p>No incidents detected 🎉</p>';
                return;
            }
            
            container.innerHTML = incidentList.map(incident => `
                <div class="incident ${incident.severity}">
                    <strong>${incident.service}</strong> - ${incident.type}
                    <div>${incident.description}</div>
                    <div class="timestamp">State: ${incident.state} | ${new Date(incident.created_at).toLocaleString()}</div>
                </div>
            `).join('');
        }
        
        function updateSystemStatus(health) {
            const container = document.getElementById('system-status');
            const status = health.status === 'healthy' ? '✅ Healthy' : '❌ Unhealthy';
            
            container.innerHTML = `
                <p><strong>Status:</strong> ${status}</p>
                <p><strong>Active Incidents:</strong> ${health.incidents?.active || 0}</p>
                <p><strong>Total Incidents:</strong> ${health.incidents?.total || 0}</p>
                <p><strong>Last Check:</strong> ${new Date(health.timestamp).toLocaleString()}</p>
            `;
        }
        
        // Load statistics
        async function loadStats() {
            try {
                const response = await fetch('/api/stats');
                const stats = await response.json();
                
                const container = document.getElementById('stats');
                container.innerHTML = `
                    <p><strong>Total Incidents:</strong> ${stats.total_incidents}</p>
                    <p><strong>Resolution Rate:</strong> ${stats.resolution_rate}%</p>
                    <p><strong>Active Connections:</strong> ${stats.active_connections}</p>
                    <p><strong>Last Updated:</strong> ${new Date(stats.last_updated).toLocaleString()}</p>
                `;
            } catch (error) {
                console.error('Failed to load stats:', error);
            }
        }
        
        // Initialize
        connect();
        loadStats();
        setInterval(loadStats, 30000); // Update stats every 30 seconds
    </script>
</body>
</html>
        """