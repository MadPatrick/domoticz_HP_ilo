# HP Integrated Lights-Out (iLO) – Domoticz Plugin

A Domoticz Python plugin to read sensor data from an HP iLO interface.

---

## Requirements

- Domoticz with Python plugin support (version 2020.2 or newer recommended)
- Python 3
- The `python-hpilo` Python library

### Install the Python library

```bash
pip3 install python-hpilo
```

---

## Installation

1. Navigate to the Domoticz plugins directory:

   ```bash
   cd /home/<user>/domoticz/plugins
   ```

2. Create a directory for the plugin and place `plugin.py` in it:

   ```bash
   mkdir HP_ilo
   cd HP_ilo
   # Copy plugin.py into this directory, or clone the repository:
   git clone https://github.com/MadPatrick/HP_ilo.git .
   ```

3. Restart Domoticz:

   ```bash
   sudo systemctl restart domoticz
   ```

---

## Configuration

In Domoticz, go to **Settings → Hardware** and add a new hardware device of type **HP Integrated Lights-Out (iLO)**.

| Parameter | Description | Default |
|-----------|-------------|-----------|
| IP Address / Hostname | The IP address or hostname of the iLO interface | `192.168.1.1` |
| Port | TCP port of the iLO interface | `443` |
| Username | iLO login username | `Administrator` |
| Password | iLO login password | *(empty)* |
| Poll Interval (sec) | How often data is retrieved (10–3600 sec) | `300` |
| Debug | Enable or disable verbose logging | `Off` |

---

## Created devices

After the first successful connection, the following Domoticz devices are created automatically:

Device names are automatically prefixed with a server identifier in this order:
1. Asset tag
2. Serial number
3. Server name
4. Configured iLO host/IP

Example: `[ASSET-1234] Server Name`

| Unit | Name | Description |
|------|------|-------------|
| 1 | `[identifier] Server Name` | Name of the server |
| 2 | `[identifier] Server FQDN` | Fully qualified domain name |
| 3 | `[identifier] Server Power State` | Power status (on/off) |
| 4 | `[identifier] Server Power On Time` | Time powered on |
| 5 | `[identifier] Server Asset Tag` | Server asset tag |
| 6 | `[identifier] Server UID Light` | UID light status |
| 7 | `[identifier] Server Health` | Hardware health overview |
| 8 | `[identifier] Network Settings` | IP address, subnet mask, gateway, DNS, and MAC |
| 9 | `[identifier] Server Host Data` | Key host data (product/serial/etc.) |
| 10 | `[identifier] Fan 1 Speed` | Fan speed |
| 11 | `[identifier] CPU Temperature` | CPU temperature |
| 12 | `[identifier] Inlet Ambient Temperature` | Inlet temperature |
| 13 | `[identifier] iLO Firmware Version` | iLO firmware version |
| 14 | `[identifier] Storage Status` | Storage/RAID health |

---

## Troubleshooting

- **iLO login failed** – Verify the username and password.
- **iLO communication error** – Check the IP address, port, and whether iLO is reachable from the Domoticz server.
- Enable **Debug** in hardware settings for detailed log messages in the Domoticz log.

---

## License

This project was ported from the [Home Assistant HP iLO integration](https://www.home-assistant.io/integrations/hp_ilo).
