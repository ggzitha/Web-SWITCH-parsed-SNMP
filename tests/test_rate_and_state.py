"""
Unit tests for monotonic rate interpolation, state management, and RFC compliance.
"""

import os
import time
import pytest
from app.mib_tree import SwitchMibBuilder, str_to_oid
from app.scraper import SwitchSnapshot, PortStatisticsItem
from app.state import StateManager


def test_rate_interpolation_monotonic():
    """Verify that packet counters extrapolate smoothly and monotonically between scrapes."""
    builder = SwitchMibBuilder(start_time=time.time() - 3600)

    # Scrape 1 at t=1000
    t1 = 1000.0
    snap1 = SwitchSnapshot(
        switch_id=1,
        ip="192.168.88.150",
        name="Test-Switch",
        last_scraped=t1,
        status="ONLINE",
        port_stats={
            1: PortStatisticsItem(port=1, link_status="1000M Full", rx_good_pkt=10000, tx_good_pkt=20000)
        }
    )
    builder.build_oid_map(snap1)

    # Scrape 2 at t=1060 (60s later): 600 new RX packets, 1200 new TX packets (10 pkts/s and 20 pkts/s)
    t2 = 1060.0
    snap2 = SwitchSnapshot(
        switch_id=1,
        ip="192.168.88.150",
        name="Test-Switch",
        last_scraped=t2,
        status="ONLINE",
        port_stats={
            1: PortStatisticsItem(port=1, link_status="1000M Full", rx_good_pkt=10600, tx_good_pkt=21200)
        }
    )
    builder.build_oid_map(snap2)

    tracker = builder.port_trackers[1]
    assert tracker.rx_pkt_rate == pytest.approx(10.0, rel=1e-2)
    assert tracker.tx_pkt_rate == pytest.approx(20.0, rel=1e-2)

    # Query between scrapes: counter must strictly be >= 10600 and monotonic
    rx_served, tx_served = builder._update_rates_and_interpolate(1, 10600, 21200, t2, True)
    assert rx_served >= 10600
    assert tx_served >= 21200


def test_rfc2863_ifmib_compliance():
    """Verify RFC 2863 IF-MIB and RFC 1213 mandatory OIDs exist."""
    builder = SwitchMibBuilder(start_time=time.time() - 100)
    snap = SwitchSnapshot(
        switch_id=1,
        ip="192.168.88.150",
        name="TL-SG1016PE",
        last_scraped=time.time(),
        status="ONLINE",
        port_stats={
            1: PortStatisticsItem(port=1, link_status="1000M Full", rx_good_pkt=5000, tx_good_pkt=6000)
        }
    )
    oid_map = builder.build_oid_map(snap)

    # System group
    assert str_to_oid("1.3.6.1.2.1.1.1.0") in oid_map  # sysDescr
    assert str_to_oid("1.3.6.1.2.1.1.2.0") in oid_map  # sysObjectID
    assert str_to_oid("1.3.6.1.2.1.1.3.0") in oid_map  # sysUpTime
    assert str_to_oid("1.3.6.1.2.1.1.5.0") in oid_map  # sysName

    # ifTable
    assert str_to_oid("1.3.6.1.2.1.2.2.1.1.1") in oid_map   # ifIndex.1
    assert str_to_oid("1.3.6.1.2.1.2.2.1.2.1") in oid_map   # ifDescr.1
    assert str_to_oid("1.3.6.1.2.1.2.2.1.3.1") in oid_map   # ifType.1 (6 = ethernet)
    assert str_to_oid("1.3.6.1.2.1.2.2.1.5.1") in oid_map   # ifSpeed.1
    assert str_to_oid("1.3.6.1.2.1.2.2.1.8.1") in oid_map   # ifOperStatus.1
    assert str_to_oid("1.3.6.1.2.1.2.2.1.10.1") in oid_map  # ifInOctets.1
    assert str_to_oid("1.3.6.1.2.1.2.2.1.11.1") in oid_map  # ifInUcastPkts.1
    assert str_to_oid("1.3.6.1.2.1.2.2.1.13.1") in oid_map  # ifInDiscards.1
    assert str_to_oid("1.3.6.1.2.1.2.2.1.16.1") in oid_map  # ifOutOctets.1
    assert str_to_oid("1.3.6.1.2.1.2.2.1.17.1") in oid_map  # ifOutUcastPkts.1
    assert str_to_oid("1.3.6.1.2.1.2.2.1.19.1") in oid_map  # ifOutDiscards.1

    # ifXTable
    assert str_to_oid("1.3.6.1.2.1.31.1.1.1.6.1") in oid_map   # ifHCInOctets.1
    assert str_to_oid("1.3.6.1.2.1.31.1.1.1.10.1") in oid_map  # ifHCOutOctets.1
    assert str_to_oid("1.3.6.1.2.1.31.1.1.1.15.1") in oid_map  # ifHighSpeed.1
    assert str_to_oid("1.3.6.1.2.1.31.1.1.1.17.1") in oid_map  # ifConnectorPresent.1

    # Latency and Status OIDs
    assert str_to_oid("1.3.6.1.4.1.11863.6.1.8.0") in oid_map   # latency gauge
    assert str_to_oid("1.3.6.1.4.1.11863.6.1.9.0") in oid_map   # latency string
    assert str_to_oid("1.3.6.1.4.1.11863.6.1.10.0") in oid_map  # status int


def test_state_manager_persistence(tmp_path):
    """Verify that StateManager persists boot times and detects physical reboots."""
    test_state_file = os.path.join(tmp_path, "state.json")
    mgr = StateManager(state_file=test_state_file)

    # Initial boot time
    b1 = mgr.get_boot_time(1)
    assert b1 > 0

    # Record normal packet traffic
    reboot = mgr.record_packets_and_check_reboot(1, 50000)
    assert not reboot

    # Reload from disk in a new instance (simulating container restart)
    mgr2 = StateManager(state_file=test_state_file)
    assert mgr2.get_boot_time(1) == b1

    # Simulate physical switch reboot (packets reset to 0)
    reboot = mgr2.record_packets_and_check_reboot(1, 5)
    assert reboot
    # Boot time should now be updated to a newer timestamp
    assert mgr2.get_boot_time(1) > b1


@pytest.mark.asyncio
async def test_probe_latency_mock():
    """Verify probe_latency measures real connection response times."""
    import asyncio
    from app.config import SwitchTarget
    from app.scraper import TpLinkSwitchScraper

    # Start a mock TCP server on random port
    server = await asyncio.start_server(lambda r, w: None, '127.0.0.1', 0)
    port = server.sockets[0].getsockname()[1]

    target = SwitchTarget(id=99, ip=f"127.0.0.1:{port}", user="admin", password="password", snmp_port=16199)
    scraper = TpLinkSwitchScraper(target)

    async with server:
        lat = await scraper.probe_latency()
        assert lat is not None
        assert lat > 0.0
        assert scraper.snapshot.latency_ms > 0.0

    # Server closed: probe should fail and return None
    lat_fail = await scraper.probe_latency()
    assert lat_fail is None
    assert scraper.snapshot.latency_ms == 0.0
