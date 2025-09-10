#!/usr/bin/env python3
"""
Incident Response Orchestrator (IRO) - Main Entry Point
A simplified Python implementation for automated incident detection and remediation.
"""

import asyncio
import logging
import signal
import sys
from pathlib import Path

from src.iro.config import load_config
from src.iro.orchestrator import IncidentOrchestrator
from src.iro.utils.logger import setup_logging


async def main():
    """Main entry point for the IRO system."""
    # Setup logging
    setup_logging()
    logger = logging.getLogger(__name__)
    
    try:
        # Load configuration
        config = load_config()
        logger.info(f"Starting Incident Response Orchestrator v{config.version}")
        
        # Create and start orchestrator
        orchestrator = IncidentOrchestrator(config)
        
        # Setup graceful shutdown
        stop_event = asyncio.Event()
        
        def signal_handler():
            logger.info("Received shutdown signal")
            stop_event.set()
        
        # Register signal handlers
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda s, f: signal_handler())
        
        # Start the orchestrator
        await orchestrator.start()
        
        # Wait for shutdown signal
        await stop_event.wait()
        
    except Exception as e:
        logger.error(f"Failed to start IRO: {e}")
        sys.exit(1)
    
    finally:
        # Graceful shutdown
        logger.info("Shutting down IRO...")
        if 'orchestrator' in locals():
            await orchestrator.stop()
        logger.info("IRO shutdown complete")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutdown initiated by user")
        sys.exit(0)