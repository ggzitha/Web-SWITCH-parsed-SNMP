"""
Mock and simulator for TP-Link TL-SG1016PE switch.
Provides realistic data based on the user's exact switch tables.
Also simulates packet counter increments over time for testing counters in Zabbix.
"""

import time
import random
from typing import Dict, Tuple
from .scraper import (
    PortStatisticsItem,
    PoeConfigItem,
    GlobalPoeState,
    SwitchSnapshot
)
from .config import SwitchTarget

# Initial sample data directly from the user's prompt
SAMPLE_PORT_DATA = [
    # port, status, link_status, tx_good, tx_bad, rx_good, rx_bad
    (1, "Enabled", "1000M Full", 8018133, 0, 1972140, 0),
    (2, "Enabled", "1000M Full", 20090666, 0, 4347407, 0),
    (3, "Enabled", "1000M Full", 9041892, 0, 2372087, 0),
    (4, "Enabled", "1000M Full", 3199727, 0, 877093, 0),
    (5, "Enabled", "1000M Full", 2614801, 0, 2788, 0),
    (6, "Enabled", "1000M Full", 11687147, 0, 4615815, 0),
    (7, "Enabled", "1000M Full", 8064182, 0, 1296423, 0),
    (8, "Enabled", "1000M Full", 10613676, 0, 1767405, 0),
    (9, "Enabled", "1000M Full", 7621885, 0, 11617460, 3),
    (10, "Enabled", "1000M Full", 14413594, 0, 36071511, 0),
    (11, "Enabled", "Link Down", 120919, 0, 15312, 0),
    (12, "Enabled", "1000M Full", 2728044, 0, 167274, 0),
    (13, "Enabled", "Link Down", 0, 0, 0, 0),
    (14, "Enabled", "Link Down", 4511, 0, 58, 0),
    (15, "Enabled", "Link Down", 0, 0, 0, 0),
    (16, "Enabled", "Link Down", 0, 0, 0, 0),
]

SAMPLE_POE_DATA = [
    # port, poe_status, poe_priority, power_limit, power_w, current_ma, voltage_v, pd_class, power_status
    (1, "Enable", "Low", "Class 4", 7.1, 137.0, 52.3, "Class 3", "ON"),
    (2, "Enable", "Low", "Class 4", 2.3, 45.0, 52.6, "Class 3", "ON"),
    (3, "Enable", "Low", "Class 4", 7.2, 137.0, 52.6, "Class 3", "ON"),
    (4, "Enable", "Low", "Class 4", 2.2, 43.0, 52.4, "Class 3", "ON"),
    (5, "Enable", "Low", "Class 4", 1.5, 30.0, 52.4, "Class 3", "ON"),
    (6, "Enable", "Low", "Class 4", 7.1, 136.0, 52.4, "Class 3", "ON"),
    (7, "Enable", "Low", "Class 4", 2.0, 39.0, 52.4, "Class 3", "ON"),
    (8, "Enable", "Low", "Class 4", 2.0, 39.0, 52.3, "Class 3", "ON"),
]


class MockSwitchState:
    """Maintains state for a simulated switch, generating dynamic traffic increases."""

    def __init__(self, target: SwitchTarget):
        self.target = target
        self.port_stats: Dict[int, PortStatisticsItem] = {}
        self.poe_stats: Dict[int, PoeConfigItem] = {}
        self.global_poe = GlobalPoeState(power_limit=110.0, power_consumption=31.4, power_remain=78.6)
        
        # Load baseline port data
        for p, st, ls, tx_g, tx_b, rx_g, rx_b in SAMPLE_PORT_DATA:
            self.port_stats[p] = PortStatisticsItem(
                port=p,
                status=st,
                link_status=ls,
                tx_good_pkt=tx_g,
                tx_bad_pkt=tx_b,
                rx_good_pkt=rx_g,
                rx_bad_pkt=rx_b
            )

        # Load baseline poe data
        total_power = 0.0
        for p, pst, pprio, plim, pwr, cur, volt, pdc, pstatus in SAMPLE_POE_DATA:
            self.poe_stats[p] = PoeConfigItem(
                port=p,
                poe_status=pst,
                poe_priority=pprio,
                power_limit=plim,
                power_w=pwr,
                current_ma=cur,
                voltage_v=volt,
                pd_class=pdc,
                power_status=pstatus
            )
            total_power += pwr

        self.global_poe.power_consumption = round(total_power, 1)
        self.global_poe.power_remain = round(self.global_poe.power_limit - total_power, 1)

    def generate_snapshot(self) -> SwitchSnapshot:
        """Advance packet counters realistically and return updated snapshot."""
        # Increment active ports packets slightly to simulate real traffic
        for p, item in self.port_stats.items():
            if item.link_status != "Link Down":
                item.tx_good_pkt += random.randint(50, 400)
                item.rx_good_pkt += random.randint(30, 350)
                # Occasional bad packet on port 9 (as shown in user data)
                if p == 9 and random.random() < 0.05:
                    item.rx_bad_pkt += 1

        # Small micro-variations in PoE consumption
        total_power = 0.0
        for p, poe in self.poe_stats.items():
            if poe.power_status == "ON":
                variation = random.choice([-0.1, 0.0, 0.1])
                new_power = max(1.0, round(poe.power_w + variation, 1))
                poe.power_w = new_power
                total_power += new_power
                
        self.global_poe.power_consumption = round(total_power, 1)
        self.global_poe.power_remain = round(max(0.0, self.global_poe.power_limit - total_power), 1)

        return SwitchSnapshot(
            switch_id=self.target.id,
            ip=self.target.clean_ip,
            name=self.target.name,
            last_scraped=time.time(),
            status="ONLINE",
            error_message="",
            port_stats=dict(self.port_stats),
            poe_stats=dict(self.poe_stats),
            global_poe=self.global_poe,
            model=self.target.model
        )


def generate_mock_html(port_data=None, poe_data=None) -> Tuple[str, str]:
    """Generate mock PortStatisticsRpm.htm and PoeConfigRpm.htm HTML content with JavaScript arrays."""
    # 1. Port Statistics HTML
    ports = port_data or SAMPLE_PORT_DATA
    pkts = []
    states = []
    link_status = []
    for p, st, ls, txg, txb, rxg, rxb in ports:
        states.append("1" if st == "Enabled" else "0")
        link_status.append("6" if "1000M" in ls else ("0" if ls == "Link Down" else "5"))
        pkts.extend([str(txg), str(txb), str(rxg), str(rxb)])

    port_html = f"""<!DOCTYPE html>
<html>
<head><title>Port Statistics</title></head>
<body>
<script>
var all_info = {{
    state: [{",".join(states)}],
    link_status: [{",".join(link_status)}],
    pkts: [{",".join(pkts)}],
    max_port_num: {len(ports)}
}};
</script>
</body>
</html>"""

    # 2. PoE Config HTML
    poes = poe_data or SAMPLE_POE_DATA
    poe_states = []
    priorities = []
    powerlimits = []
    powers = []
    currents = []
    voltages = []
    pdclasses = []
    powerstatuses = []

    for p, pst, pprio, plim, pwr, cur, volt, pdc, pstatus in poes:
        poe_states.append("1" if pst == "Enable" else "0")
        priorities.append("2" if pprio == "Low" else ("1" if pprio == "Middle" else "0"))
        powerlimits.append("300")
        powers.append(str(int(pwr * 10)))
        currents.append(str(int(cur)))
        voltages.append(str(int(volt * 10)))
        pdclasses.append("154")
        powerstatuses.append("2" if pstatus == "ON" else "0")

    poe_html = f"""<!DOCTYPE html>
<html>
<head><title>PoE Config</title></head>
<body>
<script>
var globalConfig = {{
    system_power_limit: 1100,
    system_power_consumption: 314,
    system_power_remain: 786
}};
var portConfig = {{
    state: [{",".join(poe_states)}],
    priority: [{",".join(priorities)}],
    powerlimit: [{",".join(powerlimits)}],
    power: [{",".join(powers)}],
    current: [{",".join(currents)}],
    voltage: [{",".join(voltages)}],
    pdclass: [{",".join(pdclasses)}],
    powerstatus: [{",".join(powerstatuses)}],
    poe_port_num: {len(poes)}
}};
</script>
</body>
</html>"""

    return port_html, poe_html
