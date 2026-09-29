"""
HP Integrated Lights-Out (iLO) - Domoticz Python Plugin

Author: MadPatrick
Version: 1.2.8

<plugin key="hp_ilo" name="HP Integrated Lights-Out (iLO)" author="MadPatrick"
        version="1.2.8" externallink="https://github.com/MadPatrick/HP_ilo">
    <description>
        <h2>HP Integrated Lights-Out (iLO)</h2>
        <p><strong>Version:</strong> 1.2.8</p>
        <p>Monitors and configures an HPE server through the iLO Redfish API.</p>
        <h3>Features</h3>
        <ul>
            <li>Health, temperature, fan, power, memory, processor, storage and SSD lifetime sensors.</li>
            <li>Server identification and firmware information.</li>
            <li>Minimum fan speed and thermal configuration controls when supported by iLO.</li>
            <li>Power Regulator mode control when supported by the server.</li>
        </ul>
        <h3>Configuration</h3>
        <p>Enter the iLO hostname, HTTPS port and an account with access to the required Redfish resources.</p>
    </description>
    <params>
        <param field="Address"  label="IP Address / Hostname" width="200px" required="true" default="192.168.1.1"/>
        <param field="Port"     label="Port"                  width="75px"  required="true" default="443"/>
        <param field="Username" label="Username"              width="150px" required="true" default="Administrator"/>
        <param field="Password" label="Password"              width="150px" required="true" default="" password="true"/>
        <param field="Mode1"    label="Poll interval (sec)"   width="75px"  required="true" default="300"/>
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
import json
import threading
import queue
import time
from datetime import datetime, timedelta

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- Device Units ---

UNIT_SERVER_NAME = 1
UNIT_POWER_STATE = 2
UNIT_HEALTH      = 3
UNIT_SSD_LIFETIME = 4
UNIT_CPU_TEMP    = 5
UNIT_INLET_TEMP  = 6
UNIT_FIRMWARE    = 7
UNIT_STORAGE     = 8
UNIT_NETWORK     = 9
UNIT_SERIAL      = 10
UNIT_MODEL       = 11
UNIT_MIN_FAN_SPEED = 12
UNIT_THERMAL_CONFIG = 13
UNIT_POWER_REGULATOR = 14

THERMAL_CONFIG_SELECTOR_STYLE = "1"
POWER_REGULATOR_SELECTOR_STYLE = "1"

MIN_FAN_PERCENT = 0
MAX_FAN_PERCENT = 100

THERMAL_CONFIG_OPTIONS = [
    (10, "Optimal Cooling", ["OptimalCooling", "Optimal", "Optimal_Cooling"]),
    (20, "Enhanced CPU Cooling", ["EnhancedCPUCooling", "EnhancedCpuCooling", "EnhancedCooling", "Enhanced_CPU_Cooling"]),
    (30, "Increased Cooling", ["IncreasedCooling", "Increased", "Increased_Cooling"]),
    (40, "Maximum Cooling", ["MaximumCooling", "Maximum", "MaxCooling", "Maximum_Cooling"]),
    (50, "Smooth Cooling", ["SmoothCooling", "Smooth", "Smooth_Cooling"]),
]

POWER_REGULATOR_OPTIONS = [
    (10, "Dynamic Power Savings Mode", ["DynamicPowerSavings", "DynamicPowerSavingsMode", "DynamicPowerSavings_Mode"]),
    (20, "Static Low Power Mode", ["StaticLowPower", "StaticLowPowerMode", "StaticLowPower_Mode"]),
    (30, "Static High Performance Mode", ["StaticHighPerf", "StaticHighPerformance", "StaticHighPerformanceMode", "StaticHighPerformance_Mode"]),
    (40, "OS Control Mode", ["OSControl", "OsControl", "OSControlMode", "OSControl_Mode"]),
]

POWER_REGULATOR_KEYS = (
    "PowerRegulator",
    "PowerRegulatorMode",
    "PowerProfile",
)

MIN_FAN_SETTING_KEYS = (
    "FanPercentMinimum",
    "MinimumFanSpeedPercent",
    "MinimumFanSpeed",
    "MinFanSpeedPercent",
    "MinFanSpeed",
    "FanSpeedMinimum",
    "FanSpeedMin",
    "FanMinimumPercent",
)

THERMAL_CONFIG_KEYS = (
    "ThermalConfiguration",
    "ThermalConfig",
    "CoolingConfiguration",
    "CoolingMode",
    "FanConfiguration",
)

# --- Device Definitions ---

SENSOR_DEFINITIONS = [
    (UNIT_SERVER_NAME, "Server Name",       243, 19, {}),
    (UNIT_POWER_STATE, "Power State",       243, 19, {}),
    (UNIT_HEALTH,      "Health",            243, 22, {}),
    (UNIT_SSD_LIFETIME, "SSD Lifetime",      243,  6, {"Migrated": "1"}),
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
    # Connect/read timeout (seconds) for the underlying Redfish HTTP client. Without
    # this, an unreachable iLO can block Domoticz's single callback thread indefinitely.
    CONNECT_TIMEOUT = 10

    def __init__(self, host, username, password, port=443, ca_cert=None):
        self.base_url = "https://{}:{}".format(host, port)
        self.client = redfish.redfish_client(
            base_url=self.base_url,
            username=username,
            password=password,
            default_prefix="/redfish/v1",
            timeout=self.CONNECT_TIMEOUT,
            cafile=ca_cert if ca_cert else None
        )
        self.client.login(auth="session")

    def get(self, path):
        if path.startswith("http"):
            path = path.replace(self.base_url, "")
        response = self.client.get(path)
        if response.status not in [200, 201]:
            raise Exception("GET failed (HTTP {}): {}".format(response.status, path))
        return response.dict

    def patch(self, path, payload):
        if path.startswith("http"):
            path = path.replace(self.base_url, "")
        try:
            response = self.client.patch(path, body=payload)
        except TypeError:
            response = self.client.patch(path, payload)
        if response.status not in [200, 201, 202, 204]:
            detail = self._response_detail(response)
            if detail:
                raise Exception("PATCH failed (HTTP {}): {} -> {}".format(response.status, path, detail))
            raise Exception("PATCH failed (HTTP {}): {}".format(response.status, path))
        return getattr(response, "dict", {})

    def _response_detail(self, response):
        for attr in ("dict", "obj"):
            value = getattr(response, attr, None)
            if value:
                try:
                    return json.dumps(value)
                except Exception:
                    return str(value)
        for attr in ("text", "content"):
            value = getattr(response, attr, None)
            if value:
                try:
                    if isinstance(value, bytes):
                        value = value.decode("utf-8", "replace")
                    return str(value)
                except Exception:
                    pass
        return ""

    def logout(self):
        try:
            self.client.logout()
        except Exception:
            pass

# --- Plugin ---

class BasePlugin:
    # Force a fresh Redfish login after this long, conservatively under a
    # typical iLO session-idle timeout, so a stale/invalidated session cannot
    # silently stop updating forever between age-based refreshes.
    SESSION_MAX_AGE = timedelta(minutes=25)

    # How long onStop() waits for an already-running fetch worker to finish
    # before giving up on it. The worker's Redfish calls are themselves
    # bounded by RedfishILO.CONNECT_TIMEOUT, so this only needs a small
    # margin on top of that for the one in-flight HTTP request to complete.
    WORKER_STOP_TIMEOUT = RedfishILO.CONNECT_TIMEOUT + 2

    # How long (seconds) a command received before Parameters is available
    # (e.g. Domoticz replaying a queued/scene command right at process start,
    # before onStart() has run) is held for retry before being dropped.
    PENDING_COMMAND_MAX_AGE_SECS = 120

    def __init__(self):
        self.debug               = False
        self.poll_interval       = 300
        self.heartbeat_count     = 0
        self.heartbeats_per_poll = 1
        self.min_fan_speed_supported = None
        self.thermal_config_supported = None
        self.power_regulator_supported = None
        # Cooldown timestamps: once a feature is marked unsupported after a total
        # PATCH failure, retry detection again after this time elapses instead of
        # disabling it for the rest of the plugin's process lifetime (a single
        # transient/network failure should not permanently silence a real feature).
        self.min_fan_speed_retry_after = None
        self.thermal_config_retry_after = None
        self.power_regulator_retry_after = None
        self.imageID = 0

        # Persistent Redfish session, reused across heartbeats/commands instead
        # of logging into iLO fresh on every single call. Access is serialized
        # through _redfish_lock since it's shared between the heartbeat worker
        # thread and onCommand (main thread).
        self._rf = None
        self._rf_created_at = None
        self._redfish_lock = threading.Lock()

        # Set by onStop() to block any new fetch worker from starting and to
        # let a running one wind down early, so onStop() never has to wait
        # behind _redfish_lock for a worker that keeps starting new work.
        self._stop_event = threading.Event()

        # The heartbeat's Redfish fetch runs on a background thread so a
        # slow/unreachable iLO never blocks Domoticz's single callback thread.
        # The worker only calls rf.get(...) (via _gather_all_sections, which
        # never touches Devices[...]); onHeartbeat performs all Devices[...]
        # updates on the main thread via _apply_all_sections().
        self._fetch_lock = threading.Lock()
        self._fetch_in_progress = False
        self._fetch_thread = None
        self._result_queue = queue.Queue()

        # Commands received before Parameters was ready, queued for retry on
        # the next onHeartbeat tick(s). Each entry: (Unit, Command, Level, Color, first_seen_ts).
        self._pending_commands = []

    @property
    def _devices(self):
        """Safely access the Domoticz Devices global, returning an empty dict if unavailable."""
        return globals().get('Devices', {})

    @property
    def _parameters(self):
        """Safely access the Domoticz Parameters global, returning an empty dict if
        unavailable. Domoticz can deliver a queued onCommand callback (e.g. one sent
        right before a full Domoticz restart) before this plugin's own Start()
        sequence has finished injecting Parameters - without this, that raises a
        confusing 'name Parameters is not defined' NameError deep inside Redfish
        connection setup instead of a clear, expected message."""
        return globals().get('Parameters', {})

    def _feature_blocked(self, supported_attr, retry_attr):
        """Return True if a control feature is currently known-unsupported and still
        within its retry cooldown. If the cooldown has elapsed, reset the feature's
        state to unknown so the next attempt re-probes the iLO instead of leaving it
        disabled forever.
        """
        if getattr(self, supported_attr) is False:
            retry_after = getattr(self, retry_attr)
            if retry_after is not None and datetime.now() >= retry_after:
                setattr(self, supported_attr, None)
                setattr(self, retry_attr, None)
                return False
            return True
        return False

    def _mark_feature_unsupported(self, supported_attr, retry_attr):
        """Mark a control feature unsupported for a cooldown period (currently 1
        hour) rather than permanently, so a genuine 'not supported' iLO response
        is only silenced temporarily and transient failures self-heal.
        """
        setattr(self, supported_attr, False)
        setattr(self, retry_attr, datetime.now() + timedelta(hours=1))

    def _get_device_svalue(self, unit):
        """Return the sValue of a device unit, or None if unavailable."""
        devices = self._devices
        return getattr(devices.get(unit), 'sValue', None)

    def _health_nvalue(self, health):
        """Map a Redfish Status.Health value to a Domoticz alert nValue,
        keeping Warning (3, orange) distinct from Critical (4, red) instead of
        collapsing every non-OK status to the same alarm level."""
        normalized = str(health).strip().upper()
        if normalized == "OK":
            return 1
        if normalized == "CRITICAL":
            return 4
        if normalized == "WARNING":
            return 3
        # Unrecognized/unset status: flag it as a warning rather than silently
        # treating it as OK, but distinguishable from a confirmed Critical.
        return 3

    def _get_redfish_client(self, force_new=False):
        """Returns the persistent Redfish session, creating (or refreshing) it
        as needed. Must only be called while holding self._redfish_lock."""
        now = datetime.now()
        if not force_new and self._rf is not None and self._rf_created_at is not None:
            if now - self._rf_created_at >= self.SESSION_MAX_AGE:
                force_new = True

        if force_new and self._rf is not None:
            try:
                self._rf.logout()
            except Exception:
                pass
            self._rf = None

        if self._rf is None:
            parameters = self._parameters
            if not parameters:
                raise RuntimeError(
                    "Domoticz Parameters not available yet (plugin still starting up); try again shortly"
                )
            self._rf = RedfishILO(
                host=parameters["Address"],
                username=parameters["Username"],
                password=parameters["Password"],
                port=int(parameters["Port"])
            )
            self._rf_created_at = now
        return self._rf

    def _with_redfish(self, action):
        """Runs `action(rf)` using the persistent Redfish session (serialized
        through self._redfish_lock, since it's shared between the heartbeat
        worker thread and onCommand), reconnecting and retrying once if the
        call fails - e.g. the session expired - instead of tearing down and
        creating a brand new iLO session on every single call."""
        with self._redfish_lock:
            rf = self._get_redfish_client()
            try:
                return action(rf)
            except Exception as first_err:
                if self.debug:
                    Domoticz.Log("Redfish call failed, reconnecting once: {}".format(first_err))
                rf = self._get_redfish_client(force_new=True)
                return action(rf)

    def _load_device_icon(self):
        # icon_name must start with this plugin's key ("hp_ilo") - Domoticz
        # only loads a plugin's pre-existing custom icons into Images at
        # startup when the icon's Base (in icons.txt) satisfies
        # Base LIKE '<PluginKey>%'. The short "hpilo" Base used before
        # didn't satisfy that, so Images never contained it on restart and
        # it was silently recreated (and re-logged as "created") every
        # single time instead of found.
        icon_name = "hp_ilo"
        existing_image = next(
            (image for name, image in Images.items()
             if str(name).casefold() == icon_name.casefold()),
            None,
        )
        if existing_image is not None:
            self.imageID = existing_image.ID
            Domoticz.Log("Icons found in database (ImageID={}).".format(self.imageID))
            return

        try:
            Domoticz.Image("hpilo_icons.zip").Create()
        except Exception as e:
            Domoticz.Error("Unable to load icon pack 'hpilo_icons.zip': {}".format(e))
            return
        created_image = next(
            (image for name, image in Images.items()
             if str(name).casefold() == icon_name.casefold()),
            None,
        )
        if created_image is not None:
            self.imageID = created_image.ID
            Domoticz.Log("Icons created and loaded.")
        else:
            Domoticz.Error("Unable to load icon pack 'hpilo_icons.zip'")

    def _apply_device_icon(self):
        if not self.imageID:
            return
        for device in Devices.values():
            if device.Image != self.imageID:
                device.Update(nValue=device.nValue, sValue=device.sValue, Image=self.imageID)

    def onStart(self):
        self._stop_event.clear()
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
        self._load_device_icon()
        self._delete_legacy_devices()
        self._create_devices()
        self._apply_device_icon()
        self._connect_and_update()

    def onStop(self):
        start = time.time()

        # 1/2. Mark shutdown so no new fetch worker can start (see
        # _connect_and_update), before we go anywhere near _redfish_lock -
        # a running worker may currently be holding it.
        self._stop_event.set()
        if self.debug:
            Domoticz.Log("HP iLO: shutdown requested.")

        # 3/4. Let an already-running worker finish on its own - bounded by
        # WORKER_STOP_TIMEOUT, never an unbounded join() - before touching
        # the lock it may hold.
        thread = self._fetch_thread
        if thread is not None and thread.is_alive():
            if self.debug:
                Domoticz.Log("HP iLO: waiting for active Redfish worker.")
            thread.join(timeout=self.WORKER_STOP_TIMEOUT)
            if thread.is_alive():
                Domoticz.Error("HP iLO: fetch worker did not stop within shutdown timeout.")
            elif self.debug:
                Domoticz.Log("HP iLO: Redfish worker finished.")
        self._fetch_thread = None

        # 5/6. Only now take _redfish_lock - the worker can no longer be
        # holding it - and close the persistent session.
        if self.debug:
            Domoticz.Log("HP iLO: closing Redfish session.")
        with self._redfish_lock:
            if self._rf is not None:
                try:
                    self._rf.logout()
                except Exception:
                    pass
                self._rf = None
                self._rf_created_at = None

        Domoticz.Log("HP iLO: Plugin stopped ({:.2f}s).".format(time.time() - start))

    def onHeartbeat(self):
        # Shutdown in progress: stop producing new Devices[...] updates
        # rather than processing whatever the worker queued up right before
        # it wound down.
        if self._stop_event.is_set():
            return

        self._flush_pending_commands()

        # Process any fetch cycle the background worker finished since the
        # last tick - main/callback thread, safe here to touch Devices[...].
        while True:
            try:
                status, payload = self._result_queue.get_nowait()
            except queue.Empty:
                break
            if status == "error":
                Domoticz.Error("Redfish connection error: {}".format(payload))
            else:
                self._apply_all_sections(payload)

        self.heartbeat_count += 1
        if self.heartbeat_count >= self.heartbeats_per_poll:
            self.heartbeat_count = 0
            self._connect_and_update()

    def onCommand(self, Unit, Command, Level, Color):
        # Shutdown already in progress: don't kick off a new synchronous
        # Redfish call that would only delay it further.
        if self._stop_event.is_set():
            return
        self._dispatch_command(Unit, Command, Level, Color, first_seen=None)

    def _flush_pending_commands(self):
        """Retry any commands that arrived before Parameters was ready. Called
        every onHeartbeat tick; a no-op when nothing is queued."""
        if not self._pending_commands:
            return

        pending, self._pending_commands = self._pending_commands, []
        for Unit, Command, Level, Color, first_seen in pending:
            self._dispatch_command(Unit, Command, Level, Color, first_seen=first_seen)

    def _dispatch_command(self, Unit, Command, Level, Color, first_seen):
        """Route a command to its handler. If Parameters isn't ready yet
        (Domoticz can replay a queued/scene command before onStart() has run),
        queue it for retry (up to PENDING_COMMAND_MAX_AGE_SECS) instead of
        letting it fail deep inside Redfish connection setup - `first_seen` is
        None for a fresh command from Domoticz, or the original queue
        timestamp when called from _flush_pending_commands."""
        if not self._parameters:
            now = time.time()
            queued_since = first_seen if first_seen is not None else now
            if now - queued_since > self.PENDING_COMMAND_MAX_AGE_SECS:
                Domoticz.Error(
                    "Giving up on command for Unit {}: Domoticz Parameters still not available after {}s.".format(
                        Unit, int(now - queued_since)
                    )
                )
                return
            self._pending_commands.append((Unit, Command, Level, Color, queued_since))
            if first_seen is None:
                Domoticz.Status(
                    "Domoticz Parameters not available yet (plugin still starting up); "
                    "command for Unit {} queued for retry.".format(Unit)
                )
            return

        if Unit == UNIT_MIN_FAN_SPEED:
            self._handle_min_fan_speed_command(Command, Level)
            return
        if Unit == UNIT_THERMAL_CONFIG:
            self._handle_thermal_config_command(Level)
            return
        if Unit == UNIT_POWER_REGULATOR:
            self._handle_power_regulator_command(Level)
            return

    def _delete_legacy_devices(self):
        if UNIT_THERMAL_CONFIG in Devices:
            try:
                options = getattr(Devices[UNIT_THERMAL_CONFIG], "Options", {})
                if options.get("SelectorStyle") != THERMAL_CONFIG_SELECTOR_STYLE:
                    Devices[UNIT_THERMAL_CONFIG].Delete()
                    Domoticz.Log("Recreated Thermal Configuration as selector menu")
            except Exception as err:
                Domoticz.Error("Unable to recreate Thermal Configuration selector: {}".format(err))

        if UNIT_SSD_LIFETIME in Devices:
            try:
                # Checks a marker in Options rather than Name/TypeName: Name is
                # freely user-editable in the Domoticz UI, so comparing against
                # a fixed string here would re-trigger this migration (and wipe
                # any custom name) on every single restart for anyone who ever
                # renamed the device - this migration should run at most once.
                options = getattr(Devices[UNIT_SSD_LIFETIME], "Options", {}) or {}
                if options.get("Migrated") != "1":
                    Devices[UNIT_SSD_LIFETIME].Delete()
                    Domoticz.Log("Recreated unit 4 as SSD Lifetime")
            except Exception as err:
                Domoticz.Error("Unable to recreate SSD Lifetime device: {}".format(err))

    def _create_devices(self):
        for unit, name, type_num, subtype, options in SENSOR_DEFINITIONS:
            if unit not in Devices:
                Domoticz.Device(
                    Name=name,
                    Unit=unit,
                    Type=type_num,
                    Subtype=subtype,
                    Options=options,
                    Image=self.imageID,
                    Used=1
                ).Create()
                Domoticz.Log("Created device: {}".format(name))


        if UNIT_MIN_FAN_SPEED not in Devices:
            Domoticz.Device(
                Name="Minimum Fan Speed",
                Unit=UNIT_MIN_FAN_SPEED,
                TypeName="Dimmer",
                Switchtype=7,
                Image=self.imageID,
                Used=1
            ).Create()
            Domoticz.Log("Created device: Minimum Fan Speed")

        if UNIT_THERMAL_CONFIG not in Devices:
            Domoticz.Device(
                Name="Thermal Configuration",
                Unit=UNIT_THERMAL_CONFIG,
                TypeName="Selector Switch",
                Switchtype=18,
                Options={
                    "LevelActions": "|||||",
                    "LevelNames": "Off|Optimal Cooling|Enhanced CPU Cooling|Increased Cooling|Maximum Cooling|Smooth Cooling",
                    "LevelOffHidden": "true",
                    "SelectorStyle": THERMAL_CONFIG_SELECTOR_STYLE
                },
                Image=self.imageID,
                Used=1
            ).Create()
            Domoticz.Log("Created device: Thermal Configuration")

        if UNIT_POWER_REGULATOR not in Devices:
            Domoticz.Device(
                Name="Power Regulator",
                Unit=UNIT_POWER_REGULATOR,
                TypeName="Selector Switch",
                Switchtype=18,
                Options={
                    "LevelActions": "|||",
                    "LevelNames": "Off|Dynamic Power Savings Mode|Static Low Power Mode|Static High Performance Mode|OS Control Mode",
                    "LevelOffHidden": "true",
                    "SelectorStyle": POWER_REGULATOR_SELECTOR_STYLE
                },
                Image=self.imageID,
                Used=1
            ).Create()
            Domoticz.Log("Created device: Power Regulator")

    def _update_device(self, unit, value, nvalue=0):
        if unit not in Devices:
            return
        Devices[unit].Update(nValue=nvalue, sValue=str(value))
        if self.debug:
            Domoticz.Log("Updated unit {} = {}".format(unit, value))


    def _update_min_fan_speed(self, percent):
        devices = self._devices
        if UNIT_MIN_FAN_SPEED not in devices or percent is None:
            return
        level = self._clamp_fan_percent(percent)
        devices[UNIT_MIN_FAN_SPEED].Update(nValue=2, sValue=str(level))
        if self.debug:
            Domoticz.Log("Updated minimum fan speed = {}%".format(level))

    def _update_thermal_config(self, config):
        devices = self._devices
        if UNIT_THERMAL_CONFIG not in devices or config is None:
            return
        level = self._thermal_config_to_level(config)
        if level is None:
            if self.debug:
                Domoticz.Log("Unknown thermal configuration value from iLO: {}".format(config))
            return
        devices[UNIT_THERMAL_CONFIG].Update(nValue=1, sValue=str(level))
        if self.debug:
            Domoticz.Log("Updated thermal configuration = {}".format(config))

    def _update_power_regulator(self, value):
        devices = self._devices
        if UNIT_POWER_REGULATOR not in devices or value is None:
            return
        level = self._power_regulator_to_level(value)
        if level is None:
            if self.debug:
                Domoticz.Log("Unknown power regulator value from iLO: {}".format(value))
            return
        devices[UNIT_POWER_REGULATOR].Update(nValue=1, sValue=str(level))
        if self.debug:
            Domoticz.Log("Updated power regulator = {}".format(value))

    def _restore_power_regulator_level(self, level):
        devices = self._devices
        if UNIT_POWER_REGULATOR not in devices or level is None:
            return
        devices[UNIT_POWER_REGULATOR].Update(nValue=1, sValue=str(level))

    def _handle_min_fan_speed_command(self, Command, Level):
        previous_level = self._get_device_svalue(UNIT_MIN_FAN_SPEED)
        if self._feature_blocked("min_fan_speed_supported", "min_fan_speed_retry_after"):
            Domoticz.Log("This iLO does not expose writable minimum fan speed via Redfish; restoring previous level")
            self._update_min_fan_speed(previous_level)
            self._connect_and_update()
            return

        percent = Level if Command == "Set Level" else previous_level
        percent = self._clamp_fan_percent(percent)
        Domoticz.Log("Setting iLO minimum fan speed to {}%".format(percent))

        def _do(rf):
            self._set_min_fan_speed_percent(rf, percent)
            self.min_fan_speed_supported = True
            self.min_fan_speed_retry_after = None
            self._update_min_fan_speed(percent)
            self._fetch_and_push(rf)

        try:
            self._with_redfish(_do)
        except Exception as err:
            if self._is_fan_control_not_writable(err):
                self._mark_feature_unsupported("min_fan_speed_supported", "min_fan_speed_retry_after")
                Domoticz.Error("iLO minimum fan speed is read-only or not exposed through this Redfish path")
            else:
                Domoticz.Error("Unable to set iLO minimum fan speed: {}".format(err))
            self._update_min_fan_speed(previous_level)
            self._connect_and_update()

    def _handle_thermal_config_command(self, Level):
        devices = self._devices
        previous_level = self._get_device_svalue(UNIT_THERMAL_CONFIG)
        if self._feature_blocked("thermal_config_supported", "thermal_config_retry_after"):
            Domoticz.Log("This iLO does not expose writable thermal configuration via Redfish; restoring previous level")
            self._restore_thermal_config_level(previous_level)
            self._connect_and_update()
            return

        config = self._thermal_level_to_value(Level)
        if config is None:
            self._restore_thermal_config_level(previous_level)
            return

        Domoticz.Log("Setting iLO thermal configuration to {}".format(config))

        def _do(rf):
            self._set_thermal_configuration(rf, config)
            self.thermal_config_supported = True
            self.thermal_config_retry_after = None
            if UNIT_THERMAL_CONFIG in devices:  # Devices may be absent in some onCommand contexts
                devices[UNIT_THERMAL_CONFIG].Update(nValue=1, sValue=str(Level))
            Domoticz.Log("Thermal configuration accepted; skipping immediate refresh because iLO may restart")

        try:
            self._with_redfish(_do)
            return
        except Exception as err:
            if self._is_fan_control_not_writable(err):
                self._mark_feature_unsupported("thermal_config_supported", "thermal_config_retry_after")
                Domoticz.Error("iLO thermal configuration is read-only or not exposed through this Redfish path")
            else:
                Domoticz.Error("Unable to set iLO thermal configuration: {}".format(err))
            self._restore_thermal_config_level(previous_level)
            self._connect_and_update()

    def _handle_power_regulator_command(self, Level):
        devices = self._devices
        previous_level = self._get_device_svalue(UNIT_POWER_REGULATOR)
        if self._feature_blocked("power_regulator_supported", "power_regulator_retry_after"):
            Domoticz.Log("This iLO does not expose writable power regulator via Redfish; restoring previous level")
            self._restore_power_regulator_level(previous_level)
            self._connect_and_update()
            return

        value = self._power_level_to_value(Level)
        if value is None:
            self._restore_power_regulator_level(previous_level)
            return

        Domoticz.Log("Setting iLO power regulator to {}".format(value))

        def _do(rf):
            self._set_power_regulator(rf, value)
            self.power_regulator_supported = True
            self.power_regulator_retry_after = None
            if UNIT_POWER_REGULATOR in devices:  # Devices may be absent in some onCommand contexts
                devices[UNIT_POWER_REGULATOR].Update(nValue=1, sValue=str(Level))
            Domoticz.Log("Power regulator accepted; a server reboot may be required before it becomes active")

        try:
            self._with_redfish(_do)
        except Exception as err:
            if self._is_fan_control_not_writable(err):
                self._mark_feature_unsupported("power_regulator_supported", "power_regulator_retry_after")
                Domoticz.Error("iLO power regulator is read-only or not exposed through this Redfish path")
            else:
                Domoticz.Error("Unable to set iLO power regulator: {}".format(err))
            self._restore_power_regulator_level(previous_level)
            self._connect_and_update()

    def _restore_thermal_config_level(self, level):
        devices = self._devices
        if UNIT_THERMAL_CONFIG not in devices or level is None:
            return
        devices[UNIT_THERMAL_CONFIG].Update(nValue=1, sValue=str(level))

    def _clamp_fan_percent(self, value):
        try:
            percent = int(round(float(value)))
        except Exception:
            percent = MIN_FAN_PERCENT
        return max(MIN_FAN_PERCENT, min(MAX_FAN_PERCENT, percent))

    def _connect_and_update(self):
        """Starts the background worker for one Redfish refresh cycle. Runs on
        the main thread; only starts a thread and returns immediately."""
        if self._stop_event.is_set():
            return

        with self._fetch_lock:
            if self._fetch_in_progress:
                if self.debug:
                    Domoticz.Log("Redfish fetch already in progress, skipping this heartbeat trigger.")
                return
            # Re-check under the lock: shutdown may have started while we
            # were waiting for it, and this must not be the call that starts
            # a worker after onStop() has already begun.
            if self._stop_event.is_set():
                return
            self._fetch_in_progress = True

        self._fetch_thread = threading.Thread(
            target=self._fetchWorker,
            name="HP-iLO-Fetch",
            daemon=True
        )
        self._fetch_thread.start()

    def _fetchWorker(self):
        """Runs on a background thread. Uses the persistent Redfish session to
        gather all sensor data (_gather_all_sections never touches Devices[...])
        and hands the result back through self._result_queue. Devices[...]
        updates happen in _apply_all_sections(), on the main thread, from
        onHeartbeat."""
        if self._stop_event.is_set():
            return
        if self.debug:
            Domoticz.Log("HP iLO: Redfish worker started.")
        try:
            bundle = self._with_redfish(self._gather_all_sections)
            self._result_queue.put(("ok", bundle))
        except Exception as err:
            self._result_queue.put(("error", str(err)))
        finally:
            with self._fetch_lock:
                self._fetch_in_progress = False
            if self.debug:
                Domoticz.Log("HP iLO: Redfish worker finished.")

    def _get_hpe_oem(self, data):
        oem = data.get("Oem", {})
        return oem.get("Hpe", oem.get("Hp", {}))

    def _get_thermal_setting_value(self, thermal, keys):
        hpe = self._get_hpe_oem(thermal)
        for source in (hpe, thermal):
            for key in keys:
                if source.get(key) is not None:
                    return source.get(key)
        return None

    def _power_level_to_value(self, level):
        try:
            level = int(level)
        except Exception:
            return None
        for item_level, label, aliases in POWER_REGULATOR_OPTIONS:
            if item_level == level:
                return aliases[0]
        return None

    def _power_regulator_to_level(self, value):
        normalized = str(value).replace(" ", "").replace("_", "").lower()
        for level, label, aliases in POWER_REGULATOR_OPTIONS:
            values = [label] + aliases
            for item in values:
                if normalized == str(item).replace(" ", "").replace("_", "").lower():
                    return level
        return None

    def _get_bios_attribute_value(self, bios, keys):
        attributes = bios.get("Attributes", {})
        for key in keys:
            if attributes.get(key) is not None:
                return attributes.get(key)
        for key in keys:
            if bios.get(key) is not None:
                return bios.get(key)
        return None

    def _thermal_level_to_value(self, level):
        try:
            level = int(level)
        except Exception:
            return None
        for item_level, label, aliases in THERMAL_CONFIG_OPTIONS:
            if item_level == level:
                return aliases[0]
        return None

    def _thermal_config_to_level(self, config):
        normalized = str(config).replace(" ", "").replace("_", "").lower()
        for level, label, aliases in THERMAL_CONFIG_OPTIONS:
            values = [label] + aliases
            for value in values:
                if normalized == str(value).replace(" ", "").replace("_", "").lower():
                    return level
        return None

    def _thermal_patch_targets(self, rf):
        root = rf.get("/redfish/v1/")
        chassis_path = root.get("Chassis", {}).get("@odata.id", "/redfish/v1/Chassis")
        chassis_uri = self._get_first_member_uri(rf, chassis_path)
        thermal_path = chassis_uri.rstrip("/") + "/Thermal"
        thermal = rf.get(thermal_path)
        settings_uri = thermal.get("@Redfish.Settings", {}).get("SettingsObject", {}).get("@odata.id")
        targets = []
        if settings_uri:
            targets.append(settings_uri)
        targets.append(thermal_path)
        if self.debug:
            Domoticz.Log("Thermal setting patch targets: {}".format(", ".join(targets)))
            Domoticz.Log("Thermal OEM HPE data: {}".format(self._json_for_log(self._get_hpe_oem(thermal))))
        return targets

    def _try_thermal_setting_payloads(self, rf, payloads):
        errors = []
        for path in self._thermal_patch_targets(rf):
            for payload in payloads:
                try:
                    rf.patch(path, payload)
                    Domoticz.Log("iLO accepted thermal setting update via {}".format(path))
                    return
                except Exception as err:
                    errors.append(str(err))
                    if self.debug:
                        Domoticz.Log("Thermal setting PATCH failed on {} with {}: {}".format(path, self._json_for_log(payload), err))
        raise Exception("thermal setting update not accepted by this iLO Redfish interface ({})".format("; ".join(errors)))

    def _set_min_fan_speed_percent(self, rf, percent):
        payloads = []
        for key in MIN_FAN_SETTING_KEYS:
            payloads.append({"Oem": {"Hpe": {key: percent}}})
            payloads.append({"Oem": {"Hp": {key: percent}}})
            payloads.append({key: percent})
        self._try_thermal_setting_payloads(rf, payloads)

    def _bios_settings_targets(self, rf):
        root = rf.get("/redfish/v1/")
        systems_path = root.get("Systems", {}).get("@odata.id", "/redfish/v1/Systems")
        system_uri = self._get_first_member_uri(rf, systems_path)
        bios_path = system_uri.rstrip("/") + "/Bios"
        bios = rf.get(bios_path)
        settings_uri = bios.get("@Redfish.Settings", {}).get("SettingsObject", {}).get("@odata.id")
        targets = []
        if settings_uri:
            targets.append(settings_uri)
        targets.append(bios_path + "/Settings")
        if self.debug:
            Domoticz.Log("BIOS setting patch targets: {}".format(", ".join(targets)))
            Domoticz.Log("BIOS attributes: {}".format(self._json_for_log(bios.get("Attributes", {}))))
        return targets

    def _try_bios_setting_payloads(self, rf, payloads):
        errors = []
        for path in self._bios_settings_targets(rf):
            for payload in payloads:
                try:
                    rf.patch(path, payload)
                    Domoticz.Log("iLO accepted BIOS setting update via {}".format(path))
                    return
                except Exception as err:
                    errors.append(str(err))
                    if self.debug:
                        Domoticz.Log("BIOS setting PATCH failed on {} with {}: {}".format(path, self._json_for_log(payload), err))
        raise Exception("BIOS setting update not accepted by this iLO Redfish interface ({})".format("; ".join(errors)))

    def _set_power_regulator(self, rf, value):
        payloads = []
        aliases = [value]
        for level, label, values in POWER_REGULATOR_OPTIONS:
            if value in values:
                aliases = values
                break
        for key in POWER_REGULATOR_KEYS:
            for item in aliases:
                payloads.append({"Attributes": {key: item}})
        self._try_bios_setting_payloads(rf, payloads)

    def _set_thermal_configuration(self, rf, config):
        payloads = []
        aliases = [config]
        for level, label, values in THERMAL_CONFIG_OPTIONS:
            if config in values:
                aliases = values
                break
        for key in THERMAL_CONFIG_KEYS:
            for value in aliases:
                payloads.append({"Oem": {"Hpe": {key: value}}})
                payloads.append({"Oem": {"Hp": {key: value}}})
                payloads.append({key: value})
        self._try_thermal_setting_payloads(rf, payloads)
    def _is_fan_control_not_writable(self, err):
        message = str(err)
        return (
            "PropertyNotWritableOrUnknown" in message or
            "HTTP 405" in message or
            "not accepted by this iLO Redfish interface" in message
        )

    def _get_first_member_uri(self, rf, collection_path):
        data    = rf.get(collection_path)
        members = data.get("Members", [])
        if not members:
            raise Exception("No members found in: {}".format(collection_path))
        uri = members[0].get("@odata.id")
        if not uri:
            raise Exception("No @odata.id in first member of: {}".format(collection_path))
        return uri


    def _get_drive_lifetime_percent(self, drive):
        for key in (
            "PredictedMediaLifeLeftPercent",
            "RemainingLifePercent",
            "PercentLifeRemaining",
            "MediaLifeLeftPercent",
            "SSDLifeLeft",
        ):
            if drive.get(key) is not None:
                return self._clamp_percent(drive.get(key))

        oem = drive.get("Oem", {})
        for vendor in ("Hpe", "Hp"):
            data = oem.get(vendor, {})
            for key in (
                "PredictedMediaLifeLeftPercent",
                "RemainingLifePercent",
                "PercentLifeRemaining",
                "MediaLifeLeftPercent",
                "SSDLifeLeft",
            ):
                if data.get(key) is not None:
                    return self._clamp_percent(data.get(key))

            # Some controllers report endurance used instead of lifetime left.
            for key in ("SSDEnduranceUtilizationPercentage", "DriveLifeUsedPercent", "PercentLifeUsed"):
                if data.get(key) is not None:
                    return self._clamp_percent(100 - float(data.get(key)))

        for key in ("SSDEnduranceUtilizationPercentage", "DriveLifeUsedPercent", "PercentLifeUsed"):
            if drive.get(key) is not None:
                return self._clamp_percent(100 - float(drive.get(key)))
        return None

    def _clamp_percent(self, value):
        try:
            percent = int(round(float(value)))
        except Exception:
            return None
        return max(0, min(100, percent))

    def _update_ssd_lifetime(self, lifetime):
        if UNIT_SSD_LIFETIME not in Devices or lifetime is None:
            return
        level = self._clamp_percent(lifetime)
        if level is None:
            return
        Devices[UNIT_SSD_LIFETIME].Update(nValue=0, sValue=str(level))
        if self.debug:
            Domoticz.Log("Updated SSD lifetime = {}%".format(level))

    def _json_for_log(self, value):
        try:
            text = json.dumps(value, sort_keys=True)
        except Exception:
            text = str(value)
        if len(text) > 900:
            return text[:900] + "..."
        return text


    def _fetch_and_push(self, rf):
        """Synchronous convenience wrapper (gather + apply on the same thread) -
        used by onCommand handlers, where a blocking refresh right after a
        successful PATCH is consistent with the rest of onCommand already
        being synchronous. The heartbeat path uses the async split below
        (_gather_all_sections on a worker thread, _apply_all_sections on the
        main thread) instead."""
        bundle = self._gather_all_sections(rf)
        self._apply_all_sections(bundle)

    def _gather_all_sections(self, rf):
        """Runs on a background thread (via _with_redfish/_fetchWorker) or,
        for onCommand, synchronously on the main thread. Does ONLY the
        blocking rf.get(...) calls for each section, preserving the original
        per-section error isolation, and returns a bundle of raw data. Never
        touches Devices[...] - that happens afterwards in
        _apply_all_sections()."""
        root = rf.get("/redfish/v1/")
        systems_path  = root.get("Systems",  {}).get("@odata.id", "/redfish/v1/Systems")
        chassis_path  = root.get("Chassis",  {}).get("@odata.id", "/redfish/v1/Chassis")
        managers_path = root.get("Managers", {}).get("@odata.id", "/redfish/v1/Managers")

        if self.debug:
            Domoticz.Log("Systems:  {}".format(systems_path))
            Domoticz.Log("Chassis:  {}".format(chassis_path))
            Domoticz.Log("Managers: {}".format(managers_path))

        bundle = {}
        system_uri = None

        # System
        try:
            system_uri  = self._get_first_member_uri(rf, systems_path)
            system      = rf.get(system_uri)
            model       = system.get("Model",        "Unknown")
            bios        = system.get("BiosVersion",  "")
            model_str   = "{} | BIOS: {}".format(model, bios) if bios else model
            bundle["system"] = {
                "hostname":     system.get("HostName", "Unknown"),
                "power_state":  system.get("PowerState", "Unknown"),
                "serial":       system.get("SerialNumber", "Unknown"),
                "model_str":    model_str,
                "health":       system.get("Status", {}).get("Health", "Unknown"),
            }
        except Exception as err:
            bundle["system_error"] = str(err)

        if self._stop_event.is_set():
            return bundle

        # Power Regulator
        try:
            if system_uri is None:
                system_uri = self._get_first_member_uri(rf, systems_path)
            bios = rf.get(system_uri.rstrip("/") + "/Bios")
            bundle["power_regulator_value"] = self._get_bios_attribute_value(bios, POWER_REGULATOR_KEYS)
        except Exception as err:
            bundle["power_regulator_error"] = str(err)

        if self._stop_event.is_set():
            return bundle

        # Thermal
        try:
            thermal = rf.get(self._get_first_member_uri(rf, chassis_path) + "/Thermal")

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

            bundle["thermal"] = {
                "min_fan_setting":        self._get_thermal_setting_value(thermal, MIN_FAN_SETTING_KEYS),
                "thermal_config_setting": self._get_thermal_setting_value(thermal, THERMAL_CONFIG_KEYS),
                "cpu_temp":               cpu_temp,
                "inlet_temp":             inlet_temp,
            }
        except Exception as err:
            bundle["thermal_error"] = str(err)

        if self._stop_event.is_set():
            return bundle

        # Firmware
        try:
            manager = rf.get(self._get_first_member_uri(rf, managers_path))
            bundle["firmware"] = manager.get("FirmwareVersion", "Unknown")
        except Exception as err:
            bundle["firmware_error"] = str(err)

        if self._stop_event.is_set():
            return bundle

        # Network
        try:
            manager_uri = self._get_first_member_uri(rf, managers_path)
            eth         = rf.get(self._get_first_member_uri(rf, manager_uri + "/EthernetInterfaces"))
            ipv4        = eth.get("IPv4Addresses", [])
            ip          = ipv4[0].get("Address", "N/A") if ipv4 else "N/A"
            mac         = eth.get("MACAddress", "N/A")
            bundle["network"] = "IP: {} | MAC: {}".format(ip, mac)
        except Exception as err:
            bundle["network_error"] = str(err)

        if self._stop_event.is_set():
            return bundle

        # Storage
        try:
            if system_uri is None:
                system_uri = self._get_first_member_uri(rf, systems_path)
            storage_path = system_uri.rstrip("/") + "/Storage"
            storage      = rf.get(storage_path)
            drives        = []
            ssd_lifetimes = []

            for member in storage.get("Members", []):
                uri = member.get("@odata.id")
                if not uri:
                    continue
                ctrl = rf.get(uri)
                for drive_ref in ctrl.get("Drives", []):
                    drive_uri = drive_ref.get("@odata.id")
                    if not drive_uri:
                        continue
                    try:
                        drive       = rf.get(drive_uri)
                        health      = drive.get("Status", {}).get("Health", "Unknown")
                        capacity    = drive.get("CapacityBytes", 0)
                        capacity_gb = round(capacity / 1e9, 1) if capacity else 0
                        media       = drive.get("MediaType", "Unknown")
                        lifetime    = self._get_drive_lifetime_percent(drive)
                        if lifetime is not None and str(media).lower() in ("ssd", "solidstate", "solid state drive"):
                            ssd_lifetimes.append(lifetime)
                        drives.append({
                            "gb":     capacity_gb,
                            "media":  media,
                            "health": health
                        })
                    except Exception:
                        pass

            fallback_controllers = None
            if not drives:
                # iLO 4 fallback: no individual drive data, check controller health only
                fallback_controllers = []
                for member in storage.get("Members", []):
                    uri = member.get("@odata.id")
                    if not uri:
                        continue
                    try:
                        ctrl   = rf.get(uri)
                        name   = ctrl.get("Name", "Controller")
                        status = ctrl.get("Status", {}).get("Health", "Unknown")
                        fallback_controllers.append({"name": name, "status": status})
                    except Exception:
                        pass

            bundle["storage"] = {
                "drives":               drives,
                "fallback_controllers": fallback_controllers,
                "ssd_lifetimes":        ssd_lifetimes,
            }
        except Exception as err:
            bundle["storage_error"] = str(err)

        return bundle

    def _apply_all_sections(self, bundle):
        """Devices[...]-touching part of one refresh cycle, given the raw data
        already fetched by _gather_all_sections(). Safe to call from the main
        thread only."""
        # System
        if "system" in bundle:
            s = bundle["system"]
            self._update_device(UNIT_SERVER_NAME, s["hostname"])
            self._update_device(UNIT_POWER_STATE, s["power_state"])
            self._update_device(UNIT_SERIAL, s["serial"])
            self._update_device(UNIT_MODEL, s["model_str"])
            health = s["health"]
            if str(health).upper() == "OK":
                Devices[UNIT_HEALTH].Update(nValue=1, sValue="All OK")
            else:
                Devices[UNIT_HEALTH].Update(nValue=self._health_nvalue(health), sValue=str(health))
        elif "system_error" in bundle:
            Domoticz.Error("System error: {}".format(bundle["system_error"]))

        # Power Regulator
        if "power_regulator_value" in bundle:
            self._update_power_regulator(bundle["power_regulator_value"])
        elif "power_regulator_error" in bundle and self.debug:
            Domoticz.Log("Power regulator read error: {}".format(bundle["power_regulator_error"]))

        # Thermal
        if "thermal" in bundle:
            t = bundle["thermal"]
            self._update_min_fan_speed(t["min_fan_setting"])
            self._update_thermal_config(t["thermal_config_setting"])
            if t["cpu_temp"] is not None:
                self._update_device(UNIT_CPU_TEMP, t["cpu_temp"])
            if t["inlet_temp"] is not None:
                self._update_device(UNIT_INLET_TEMP, t["inlet_temp"])
        elif "thermal_error" in bundle:
            Domoticz.Error("Thermal error: {}".format(bundle["thermal_error"]))

        # Firmware
        if "firmware" in bundle:
            self._update_device(UNIT_FIRMWARE, bundle["firmware"])
        elif "firmware_error" in bundle:
            Domoticz.Error("Firmware error: {}".format(bundle["firmware_error"]))

        # Network
        if "network" in bundle:
            self._update_device(UNIT_NETWORK, bundle["network"])
        elif "network_error" in bundle:
            Domoticz.Error("Network error: {}".format(bundle["network_error"]))

        # Storage
        if "storage" in bundle:
            st = bundle["storage"]
            drives = st["drives"]
            fallback_controllers = st["fallback_controllers"]
            ssd_lifetimes = st["ssd_lifetimes"]

            if not drives:
                bad, ok = [], []
                worst_nvalue = 1
                for ctrl in (fallback_controllers or []):
                    status = ctrl["status"]
                    if str(status).upper() != "OK":
                        bad.append("{}: {}".format(ctrl["name"], status))
                        worst_nvalue = max(worst_nvalue, self._health_nvalue(status))
                    else:
                        ok.append(ctrl["name"])
                if bad:
                    Devices[UNIT_STORAGE].Update(nValue=worst_nvalue, sValue=" | ".join(bad))
                elif ok:
                    Devices[UNIT_STORAGE].Update(nValue=1, sValue="OK: {}".format(", ".join(ok)))
                else:
                    Devices[UNIT_STORAGE].Update(nValue=0, sValue="No storage data")
            else:
                parts = []
                worst_nvalue = 1
                for i, d in enumerate(drives, 1):
                    parts.append("Storage {}: {} | {} | {} GB".format(
                        i, d["health"], d["media"], d["gb"]
                    ))
                    worst_nvalue = max(worst_nvalue, self._health_nvalue(d["health"]))
                sValue = "\n".join(parts)
                Devices[UNIT_STORAGE].Update(nValue=worst_nvalue, sValue=sValue)

            if ssd_lifetimes:
                self._update_ssd_lifetime(min(ssd_lifetimes))
        elif "storage_error" in bundle:
            err = bundle["storage_error"]
            if "404" in str(err):
                Devices[UNIT_STORAGE].Update(nValue=0, sValue="Not supported by this iLO version")
            else:
                Domoticz.Error("Storage error: {}".format(err))


# --- Domoticz Hooks ---

_plugin = BasePlugin()

def onStart():    _plugin.onStart()
def onStop():     _plugin.onStop()
def onHeartbeat(): _plugin.onHeartbeat()
def onCommand(Unit, Command, Level, Color): _plugin.onCommand(Unit, Command, Level, Color)
