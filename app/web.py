"""
Web Dashboard for Python-SNMP-Parser-WEB.
Provides a real-time responsive dashboard to monitor scraped switch states,
view Port Statistics, PoE Consumption, and inspect active SNMP OIDs.
"""

import json
import logging
from typing import Dict, Callable
from flask import Flask, render_template, jsonify, request
from .config import AppConfig
from .scraper import SwitchSnapshot
from .mib_tree import SwitchMibBuilder, oid_to_str

logger = logging.getLogger(__name__)


def create_web_app(
    config: AppConfig,
    get_snapshots: Callable[[], Dict[int, SwitchSnapshot]],
    start_time: float
) -> Flask:
    app = Flask(__name__, template_folder="templates")
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    mib_helper = SwitchMibBuilder(start_time)

    @app.route("/health")
    @app.route("/api/health")
    def health_check():
        """Unauthenticated health endpoint for Docker HEALTHCHECK and monitoring probes."""
        return jsonify({"status": "ok", "active_switches": len(config.switches)})

    @app.before_request
    def check_web_auth():
        """Enforce HTTP Basic Authentication if WEB_USER or WEB_PASSWORD is set."""
        # Exempt health endpoints so container probes never fail
        if request.path in ("/health", "/api/health"):
            return None

        # If neither username nor password is configured, bypass authentication
        if not config.web_user and not config.web_password:
            return None

        auth = request.authorization
        if (
            not auth
            or (config.web_user and auth.username != config.web_user)
            or (config.web_password and auth.password != config.web_password)
        ):
            return (
                "<!DOCTYPE html><html><head><title>401 Unauthorized</title></head>"
                "<body style='font-family: sans-serif; background: #0b0f19; color: #f1f5f9; text-align: center; padding-top: 100px;'>"
                "<h2 style='color: #38bdf8;'>🔒 TP-Link SNMP Gateway Web Dashboard</h2>"
                "<p style='color: #94a3b8;'>Authentication required. Please enter your WEB_USER and WEB_PASSWORD.</p>"
                "</body></html>",
                401,
                {"WWW-Authenticate": 'Basic realm="TP-Link SNMP Gateway Dashboard"'}
            )

    @app.route("/")
    def index():
        snapshots = get_snapshots()
        switches_data = []
        for target in config.switches:
            snap = snapshots.get(target.id)
            switches_data.append({
                "target": target,
                "snapshot": snap
            })
        return render_template(
            "index.html",
            switches=switches_data,
            config=config,
            active_switch_id=config.switches[0].id if config.switches else 1
        )

    @app.route("/api/switches")
    def api_switches():
        snapshots = get_snapshots()
        result = []
        for target in config.switches:
            snap = snapshots.get(target.id)
            if not snap:
                continue
            ports = [
                {
                    "port": p.port,
                    "status": p.status,
                    "link_status": p.link_status,
                    "tx_good_pkt": p.tx_good_pkt,
                    "tx_bad_pkt": p.tx_bad_pkt,
                    "rx_good_pkt": p.rx_good_pkt,
                    "rx_bad_pkt": p.rx_bad_pkt
                }
                for p in snap.port_stats.values()
            ]
            poe = [
                {
                    "port": p.port,
                    "poe_status": p.poe_status,
                    "poe_priority": p.poe_priority,
                    "power_limit": p.power_limit,
                    "power_w": p.power_w,
                    "current_ma": p.current_ma,
                    "voltage_v": p.voltage_v,
                    "pd_class": p.pd_class,
                    "power_status": p.power_status
                }
                for p in snap.poe_stats.values()
            ]
            result.append({
                "id": target.id,
                "name": target.name,
                "ip": target.clean_ip,
                "base_url": target.base_url,
                "snmp_port": target.snmp_port,
                "status": snap.status,
                "latency_ms": getattr(snap, "latency_ms", 0.0),
                "error_message": snap.error_message,
                "last_scraped": snap.last_scraped,
                "global_poe": {
                    "limit": snap.global_poe.power_limit,
                    "consumption": snap.global_poe.power_consumption,
                    "remain": snap.global_poe.power_remain
                },
                "port_count": len(ports),
                "poe_count": len(poe),
                "ports": ports,
                "poe": poe
            })
        return jsonify({"switches": result, "refresh_interval": config.refresh_interval})

    @app.route("/api/switch/<int:switch_id>/oids")
    def api_switch_oids(switch_id: int):
        snapshots = get_snapshots()
        snap = snapshots.get(switch_id)
        if not snap:
            return jsonify({"error": "Switch not found"}), 404
        if snap.status != "ONLINE":
            return jsonify({
                "switch_id": switch_id,
                "ip": snap.ip,
                "status": snap.status,
                "error": snap.error_message or "Switch is offline",
                "count": 0,
                "oids": []
            })

        oid_map = mib_helper.build_oid_map(snap)
        oids_formatted = []
        for oid_tuple, val in sorted(oid_map.items()):
            oids_formatted.append({
                "oid": oid_to_str(oid_tuple),
                "type": val.__class__.__name__,
                "value": str(val)
            })

        return jsonify({
            "switch_id": switch_id,
            "ip": snap.ip,
            "count": len(oids_formatted),
            "oids": oids_formatted
        })

    return app
