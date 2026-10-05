"""
Configuration loader and validator.
Loads configuration from environment variables and .env file.
Supports dynamic switch target lists (numbered env variables or delimited list).
"""

import os
import re
import logging
from dataclasses import dataclass, field
from typing import List, Optional
from dotenv import load_dotenv

# Load .env file if present
load_dotenv()

logger = logging.getLogger(__name__)


@dataclass
class SwitchTarget:
    """Represents a single target switch to scrape and expose via SNMP."""
    id: int
    ip: str
    user: str
    password: str
    snmp_port: int
    name: str = ""
    use_https: bool = False
    http_port: int = 80
    model: str = "TL-SG1016PE"

    @property
    def base_url(self) -> str:
        protocol = "https" if self.use_https else "http"
        # If IP already has scheme, clean it
        clean_ip = self.ip
        if clean_ip.startswith("http://"):
            clean_ip = clean_ip[7:]
        elif clean_ip.startswith("https://"):
            clean_ip = clean_ip[8:]
        clean_ip = clean_ip.rstrip("/")
        if ":" in clean_ip and not clean_ip.endswith("]"):  # port included
            return f"{protocol}://{clean_ip}"
        if (self.use_https and self.http_port != 443) or (not self.use_https and self.http_port != 80):
            return f"{protocol}://{clean_ip}:{self.http_port}"
        return f"{protocol}://{clean_ip}"

    @property
    def clean_ip(self) -> str:
        ip = self.ip
        if ip.startswith("http://"):
            ip = ip[7:]
        elif ip.startswith("https://"):
            ip = ip[8:]
        return ip.split(":")[0].rstrip("/")


@dataclass
class SnmpConfig:
    """SNMP agent configuration."""
    version: str = "both"  # v2c, v3, or both
    community: str = "public"
    
    # SNMP v3
    v3_user: str = "zabbix"
    v3_sec_level: str = "authPriv"  # noAuthNoPriv, authNoPriv, authPriv
    v3_auth_protocol: str = "SHA"   # MD5, SHA, SHA224, SHA256, SHA384, SHA512
    v3_auth_passphrase: str = "authpass123"
    v3_priv_protocol: str = "AES"   # DES, AES, AES128, AES192, AES256
    v3_priv_passphrase: str = "privpass123"


@dataclass
class AppConfig:
    """Global application settings."""
    app_host: str = "0.0.0.0"
    web_port: int = 8080
    web_user: str = ""
    web_password: str = ""
    refresh_interval: int = 10
    log_level: str = "INFO"
    mock_mode: bool = False
    snmp: SnmpConfig = field(default_factory=SnmpConfig)
    switches: List[SwitchTarget] = field(default_factory=list)


def parse_config() -> AppConfig:
    """Parse configuration from environment variables."""
    config = AppConfig()
    
    config.app_host = os.getenv("APP_HOST", "0.0.0.0")
    config.web_port = int(os.getenv("WEB_PORT", "8080"))
    config.web_user = os.getenv("WEB_USER", "").strip()
    config.web_password = os.getenv("WEB_PASSWORD", "").strip()
    
    # Refresh interval - supports REFRESHED_PAGE or REFRESH_INTERVAL
    refreshed_page_env = os.getenv("REFRESHED_PAGE") or os.getenv("REFRESH_INTERVAL") or "10"
    try:
        config.refresh_interval = max(3, int(refreshed_page_env))
    except ValueError:
        config.refresh_interval = 10
        
    config.log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    config.mock_mode = os.getenv("MOCK_MODE", "false").lower() in ("true", "1", "yes")

    # SNMP Settings
    snmp = SnmpConfig()
    snmp.version = os.getenv("SNMP_VERSION", "both").lower()
    snmp.community = os.getenv("SNMP_COMMUNITY", "public")
    snmp.v3_user = os.getenv("SNMP_V3_USER", "zabbix")
    snmp.v3_sec_level = os.getenv("SNMP_V3_SEC_LEVEL", "authPriv")
    snmp.v3_auth_protocol = os.getenv("SNMP_V3_AUTH_PROTOCOL", "SHA").upper()
    snmp.v3_auth_passphrase = os.getenv("SNMP_V3_AUTH_PASSPHRASE", "authpass123")
    snmp.v3_priv_protocol = os.getenv("SNMP_V3_PRIV_PROTOCOL", "AES").upper()
    snmp.v3_priv_passphrase = os.getenv("SNMP_V3_PRIV_PASSPHRASE", "privpass123")
    config.snmp = snmp

    # Parse Switches:
    switches: List[SwitchTarget] = []
    
    # 1. Look for numbered environment variables: SWITCH_1_IP, SWITCH_2_IP, ...
    pattern = re.compile(r"^SWITCH_(\d+)_IP$", re.IGNORECASE)
    found_indices = []
    for k in os.environ.keys():
        match = pattern.match(k)
        if match:
            found_indices.append(int(match.group(1)))
            
    found_indices.sort()
    for idx in found_indices:
        ip = os.getenv(f"SWITCH_{idx}_IP", "").strip()
        if not ip:
            continue
        user = os.getenv(f"SWITCH_{idx}_USER", os.getenv("SWITCH_DEFAULT_USER", "admin")).strip()
        pwd = os.getenv(f"SWITCH_{idx}_PASS", os.getenv("SWITCH_DEFAULT_PASS", "admin123")).strip()
        snmp_port_str = os.getenv(f"SWITCH_{idx}_SNMP_PORT", str(160 + idx))
        try:
            snmp_port = int(snmp_port_str)
        except ValueError:
            snmp_port = 160 + idx
            
        name = os.getenv(f"SWITCH_{idx}_NAME", f"Switch-{idx}-{ip}").strip()
        use_https = os.getenv(f"SWITCH_{idx}_HTTPS", "false").lower() in ("true", "1", "yes")
        http_port = int(os.getenv(f"SWITCH_{idx}_HTTP_PORT", "443" if use_https else "80"))
        model = os.getenv(f"SWITCH_{idx}_MODEL", "TL-SG1016PE").strip()
        
        switches.append(
            SwitchTarget(
                id=idx,
                ip=ip,
                user=user,
                password=pwd,
                snmp_port=snmp_port,
                name=name,
                use_https=use_https,
                http_port=http_port,
                model=model
            )
        )

    # 2. Look for comma-delimited SWITCH_TARGETS if no numbered variables or in addition
    # Format: ip:user:pass:port[:name],...
    targets_str = os.getenv("SWITCH_TARGETS", "").strip()
    if targets_str:
        entries = targets_str.split(",")
        base_id = len(switches) + 1
        for item in entries:
            item = item.strip()
            if not item:
                continue
            parts = item.split(":")
            if len(parts) >= 3:
                # parts: host, user, pass, [snmp_port], [name]
                s_ip = parts[0]
                s_user = parts[1]
                s_pass = parts[2]
                s_port = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 160 + base_id
                s_name = parts[4] if len(parts) > 4 else f"Switch-{base_id}-{s_ip}"
                switches.append(
                    SwitchTarget(
                        id=base_id,
                        ip=s_ip,
                        user=s_user,
                        password=s_pass,
                        snmp_port=s_port,
                        name=s_name
                    )
                )
                base_id += 1

    if not switches:
        logger.warning("No switch targets configured in .env (all commented out or empty).")

    config.switches = switches
    return config
