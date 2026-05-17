"""
HP Integrated Lights-Out (iLO) - Domoticz Python Plugin

Author: MadPatrick
Version: 1.0.1

<plugin key="hp_ilo" name="HP Integrated Lights-Out (iLO)" author="MadPatrick"
        version="1.0.1" wikilink="https://www.home-assistant.io/integrations/hp_ilo" externallink="https://github.com/MadPatrick/HP_ilo">
    <description>
        <br/><h2>HP Integrated Lights-Out (iLO)</h2>
        Reads sensor data from an HP iLO interface.
        <br/><br/>
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
import urllib3
import redfish

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- Device Units ---

UNIT_SERVER_NAME = 1
UNIT_POWER_STATE = 2
UNIT_HEALTH      = 3
UNIT_FAN_SPEED   = 4
UNIT_CPU_TEMP    = 5
UNIT_INLET_TEMP  = 6
UNIT_FIRMWARE    = 7
UNIT_STORAGE     = 8
UNIT_NETWORK     = 9
UNIT_SERIAL      = 10
UNIT_MODEL       = 11

# --- Device Definitions ---

SENSOR_DEFINITIONS = [
    (UNIT_SERVER_NAME, "Server Name",       243, 19, {}),
    (UNIT_POWER_STATE, "Power State",       243, 19, {}),
    (UNIT_HEALTH,      "Health",            243, 22, {}),
    (UNIT_FAN_SPEED,   "Fan Speed",         243,  6, {}),
    (UNIT_CPU_TEMP,    "CPU Temperature",    80,  5, {"Custom": "1;C"}),
    (UNIT_INLET_TEMP,  "Inlet Temperature",  80,  5, {"Custom": "1;C"}),
    (UNIT_FIRMWARE,    "iLO Firmware",      243, 19, {}),
    (UNIT_STORAGE,     "Storage",           243, 22, {}),
    (UNIT_NETWORK,     "Network",           243, 19, {}),
    (UNIT_SERIAL,      "Serial Number",     243, 19, {}),
    (UNIT_MODEL,       "Model",             243, 19, {}),
]

# --- Redfish Helper ---

class RedfishILO:
    def __init__(self, host, username, password, port=443):
        self.base_url = "https://{}:{}".format(host, port)
        self.client = redfish.redfish_client(
            base_url=self.base_url,
            username=username,
            password=password,
            default_prefix="/redfish/v1"
        )
        self.client.login(auth="session")

    def get(self, path):
        if path.startswith("http"):
            path = path.replace(self.base_url, "")
        response = self.client.get(path)
        if response.status not in [200, 201]:
            raise Exception("GET failed (HTTP {}): {}".format(response.status, path))
        return response.dict

    def logout(self):
        try:
            self.client.logout()
        except Exception:
            pass

# --- Plugin ---

class BasePlugin:
    def __init__(self):
        self.debug               = False
        self.poll_interval       = 300
        self.heartbeat_count     = 0
        self.heartbeats_per_poll = 1

    def onStart(self):
        self.debug = Parameters["Mode6"] == "1"
        if self.debug:
            Domoticz.Debugging(1)
        try:
            self.poll_interval = int(Parameters["Mode1"])
        except Exception:
            self.poll_interval = 300
        heartbeat_sec = 10
        self.heartbeats_per_poll = max(1, self.poll_interval // heartbeat_sec)
        Domoticz.Heartbeat(heartbeat_sec)
        Domoticz.Log("HP iLO Redfish plugin started")
        if "hpilo" not in Images:
            Domoticz.Image("hpilo_icons.zip").Create()
            Domoticz.Log("Created custom icon: hpilo")
        self._create_devices()
        self._connect_and_update()

    def onStop(self):
        Domoticz.Log("Plugin stopped")

    def onHeartbeat(self):
        self.heartbeat_count += 1
        if self.heartbeat_count >= self.heartbeats_per_poll:
            self.heartbeat_count = 0
            self._connect_and_update()

    def _create_devices(self):
        icon_id = Images["hpilo"].ID if "hpilo" in Images else 0
        for unit, name, type_num, subtype, options in SENSOR_DEFINITIONS:
            if unit not in Devices:
                Domoticz.Device(
                    Name=name,
                    Unit=unit,
                    Type=type_num,
                    Subtype=subtype,
                    Options=options,
                    Image=icon_id,
                    Used=1
                ).Create()
                Domoticz.Log("Created device: {}".format(name))

    def _update_device(self, unit, value, nvalue=0):
        if unit not in Devices:
            return
        Devices[unit].Update(nValue=nvalue, sValue=str(value))
        if self.debug:
            Domoticz.Log("Updated unit {} = {}".format(unit, value))

    def _connect_and_update(self):
        try:
            rf = RedfishILO(
                host=Parameters["Address"],
                username=Parameters["Username"],
                password=Parameters["Password"],
                port=int(Parameters["Port"])
            )
            self._fetch_and_push(rf)
            rf.logout()
        except Exception as err:
            Domoticz.Error("Redfish connection error: {}".format(err))

    def _get_first_member_uri(self, rf, collection_path):
        data    = rf.get(collection_path)
        members = data.get("Members", [])
        if not members:
            raise Exception("No members found in: {}".format(collection_path))
        uri = members[0].get("@odata.id")
        if not uri:
            raise Exception("No @odata.id in first member of: {}".format(collection_path))
        return uri

    def _fetch_and_push(self, rf):
        root = rf.get("/redfish/v1/")
        systems_path  = root.get("Systems",  {}).get("@odata.id", "/redfish/v1/Systems")
        chassis_path  = root.get("Chassis",  {}).get("@odata.id", "/redfish/v1/Chassis")
        managers_path = root.get("Managers", {}).get("@odata.id", "/redfish/v1/Managers")

        if self.debug:
            Domoticz.Log("Systems:  {}".format(systems_path))
            Domoticz.Log("Chassis:  {}".format(chassis_path))
            Domoticz.Log("Managers: {}".format(managers_path))

        # System
        try:
            system      = rf.get(self._get_first_member_uri(rf, systems_path))
            model       = system.get("Model",        "Unknown")
            bios        = system.get("BiosVersion",  "")
            model_str   = "{} | BIOS: {}".format(model, bios) if bios else model
            health      = system.get("Status", {}).get("Health", "Unknown")

            self._update_device(UNIT_SERVER_NAME, system.get("HostName",     "Unknown"))
            self._update_device(UNIT_POWER_STATE, system.get("PowerState",   "Unknown"))
            self._update_device(UNIT_SERIAL,      system.get("SerialNumber", "Unknown"))
            self._update_device(UNIT_MODEL,       model_str)

            if str(health).upper() == "OK":
                Devices[UNIT_HEALTH].Update(nValue=1, sValue="All OK")
            else:
                Devices[UNIT_HEALTH].Update(nValue=4, sValue=str(health))
        except Exception as err:
            Domoticz.Error("System error: {}".format(err))

        # Thermal
        try:
            thermal    = rf.get(self._get_first_member_uri(rf, chassis_path) + "/Thermal")
            fans       = thermal.get("Fans", [])
            fan_speed  = fans[0].get("Reading", 0) if fans else 0
            self._update_device(UNIT_FAN_SPEED, fan_speed)

            cpu_temp   = None
            inlet_temp = None
            for sensor in thermal.get("Temperatures", []):
                name    = sensor.get("Name", "").lower()
                reading = sensor.get("ReadingCelsius")
                if reading is None:
                    continue
                if "cpu" in name and cpu_temp is None:
                    cpu_temp = reading
                if "inlet ambient" in name or "ambient" in name:
                    inlet_temp = reading
                elif "inlet" in name and "board" not in name and inlet_temp is None:
                    inlet_temp = reading

            if cpu_temp is not None:
                self._update_device(UNIT_CPU_TEMP, cpu_temp)
            if inlet_temp is not None:
                self._update_device(UNIT_INLET_TEMP, inlet_temp)
        except Exception as err:
            Domoticz.Error("Thermal error: {}".format(err))

        # Firmware
        try:
            manager  = rf.get(self._get_first_member_uri(rf, managers_path))
            firmware = manager.get("FirmwareVersion", "Unknown")
            self._update_device(UNIT_FIRMWARE, firmware)
        except Exception as err:
            Domoticz.Error("Firmware error: {}".format(err))

        # Network
        try:
            manager_uri = self._get_first_member_uri(rf, managers_path)
            eth         = rf.get(self._get_first_member_uri(rf, manager_uri + "/EthernetInterfaces"))
            ipv4        = eth.get("IPv4Addresses", [])
            ip          = ipv4[0].get("Address", "N/A") if ipv4 else "N/A"
            mac         = eth.get("MACAddress", "N/A")
            self._update_device(UNIT_NETWORK, "IP: {} | MAC: {}".format(ip, mac))
        except Exception as err:
            Domoticz.Error("Network error: {}".format(err))

        # Storage
        try:
            system_uri = self._get_first_member_uri(rf, systems_path)
            storage    = rf.get(system_uri + "/Storage")
            bad, ok    = [], []
            for member in storage.get("Members", []):
                uri = member.get("@odata.id")
                if not uri:
                    continue
                ctrl   = rf.get(uri)
                name   = ctrl.get("Name", "Controller")
                status = ctrl.get("Status", {}).get("Health", "Unknown")
                if str(status).upper() != "OK":
                    bad.append("{}: {}".format(name, status))
                else:
                    ok.append(name)

            if bad:
                Devices[UNIT_STORAGE].Update(nValue=4, sValue=" | ".join(bad))
            elif ok:
                Devices[UNIT_STORAGE].Update(nValue=1, sValue="All OK: {}".format(", ".join(ok)))
            else:
                Devices[UNIT_STORAGE].Update(nValue=0, sValue="No storage data")
        except Exception as err:
            Domoticz.Error("Storage error: {}".format(err))

        Domoticz.Log("Redfish update completed")

# --- Domoticz Hooks ---

_plugin = BasePlugin()

def onStart():    _plugin.onStart()
def onStop():     _plugin.onStop()
def onHeartbeat(): _plugin.onHeartbeat()
