import gi
import datetime
import time
import pytz
import re
from data_source import DataSource
from config_dialog import ConfigOption
from ui_helpers import CustomDialog

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Pango, GLib

class AnalogClockDataSource(DataSource):
    """Data source for providing time data and managing alarms and timers."""
    def __init__(self, config):
        self.alarm_config_prefix = "clock_alarm_"
        super().__init__(config) 
        self.config.setdefault("update_interval_seconds", "1")
        self.config.setdefault("timezone", "UTC")
        self.config.setdefault("alarms", "")
        self.config.setdefault("date_format", "%Y-%m-%d")
        self.config.setdefault("hour_format", "24")
        self.config.setdefault("show_seconds", "True")
        
        self._ringing_alarms = set()
        self._temp_tz = self.config.get("timezone", "UTC")

        # Timer state
        self._timer_end_time = None
        self._timer_is_running = False
        self._timer_is_ringing = False

    def _parse_alarms_from_config(self):
        alarms_str = self.config.get("alarms", ""); parsed_alarms = []
        if alarms_str:
            for entry in alarms_str.split(';'):
                parts = entry.strip().split(',')
                if len(parts) == 2 and re.match(r'^\d{2}:\d{2}$', parts[0]):
                    parsed_alarms.append({"time": parts[0], "enabled": parts[1].lower() == 'true'})
        return parsed_alarms

    def get_data(self):
        try:
            tz = pytz.timezone(self.config.get("timezone", "UTC"))
            now = datetime.datetime.now(tz)
        except pytz.UnknownTimeZoneError:
            tz = pytz.timezone("UTC")
            now = datetime.datetime.now(tz)

        is_alarm_ringing = False
        current_time_hm = now.strftime("%H:%M")
        for alarm in self._parse_alarms_from_config():
            if alarm["enabled"] and alarm["time"] == current_time_hm:
                if alarm["time"] not in self._ringing_alarms:
                    self._ringing_alarms.add(alarm["time"])
                    is_alarm_ringing = True
            elif alarm["time"] in self._ringing_alarms:
                self._ringing_alarms.remove(alarm["time"])
        
        timer_remaining = None
        if self._timer_is_running and self._timer_end_time:
            remaining = self._timer_end_time - time.monotonic()
            if remaining <= 0:
                self._timer_is_running = False
                self._timer_is_ringing = True
                timer_remaining = 0
            else:
                timer_remaining = remaining

        return {
            "datetime": now,
            "tz_str": now.strftime('%Z'),
            "is_alarm_ringing": is_alarm_ringing,
            "is_timer_running": self._timer_is_running,
            "is_timer_ringing": self._timer_is_ringing,
            "timer_remaining_seconds": timer_remaining
        }

    def get_display_string(self, data):
        """Returns the main time string (e.g., HH:MM:SS)."""
        now = data.get("datetime")
        if not now: return "N/A"
        
        hour_format = self.config.get("hour_format", "24")
        show_seconds = str(self.config.get("show_seconds", "True")).lower() == 'true'
        
        time_format = "%H:%M"
        if hour_format == "12":
            time_format = "%I:%M %p"
        if show_seconds:
            time_format = time_format.replace("%M", "%M:%S")
            
        return now.strftime(time_format)

    def get_primary_label_string(self, data):
        """Returns the full date string."""
        now = data.get("datetime")
        if not now: return ""
        date_format = self.config.get("date_format", "%Y-%m-%d")
        return now.strftime(date_format)

    def get_secondary_display_string(self, data):
        """Returns the timezone abbreviation."""
        return data.get("tz_str", "N/A")

    def force_update(self):
        self._ringing_alarms.clear()

    @staticmethod
    def get_config_model():
        tz_options = {tz: tz for tz in sorted(pytz.common_timezones)}
        
        return {
            "Time & Date": [
                ConfigOption("timezone", "dropdown", "Timezone:", "UTC", options_dict=tz_options),
                ConfigOption("date_format", "string", "Date Format:", "%Y-%m-%d", tooltip="Python strftime format codes"),
                ConfigOption("hour_format", "dropdown", "Hour Format:", "24", options_dict={"24 Hour": "24", "12 Hour": "12"}),
                ConfigOption("show_seconds", "bool", "Show Seconds:", "True")
            ]
        }
        
    def start_timer(self, seconds):
        if seconds > 0:
            self._timer_end_time = time.monotonic() + seconds
            self._timer_is_running = True
            self._timer_is_ringing = False

    def cancel_timer(self):
        """Stops a running (but not yet ringing) timer."""
        self._timer_end_time = None
        self._timer_is_running = False
        
    def stop_ringing_timer(self):
        """Stops a ringing timer notification."""
        self._timer_is_ringing = False
