"""
Integration test for SNMP Agent with both v2c and v3 queries.
Verifies MIB-II, IF-MIB, and TP-Link custom OIDs.
"""

import asyncio
import pytest
import time
from pysnmp.entity import engine
import pysnmp.hlapi.asyncio as hlapi

from app.config import SwitchTarget, SnmpConfig
from app.simulator import MockSwitchState
from app.scraper import SwitchSnapshot
from app.snmp_server import SwitchSnmpAgent


@pytest.mark.asyncio
async def test_snmp_agent_v2c_and_v3():
    test_port = 11165
    target = SwitchTarget(
        id=1,
        ip="192.168.88.150",
        user="admin_1",
        password="admin4321",
        snmp_port=test_port,
        name="TL-SG1016PE-Test"
    )
    snmp_conf = SnmpConfig(
        version="both",
        community="public",
        v3_user="zabbix",
        v3_sec_level="authPriv",
        v3_auth_protocol="SHA",
        v3_auth_passphrase="authpassword123",
        v3_priv_protocol="AES",
        v3_priv_passphrase="privpassword123"
    )

    sim = MockSwitchState(target)
    agent = SwitchSnmpAgent(
        bind_host="127.0.0.1",
        target=target,
        snmp_config=snmp_conf,
        get_snapshot=sim.generate_snapshot,
        start_time=time.time()
    )
    agent.start()

    try:
        # 1. Test SNMP v2c GET sysName (Should return REAL switch IP)
        client_engine = engine.SnmpEngine()
        g_v2 = await hlapi.get_cmd(
            client_engine,
            hlapi.CommunityData("public"),
            await hlapi.UdpTransportTarget.create(("127.0.0.1", test_port)),
            hlapi.ContextData(),
            hlapi.ObjectType(hlapi.ObjectIdentity("1.3.6.1.2.1.1.1.0")),  # sysDescr
            hlapi.ObjectType(hlapi.ObjectIdentity("1.3.6.1.2.1.1.5.0")),  # sysName (real IP)
            hlapi.ObjectType(hlapi.ObjectIdentity("1.3.6.1.2.1.2.2.1.11.1")), # ifInUcastPkts Port 1
            hlapi.ObjectType(hlapi.ObjectIdentity("1.3.6.1.2.1.2.2.1.17.1")), # ifOutUcastPkts Port 1
        )
        errInd, errStat, errIdx, varBinds = g_v2
        assert not errInd, f"SNMP v2c error: {errInd}"
        assert not errStat, f"SNMP v2c status: {errStat}"
        assert len(varBinds) == 4

        sys_descr = str(varBinds[0][1])
        sys_name = str(varBinds[1][1])
        rx_pkts_1 = int(varBinds[2][1])
        tx_pkts_1 = int(varBinds[3][1])

        assert "TL-SG1016PE" in sys_descr
        assert sys_name == "192.168.88.150", f"Expected real switch IP 192.168.88.150, got {sys_name}"
        assert rx_pkts_1 >= 1972140
        assert tx_pkts_1 >= 8018133

        # 2. Test SNMP v3 GET (AuthPriv) on PoE Custom OIDs
        client_engine_v3 = engine.SnmpEngine()
        g_v3 = await hlapi.get_cmd(
            client_engine_v3,
            hlapi.UsmUserData(
                "zabbix",
                "authpassword123",
                "privpassword123",
                authProtocol=hlapi.usmHMACSHAAuthProtocol,
                privProtocol=hlapi.usmAesCfb128Protocol
            ),
            await hlapi.UdpTransportTarget.create(("127.0.0.1", test_port)),
            hlapi.ContextData(),
            hlapi.ObjectType(hlapi.ObjectIdentity("1.3.6.1.4.1.11863.6.1.2.0")),  # Real IP
            hlapi.ObjectType(hlapi.ObjectIdentity("1.3.6.1.4.1.11863.6.3.1.5.1")), # Port 1 PoE Power (x10)
            hlapi.ObjectType(hlapi.ObjectIdentity("1.3.6.1.4.1.11863.6.3.1.7.1")), # Port 1 PoE Current (mA)
            hlapi.ObjectType(hlapi.ObjectIdentity("1.3.6.1.4.1.11863.6.3.1.11.1")), # Port 1 PoE Power Status
        )
        errInd, errStat, errIdx, varBinds_v3 = g_v3
        assert not errInd, f"SNMP v3 error: {errInd}"
        assert not errStat, f"SNMP v3 status: {errStat}"
        assert len(varBinds_v3) == 4

        real_ip = str(varBinds_v3[0][1])
        poe_pwr_x10 = int(varBinds_v3[1][1])
        poe_cur = int(varBinds_v3[2][1])
        poe_status = str(varBinds_v3[3][1])

        assert real_ip == "192.168.88.150"
        assert 50 <= poe_pwr_x10 <= 100  # ~7.1W * 10
        assert poe_cur >= 100
        assert poe_status == "ON"

        client_engine.transport_dispatcher.close_dispatcher()
        client_engine_v3.transport_dispatcher.close_dispatcher()
    finally:
        agent.stop()


@pytest.mark.asyncio
async def test_offline_switch_snmp_timeout():
    """Verify that when a switch is OFFLINE, the SNMP agent drops packets resulting in a client timeout."""
    test_port = 19169
    target = SwitchTarget(
        id=99,
        ip="192.168.88.99",
        user="admin",
        password="password",
        snmp_port=test_port,
        name="Offline-Switch"
    )
    snmp_conf = SnmpConfig(version="both", community="public")

    offline_snap = SwitchSnapshot(
        switch_id=99,
        ip="192.168.88.99",
        name="Offline-Switch",
        status="OFFLINE",
        error_message="Host unreachable"
    )

    agent = SwitchSnmpAgent(
        bind_host="127.0.0.1",
        target=target,
        snmp_config=snmp_conf,
        get_snapshot=lambda: offline_snap,
        start_time=time.time()
    )
    agent.start()

    try:
        client_engine = engine.SnmpEngine()
        transport = await hlapi.UdpTransportTarget.create(("127.0.0.1", test_port), timeout=1.0, retries=0)
        g = await hlapi.get_cmd(
            client_engine,
            hlapi.CommunityData("public"),
            transport,
            hlapi.ContextData(),
            hlapi.ObjectType(hlapi.ObjectIdentity("1.3.6.1.2.1.1.1.0"))
        )
        errInd, errStat, errIdx, varBinds = g
        assert errInd is not None, f"Expected timeout error for offline switch, but got response: {varBinds}"
        assert "timeout" in str(errInd).lower()
        client_engine.transport_dispatcher.close_dispatcher()
    finally:
        agent.stop()
