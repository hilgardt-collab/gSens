# /data_sources/analog_clock.py
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

    def get_active_alarms(self):
        return [a for a in self._parse_alarms_from_config() if a['enabled']]

    def get_data(self):
        try:
            tz = pytz.timezone(self.config.get("timezone", "UTC"))
            now = datetime.datetime.now(tz)
        except pytz.UnknownTimeZoneError:
            tz = pytz.utc
            now = datetime.datetime.now(tz)
        
        current_time_hm = now.strftime("%H:%M")
        active_alarms = self.get_active_alarms()
        is_alarm_ringing = False
        
        for alarm in active_alarms:
            if alarm['time'] == current_time_hm:
                self._ringing_alarms.add(alarm['time'])

        if self._ringing_alarms:
            is_alarm_ringing = True

        timer_remaining_seconds = None
        if self._timer_is_running and self._timer_end_time:
            remaining = self._timer_end_time - time.monotonic()
            if remaining <= 0:
                self._timer_is_running = False
                self._timer_is_ringing = True
                timer_remaining_seconds = 0
            else:
                timer_remaining_seconds = remaining
        
        return {
            "datetime": now,
            "is_alarm_ringing": is_alarm_ringing,
            "is_timer_running": self._timer_is_running,
            "is_timer_ringing": self._timer_is_ringing,
            "timer_remaining_seconds": timer_remaining_seconds
        }

    def stop_ringing_alarms(self):
        self._ringing_alarms.clear()
        
    def force_update(self):
        self.get_data()

    def get_display_string(self, data):
        """
        Returns the formatted time string, preventing the "..." fallback.
        """
        if not isinstance(data, dict) or not data.get("datetime"):
            return "N/A"
        
        dt = data["datetime"]
        hour_format = self.config.get("hour_format", "24")
        show_seconds = str(self.config.get("show_seconds", "True")).lower() == 'true'
        
        time_format = ""
        if hour_format == "12":
            time_format = "%I:%M"
            if show_seconds:
                time_format += ":%S"
            time_format += " %p" # AM/PM
        else: # 24 hour
            time_format = "%H:%M"
            if show_seconds:
                time_format += ":%S"
                
        return dt.strftime(time_format)

    def get_primary_label_string(self, data):
        if not isinstance(data, dict) or not data.get("datetime"): return ""
        dt = data["datetime"]
        fmt = self.config.get("date_format", "%Y-%m-%d")
        return dt.strftime(fmt)

    def get_secondary_display_string(self, data):
        return self.config.get("timezone", "UTC")

    @staticmethod
    def get_config_model():
        model = DataSource.get_config_model()
        model.pop("Alarm", None) # Remove the generic alarm
        model["Time & Date"] = [
            ConfigOption("timezone", "timezone_selector", "Timezone:", "UTC"),
            ConfigOption("date_format", "string", "Date Format:", "%Y-%m-%d", 
                         tooltip="Python strftime format codes.\\n%Y-%m-%d -> 2023-10-27\\n%a, %b %d -> Fri, Oct 27"),
            ConfigOption("hour_format", "dropdown", "Hour Format:", "24",
                         options_dict={"24 Hour": "24", "12 Hour": "12"}),
            ConfigOption("show_seconds", "bool", "Show Seconds:", "True"),
        ]
        return model
        
    def get_configure_callback(self):
        def setup_timezone_selector(dialog, content_box, widgets, available_sources, panel_config, prefix=None):
            key_prefix = f"{prefix}opt_" if prefix else ""
            tz_entry_key = f"{key_prefix}timezone"
            tz_button_key = f"{key_prefix}timezone_button"
            tz_entry = widgets.get(tz_entry_key)
            tz_button = widgets.get(tz_button_key)

            if not tz_entry or not tz_button:
                print(f"Timezone selector widgets not found for prefix '{prefix}'")
                return

            def on_choose_timezone_clicked(_btn):
                tz_dialog = CustomDialog(parent=dialog, title="Select Timezone", modal=True)
                tz_dialog.set_default_size(400, 600)
                
                vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, 
                               margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
                
                search_entry = Gtk.SearchEntry(placeholder_text="Search timezones...")
                vbox.append(search_entry)

                scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
                vbox.append(scroll)
                tz_dialog.get_content_area().append(vbox)
                
                list_box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
                scroll.set_child(list_box)
                
                all_timezones = sorted(pytz.common_timezones)
                for tz_name in all_timezones:
                    row = Gtk.ListBoxRow()
                    row.set_child(Gtk.Label(label=tz_name, xalign=0, margin_start=10, margin_end=10))
                    row.tz_name = tz_name
                    list_box.append(row)
                    if tz_name == tz_entry.get_text():
                        list_box.select_row(row)
                
                def on_search_changed(entry):
                    search_text = entry.get_text().lower()
                    def filter_func(row):
                        return search_text in row.tz_name.lower()
                    list_box.set_filter_func(filter_func if search_text else None)
                
                search_entry.connect("search-changed", on_search_changed)
                
                def on_row_activated(lb, row):
                    if row: tz_dialog.respond(Gtk.ResponseType.ACCEPT)
                list_box.connect("row-activated", on_row_activated)

                tz_dialog.add_styled_button("_Cancel", Gtk.ResponseType.CANCEL)
                select_button = tz_dialog.add_styled_button("_Select", Gtk.ResponseType.ACCEPT, "suggested-action", is_default=True)
                select_button.set_sensitive(list_box.get_selected_row() is not None)

                def on_selection_changed(lb, row):
                    select_button.set_sensitive(row is not None)
                list_box.connect("row-selected", on_selection_changed)

                response = tz_dialog.run()
                if response == Gtk.ResponseType.ACCEPT:
                    selected_row = list_box.get_selected_row()
                    if selected_row:
                        tz_entry.set_text(selected_row.tz_name)

            tz_button.connect("clicked", on_choose_timezone_clicked)

        return setup_timezone_selector

    def start_timer(self, seconds):
        if seconds > 0:
            self._timer_end_time = time.monotonic() + seconds
            self._timer_is_running = True
            self._timer_is_ringing = False

    def cancel_timer(self):
        self._timer_end_time = None
        self._timer_is_running = False
        self._timer_is_ringing = False
        
    def stop_ringing_timer(self):
        self._timer_end_time = None
        self._timer_is_running = False
        self._timer_is_ringing = False

