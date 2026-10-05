"""
Unit tests for configuration parsing.
"""

import os
import pytest
from app.config import parse_config


def test_parse_dynamic_switches(monkeypatch):
    monkeypatch.setenv("SWITCH_1_IP", "192.168.88.150")
    monkeypatch.setenv("SWITCH_1_USER", "admin_1")
    monkeypatch.setenv("SWITCH_1_PASS", "admin4321")
    monkeypatch.setenv("SWITCH_1_SNMP_PORT", "161")
    monkeypatch.setenv("SWITCH_1_NAME", "Core-Switch")

    monkeypatch.setenv("SWITCH_2_IP", "192.168.88.153")
    monkeypatch.setenv("SWITCH_2_USER", "admin")
    monkeypatch.setenv("SWITCH_2_PASS", "admin123")
    monkeypatch.setenv("SWITCH_2_SNMP_PORT", "162")

    monkeypatch.setenv("REFRESHED_PAGE", "15")
    monkeypatch.setenv("SNMP_COMMUNITY", "zabbix_comm")
    monkeypatch.setenv("SNMP_V3_USER", "zabbix_user")

    conf = parse_config()

    assert conf.refresh_interval == 15
    assert conf.snmp.community == "zabbix_comm"
    assert conf.snmp.v3_user == "zabbix_user"
    assert len(conf.switches) >= 2

    s1 = next(s for s in conf.switches if s.id == 1)
    assert s1.clean_ip == "192.168.88.150"
    assert s1.user == "admin_1"
    assert s1.password == "admin4321"
    assert s1.snmp_port == 161
    assert s1.name == "Core-Switch"

    s2 = next(s for s in conf.switches if s.id == 2)
    assert s2.clean_ip == "192.168.88.153"
    assert s2.user == "admin"
    assert s2.password == "admin123"
    assert s2.snmp_port == 162


def test_parse_method_b_inline(monkeypatch):
    # Clear any SWITCH_1 env
    for k in list(os.environ.keys()):
        if k.startswith("SWITCH_") and k != "SWITCH_TARGETS":
            monkeypatch.delenv(k, raising=False)
            
    monkeypatch.setenv("SWITCH_TARGETS", "192.168.88.150:admin_1:admin4321:161:Core,192.168.88.153:admin:admin123:162:Access3")
    monkeypatch.setenv("WEB_USER", "secuser")
    monkeypatch.setenv("WEB_PASSWORD", "secpass123")

    conf = parse_config()
    assert conf.web_user == "secuser"
    assert conf.web_password == "secpass123"
    assert len(conf.switches) == 2

    s1 = conf.switches[0]
    assert s1.clean_ip == "192.168.88.150"
    assert s1.user == "admin_1"
    assert s1.password == "admin4321"
    assert s1.snmp_port == 161
    assert s1.name == "Core"

    s2 = conf.switches[1]
    assert s2.clean_ip == "192.168.88.153"
    assert s2.user == "admin"
    assert s2.snmp_port == 162
    assert s2.name == "Access3"


def test_web_auth_and_health():
    import base64
    from app.web import create_web_app
    from app.config import AppConfig

    conf = AppConfig()
    conf.web_user = "testadmin"
    conf.web_password = "testpassword"

    app = create_web_app(conf, lambda: {}, 0.0)
    client = app.test_client()

    # 1. Health check should succeed without auth
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "ok"

    # 2. Main page without auth should return 401
    resp = client.get("/")
    assert resp.status_code == 401

    # 3. Main page with valid Basic auth should return 200
    valid_creds = base64.b64encode(b"testadmin:testpassword").decode()
    resp = client.get("/", headers={"Authorization": f"Basic {valid_creds}"})
    assert resp.status_code == 200
