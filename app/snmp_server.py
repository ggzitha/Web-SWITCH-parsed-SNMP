"""
SNMP Agent Server for TP-Link Easy Smart Switches.
Supports both SNMP v2c (Community) and SNMP v3 (USM Auth/Priv).
Dynamically serves the latest scraped SwitchSnapshot for each switch port.
"""

import asyncio
import logging
import time
from typing import Callable, Optional, Dict, Tuple, Any

from pysnmp.carrier.asyncio.dgram import udp
from pysnmp.entity import engine, config
from pysnmp.entity.rfc3413 import cmdrsp
from pysnmp.entity.rfc3413.context import SnmpContext
from pysnmp.smi import instrum, exval, builder
import pysnmp.hlapi.asyncio as hlapi

from .config import SnmpConfig, SwitchTarget
from .scraper import SwitchSnapshot
from .mib_tree import SwitchMibBuilder

logger = logging.getLogger(__name__)

# Protocol mapping dictionaries
AUTH_PROTOCOLS = {
    "MD5": hlapi.usmHMACMD5AuthProtocol,
    "SHA": hlapi.usmHMACSHAAuthProtocol,
    "SHA1": hlapi.usmHMACSHAAuthProtocol,
    "SHA224": hlapi.usmHMAC128SHA224AuthProtocol,
    "SHA256": hlapi.usmHMAC192SHA256AuthProtocol,
    "SHA384": hlapi.usmHMAC256SHA384AuthProtocol,
    "SHA512": hlapi.usmHMAC384SHA512AuthProtocol,
}

PRIV_PROTOCOLS = {
    "DES": hlapi.usmDESPrivProtocol,
    "AES": hlapi.usmAesCfb128Protocol,
    "AES128": hlapi.usmAesCfb128Protocol,
    "AES192": hlapi.usmAesCfb192Protocol,
    "AES256": hlapi.usmAesCfb256Protocol,
    "3DES": hlapi.usm3DESEDEPrivProtocol,
}


from pysnmp.smi.error import PySnmpError

class DynamicSwitchMibInstrum(instrum.MibInstrumController):
    """Dynamic MIB Instrumentation Controller that reads fresh data on every SNMP request."""

    def __init__(self, mib_builder: builder.MibBuilder, get_snapshot: Callable[[], SwitchSnapshot], start_time: float):
        super().__init__(mib_builder)
        self.get_snapshot = get_snapshot
        self.mib_builder_helper = SwitchMibBuilder(start_time)

    def _get_current_oids(self) -> Dict[Tuple[int, ...], Any]:
        snapshot = self.get_snapshot()
        return self.mib_builder_helper.build_oid_map(snapshot)

    def read_variables(self, *varBinds, **context):
        """Handle SNMP GET requests."""
        snapshot = self.get_snapshot()
        if snapshot.status != "ONLINE":
            # Device is offline / powered off / unreachable.
            # Raising PySnmpError causes PySNMP to silently drop the packet,
            # producing a standard network timeout so Zabbix / snmpwalk marks host DOWN.
            raise PySnmpError(f"Switch {snapshot.name} ({snapshot.ip}) is {snapshot.status}")
        oids = self._get_current_oids()
        res = []
        for name, _ in varBinds:
            t = tuple(name)
            val = oids.get(t, exval.noSuchInstance)
            res.append((name, val))
        return res

    def read_next_variables(self, *varBinds, **context):
        """Handle SNMP GETNEXT and GETBULK requests."""
        snapshot = self.get_snapshot()
        if snapshot.status != "ONLINE":
            # Device is offline / powered off / unreachable.
            raise PySnmpError(f"Switch {snapshot.name} ({snapshot.ip}) is {snapshot.status}")
        oids = self._get_current_oids()
        sorted_keys = sorted(oids.keys())
        res = []
        for name, _ in varBinds:
            t = tuple(name)
            nxt = next((k for k in sorted_keys if k > t), None)
            if nxt:
                res.append((nxt, oids[nxt]))
            else:
                res.append((name, exval.endOfMibView))
        return res


class SwitchSnmpAgent:
    """Manages an SNMP Agent instance listening on a dedicated UDP port for a specific switch."""

    def __init__(
        self,
        bind_host: str,
        target: SwitchTarget,
        snmp_config: SnmpConfig,
        get_snapshot: Callable[[], SwitchSnapshot],
        start_time: float
    ):
        self.bind_host = bind_host
        self.target = target
        self.snmp_config = snmp_config
        self.get_snapshot = get_snapshot
        self.start_time = start_time

        self.snmp_engine: Optional[engine.SnmpEngine] = None
        self.is_running = False

    def start(self):
        """Initialize SNMP engine and register listeners for v2c and v3."""
        logger.info(
            "[%s] Initializing SNMP Agent on %s:%d (Target: %s, Real IP: %s)",
            self.target.name,
            self.bind_host,
            self.target.snmp_port,
            self.target.base_url,
            self.target.clean_ip
        )

        self.snmp_engine = engine.SnmpEngine()

        # 1. Transport Domain
        config.add_transport(
            self.snmp_engine,
            udp.DOMAIN_NAME,
            udp.UdpTransport().open_server_mode((self.bind_host, self.target.snmp_port))
        )

        version = self.snmp_config.version.lower()

        # 2. SNMP v2c Setup
        if version in ("v2c", "v2", "both"):
            community = self.snmp_config.community
            logger.debug("[%s] Enabling SNMP v2c with community '%s'", self.target.name, community)
            config.add_v1_system(self.snmp_engine, f"v2-area-{self.target.id}", community)
            config.add_vacm_user(
                self.snmp_engine,
                2,  # securityModel SNMPv2c
                f"v2-area-{self.target.id}",
                "noAuthNoPriv",
                (1, 3, 6),
                (1, 3, 6)
            )

        # 3. SNMP v3 Setup
        if version in ("v3", "both"):
            user = self.snmp_config.v3_user
            sec_level = self.snmp_config.v3_sec_level
            auth_proto = AUTH_PROTOCOLS.get(self.snmp_config.v3_auth_protocol, hlapi.usmHMACSHAAuthProtocol)
            auth_pass = self.snmp_config.v3_auth_passphrase
            priv_proto = PRIV_PROTOCOLS.get(self.snmp_config.v3_priv_protocol, hlapi.usmAesCfb128Protocol)
            priv_pass = self.snmp_config.v3_priv_passphrase

            logger.debug(
                "[%s] Enabling SNMP v3 (User: %s, SecLevel: %s, Auth: %s, Priv: %s)",
                self.target.name,
                user,
                sec_level,
                self.snmp_config.v3_auth_protocol,
                self.snmp_config.v3_priv_protocol
            )

            if sec_level == "noAuthNoPriv":
                config.add_v3_user(self.snmp_engine, user)
            elif sec_level == "authNoPriv":
                config.add_v3_user(self.snmp_engine, user, auth_proto, auth_pass)
            else:  # authPriv
                config.add_v3_user(self.snmp_engine, user, auth_proto, auth_pass, priv_proto, priv_pass)

            config.add_vacm_user(
                self.snmp_engine,
                3,  # securityModel SNMPv3 (USM)
                user,
                sec_level,
                (1, 3, 6),
                (1, 3, 6)
            )

        # 4. Custom MIB Instrumentation
        snmp_context = SnmpContext(self.snmp_engine)
        snmp_context.unregister_context_name(b"")
        custom_instrum = DynamicSwitchMibInstrum(
            builder.MibBuilder(),
            self.get_snapshot,
            self.start_time
        )
        snmp_context.register_context_name(b"", custom_instrum)

        # 5. Command Responders
        cmdrsp.GetCommandResponder(self.snmp_engine, snmp_context)
        cmdrsp.NextCommandResponder(self.snmp_engine, snmp_context)
        cmdrsp.BulkCommandResponder(self.snmp_engine, snmp_context)

        self.is_running = True
        logger.info("[%s] SNMP Agent listening on UDP port %d", self.target.name, self.target.snmp_port)

    def stop(self):
        """Stop SNMP agent and close transport dispatcher."""
        if self.snmp_engine and self.snmp_engine.transport_dispatcher:
            try:
                self.snmp_engine.transport_dispatcher.close_dispatcher()
            except Exception as e:
                logger.debug("[%s] Error closing transport dispatcher: %s", self.target.name, e)
            self.is_running = False
            logger.info("[%s] SNMP Agent stopped", self.target.name)
