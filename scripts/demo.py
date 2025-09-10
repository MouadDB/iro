#!/usr/bin/env python3
"""
Demo script for IRO (Incident Response Orchestrator).
Simulates various incidents and showcases the system's capabilities.
"""

import asyncio
import json
import random
import time
from datetime import datetime, timezone
from typing import List, Dict, Any

import aiohttp
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class IRODemo:
    """
    Demonstration class for IRO system capabilities.
    """
    
    def __init__(self, base_url: str = "http://localhost:8080"):
        self.base_url = base_url
        self.session: aiohttp.ClientSession = None
        
        # Demo scenarios
        self.scenarios = [
            {
                "name": "High CPU Usage",
                "service": "balancereader",
                "type": "high_cpu",
                "severity": "critical",
                "description": "CPU usage at 95% for balance reader service",
                "metrics": {
                    "cpu_usage": 0.95,
                    "memory_usage": 0.7,
                    "request_rate": 150.0,
                    "error_rate": 0.02
                }
            },
            {
                "name": "Memory Leak",
                "service": "userservice",
                "type": "high_memory",
                "severity": "error",
                "description": "Memory usage steadily increasing in user service",
                "metrics": {
                    "cpu_usage": 0.4,
                    "memory_usage": 0.92,
                    "request_rate": 50.0,
                    "error_rate": 0.01
                }
            },
            {
                "name": "Pod Restart Loop",
                "service": "ledgerwriter",
                "type": "high_restart_count",
                "severity": "critical",
                "description": "Ledger writer pods restarting frequently",
                "metrics": {
                    "restart_count": 8,
                    "pod_count": 3,
                    "ready_pods": 1,
                    "error_rate": 0.15
                }
            },
            {
                "name": "High Error Rate",
                "service": "frontend",
                "type": "high_error_rate",
                "severity": "warning",
                "description": "Frontend service experiencing elevated error rates",
                "metrics": {
                    "cpu_usage": 0.6,
                    "memory_usage": 0.5,
                    "request_rate": 200.0,
                    "error_rate": 0.08,
                    "latency_p99": 2500
                }
            },
            {
                "name": "Database Connection Issues",
                "service": "contacts",
                "type": "database_errors",
                "severity": "error",
                "description": "Contact service unable to connect to database",
                "metrics": {
                    "cpu_usage": 0.3,
                    "memory_usage": 0.4,
                    "request_rate": 10.0,
                    "error_rate": 0.5,
                    "db_connection_errors": 25
                }
            }
        ]
    
    async def __aenter__(self):
        """Async context manager entry."""
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self.session:
            await self.session.close()
    
    async def check_iro_health(self) -> bool:
        """Check if IRO is running and healthy."""
        try:
            async with self.session.get(f"{self.base_url}/api/health") as response:
                if response.status == 200:
                    health_data = await response.json()
                    logger.info(f"IRO Health Status: {health_data}")
                    return health_data.get('healthy', False)
                else:
                    logger.error(f"Health check failed with status {response.status}")
                    return False
        except Exception as e:
            logger.error(f"Failed to connect to IRO: {e}")
            return False
    
    async def get_current_incidents(self) -> List[Dict[str, Any]]:
        """Get current incidents from IRO."""
        try:
            async with self.session.get(f"{self.base_url}/api/incidents") as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get('incidents', [])
                else:
                    logger.error(f"Failed to get incidents: {response.status}")
                    return []
        except Exception as e:
            logger.error(f"Error getting incidents: {e}")
            return []
    
    async def get_system_stats(self) -> Dict[str, Any]:
        """Get system statistics from IRO."""
        try:
            async with self.session.get(f"{self.base_url}/api/stats") as response:
                if response.status == 200:
                    return await response.json()
                else:
                    logger.error(f"Failed to get stats: {response.status}")
                    return {}
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return {}
    
    async def simulate_incident(self, scenario: Dict[str, Any]) -> None:
        """Simulate an incident by creating fake data."""
        logger.info(f"🚨 Simulating incident: {scenario['name']}")
        
        # In a real system, this would trigger the monitoring detector
        # For demo purposes, we'll just log the scenario
        
        logger.info(f"   Service: {scenario['service']}")
        logger.info(f"   Type: {scenario['type']}")
        logger.info(f"   Severity: {scenario['severity']}")
        logger.info(f"   Description: {scenario['description']}")
        logger.info(f"   Metrics: {json.dumps(scenario['metrics'], indent=2)}")
        
        # Wait a moment to simulate detection time
        await asyncio.sleep(2)
    
    async def demonstrate_websocket(self) -> None:
        """Demonstrate WebSocket connection for real-time updates."""
        logger.info("🔌 Connecting to WebSocket for real-time updates...")
        
        try:
            import websockets
            
            ws_url = self.base_url.replace('http:', 'ws:').replace('https:', 'wss:') + '/ws'
            
            async with websockets.connect(ws_url) as websocket:
                logger.info("✅ WebSocket connected successfully")
                
                # Listen for a few messages
                for i in range(5):
                    try:
                        message = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                        data = json.loads(message)
                        logger.info(f"📡 WebSocket message: {data.get('type', 'unknown')}")
                    except asyncio.TimeoutError:
                        logger.info("⏱️  No WebSocket messages received")
                        break
                
        except ImportError:
            logger.warning("⚠️  websockets library not installed, skipping WebSocket demo")
        except Exception as e:
            logger.error(f"❌ WebSocket connection failed: {e}")
    
    async def run_scenario_demo(self) -> None:
        """Run through all demo scenarios."""
        logger.info("🎬 Starting IRO Demo Scenarios")
        logger.info("=" * 50)
        
        for i, scenario in enumerate(self.scenarios, 1):
            logger.info(f"\n📋 Scenario {i}/{len(self.scenarios)}: {scenario['name']}")
            logger.info("-" * 40)
            
            # Simulate the incident
            await self.simulate_incident(scenario)
            
            # Wait for processing (in real system, this would trigger analysis)
            logger.info("⏳ Waiting for IRO to process the incident...")
            await asyncio.sleep(5)
            
            # Check for new incidents
            incidents = await self.get_current_incidents()
            logger.info(f"📊 Current incidents in system: {len(incidents)}")
            
            # Show latest incident if any
            if incidents:
                latest = incidents[0]
                logger.info(f"   Latest incident: {latest.get('description', 'N/A')}")
                logger.info(f"   State: {latest.get('state', 'unknown')}")
                logger.info(f"   Service: {latest.get('service', 'unknown')}")
            
            # Wait before next scenario
            if i < len(self.scenarios):
                logger.info("⏸️  Waiting before next scenario...")
                await asyncio.sleep(3)
    
    async def run_monitoring_demo(self) -> None:
        """Demonstrate real-time monitoring capabilities."""
        logger.info("\n🔍 Real-time Monitoring Demo")
        logger.info("=" * 50)
        
        for i in range(10):
            # Get current stats
            stats = await self.get_system_stats()
            
            if stats:
                logger.info(f"📈 Stats Update {i+1}/10:")
                logger.info(f"   Total incidents: {stats.get('total_incidents', 0)}")
                logger.info(f"   Resolution rate: {stats.get('resolution_rate', 0)}%")
                logger.info(f"   Active connections: {stats.get('active_connections', 0)}")
                
                # Show incident breakdown
                by_severity = stats.get('by_severity', {})
                if by_severity:
                    logger.info(f"   By severity: {by_severity}")
            else:
                logger.info(f"📉 No stats available (attempt {i+1}/10)")
            
            await asyncio.sleep(2)
    
    async def run_interactive_demo(self) -> None:
        """Run interactive demo with user input."""
        logger.info("\n🎮 Interactive Demo Mode")
        logger.info("=" * 50)
        
        while True:
            print("\nIRO Demo Options:")
            print("1. Simulate random incident")
            print("2. Show current incidents")
            print("3. Show system statistics")
            print("4. Test WebSocket connection")
            print("5. Run all scenarios")
            print("6. Exit")
            
            try:
                choice = input("\nSelect an option (1-6): ").strip()
                
                if choice == '1':
                    scenario = random.choice(self.scenarios)
                    await self.simulate_incident(scenario)
                
                elif choice == '2':
                    incidents = await self.get_current_incidents()
                    if incidents:
                        print(f"\n📋 Found {len(incidents)} incidents:")
                        for incident in incidents[:5]:  # Show top 5
                            print(f"   • {incident.get('service')}: {incident.get('description')}")
                    else:
                        print("\n✅ No incidents found")
                
                elif choice == '3':
                    stats = await self.get_system_stats()
                    if stats:
                        print(f"\n📊 System Statistics:")
                        print(json.dumps(stats, indent=2))
                    else:
                        print("\n❌ No statistics available")
                
                elif choice == '4':
                    await self.demonstrate_websocket()
                
                elif choice == '5':
                    await self.run_scenario_demo()
                
                elif choice == '6':
                    logger.info("👋 Exiting interactive demo")
                    break
                
                else:
                    print("❌ Invalid option, please try again")
            
            except KeyboardInterrupt:
                logger.info("\n🛑 Demo interrupted by user")
                break
            except Exception as e:
                logger.error(f"❌ Error in interactive demo: {e}")
    
    async def run_full_demo(self) -> None:
        """Run the complete demo suite."""
        logger.info("🚀 Starting IRO Complete Demo")
        logger.info("=" * 50)
        
        # Check if IRO is running
        if not await self.check_iro_health():
            logger.error("❌ IRO is not running or not healthy!")
            logger.info("💡 Start IRO with: python -m src.iro.main")
            return
        
        logger.info("✅ IRO is running and healthy")
        
        # Run scenario demo
        await self.run_scenario_demo()
        
        # Show WebSocket capabilities
        await self.demonstrate_websocket()
        
        # Run monitoring demo
        await self.run_monitoring_demo()
        
        # Final summary
        logger.info("\n📋 Demo Summary")
        logger.info("=" * 50)
        
        incidents = await self.get_current_incidents()
        stats = await self.get_system_stats()
        
        logger.info(f"✨ Demo completed successfully!")
        logger.info(f"📊 Total incidents created: {len(incidents)}")
        logger.info(f"📈 Final statistics: {stats}")
        logger.info(f"🌐 Dashboard available at: {self.base_url}")
        
        logger.info("\n🎯 What you've seen:")
        logger.info("   • Incident detection simulation")
        logger.info("   • Real-time monitoring capabilities")
        logger.info("   • WebSocket live updates")
        logger.info("   • System health checking")
        logger.info("   • Statistics and reporting")


async def main():
    """Main demo function."""
    import argparse
    
    parser = argparse.ArgumentParser(description="IRO Demo Script")
    parser.add_argument(
        "--url", 
        default="http://localhost:8080",
        help="IRO base URL (default: http://localhost:8080)"
    )
    parser.add_argument(
        "--mode",
        choices=["full", "scenarios", "monitoring", "interactive"],
        default="full",
        help="Demo mode to run"
    )
    
    args = parser.parse_args()
    
    async with IRODemo(args.url) as demo:
        try:
            if args.mode == "full":
                await demo.run_full_demo()
            elif args.mode == "scenarios":
                await demo.run_scenario_demo()
            elif args.mode == "monitoring":
                await demo.run_monitoring_demo()
            elif args.mode == "interactive":
                await demo.run_interactive_demo()
        
        except KeyboardInterrupt:
            logger.info("\n🛑 Demo stopped by user")
        except Exception as e:
            logger.error(f"❌ Demo failed: {e}")
            raise


if __name__ == "__main__":
    asyncio.run(main())