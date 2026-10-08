"""
CLI Utility to test querying the SNMP Gateway.
Works without needing net-snmp binaries on Windows.
Supports SNMP v2c and v3 (AuthPriv).
"""

import argparse
import asyncio
import sys

from pysnmp.entity import engine
from pysnmp.proto import rfc1902
import pysnmp.hlapi.asyncio as hlapi

from app.config import parse_config


async def query_snmp(args):
    config = parse_config()
    host = args.host
    port = args.port

    print("=" * 70)
    print(f"Querying SNMP Agent at {host}:{port}")
    print(f"Protocol Version: {args.version}")
    print("=" * 70)

    client_engine = engine.SnmpEngine()

    if args.version == "v2c":
        auth_data = hlapi.CommunityData(config.snmp.community)
    else:
        auth_proto = hlapi.usmHMACSHAAuthProtocol if config.snmp.v3_auth_protocol == "SHA" else hlapi.usmHMACMD5AuthProtocol
        priv_proto = hlapi.usmAesCfb128Protocol if "AES" in config.snmp.v3_priv_protocol else hlapi.usmDESPrivProtocol
        auth_data = hlapi.UsmUserData(
            config.snmp.v3_user,
            config.snmp.v3_auth_passphrase,
            config.snmp.v3_priv_passphrase,
            authProtocol=auth_proto,
            privProtocol=priv_proto
        )

    transport = await hlapi.UdpTransportTarget.create((host, port), timeout=3.0, retries=1)

    # 1. System Info Queries
    print("\n--- System & Identity (RFC 1213 / SNMPv2-MIB) ---")
    system_oids = [
        ("sysDescr", "1.3.6.1.2.1.1.1.0"),
        ("sysUpTime", "1.3.6.1.2.1.1.3.0"),
        ("sysName (Real Switch IP)", "1.3.6.1.2.1.1.5.0"),
        ("Switch Status", "1.3.6.1.4.1.11863.6.1.3.0"),
        ("Switch Latency", "1.3.6.1.4.1.11863.6.1.9.0"),
    ]
    for label, oid in system_oids:
        g = await hlapi.get_cmd(
            client_engine,
            auth_data,
            transport,
            hlapi.ContextData(),
            hlapi.ObjectType(hlapi.ObjectIdentity(oid))
        )
        errInd, errStat, errIdx, varBinds = g
        if errInd:
            print(f"  {label}: Error - {errInd}")
            if label == "sysDescr":
                print(f"\n[!] Port {port} is OFF or unreachable ({errInd}). Aborting further queries.")
                return
        else:
            val_str = str(varBinds[0][1])
            print(f"  {label} ({oid}): {val_str}")

    # 2. Port Statistics Sample (Port 1 & Port 2)
    print("\n--- Port Statistics (IF-MIB: 1.3.6.1.2.1.2) ---")
    port_oids = [
        ("Port 1 Descr", "1.3.6.1.2.1.2.2.1.2.1"),
        ("Port 1 OperStatus", "1.3.6.1.2.1.2.2.1.8.1"),
        ("Port 1 RxGoodPkt", "1.3.6.1.2.1.2.2.1.11.1"),
        ("Port 1 TxGoodPkt", "1.3.6.1.2.1.2.2.1.17.1"),
        ("Port 2 Descr", "1.3.6.1.2.1.2.2.1.2.2"),
        ("Port 2 RxGoodPkt", "1.3.6.1.2.1.2.2.1.11.2"),
        ("Port 2 TxGoodPkt", "1.3.6.1.2.1.2.2.1.17.2"),
    ]
    for label, oid in port_oids:
        g = await hlapi.get_cmd(
            client_engine,
            auth_data,
            transport,
            hlapi.ContextData(),
            hlapi.ObjectType(hlapi.ObjectIdentity(oid))
        )
        errInd, errStat, errIdx, varBinds = g
        if not errInd:
            print(f"  {label} ({oid}): {varBinds[0][1]}")

    # 3. PoE Sample
    print("\n--- PoE Config & Consumption (Custom MIB: 1.3.6.1.4.1.11863.6) ---")
    poe_oids = [
        ("Total PoE Power Limit (0.1W)", "1.3.6.1.4.1.11863.6.1.5.0"),
        ("Total PoE Consumption (0.1W)", "1.3.6.1.4.1.11863.6.1.6.0"),
        ("Port 1 PoE Status", "1.3.6.1.4.1.11863.6.3.1.2.1"),
        ("Port 1 Power (0.1W)", "1.3.6.1.4.1.11863.6.3.1.5.1"),
        ("Port 1 Current (mA)", "1.3.6.1.4.1.11863.6.3.1.7.1"),
        ("Port 1 Voltage (0.1V)", "1.3.6.1.4.1.11863.6.3.1.8.1"),
        ("Port 1 Power State", "1.3.6.1.4.1.11863.6.3.1.11.1"),
    ]
    for label, oid in poe_oids:
        g = await hlapi.get_cmd(
            client_engine,
            auth_data,
            transport,
            hlapi.ContextData(),
            hlapi.ObjectType(hlapi.ObjectIdentity(oid))
        )
        errInd, errStat, errIdx, varBinds = g
        if not errInd:
            print(f"  {label} ({oid}): {varBinds[0][1]}")

    client_engine.transport_dispatcher.close_dispatcher()
    print("\n" + "=" * 70)
    print("SNMP query completed successfully!")


def main():
    parser = argparse.ArgumentParser(description="Test SNMP queries against the TP-Link gateway")
    parser.add_argument("--host", default="127.0.0.1", help="SNMP Agent host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=6161, help="SNMP UDP port (default: 6161)")
    parser.add_argument("--version", choices=["v2c", "v3"], default="v2c", help="SNMP Version (default: v2c)")
    args = parser.parse_args()

    asyncio.run(query_snmp(args))


if __name__ == "__main__":
    main()
