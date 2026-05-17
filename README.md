# HP Integrated Lights-Out (iLO) – Domoticz Plugin

A Domoticz Python plugin to read sensor data from an HP iLO interface via Redfish.

---

## Requirements

- Domoticz with Python plugin support (version 2020.2 or newer recommended)
- Python 3
- The `redfish` Python library

### Install the Python library

```bash
pip3 install redfish
```

---

## Installation

1. Navigate to the Domoticz plugins directory:

   ```bash
   cd /home/<user>/domoticz/plugins
   ```

2. Clone the repository into a subdirectory:

   ```bash
   git clone https://github.com/MadPatrick/Domoticz_HP_ilo.git HP_ilo
   ```

3. Restart Domoticz:

   ```bash
   sudo systemctl restart domoticz
   ```

---

## Configuration

In Domoticz, go to **Settings → Hardware** and add a new hardware device of type **HP Integrated Lights-Out (iLO)**.

| Parameter | Description | Default |
|-----------|-------------|---------|
| IP Address / Hostname | The IP address or hostname of the iLO interface | `192.168.1.1` |
| Port | TCP port of the iLO interface | `443` |
| Username | iLO login username | `Administrator` |
| Password | iLO login password | *(empty)* |
| Poll interval (sec) | How often data is retrieved (in seconds) | `300` |
| Protocol | Connection protocol | `Automatic` |
| Debug | Enable or disable verbose logging | `Off` |

---

## Created devices

After the first successful connection, the following Domoticz devices are created automatically:

| Unit | Name | Description |
|------|------|-------------|
| 1 | `Server Name` | Hostname of the server |
| 2 | `Power State` | Power status (On/Off) |
| 3 | `Health` | Overall hardware health (OK / degraded) |
| 4 | `Fan Speed` | Speed of the first fan (RPM) |
| 5 | `CPU Temperature` | CPU temperature (°C) |
| 6 | `Inlet Temperature` | Inlet ambient temperature (°C) |
| 7 | `iLO Firmware` | iLO firmware version |
| 8 | `Storage` | Storage/RAID health status |
| 9 | `Network` | IP address and MAC address of the iLO interface |
| 10 | `Serial Number` | Server serial number |
| 11 | `Model` | Server model and BIOS version |

---

## Troubleshooting

- **iLO login failed** – Verify the username and password.
- **iLO communication error** – Check the IP address, port, and whether iLO is reachable from the Domoticz server.
- Enable **Debug** in hardware settings for detailed log messages in the Domoticz log.

---

## License

This project was ported from the [Home Assistant HP iLO integration](https://www.home-assistant.io/integrations/hp_ilo).
