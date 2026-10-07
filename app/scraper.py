"""
TP-Link Easy Smart Switch Web Scraper.
Authenticates via logon.cgi and extracts:
1. Monitoring > Port Statistics (PortStatisticsRpm.htm)
2. PoE > PoE Config (PoeConfigRpm.htm)
Supports both embedded JavaScript arrays and HTML table fallbacks.
"""

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any

import aiohttp
from bs4 import BeautifulSoup

from .config import SwitchTarget

logger = logging.getLogger(__name__)

# Link speed integer to string mapping
LINK_SPEED_MAP = {
    0: "Link Down",
    1: "Auto",
    2: "10M Half",
    3: "10M Full",
    4: "100M Half",
    5: "100M Full",
    6: "1000M Full",
}

POE_PRIORITY_MAP = {
    0: "High",
    1: "Middle",
    2: "Low",
}

POE_CLASS_MAP = {
    40: "Class 1",
    70: "Class 2",
    154: "Class 3",
    300: "Class 4",
    330: "Class 0",
    331: "None",
}

POE_STATUS_MAP = {
    0: "OFF",
    1: "Turning ON",
    2: "ON",
    3: "Overload",
    4: "Short",
    5: "Non-standard PD",
    6: "Voltage High",
    7: "Voltage Low",
    8: "Hardware Fault",
    9: "Over Temperature",
}


@dataclass
class PortStatisticsItem:
    port: int
    status: str = "Enabled"        # "Enabled" or "Disabled"
    link_status: str = "Link Down" # "1000M Full", "Link Down", etc.
    tx_good_pkt: int = 0
    tx_bad_pkt: int = 0
    rx_good_pkt: int = 0
    rx_bad_pkt: int = 0


@dataclass
class PoeConfigItem:
    port: int
    poe_status: str = "Disable"    # "Enable" or "Disable"
    poe_priority: str = "Low"      # "High", "Middle", "Low"
    power_limit: str = "Class 4"   # "Class 4", "30.0W", etc.
    power_w: float = 0.0           # Power in Watts
    current_ma: float = 0.0        # Current in mA
    voltage_v: float = 0.0         # Voltage in Volts
    pd_class: str = "Unknown"      # "Class 0", "Class 3", etc.
    power_status: str = "OFF"      # "ON", "OFF", etc.


@dataclass
class GlobalPoeState:
    power_limit: float = 110.0
    power_consumption: float = 0.0
    power_remain: float = 110.0


@dataclass
class SwitchSnapshot:
    switch_id: int
    ip: str
    name: str
    last_scraped: float = 0.0
    status: str = "Initializing"
    error_message: str = ""
    port_stats: Dict[int, PortStatisticsItem] = field(default_factory=dict)
    poe_stats: Dict[int, PoeConfigItem] = field(default_factory=dict)
    global_poe: GlobalPoeState = field(default_factory=GlobalPoeState)
    model: str = "TL-SG1016PE"


class TpLinkSwitchScraper:
    """Handles authentication and scraping for a single TP-Link Easy Smart Switch."""

    def __init__(self, target: SwitchTarget):
        self.target = target
        self._session: Optional[aiohttp.ClientSession] = None
        self._authenticated = False
        self._lock = asyncio.Lock()
        self.snapshot = SwitchSnapshot(
            switch_id=target.id,
            ip=target.clean_ip,
            name=target.name,
            model=target.model
        )

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            # TP-Link Easy Smart switches expect cookie support on IP addresses
            cookie_jar = aiohttp.CookieJar(unsafe=True)
            timeout = aiohttp.ClientTimeout(total=6.0, connect=3.0)
            self._session = aiohttp.ClientSession(
                cookie_jar=cookie_jar,
                timeout=timeout
            )
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
            self._authenticated = False

    async def login(self) -> bool:
        """Authenticate with the switch using logon.cgi."""
        session = await self._get_session()
        login_url = f"{self.target.base_url}/logon.cgi"
        payload = {
            "username": self.target.user,
            "password": self.target.password,
            "logon": "Login"
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Referer": f"{self.target.base_url}/",
            "Content-Type": "application/x-www-form-urlencoded"
        }

        logger.debug("[%s] Attempting login at %s with user %s", self.target.name, login_url, self.target.user)
        try:
            async with session.post(login_url, data=payload, headers=headers) as resp:
                text = await resp.text(errors="ignore")
                
                # Check for logonInfo variable in javascript response
                # var logonInfo = new Array(0, ...);
                match = re.search(r"var\s+logonInfo\s*=\s*new\s*Array\s*\(([^)]+)\)", text)
                if match:
                    code_str = match.group(1).split(",")[0].strip()
                    if code_str == "0":
                        logger.info("[%s] Login successful", self.target.name)
                        self._authenticated = True
                        return True
                    elif code_str == "1":
                        logger.error("[%s] Login failed: Wrong username or password", self.target.name)
                        self.snapshot.error_message = "Wrong username or password"
                    elif code_str in ("3", "4"):
                        logger.warning("[%s] Login failed: Switch web interface busy (admin session active)", self.target.name)
                        self.snapshot.error_message = "Web interface busy (admin session active)"
                    else:
                        logger.warning("[%s] Login returned error code: %s", self.target.name, code_str)
                        self.snapshot.error_message = f"Switch returned error code {code_str}"
                elif resp.status == 200:
                    self._authenticated = True
                    return True
        except Exception as e:
            logger.error("[%s] Login connection error: %s", self.target.name, e)
            self.snapshot.error_message = f"Connection error: {e}"

        self._authenticated = False
        return False

    async def _fetch_page(self, path: str) -> Optional[str]:
        """Fetch a page, re-authenticating if needed."""
        session = await self._get_session()
        url = f"{self.target.base_url}/{path}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Referer": f"{self.target.base_url}/",
        }

        for attempt in range(2):
            if not self._authenticated:
                ok = await self.login()
                if not ok:
                    return None

            try:
                async with session.get(url, headers=headers) as resp:
                    if resp.status == 200:
                        text = await resp.text(errors="ignore")
                        # Check if redirected to login or session timeout
                        if "logon.cgi" in text or "var logonInfo" in text:
                            logger.debug("[%s] Session expired while requesting %s, re-authenticating...", self.target.name, path)
                            self._authenticated = False
                            continue
                        return text
                    elif resp.status in (401, 403):
                        self._authenticated = False
                        continue
            except Exception as e:
                logger.debug("[%s] Fetch page %s error: %s", self.target.name, path, e)
                self._authenticated = False

        return None

    # ----------------------------------------------------------------------
    # Parsing: Port Statistics
    # ----------------------------------------------------------------------
    def parse_port_statistics(self, html: str) -> Dict[int, PortStatisticsItem]:
        """Extract port statistics from PortStatisticsRpm.htm (JS array or HTML table)."""
        result: Dict[int, PortStatisticsItem] = {}

        # 1. Primary: Parse embedded JavaScript arrays
        # all_info = { state:[1,...], link_status:[6,...], pkts:[...], max_port_num: 16 }
        max_ports_match = re.search(r"max_port_num\s*[:=]\s*(\d+)", html)
        max_ports = int(max_ports_match.group(1)) if max_ports_match else 16

        state_match = re.search(r"state\s*[:=]\s*\[([^\]]+)\]", html)
        link_status_match = re.search(r"link_status\s*[:=]\s*\[([^\]]+)\]", html)
        pkts_match = re.search(r"pkts\s*[:=]\s*\[([^\]]+)\]", html)

        if pkts_match:
            try:
                pkts = [int(x.strip()) for x in pkts_match.group(1).split(",") if x.strip().isdigit()]
                states = [int(x.strip()) for x in state_match.group(1).split(",") if x.strip().isdigit()] if state_match else []
                link_statuses = [int(x.strip()) for x in link_status_match.group(1).split(",") if x.strip().isdigit()] if link_status_match else []

                total_ports = len(pkts) // 4
                if total_ports == 0 and max_ports:
                    total_ports = max_ports

                for i in range(1, total_ports + 1):
                    idx = i - 1
                    status_val = states[idx] if idx < len(states) else 1
                    status_str = "Enabled" if status_val == 1 else "Disabled"
                    
                    link_val = link_statuses[idx] if idx < len(link_statuses) else 0
                    link_str = LINK_SPEED_MAP.get(link_val, "Link Down" if link_val == 0 else f"{link_val}")

                    base_pkt = idx * 4
                    tx_good = pkts[base_pkt] if base_pkt < len(pkts) else 0
                    tx_bad = pkts[base_pkt + 1] if base_pkt + 1 < len(pkts) else 0
                    rx_good = pkts[base_pkt + 2] if base_pkt + 2 < len(pkts) else 0
                    rx_bad = pkts[base_pkt + 3] if base_pkt + 3 < len(pkts) else 0

                    result[i] = PortStatisticsItem(
                        port=i,
                        status=status_str,
                        link_status=link_str,
                        tx_good_pkt=tx_good,
                        tx_bad_pkt=tx_bad,
                        rx_good_pkt=rx_good,
                        rx_bad_pkt=rx_bad
                    )
                if result:
                    return result
            except Exception as e:
                logger.debug("[%s] JS array parse error for Port Statistics: %s", self.target.name, e)

        # 2. Fallback: Parse HTML table
        soup = BeautifulSoup(html, "html.parser")
        for tr in soup.find_all("tr"):
            tds = [td.get_text(strip=True) for td in tr.find_all("td")]
            if len(tds) >= 7 and "port" in tds[0].lower():
                # Format: Port 1, Enabled, 1000M Full, TxGood, TxBad, RxGood, RxBad
                port_match = re.search(r"(\d+)", tds[0])
                if not port_match:
                    continue
                port_num = int(port_match.group(1))
                status_str = tds[1]
                link_status_str = tds[2]
                tx_good = int(tds[3]) if tds[3].isdigit() else 0
                tx_bad = int(tds[4]) if tds[4].isdigit() else 0
                rx_good = int(tds[5]) if tds[5].isdigit() else 0
                rx_bad = int(tds[6]) if tds[6].isdigit() else 0

                result[port_num] = PortStatisticsItem(
                    port=port_num,
                    status=status_str,
                    link_status=link_status_str,
                    tx_good_pkt=tx_good,
                    tx_bad_pkt=tx_bad,
                    rx_good_pkt=rx_good,
                    rx_bad_pkt=rx_bad
                )

        return result

    # ----------------------------------------------------------------------
    # Parsing: PoE Config
    # ----------------------------------------------------------------------
    def parse_poe_config(self, html: str) -> Tuple[Dict[int, PoeConfigItem], GlobalPoeState]:
        """Extract PoE configuration from PoeConfigRpm.htm (JS array or HTML table)."""
        result: Dict[int, PoeConfigItem] = {}
        global_poe = GlobalPoeState()

        # 1. Parse Global PoE config
        # globalConfig: { system_power_limit: 1100, system_power_consumption: 264, system_power_remain: 836 }
        sys_limit_match = re.search(r"system_power_limit\s*[:=]\s*(\d+)", html)
        sys_cons_match = re.search(r"system_power_consumption\s*[:=]\s*(\d+)", html)
        sys_rem_match = re.search(r"system_power_remain\s*[:=]\s*(\d+)", html)

        if sys_limit_match:
            global_poe.power_limit = float(sys_limit_match.group(1)) / 10.0
        if sys_cons_match:
            global_poe.power_consumption = float(sys_cons_match.group(1)) / 10.0
        if sys_rem_match:
            global_poe.power_remain = float(sys_rem_match.group(1)) / 10.0

        # 2. Parse JS arrays in portConfig
        poe_ports_match = re.search(r"poe_port_num\s*[:=]\s*(\d+)", html)
        poe_port_count = int(poe_ports_match.group(1)) if poe_ports_match else 8

        state_m = re.search(r"state\s*[:=]\s*\[([^\]]+)\]", html)
        priority_m = re.search(r"priority\s*[:=]\s*\[([^\]]+)\]", html)
        powerlimit_m = re.search(r"powerlimit\s*[:=]\s*\[([^\]]+)\]", html)
        power_m = re.search(r"power\s*[:=]\s*\[([^\]]+)\]", html)
        current_m = re.search(r"current\s*[:=]\s*\[([^\]]+)\]", html)
        voltage_m = re.search(r"voltage\s*[:=]\s*\[([^\]]+)\]", html)
        pdclass_m = re.search(r"pdclass\s*[:=]\s*\[([^\]]+)\]", html)
        powerstatus_m = re.search(r"powerstatus\s*[:=]\s*\[([^\]]+)\]", html)

        if power_m and current_m:
            try:
                states = [int(x.strip()) for x in state_m.group(1).split(",") if x.strip().isdigit()] if state_m else []
                priorities = [int(x.strip()) for x in priority_m.group(1).split(",") if x.strip().isdigit()] if priority_m else []
                powerlimits = [int(x.strip()) for x in powerlimit_m.group(1).split(",") if x.strip().isdigit()] if powerlimit_m else []
                powers = [float(x.strip()) for x in power_m.group(1).split(",") if x.strip().replace(".", "").isdigit()]
                currents = [float(x.strip()) for x in current_m.group(1).split(",") if x.strip().replace(".", "").isdigit()]
                voltages = [float(x.strip()) for x in voltage_m.group(1).split(",") if x.strip().replace(".", "").isdigit()] if voltage_m else []
                pdclasses = [int(x.strip()) for x in pdclass_m.group(1).split(",") if x.strip().isdigit()] if pdclass_m else []
                powerstatuses = [int(x.strip()) for x in powerstatus_m.group(1).split(",") if x.strip().isdigit()] if powerstatus_m else []

                count = min(len(powers), poe_port_count) if poe_port_count else len(powers)
                for i in range(1, count + 1):
                    idx = i - 1
                    st_val = states[idx] if idx < len(states) else 1
                    st_str = "Enable" if st_val == 1 else "Disable"

                    prio_val = priorities[idx] if idx < len(priorities) else 2
                    prio_str = POE_PRIORITY_MAP.get(prio_val, "Low")

                    pl_val = powerlimits[idx] if idx < len(powerlimits) else 300
                    pl_str = POE_CLASS_MAP.get(pl_val, f"{pl_val / 10.0:.1f}W")

                    pwr_val = powers[idx] / 10.0
                    cur_val = currents[idx]
                    volt_val = voltages[idx] / 10.0 if voltages[idx] > 0 else 0.0

                    pd_val = pdclasses[idx] if idx < len(pdclasses) else 154
                    pd_str = POE_CLASS_MAP.get(pd_val, f"Class {pd_val}")

                    pstatus_val = powerstatuses[idx] if idx < len(powerstatuses) else (2 if cur_val > 0 else 0)
                    pstatus_str = POE_STATUS_MAP.get(pstatus_val, "ON" if pstatus_val == 2 else "OFF")

                    result[i] = PoeConfigItem(
                        port=i,
                        poe_status=st_str,
                        poe_priority=prio_str,
                        power_limit=pl_str,
                        power_w=round(pwr_val, 1),
                        current_ma=round(cur_val, 0),
                        voltage_v=round(volt_val, 1),
                        pd_class=pd_str,
                        power_status=pstatus_str
                    )

                if result:
                    return result, global_poe
            except Exception as e:
                logger.debug("[%s] JS array parse error for PoE Config: %s", self.target.name, e)

        # 3. Fallback: Parse HTML table
        soup = BeautifulSoup(html, "html.parser")
        for tr in soup.find_all("tr"):
            tds = [td.get_text(strip=True) for td in tr.find_all("td")]
            if len(tds) >= 8 and "port" in tds[0].lower():
                # Format: Port 1, Enable, Low, Class 4, 7.1, 137, 52.3, Class 3, ON
                port_match = re.search(r"(\d+)", tds[0])
                if not port_match:
                    continue
                port_num = int(port_match.group(1))
                poe_status = tds[1]
                poe_priority = tds[2]
                power_limit = tds[3]
                try:
                    power_w = float(tds[4])
                except ValueError:
                    power_w = 0.0
                try:
                    current_ma = float(tds[5])
                except ValueError:
                    current_ma = 0.0
                try:
                    voltage_v = float(tds[6])
                except ValueError:
                    voltage_v = 0.0
                pd_class = tds[7]
                power_status = tds[8] if len(tds) > 8 else ("ON" if current_ma > 0 else "OFF")

                result[port_num] = PoeConfigItem(
                    port=port_num,
                    poe_status=poe_status,
                    poe_priority=poe_priority,
                    power_limit=power_limit,
                    power_w=power_w,
                    current_ma=current_ma,
                    voltage_v=voltage_v,
                    pd_class=pd_class,
                    power_status=power_status
                )

        return result, global_poe

    async def logout(self):
        """Release the switch session immediately so human administrators can use the Web GUI."""
        if self._session and not self._session.closed:
            try:
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                    "Referer": f"{self.target.base_url}/",
                }
                async with self._session.get(f"{self.target.base_url}/Logout.htm", headers=headers, timeout=2.0) as _:
                    pass
            except Exception:
                pass
            finally:
                self._authenticated = False
                if self._session and not self._session.closed and self._session.cookie_jar:
                    self._session.cookie_jar.clear()

    async def scrape(self) -> SwitchSnapshot:
        """Execute full scrape cycle: fetch Port Statistics and PoE Config."""
        async with self._lock:
            t0 = time.time()
            logger.info("[%s] Scraping switch at %s...", self.target.name, self.target.base_url)

            # 1. Fetch Port Statistics
            port_html = await self._fetch_page("PortStatisticsRpm.htm")
            if port_html is None:
                await self.logout()
                self.snapshot.status = "OFFLINE"
                self.snapshot.port_stats = {}
                self.snapshot.poe_stats = {}
                self.snapshot.global_poe = GlobalPoeState(0.0, 0.0, 0.0)
                if not self.snapshot.error_message:
                    self.snapshot.error_message = "Failed to connect or authenticate"
                return self.snapshot

            port_stats = self.parse_port_statistics(port_html)

            # 2. Fetch PoE Config
            poe_html = await self._fetch_page("PoeConfigRpm.htm")
            poe_stats: Dict[int, PoeConfigItem] = {}
            global_poe = GlobalPoeState()
            if poe_html:
                poe_stats, global_poe = self.parse_poe_config(poe_html)
            elif self.snapshot.poe_stats:
                # Keep last known good PoE stats if secondary request had transient timeout
                poe_stats = self.snapshot.poe_stats
                global_poe = self.snapshot.global_poe

            # Immediately release switch session so administrator can access Web GUI
            await self.logout()

            # Update snapshot
            self.snapshot.port_stats = port_stats
            self.snapshot.poe_stats = poe_stats
            self.snapshot.global_poe = global_poe
            self.snapshot.last_scraped = time.time()
            self.snapshot.status = "ONLINE"
            self.snapshot.error_message = ""

            elapsed = time.time() - t0
            logger.info(
                "[%s] Scraped successfully in %.2fs: %d ports, %d PoE ports (Total PoE: %.1fW / %.1fW)",
                self.target.name,
                elapsed,
                len(port_stats),
                len(poe_stats),
                global_poe.power_consumption,
                global_poe.power_limit
            )
            return self.snapshot
