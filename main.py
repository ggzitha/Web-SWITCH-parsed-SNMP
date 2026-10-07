"""
Application Entry Point for TP-Link Easy Smart Switch Web-to-SNMP Gateway.
Orchestrates:
1. Periodic background scraper for all configured switches.
2. Independent SNMP v2c / v3 Agents for each switch on its assigned UDP port.
3. Web Dashboard and REST API for real-time monitoring and OID inspection.
4. Memory garbage collection and persistent state management to preserve uptime across restarts.
"""

import asyncio
import gc
import logging
import signal
import sys
import threading
import time
from typing import Dict

from app.config import parse_config, AppConfig, SwitchTarget
from app.scraper import TpLinkSwitchScraper, SwitchSnapshot
from app.simulator import MockSwitchState
from app.snmp_server import SwitchSnmpAgent
from app.state import StateManager
from app.web import create_web_app

# Store active switch snapshots in memory
snapshots: Dict[int, SwitchSnapshot] = {}
scrapers: Dict[int, TpLinkSwitchScraper] = {}
simulators: Dict[int, MockSwitchState] = {}
snmp_agents: Dict[int, SwitchSnmpAgent] = {}
state_manager = StateManager()
shutdown_event = asyncio.Event()


async def scrape_loop(target: SwitchTarget, interval: int, mock_mode: bool):
    """Continuous scraper loop for a single switch target."""
    scraper = scrapers.get(target.id)
    sim = simulators.get(target.id)

    logger = logging.getLogger(f"scraper.{target.id}")
    logger.info("Starting scrape loop for %s (Refresh: %ds, Mock: %s)", target.name, interval, mock_mode)

    while not shutdown_event.is_set():
        try:
            if mock_mode:
                snap = sim.generate_snapshot()
            else:
                snap = await scraper.scrape()
            snapshots[target.id] = snap

            # Check if physical switch rebooted (packet counters reset)
            total_pkts = sum(p.rx_good_pkt + p.tx_good_pkt for p in snap.port_stats.values())
            if state_manager.record_packets_and_check_reboot(target.id, total_pkts):
                agent = snmp_agents.get(target.id)
                if agent:
                    new_boot = state_manager.get_boot_time(target.id)
                    agent.start_time = new_boot
                    if hasattr(agent, "mib_builder_helper"):
                        agent.mib_builder_helper.start_time = new_boot
        except Exception as e:
            logger.error("[%s] Unexpected scrape error: %s", target.name, e)
            if mock_mode:
                snap = sim.generate_snapshot()
                snapshots[target.id] = snap
            else:
                snapshots[target.id] = SwitchSnapshot(
                    switch_id=target.id,
                    ip=target.clean_ip,
                    name=target.name,
                    status="OFFLINE",
                    error_message=str(e),
                    model=target.model
                )

        # Wait for the next refresh interval or until shutdown
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass


async def maintenance_loop():
    """Periodic maintenance loop for cyclic garbage collection and state persistence."""
    logger = logging.getLogger("maintenance")
    while not shutdown_event.is_set():
        try:
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=300)
                break
            except asyncio.TimeoutError:
                pass

            # 1. Cyclic Garbage Collection to reclaim memory from HTML trees and ASN.1 objects
            collected = gc.collect()
            logger.debug("Periodic maintenance: garbage collector freed %d cyclic objects", collected)

            # 2. Persist state to disk
            state_manager.save()
        except Exception as e:
            logger.warning("Maintenance error: %s", e)


def get_snapshot_for_switch(switch_id: int) -> SwitchSnapshot:
    """Callback returning the latest snapshot for a specific switch."""
    if switch_id in snapshots:
        return snapshots[switch_id]
    return SwitchSnapshot(switch_id=switch_id, ip="0.0.0.0", name="Unknown", status="OFFLINE")


def get_all_snapshots() -> Dict[int, SwitchSnapshot]:
    """Callback returning all current snapshots."""
    return dict(snapshots)


def run_flask(app, host: str, port: int):
    """Run Flask server in background thread with multithreading enabled."""
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    app.run(host=host, port=port, debug=False, use_reloader=False, threaded=True)


async def main():
    config: AppConfig = parse_config()

    logging.basicConfig(
        level=getattr(logging, config.log_level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    logger = logging.getLogger("gateway")

    logger.info("=" * 70)
    logger.info("TP-Link Easy Smart Web-to-SNMP Gateway Starting")
    logger.info("Active Switches Configured: %d", len(config.switches))
    logger.info("SNMP Version: %s | Community: %s", config.snmp.version, config.snmp.community)
    logger.info("Scrape Refresh Interval: %ds (env: REFRESHED_PAGE)", config.refresh_interval)
    logger.info("Web Dashboard: http://%s:%d", config.app_host, config.web_port)
    logger.info("=" * 70)

    # 1. Initialize data structures and scrapers for each switch
    for target in config.switches:
        scrapers[target.id] = TpLinkSwitchScraper(target)
        if config.mock_mode:
            simulators[target.id] = MockSwitchState(target)
            snapshots[target.id] = simulators[target.id].generate_snapshot()
        else:
            snapshots[target.id] = SwitchSnapshot(
                switch_id=target.id,
                ip=target.clean_ip,
                name=target.name,
                status="INITIALIZING",
                model=target.model
            )

    # 2. Start SNMP Agents for each switch on its designated UDP port
    for target in config.switches:
        switch_boot_time = state_manager.get_boot_time(target.id)
        agent = SwitchSnmpAgent(
            bind_host=config.app_host,
            target=target,
            snmp_config=config.snmp,
            get_snapshot=lambda s_id=target.id: get_snapshot_for_switch(s_id),
            start_time=switch_boot_time
        )
        try:
            agent.start()
            snmp_agents[target.id] = agent
        except Exception as e:
            logger.error("[%s] Failed to bind SNMP on port %d: %s", target.name, target.snmp_port, e)

    # 3. Start Web Dashboard in thread
    flask_app = create_web_app(config, get_all_snapshots, time.time())
    web_thread = threading.Thread(
        target=run_flask,
        args=(flask_app, config.app_host, config.web_port),
        daemon=True
    )
    web_thread.start()
    logger.info("Web Dashboard running at http://%s:%d", config.app_host, config.web_port)

    # 4. Launch scraper tasks and maintenance loop
    scrape_tasks = []
    for target in config.switches:
        task = asyncio.create_task(
            scrape_loop(target, config.refresh_interval, config.mock_mode)
        )
        scrape_tasks.append(task)

    maintenance_task = asyncio.create_task(maintenance_loop())

    # Handle graceful exit
    loop = asyncio.get_running_loop()
    def stop():
        logger.info("Shutdown signal received, closing services...")
        shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop)
        except NotImplementedError:
            pass

    try:
        await shutdown_event.wait()
    except (KeyboardInterrupt, SystemExit):
        stop()

    # Cleanup
    for agent in snmp_agents.values():
        agent.stop()
    for scraper in scrapers.values():
        await scraper.close()
    for task in scrape_tasks:
        task.cancel()
    maintenance_task.cancel()

    state_manager.save()
    logger.info("Gateway terminated cleanly.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
    except Exception as e:
        logging.critical("Fatal exception in main: %s", e, exc_info=True)
        sys.exit(1)
