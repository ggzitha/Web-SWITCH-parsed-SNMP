# TP-Link Easy Smart Switch Web-to-SNMP Gateway

A Python-based monitoring gateway and SNMP agent that scrapes Web GUIs of **TP-Link Easy Smart Switches** (such as **TL-SG1016PE**, **TL-SG108PE**, etc.) and serves valid **SNMP v2c** and **SNMP v3** (AuthPriv) metrics to monitoring platforms like **Zabbix**.

---

## 🌟 Key Features

- **Multi-Switch Dynamic Targets**: Configure any number of switches in `.env` (`SWITCH_1_...`, `SWITCH_2_...` or delimited strings).
- **Independent SNMP UDP Ports**: Each switch is exposed on its own dedicated SNMP port (e.g. `161`, `162`, `163`, etc.).
- **Real Switch Identity Reporting**: When Zabbix queries the docker server (e.g., `192.168.88.8:161`), the SNMP agent reports the switch's real IP address (e.g., `192.168.88.150`) in standard MIB-II `sysName` (`1.3.6.1.2.1.1.5.0`).
- **Complete Metric Scraping**:
  - **Monitoring > Port Statistics**: Port status, link speed (e.g., 1000M Full, Link Down), `TxGoodPkt`, `TxBadPkt`, `RxGoodPkt`, `RxBadPkt`.
  - **PoE > PoE Config**: Port PoE status, priority, power limits, real-time power (W), current (mA), voltage (V), PD class, and power status (ON/OFF).
  - **Global PoE Budget**: Total power limit, power consumption, and power remaining.
- **Standards-Compliant MIBs**:
  - Standard **RFC 1213 / SNMPv2-MIB** (`sysDescr`, `sysName`, `sysUpTime`)
  - Standard **IF-MIB** (`ifIndex`, `ifDescr`, `ifOperStatus`, `ifSpeed`, `ifInUcastPkts`, `ifOutUcastPkts`, `ifInErrors`, `ifOutErrors`)
  - Standard **POWER-ETHERNET-MIB (RFC 3621)** (`pethMainPsePower`, `pethMainPseConsumptionPower`, `pethPsePortDetectionStatus`)
  - Custom Enterprise Tree (`1.3.6.1.4.1.11863.6`) for full granularity.
- **Configurable Polling Interval**: Update period configurable via `.env` (`REFRESHED_PAGE=10`).
- **SNMP v2c & v3 Support**: Supports both community strings and USM AuthPriv (SHA/AES, MD5/DES, etc.).
- **Built-in Web Dashboard**: Real-time dark mode web dashboard at `http://localhost:8080` with a live SNMP OID explorer.
- **Ready-to-Use Zabbix Template**: Includes `zabbix/zabbix_template_tl_sg1016pe.yaml` with Low-Level Discovery (LLD) for ports and PoE.
- **Docker Ready**: Production `Dockerfile` and `docker-compose.yml`.

---

## 🏗️ Architecture

```
[TP-Link TL-SG1016PE (192.168.88.150)]  ---> HTTP Scrape (logon.cgi)
[TP-Link TL-SG1016PE (192.168.88.151)]  ---> PortStatisticsRpm.htm
[TP-Link TL-SG1016PE (192.168.88.153)]  ---> PoeConfigRpm.htm
                                                      │
                                                      ▼
                              ┌───────────────────────────────────────────────┐
                              │  Python Web-to-SNMP Gateway (Docker/Host)     │
                              │  - Background Scraper (every 10s)             │
                              │  - In-Memory MIB Tree (610+ OIDs per switch)  │
                              │  - Web Dashboard (Port 8080)                  │
                              └───────┬───────────────┬───────────────┬───────┘
                                      │               │               │
                                   UDP:161         UDP:162         UDP:163
                                      │               │               │
                                      ▼               ▼               ▼
                        ┌─────────────────────────────────────────────────────┐
                        │              Zabbix Server / Proxy                  │
                        │   - Queries 192.168.88.8:161 for Switch 1 (.150)   │
                        │   - Queries 192.168.88.8:162 for Switch 2 (.151)   │
                        │   - Queries 192.168.88.8:163 for Switch 3 (.152)   │
                        └─────────────────────────────────────────────────────┘
```

---

## ⚙️ Configuration (.env)

Edit the `.env` file to customize targets and credentials:

```bash
# Server & Dashboard Settings
APP_HOST=0.0.0.0
WEB_PORT=8080
REFRESHED_PAGE=10
LOG_LEVEL=INFO
MOCK_MODE=false

# SNMP Global Configuration (v2c, v3, or both)
SNMP_VERSION=both
SNMP_COMMUNITY=public

# SNMP v3 USM Configuration
SNMP_V3_USER=zabbix
SNMP_V3_SEC_LEVEL=authPriv
SNMP_V3_AUTH_PROTOCOL=SHA
SNMP_V3_AUTH_PASSPHRASE=admin12345
SNMP_V3_PRIV_PROTOCOL=AES
SNMP_V3_PRIV_PASSPHRASE=admin12345

# --- Dynamic Target Switches ---
# Switch 1: 192.168.88.150 mapped to SNMP UDP Port 161
SWITCH_1_IP=192.168.88.150
SWITCH_1_USER=admin_1
SWITCH_1_PASS=admin4321
SWITCH_1_SNMP_PORT=161
SWITCH_1_NAME=TL-SG1016PE-150

# Switch 2: 192.168.88.151 mapped to SNMP UDP Port 162
SWITCH_2_IP=192.168.88.151
SWITCH_2_USER=admin
SWITCH_2_PASS=admin123
SWITCH_2_SNMP_PORT=162
SWITCH_2_NAME=TL-SG1016PE-151

# Switch 3: 192.168.88.152 mapped to SNMP UDP Port 163
SWITCH_3_IP=192.168.88.152
SWITCH_3_USER=admin
SWITCH_3_PASS=admin123
SWITCH_3_SNMP_PORT=163
SWITCH_3_NAME=TL-SG1016PE-152

# Switch 4: 192.168.88.153 mapped to SNMP UDP Port 164
SWITCH_4_IP=192.168.88.153
SWITCH_4_USER=admin
SWITCH_4_PASS=admin123
SWITCH_4_SNMP_PORT=164
SWITCH_4_NAME=TL-SG1016PE-153

# Switch 5: 192.168.88.154 mapped to SNMP UDP Port 165
SWITCH_5_IP=192.168.88.154
SWITCH_5_USER=admin
SWITCH_5_PASS=admin123
SWITCH_5_SNMP_PORT=165
SWITCH_5_NAME=TL-SG1016PE-154

# Switch 6: 192.168.88.155 mapped to SNMP UDP Port 166
SWITCH_6_IP=192.168.88.155
SWITCH_6_USER=admin
SWITCH_6_PASS=admin123
SWITCH_6_SNMP_PORT=166
SWITCH_6_NAME=TL-SG1016PE-155
```

---

## 🚀 Running Locally (Testing on Python)

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Run Test Suite
```bash
python -m pytest
```

### 3. Run the Gateway
```bash
python main.py
```

### 4. Test SNMP Response via CLI
```bash
# Test SNMP v2c on Switch 1 (port 161)
python test_snmp_cli.py --port 161 --version v2c

# Test SNMP v3 on Switch 1 (port 161)
python test_snmp_cli.py --port 161 --version v3

# Test SNMP v2c on Switch 2 (port 162)
python test_snmp_cli.py --port 162 --version v2c
```

### 5. Access the Web Dashboard
Open your browser to:
```
http://localhost:8080
```
Here you can observe live table refresh, PoE power bars, and inspect the raw OID map.

---

## 🐳 Running with Docker

### Build and Start with Docker Compose
```bash
docker compose up -d
```

Check logs:
```bash
docker compose logs -f
```

---

## 📊 Querying with `snmpwalk` / `snmpget`

### SNMP v2c
```bash
# Query System Info (Returns real switch IP in sysName)
snmpwalk -v2c -c public 192.168.88.8:161 1.3.6.1.2.1.1

# Query Port Statistics (IF-MIB)
snmpwalk -v2c -c public 192.168.88.8:161 1.3.6.1.2.1.2.2.1

# Query Custom PoE & TP-Link Enterprise Metrics
snmpwalk -v2c -c public 192.168.88.8:161 1.3.6.1.4.1.11863.6
```

### SNMP v3 (AuthPriv)
```bash
snmpwalk -v3 -l authPriv \
  -u zabbix \
  -a SHA -A admin12345 \
  -x AES -X admin12345 \
  192.168.88.8:161 1.3.6.1.4.1.11863.6
```

---

## 📈 Zabbix Server Integration

1. In Zabbix Web UI, navigate to **Data collection** > **Templates**.
2. Click **Import** in the upper right corner and select `zabbix/zabbix_template_tl_sg1016pe.yaml`.
3. Create a Host for each switch:
   - **Host name**: `TL-SG1016PE-150`
   - **Interfaces**: Add **SNMP** interface:
     - IP address: `192.168.88.8` (Your Docker server IP)
     - Port: `161` (Or `162` for Switch 2, `163` for Switch 3, etc.)
     - SNMP version: `SNMPv2` or `SNMPv3`
     - Context name: leave empty
     - Security name / passphrase: as defined in `.env`
   - **Templates**: Link `TP-Link TL-SG1016PE Easy Smart Switch by SNMP`.
4. Low-Level Discovery (LLD) will automatically discover all 16 ethernet ports and 8 PoE ports, creating items, graphs, and triggers!

---

## 📖 OID Reference

| Metric | OID | Type | Example Value |
|---|---|---|---|
| **System Description** | `1.3.6.1.2.1.1.1.0` | OctetString | `TP-Link TL-SG1016PE Easy Smart Switch (TL-SG1016PE-150)` |
| **Real Switch IP** | `1.3.6.1.2.1.1.5.0` | OctetString | `192.168.88.150` |
| **System Uptime** | `1.3.6.1.2.1.1.3.0` | TimeTicks | `317800` |
| **Total PoE Power Limit** | `1.3.6.1.4.1.11863.6.1.5.0` | Gauge32 | `1100` (110.0W in 0.1W units) |
| **Total PoE Consumption**| `1.3.6.1.4.1.11863.6.1.6.0` | Gauge32 | `314` (31.4W in 0.1W units) |
| **Total PoE Remaining**  | `1.3.6.1.4.1.11863.6.1.7.0` | Gauge32 | `786` (78.6W in 0.1W units) |
| **Port Description**     | `1.3.6.1.2.1.2.2.1.2.{port}` | OctetString | `Port 1` |
| **Port Admin Status**    | `1.3.6.1.2.1.2.2.1.7.{port}` | Integer32 | `1` (Up/Enabled), `2` (Down) |
| **Port Oper Status**     | `1.3.6.1.2.1.2.2.1.8.{port}` | Integer32 | `1` (Up), `2` (Down) |
| **Port Link Speed**      | `1.3.6.1.2.1.31.1.1.1.15.{port}` | Gauge32 | `1000` (Mbps) |
| **Inbound Good Packets** | `1.3.6.1.2.1.2.2.1.11.{port}` | Counter32 | `1972140` |
| **Outbound Good Packets**| `1.3.6.1.2.1.2.2.1.17.{port}` | Counter32 | `8018133` |
| **Inbound Bad Packets**  | `1.3.6.1.2.1.2.2.1.14.{port}` | Counter32 | `3` |
| **Outbound Bad Packets** | `1.3.6.1.2.1.2.2.1.20.{port}` | Counter32 | `0` |
| **PoE Port Status**      | `1.3.6.1.4.1.11863.6.3.1.2.{port}` | OctetString | `Enable` |
| **PoE Port Priority**    | `1.3.6.1.4.1.11863.6.3.1.3.{port}` | OctetString | `Low` |
| **PoE Power Limit**      | `1.3.6.1.4.1.11863.6.3.1.4.{port}` | OctetString | `Class 4` |
| **PoE Power (0.1W)**     | `1.3.6.1.4.1.11863.6.3.1.5.{port}` | Gauge32 | `71` (7.1W) |
| **PoE Current (mA)**     | `1.3.6.1.4.1.11863.6.3.1.7.{port}` | Gauge32 | `137` (mA) |
| **PoE Voltage (0.1V)**   | `1.3.6.1.4.1.11863.6.3.1.8.{port}` | Gauge32 | `523` (52.3V) |
| **PoE PD Class**         | `1.3.6.1.4.1.11863.6.3.1.10.{port}`| OctetString | `Class 3` |
| **PoE Power State**      | `1.3.6.1.4.1.11863.6.3.1.11.{port}`| OctetString | `ON` |
