"""
HP Integrated Lights-Out (iLO) - Domoticz Python Plugin
Ported from Home Assistant integration.

Author: Ported from HA hp_ilo integration
Version: 1.0.0

<plugin key="hp_ilo" name="HP Integrated Lights-Out (iLO)" author="MadPatrick"
        version="1.0.0" wikillink="https://www.home-assistant.io/integrations/hp_ilo" externallink="https://github.com/MadPatrick/HP_ilo">
    <description>
        <h2>HP Integrated Lights-Out (iLO)</h2>
        Reads sensor data from an HP iLO interface.
        <h3>Parameters</h3>
        Enter the connection details for your HP iLO interface below.
    </description>
    <params>
        <param field="Address"  label="IP Address / Hostname" width="200px" required="true" default="192.168.1.1"/>
        <param field="Port"     label="Port"                  width="75px"  required="true" default="443"/>
        <param field="Username" label="Username"              width="150px" required="true" default="Administrator"/>
        <param field="Password" label="Password"              width="150px" required="true" default="" password="true"/>
        <param field="Mode1"    label="Poll interval (sec)"   width="75px"  required="true" default="300"/>
        <param field="Mode2"    label="Protocol"              width="120px">
            <options>
                <option label="Automatic" value="AUTO" default="true"/>
                <option label="ILO (XML/SSL)" value="ILO"/>
                <option label="LIPB (local)" value="LIPB"/>
            </options>
        </param>
        <param field="Mode6"    label="Debug"                 width="100px">
            <options>
                <option label="Off" value="0" default="true"/>
                <option label="On"  value="1"/>
            </options>
        </param>
    </params>
</plugin>
"""

import Domoticz  
import hpilo
from datetime import datetime

# ---------------------------------------------------------------------------
# Device unit numbers (1-255, unique per plugin instance)
# ---------------------------------------------------------------------------
UNIT_SERVER_NAME         = 1
UNIT_SERVER_FQDN         = 2
UNIT_POWER_STATUS        = 3
UNIT_POWER_ON_TIME       = 4
UNIT_ASSET_TAG           = 5
UNIT_UID_STATUS          = 6
UNIT_HEALTH              = 7
UNIT_NETWORK_SETTINGS    = 8
UNIT_SERVER_HOST_DATA    = 9
UNIT_FANS                = 10
UNIT_CPU_TEMP            = 11
UNIT_INLET_TEMP          = 12
UNIT_ILO_FIRMWARE        = 13
UNIT_STORAGE             = 14

# Definition: (unit, name, type, subtype, options-dict or None)
#   Domoticz type 243 = General, subtype 19 = Text
SENSOR_DEFINITIONS = [
    (UNIT_SERVER_NAME,      "Name",                    243, 19, {}),
    (UNIT_SERVER_FQDN,      "FQDN",                    243, 19, {}),
    (UNIT_POWER_STATUS,     "Power State",             243, 19, {}),
    (UNIT_POWER_ON_TIME,    "Power On Time",           243, 19, {}),
    (UNIT_ASSET_TAG,        "Asset Tag",               243, 19, {}),
    (UNIT_UID_STATUS,       "UID Light",               243, 19, {}),
    (UNIT_HEALTH,           "Health",                  243, 22, {}),
    (UNIT_NETWORK_SETTINGS, "Network Settings",        243, 19, {}),
    (UNIT_SERVER_HOST_DATA, "Host Data",               243, 19, {}),
    (UNIT_FANS,             "Fan 1 Speed",             243,  6, {}),
    (UNIT_CPU_TEMP,         "CPU Temperature",         80,  5,  {"Custom": "1;C"}),
    (UNIT_INLET_TEMP,       "Inlet Temperature",       80,  5,  {"Custom": "1;C"}),
    (UNIT_STORAGE,          "Storage Status",          243, 22, {}),
    (UNIT_ILO_FIRMWARE,     "iLO FW Version",          243, 19, {}),
]


class BasePlugin:
    """Main plugin class called by Domoticz."""

    def __init__(self):
        self._ilo = None
        self._poll_interval = 300  # seconds
        self._heartbeat_count = 0
        self._heartbeats_per_poll = 1
        self._debug = False
        self._icon_id = 0
        self._device_prefix = ""

    # ------------------------------------------------------------------
    # Lifecycle callbacks
    # ------------------------------------------------------------------

    def onStart(self):
        self._debug = Parameters["Mode6"] == "1"
        if self._debug:
            Domoticz.Debugging(1)
            Domoticz.Log("Debug mode enabled")

        # Set poll interval (minimum 10 sec, maximum 3600 sec)
        try:
            self._poll_interval = max(10, min(3600, int(Parameters["Mode1"])))
        except ValueError:
            self._poll_interval = 300

        # Domoticz heartbeat is 10 seconds by default
        heartbeat_sec = 10
        self._heartbeats_per_poll = max(1, self._poll_interval // heartbeat_sec)
        Domoticz.Heartbeat(heartbeat_sec)

        Domoticz.Log(
            f"HP iLO plugin started - host={Parameters['Address']}:{Parameters['Port']} "
            f"poll={self._poll_interval}s"
        )

        # Load icons (once, Domoticz stores them)
        if "hpilo" not in Images:
            Domoticz.Image("hpilo_icons.zip").Create()
        self._icon_id = Images["hpilo"].ID if "hpilo" in Images else 0

        # Create missing Domoticz devices
        self._create_devices()

        # Initial first connection
        self._connect_and_update()

    def onStop(self):
        Domoticz.Log("HP iLO plugin stopped.")

    def onHeartbeat(self):
        self._heartbeat_count += 1
        if self._heartbeat_count >= self._heartbeats_per_poll:
            self._heartbeat_count = 0
            self._connect_and_update()

    # ------------------------------------------------------------------
    # Internal helper functions
    # ------------------------------------------------------------------

    def _create_devices(self):
        """Create missing Domoticz devices."""
        for unit, name, type_num, subtype, options in SENSOR_DEFINITIONS:
            if unit not in Devices:
                icon = self._icon_id if unit != UNIT_HEALTH else 0
                Domoticz.Device(
                    Name=self._full_device_name(name),
                    Unit=unit,
                    Type=type_num,
                    Subtype=subtype,
                    Options=options,
                    Image=icon,
                    Used=1,
                ).Create()
                Domoticz.Log(f"Device created: {self._full_device_name(name)} (unit {unit})")

    def _full_device_name(self, base_name):
        if not self._device_prefix:
            return base_name
        return f"{self._device_prefix} {base_name}"

    def _clean_identifier(self, value):
        if value is None:
            return None
        candidate = str(value).strip()
        if not candidate:
            return None
        if candidate.upper() in {
            "N/A",
            "NA",
            "NONE",
            "NULL",
            "UNKNOWN",
            "NOT AVAILABLE",
            "NOT SET",
        }:
            return None
        return candidate

    def _update_device_prefix(self, asset_tag, serial_number, server_name):
        # Priority for recognizable name: asset tag -> serial number -> server name -> configured host/IP.
        for raw in (asset_tag, serial_number, server_name, Parameters["Address"]):
            identifier = self._clean_identifier(raw)
            if identifier:
                new_prefix = f"[{identifier}]"
                break
        else:
            new_prefix = ""

        if new_prefix == self._device_prefix:
            return

        self._device_prefix = new_prefix
        for unit, name, _type_num, _subtype, _options in SENSOR_DEFINITIONS:
            if unit in Devices:
                target_name = self._full_device_name(name)
                if Devices[unit].Name != target_name:
                    Devices[unit].Update(
                        nValue=Devices[unit].nValue,
                        sValue=Devices[unit].sValue,
                        Name=target_name,
                    )
        Domoticz.Log(f"Device name prefix set to: {self._device_prefix or '(none)'}")

    def _connect_and_update(self):
        """Connect to iLO and refresh all sensors."""
        host     = Parameters["Address"]
        port     = int(Parameters["Port"])
        login    = Parameters["Username"]
        password = Parameters["Password"]
        try:
            ilo = hpilo.Ilo(
                hostname=host,
                login=login,
                password=password,
                port=port,
            )
            self._fetch_and_push(ilo)
        except hpilo.IloLoginFailed as err:
            Domoticz.Error(f"iLO login failed: {err}")
        except hpilo.IloCommunicationError as err:
            Domoticz.Error(f"iLO communication error: {err}")
        except hpilo.IloError as err:
            Domoticz.Error(f"iLO error: {err}")
        except Exception as err:  # noqa: BLE001
            Domoticz.Error(f"Unexpected error during iLO connection: {err}")

    def _fetch_and_push(self, ilo: hpilo.Ilo):
        """Fetch iLO data and store in Domoticz devices."""

        def safe_get(func, *args, default="N/A"):
            """Call iLO method and catch errors."""
            try:
                result = func(*args)
                return result if result is not None else default
            except Exception as err:  # noqa: BLE001
                Domoticz.Error(f"Error in {func.__name__}: {err}")
                return default

        def update(unit, value):
            """Update Domoticz device if it exists."""
            if unit in Devices:
                svalue = str(value) if not isinstance(value, str) else value
                Devices[unit].Update(nValue=0, sValue=svalue)
                if self._debug:
                    Domoticz.Log(f"Unit {unit} updated: {svalue[:120]}")

        # --- Server name & FQDN ---
        server_name = safe_get(ilo.get_server_name)
        update(UNIT_SERVER_NAME, server_name)
        update(UNIT_SERVER_FQDN, safe_get(ilo.get_server_fqdn))

        # --- Power status ---
        power_status = safe_get(ilo.get_host_power_status)
        update(UNIT_POWER_STATUS, power_status)

        # --- Powered on since (converted to days/hours/minutes) ---
        power_on_time = safe_get(ilo.get_server_power_on_time, default=0)
        try:
            mins = int(power_on_time)
            days = mins // 1440
            hours = (mins % 1440) // 60
            remaining_mins = mins % 60
            power_on_str = f"{days}d {hours}h {remaining_mins}min"
        except (ValueError, TypeError):
            power_on_str = str(power_on_time)
        update(UNIT_POWER_ON_TIME, power_on_str)

        # --- Asset tag ---
        asset_raw = safe_get(ilo.get_asset_tag)
        if isinstance(asset_raw, dict):
            asset_val = asset_raw.get("asset_tag", next(iter(asset_raw.values()), "N/A"))
        else:
            asset_val = str(asset_raw)
        update(UNIT_ASSET_TAG, asset_val)

        # --- UID status ---
        update(UNIT_UID_STATUS, safe_get(ilo.get_uid_status))

        # --- Health (Alert device: 0=green/OK, 1=yellow, 2=orange, 4=red) ---
        health = safe_get(ilo.get_embedded_health)
        if isinstance(health, dict):
            summary = health.get("health_at_a_glance", {})
            not_ok = []
            if isinstance(summary, dict):
                for component, val in summary.items():
                    status = val.get("status", val) if isinstance(val, dict) else val
                    status_up = str(status).upper()
                    if status_up != "OK" and "NOT INSTALL" not in status_up:
                        not_ok.append(f"{component.replace('_',' ').title()}: {status}")
            if not_ok:
                alert_level = 4  # red
                alert_msg = " | ".join(not_ok)
            else:
                alert_level = 1  # green
                alert_msg = "All OK"
            if UNIT_HEALTH in Devices:
                Devices[UNIT_HEALTH].Update(nValue=alert_level, sValue=alert_msg)
        else:
            if UNIT_HEALTH in Devices:
                Devices[UNIT_HEALTH].Update(nValue=4, sValue="Health data not available")

        # --- Fans ---
        if isinstance(health, dict):
            fans = health.get("fans", {})
            fan_speed = None
            if isinstance(fans, dict):
                for fan_name, fan_data in fans.items():
                    if isinstance(fan_data, dict):
                        speed = fan_data.get("speed", None)
                        if speed is not None and fan_speed is None:
                            try:
                                fan_speed = int(speed[0]) if isinstance(speed, tuple) else int(str(speed).replace("%","").strip())
                            except (ValueError, TypeError):
                                pass
            update(UNIT_FANS, str(fan_speed) if fan_speed is not None else "0")

            # --- Temperaturen ---
            temps = health.get("temperature", {})
            cpu_temp   = None
            inlet_temp = None
            if isinstance(temps, dict):
                for sensor_name, temp_data in temps.items():
                    if isinstance(temp_data, dict):
                        reading = temp_data.get("currentreading", temp_data.get("reading", None))
                        label   = temp_data.get("label", sensor_name).lower()
                        try:
                            reading_int = int(reading[0]) if isinstance(reading, tuple) else int(str(reading).replace("C","").replace("F","").strip())
                        except (ValueError, TypeError):
                            reading_int = None
                        if reading_int is not None:
                            if ("cpu" in label or "p1 pkg" in label) and cpu_temp is None:
                                cpu_temp = reading_int
                            if ("inlet" in label or "ambient" in label) and inlet_temp is None:
                                inlet_temp = reading_int
            if cpu_temp is not None:
                update(UNIT_CPU_TEMP, str(cpu_temp))
            if inlet_temp is not None:
                update(UNIT_INLET_TEMP, str(inlet_temp))
        else:
            update(UNIT_FANS, "0")

        # --- Network settings ---
        net = safe_get(ilo.get_network_settings)
        if isinstance(net, dict):
            parts = []
            for key, label in [
                ("ip_address",          "IP"),
                ("subnet_mask",         "Mask"),
                ("gateway_ip_address",  "Gateway"),
                ("dns_name",            "DNS name"),
                ("mac_address",         "MAC"),
            ]:
                if net.get(key):
                    parts.append(f"{label}: {net[key]}")
            update(UNIT_NETWORK_SETTINGS, " | ".join(parts) if parts else "N/A")
        else:
            update(UNIT_NETWORK_SETTINGS, str(net)[:300])

        # --- Host data: show only the most relevant fields ---
        IMPORTANT_KEYS_ORDER = ("product name", "serial number", "family", "date")
        IMPORTANT_KEYS = set(IMPORTANT_KEYS_ORDER)
        NO_LABEL_KEYS = {"product name"}  # show only the value, without label

        def _fmt_host_field(norm, lbl, val):
            return val if norm in NO_LABEL_KEYS else f"{lbl}: {val}"

        def _render_host_data(collected):
            parts = [_fmt_host_field(k, *collected[k]) for k in IMPORTANT_KEYS_ORDER if k in collected]
            return " | ".join(parts) if parts else "N/A"

        def _collect_host_fields(data):
            collected = {}
            if not isinstance(data, dict):
                return collected
            for key, val in data.items():
                norm = key.lower().strip()
                if norm in IMPORTANT_KEYS and norm not in collected:
                    if isinstance(val, str) and val.strip() and val.isprintable():
                        collected[norm] = (key.replace("_", " ").title(), val.strip())
            return collected

        host_data = safe_get(ilo.get_host_data)
        serial_number = None
        if isinstance(host_data, list):
            collected = {}
            for entry in host_data:
                if not isinstance(entry, dict):
                    continue
                for norm, pair in _collect_host_fields(entry).items():
                    if norm not in collected:
                        collected[norm] = pair
            serial_number = collected.get("serial number", (None, None))[1]
            update(UNIT_SERVER_HOST_DATA, _render_host_data(collected))
        elif isinstance(host_data, dict):
            collected = _collect_host_fields(host_data)
            serial_number = collected.get("serial number", (None, None))[1]
            update(UNIT_SERVER_HOST_DATA, _render_host_data(collected))
        else:
            update(UNIT_SERVER_HOST_DATA, str(host_data)[:300])

        self._update_device_prefix(
            asset_tag=asset_val,
            serial_number=serial_number,
            server_name=server_name,
        )


        # --- iLO informatie ---
        try:
            ilo_info = ilo.get_fw_version()
            if isinstance(ilo_info, dict):
                fw  = ilo_info.get("firmware_version", ilo_info.get("firmware_date", "?"))
                mgmt = ilo_info.get("management_processor", "iLO")
                update(UNIT_ILO_FIRMWARE, f"{mgmt} {fw}")
            else:
                update(UNIT_ILO_FIRMWARE, str(ilo_info))
        except Exception as err:
            Domoticz.Error(f"Error in get_fw_version: {err}")

        # --- Storage / RAID ---
        try:
            # Reuse already fetched health data (no extra network call needed)
            storage = health
            # Log all available health keys and their type (including None values)
            if isinstance(storage, dict) and self._debug:
                for k, v in storage.items():
                    Domoticz.Log(f"DEBUG health[{k}]: {str(v)[:200]}")
            # Use `or []` so that None values are also correctly handled as empty list
            storage_raw = storage.get("storage") if isinstance(storage, dict) else None
            if self._debug:
                Domoticz.Log(f"DEBUG storage raw type={type(storage_raw).__name__} value={str(storage_raw)[:200]}")
            not_ok = []
            ok_parts = []

            # Normalize storage_data to a list of controller dicts
            if isinstance(storage_raw, list):
                storage_list = storage_raw
            elif isinstance(storage_raw, dict):
                # Some iLO versions return a dict: {name: {...}, ...}
                storage_list = list(storage_raw.values())
            else:
                storage_list = []

            for ctrl in storage_list:
                if not isinstance(ctrl, dict):
                    continue
                ctrl_label  = ctrl.get("label", "Controller")
                ctrl_status = ctrl.get("status", "OK")
                if ctrl_status and str(ctrl_status).upper() not in ("OK", ""):
                    not_ok.append(f"{ctrl_label}: {ctrl_status}")
                else:
                    ok_parts.append(ctrl_label)
                # Logical drives
                for ld in ctrl.get("logical_drives", []):
                    if not isinstance(ld, dict):
                        continue
                    ld_label  = ld.get("label", "Logical Drive")
                    ld_status = ld.get("status", "OK")
                    ld_cap    = ld.get("capacity", "")
                    ld_fault  = ld.get("fault_tolerance", "")
                    desc = ld_label
                    if ld_cap:
                        desc += f" {ld_cap}"
                    if ld_fault:
                        desc += f" ({ld_fault})"
                    if ld_status and str(ld_status).upper() not in ("OK", ""):
                        not_ok.append(f"{desc}: {ld_status}")
                    else:
                        ok_parts.append(desc)
                    # Physical drives
                    for pd in ld.get("physical_drives", []):
                        if not isinstance(pd, dict):
                            continue
                        pd_label  = pd.get("label", "Drive")
                        pd_status = pd.get("status", "OK")
                        pd_cap    = pd.get("capacity", "")
                        pd_media  = pd.get("drive_type", pd.get("media_type", ""))
                        desc = pd_label
                        if pd_cap:
                            desc += f" {pd_cap}"
                        if pd_media:
                            desc += f" ({pd_media})"
                        if pd_status and str(pd_status).upper() not in ("OK", ""):
                            not_ok.append(f"{desc}: {pd_status}")
                        else:
                            ok_parts.append(desc)

            if not_ok:
                if UNIT_STORAGE in Devices:
                    Devices[UNIT_STORAGE].Update(nValue=4, sValue=" | ".join(not_ok))
            elif ok_parts:
                if UNIT_STORAGE in Devices:
                    Devices[UNIT_STORAGE].Update(nValue=1, sValue="All OK: " + ", ".join(ok_parts))
            else:
                if UNIT_STORAGE in Devices:
                    Devices[UNIT_STORAGE].Update(nValue=0, sValue="Not available via iLO")
        except Exception as err:
            Domoticz.Error(f"Error in storage: {err}")

        Domoticz.Log("HP iLO sensors updated.")


# ---------------------------------------------------------------------------
# Domoticz plugin interface - required global functions
# ---------------------------------------------------------------------------

_plugin = BasePlugin()


def onStart():
    _plugin.onStart()


def onStop():
    _plugin.onStop()


def onHeartbeat():
    _plugin.onHeartbeat()
