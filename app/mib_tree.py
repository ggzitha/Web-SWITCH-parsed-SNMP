"""
SNMP MIB Tree builder for TP-Link Easy Smart Switches.
Provides standard MIBs (MIB-II, IF-MIB, POWER-ETHERNET-MIB RFC 3621)
and Enterprise custom OIDs (1.3.6.1.4.1.11863.6) for full Zabbix compatibility.
"""

import datetime
import re
import time
from typing import Dict, Tuple, Any

from pysnmp.proto import rfc1902
from .scraper import SwitchSnapshot


def str_to_oid(oid_str: str) -> Tuple[int, ...]:
    """Convert dotted OID string to tuple of integers."""
    return tuple(int(x) for x in oid_str.strip(".").split("."))


def oid_to_str(oid_tuple: Tuple[int, ...]) -> str:
    """Convert tuple of integers to dotted OID string."""
    return ".".join(str(x) for x in oid_tuple)


class SwitchMibBuilder:
    """Builds a complete, queryable dictionary of SNMP OIDs from a SwitchSnapshot."""

    def __init__(self, start_time: float):
        self.start_time = start_time

    def build_oid_map(self, snapshot: SwitchSnapshot) -> Dict[Tuple[int, ...], Any]:
        """Convert snapshot into a sorted map of (tuple_oid) -> rfc1902 ASN.1 value."""
        oids: Dict[Tuple[int, ...], Any] = {}
        now = time.time()
        uptime_hundredths = int((now - self.start_time) * 100)

        # ------------------------------------------------------------------
        # 1. SNMPv2-MIB / RFC 1213 System Group (1.3.6.1.2.1.1)
        # ------------------------------------------------------------------
        sys_descr = f"TP-Link {snapshot.model} Easy Smart Switch ({snapshot.name})"
        oids[str_to_oid("1.3.6.1.2.1.1.1.0")] = rfc1902.OctetString(sys_descr)
        oids[str_to_oid("1.3.6.1.2.1.1.2.0")] = rfc1902.ObjectIdentifier((1, 3, 6, 1, 4, 1, 11863, 1, 1))
        oids[str_to_oid("1.3.6.1.2.1.1.3.0")] = rfc1902.TimeTicks(uptime_hundredths)
        oids[str_to_oid("1.3.6.1.2.1.1.4.0")] = rfc1902.OctetString("admin@local")
        # sysName returns the REAL switch IP as requested by the user!
        oids[str_to_oid("1.3.6.1.2.1.1.5.0")] = rfc1902.OctetString(snapshot.ip)
        oids[str_to_oid("1.3.6.1.2.1.1.6.0")] = rfc1902.OctetString(snapshot.name or "Rack 1")
        oids[str_to_oid("1.3.6.1.2.1.1.7.0")] = rfc1902.Integer32(2)  # datalink layer

        # ------------------------------------------------------------------
        # 2. IF-MIB (1.3.6.1.2.1.2 and 1.3.6.1.2.1.31)
        # ------------------------------------------------------------------
        ports = snapshot.port_stats
        total_ports = len(ports) if ports else 16
        oids[str_to_oid("1.3.6.1.2.1.2.1.0")] = rfc1902.Integer32(total_ports)

        for p_num, p in sorted(ports.items()):
            # Parse speed
            speed_bps = 0
            speed_mbps = 0
            if "1000M" in p.link_status:
                speed_bps = 1_000_000_000
                speed_mbps = 1000
            elif "100M" in p.link_status:
                speed_bps = 100_000_000
                speed_mbps = 100
            elif "10M" in p.link_status:
                speed_bps = 10_000_000
                speed_mbps = 10

            admin_status = 1 if p.status == "Enabled" else 2
            oper_status = 1 if p.link_status != "Link Down" else 2

            # Estimate octets based on packets (average 512 bytes per packet)
            rx_octets = (p.rx_good_pkt * 512) % (2**32)
            tx_octets = (p.tx_good_pkt * 512) % (2**32)
            rx_hc_octets = p.rx_good_pkt * 512
            tx_hc_octets = p.tx_good_pkt * 512

            # ifTable (1.3.6.1.2.1.2.2.1)
            oids[str_to_oid(f"1.3.6.1.2.1.2.2.1.1.{p_num}")] = rfc1902.Integer32(p_num)
            oids[str_to_oid(f"1.3.6.1.2.1.2.2.1.2.{p_num}")] = rfc1902.OctetString(f"Port {p_num}")
            oids[str_to_oid(f"1.3.6.1.2.1.2.2.1.3.{p_num}")] = rfc1902.Integer32(6)  # ethernetCsmacd
            oids[str_to_oid(f"1.3.6.1.2.1.2.2.1.4.{p_num}")] = rfc1902.Integer32(1500)
            oids[str_to_oid(f"1.3.6.1.2.1.2.2.1.5.{p_num}")] = rfc1902.Gauge32(speed_bps)
            oids[str_to_oid(f"1.3.6.1.2.1.2.2.1.7.{p_num}")] = rfc1902.Integer32(admin_status)
            oids[str_to_oid(f"1.3.6.1.2.1.2.2.1.8.{p_num}")] = rfc1902.Integer32(oper_status)
            oids[str_to_oid(f"1.3.6.1.2.1.2.2.1.10.{p_num}")] = rfc1902.Counter32(rx_octets)
            oids[str_to_oid(f"1.3.6.1.2.1.2.2.1.11.{p_num}")] = rfc1902.Counter32(p.rx_good_pkt % (2**32))
            oids[str_to_oid(f"1.3.6.1.2.1.2.2.1.14.{p_num}")] = rfc1902.Counter32(p.rx_bad_pkt % (2**32))
            oids[str_to_oid(f"1.3.6.1.2.1.2.2.1.16.{p_num}")] = rfc1902.Counter32(tx_octets)
            oids[str_to_oid(f"1.3.6.1.2.1.2.2.1.17.{p_num}")] = rfc1902.Counter32(p.tx_good_pkt % (2**32))
            oids[str_to_oid(f"1.3.6.1.2.1.2.2.1.20.{p_num}")] = rfc1902.Counter32(p.tx_bad_pkt % (2**32))

            # ifXTable (1.3.6.1.2.1.31.1.1.1) - 64-bit high-capacity counters
            oids[str_to_oid(f"1.3.6.1.2.1.31.1.1.1.1.{p_num}")] = rfc1902.OctetString(f"Port {p_num}")
            oids[str_to_oid(f"1.3.6.1.2.1.31.1.1.1.6.{p_num}")] = rfc1902.Counter64(rx_hc_octets)
            oids[str_to_oid(f"1.3.6.1.2.1.31.1.1.1.7.{p_num}")] = rfc1902.Counter64(p.rx_good_pkt)
            oids[str_to_oid(f"1.3.6.1.2.1.31.1.1.1.10.{p_num}")] = rfc1902.Counter64(tx_hc_octets)
            oids[str_to_oid(f"1.3.6.1.2.1.31.1.1.1.11.{p_num}")] = rfc1902.Counter64(p.tx_good_pkt)
            oids[str_to_oid(f"1.3.6.1.2.1.31.1.1.1.15.{p_num}")] = rfc1902.Gauge32(speed_mbps)
            oids[str_to_oid(f"1.3.6.1.2.1.31.1.1.1.18.{p_num}")] = rfc1902.OctetString(f"Port {p_num}")

        # ------------------------------------------------------------------
        # 3. POWER-ETHERNET-MIB (RFC 3621: 1.3.6.1.2.1.105)
        # ------------------------------------------------------------------
        g_poe = snapshot.global_poe
        oids[str_to_oid("1.3.6.1.2.1.105.1.3.1.1.2.1")] = rfc1902.Integer32(int(g_poe.power_limit))
        oids[str_to_oid("1.3.6.1.2.1.105.1.3.1.1.3.1")] = rfc1902.Integer32(1)  # on
        oids[str_to_oid("1.3.6.1.2.1.105.1.3.1.1.4.1")] = rfc1902.Gauge32(int(g_poe.power_consumption))

        poe_ports = snapshot.poe_stats
        for p_num, poe in sorted(poe_ports.items()):
            # Admin enable (1=true, 2=false)
            admin_en = 1 if poe.poe_status == "Enable" else 2
            # Detection status: 1=disabled, 2=searching, 3=deliveringPower, 4=fault
            det_status = 3 if poe.power_status == "ON" else (2 if poe.poe_status == "Enable" else 1)
            # Power priority: 1=critical, 2=high, 3=low
            prio = 1 if poe.poe_priority == "High" else (2 if poe.poe_priority == "Middle" else 3)
            # Classification
            class_num = 3
            match = re.search(r"\d+", poe.pd_class)
            if match:
                class_num = int(match.group(0))

            oids[str_to_oid(f"1.3.6.1.2.1.105.1.1.1.3.1.{p_num}")] = rfc1902.Integer32(admin_en)
            oids[str_to_oid(f"1.3.6.1.2.1.105.1.1.1.4.1.{p_num}")] = rfc1902.Integer32(1)
            oids[str_to_oid(f"1.3.6.1.2.1.105.1.1.1.5.1.{p_num}")] = rfc1902.Integer32(1)
            oids[str_to_oid(f"1.3.6.1.2.1.105.1.1.1.6.1.{p_num}")] = rfc1902.Integer32(det_status)
            oids[str_to_oid(f"1.3.6.1.2.1.105.1.1.1.7.1.{p_num}")] = rfc1902.Integer32(prio)
            oids[str_to_oid(f"1.3.6.1.2.1.105.1.1.1.10.1.{p_num}")] = rfc1902.Integer32(class_num)

        # ------------------------------------------------------------------
        # 4. Custom Enterprise MIB (1.3.6.1.4.1.11863.6)
        # Dedicated OIDs for exact metrics from TP-Link Web GUI
        # ------------------------------------------------------------------
        # 4.1 System Overview
        last_scrape_iso = datetime.datetime.fromtimestamp(snapshot.last_scraped).isoformat() if snapshot.last_scraped > 0 else "Never"
        oids[str_to_oid("1.3.6.1.4.1.11863.6.1.1.0")] = rfc1902.OctetString(snapshot.model)
        oids[str_to_oid("1.3.6.1.4.1.11863.6.1.2.0")] = rfc1902.OctetString(snapshot.ip)
        oids[str_to_oid("1.3.6.1.4.1.11863.6.1.3.0")] = rfc1902.OctetString(snapshot.status)
        oids[str_to_oid("1.3.6.1.4.1.11863.6.1.4.0")] = rfc1902.OctetString(last_scrape_iso)
        oids[str_to_oid("1.3.6.1.4.1.11863.6.1.5.0")] = rfc1902.Gauge32(int(g_poe.power_limit * 10))
        oids[str_to_oid("1.3.6.1.4.1.11863.6.1.6.0")] = rfc1902.Gauge32(int(g_poe.power_consumption * 10))
        oids[str_to_oid("1.3.6.1.4.1.11863.6.1.7.0")] = rfc1902.Gauge32(int(g_poe.power_remain * 10))

        # 4.2 Port Statistics Table (1.3.6.1.4.1.11863.6.2.1)
        for p_num, p in sorted(ports.items()):
            oids[str_to_oid(f"1.3.6.1.4.1.11863.6.2.1.1.{p_num}")] = rfc1902.Integer32(p_num)
            oids[str_to_oid(f"1.3.6.1.4.1.11863.6.2.1.2.{p_num}")] = rfc1902.OctetString(f"Port {p_num}")
            oids[str_to_oid(f"1.3.6.1.4.1.11863.6.2.1.3.{p_num}")] = rfc1902.OctetString(p.status)
            oids[str_to_oid(f"1.3.6.1.4.1.11863.6.2.1.4.{p_num}")] = rfc1902.OctetString(p.link_status)
            oids[str_to_oid(f"1.3.6.1.4.1.11863.6.2.1.5.{p_num}")] = rfc1902.Counter64(p.tx_good_pkt)
            oids[str_to_oid(f"1.3.6.1.4.1.11863.6.2.1.6.{p_num}")] = rfc1902.Counter64(p.tx_bad_pkt)
            oids[str_to_oid(f"1.3.6.1.4.1.11863.6.2.1.7.{p_num}")] = rfc1902.Counter64(p.rx_good_pkt)
            oids[str_to_oid(f"1.3.6.1.4.1.11863.6.2.1.8.{p_num}")] = rfc1902.Counter64(p.rx_bad_pkt)

        # 4.3 PoE Config Table (1.3.6.1.4.1.11863.6.3.1)
        for p_num, poe in sorted(poe_ports.items()):
            oids[str_to_oid(f"1.3.6.1.4.1.11863.6.3.1.1.{p_num}")] = rfc1902.Integer32(p_num)
            oids[str_to_oid(f"1.3.6.1.4.1.11863.6.3.1.2.{p_num}")] = rfc1902.OctetString(poe.poe_status)
            oids[str_to_oid(f"1.3.6.1.4.1.11863.6.3.1.3.{p_num}")] = rfc1902.OctetString(poe.poe_priority)
            oids[str_to_oid(f"1.3.6.1.4.1.11863.6.3.1.4.{p_num}")] = rfc1902.OctetString(poe.power_limit)
            oids[str_to_oid(f"1.3.6.1.4.1.11863.6.3.1.5.{p_num}")] = rfc1902.Gauge32(int(poe.power_w * 10)) # 0.1W
            oids[str_to_oid(f"1.3.6.1.4.1.11863.6.3.1.6.{p_num}")] = rfc1902.OctetString(f"{poe.power_w:.1f}")
            oids[str_to_oid(f"1.3.6.1.4.1.11863.6.3.1.7.{p_num}")] = rfc1902.Gauge32(int(poe.current_ma)) # mA
            oids[str_to_oid(f"1.3.6.1.4.1.11863.6.3.1.8.{p_num}")] = rfc1902.Gauge32(int(poe.voltage_v * 10)) # 0.1V
            oids[str_to_oid(f"1.3.6.1.4.1.11863.6.3.1.9.{p_num}")] = rfc1902.OctetString(f"{poe.voltage_v:.1f}")
            oids[str_to_oid(f"1.3.6.1.4.1.11863.6.3.1.10.{p_num}")] = rfc1902.OctetString(poe.pd_class)
            oids[str_to_oid(f"1.3.6.1.4.1.11863.6.3.1.11.{p_num}")] = rfc1902.OctetString(poe.power_status)
            oids[str_to_oid(f"1.3.6.1.4.1.11863.6.3.1.12.{p_num}")] = rfc1902.Gauge32(int(poe.power_w * 1000)) # mW

        return oids
