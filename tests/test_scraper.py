"""
Unit tests for TP-Link Easy Smart Web Scraper.
Validates extraction of Port Statistics and PoE Config against user sample data.
"""

from app.config import SwitchTarget
from app.scraper import TpLinkSwitchScraper
from app.simulator import generate_mock_html, SAMPLE_PORT_DATA, SAMPLE_POE_DATA


def test_parse_port_statistics_js():
    target = SwitchTarget(id=1, ip="192.168.88.150", user="admin_1", password="password", snmp_port=161)
    scraper = TpLinkSwitchScraper(target)

    port_html, _ = generate_mock_html()
    result = scraper.parse_port_statistics(port_html)

    assert len(result) == 16, f"Expected 16 ports, got {len(result)}"

    # Port 1 verification
    p1 = result[1]
    assert p1.port == 1
    assert p1.status == "Enabled"
    assert p1.link_status == "1000M Full"
    assert p1.tx_good_pkt == 8018133
    assert p1.tx_bad_pkt == 0
    assert p1.rx_good_pkt == 1972140
    assert p1.rx_bad_pkt == 0

    # Port 9 verification (has RxBadPkt: 3)
    p9 = result[9]
    assert p9.port == 9
    assert p9.tx_good_pkt == 7621885
    assert p9.rx_good_pkt == 11617460
    assert p9.rx_bad_pkt == 3

    # Port 11 verification (Link Down)
    p11 = result[11]
    assert p11.link_status == "Link Down"
    assert p11.tx_good_pkt == 120919


def test_parse_poe_config_js():
    target = SwitchTarget(id=1, ip="192.168.88.150", user="admin_1", password="password", snmp_port=161)
    scraper = TpLinkSwitchScraper(target)

    _, poe_html = generate_mock_html()
    poe_result, global_poe = scraper.parse_poe_config(poe_html)

    assert len(poe_result) == 8, f"Expected 8 PoE ports, got {len(poe_result)}"
    assert global_poe.power_limit == 110.0
    assert global_poe.power_consumption == 31.4
    assert global_poe.power_remain == 78.6

    # Port 1 verification
    poe1 = poe_result[1]
    assert poe1.port == 1
    assert poe1.poe_status == "Enable"
    assert poe1.poe_priority == "Low"
    assert poe1.power_w == 7.1
    assert poe1.current_ma == 137.0
    assert poe1.voltage_v == 52.3
    assert poe1.power_status == "ON"


def test_parse_html_table_fallback():
    target = SwitchTarget(id=1, ip="192.168.88.150", user="admin_1", password="password", snmp_port=161)
    scraper = TpLinkSwitchScraper(target)

    # Raw HTML table as seen in some firmware Web GUIs
    raw_html_port = """
    <table>
      <tr><th>Port</th><th>Status</th><th>Link Status</th><th>TxGoodPkt</th><th>TxBadPkt</th><th>RxGoodPkt</th><th>RxBadPkt</th></tr>
      <tr><td>Port 1</td><td>Enabled</td><td>1000M Full</td><td>8018133</td><td>0</td><td>1972140</td><td>0</td></tr>
      <tr><td>Port 2</td><td>Enabled</td><td>1000M Full</td><td>20090666</td><td>0</td><td>4347407</td><td>0</td></tr>
    </table>
    """
    res = scraper.parse_port_statistics(raw_html_port)
    assert 1 in res
    assert res[1].tx_good_pkt == 8018133
    assert res[2].rx_good_pkt == 4347407

    raw_html_poe = """
    <table>
      <tr><th>Port</th><th>PoE Status</th><th>PoE Priority</th><th>Power Limit</th><th>Power(w)</th><th>Current(mA)</th><th>Voltage(v)</th><th>PD Class</th><th>Power Status</th></tr>
      <tr><td>Port 1</td><td>Enable</td><td>Low</td><td>Class 4</td><td>7.1</td><td>137</td><td>52.3</td><td>Class 3</td><td>ON</td></tr>
    </table>
    """
    poe_res, _ = scraper.parse_poe_config(raw_html_poe)
    assert 1 in poe_res
    assert poe_res[1].power_w == 7.1
    assert poe_res[1].current_ma == 137.0
    assert poe_res[1].voltage_v == 52.3
    assert poe_res[1].power_status == "ON"
