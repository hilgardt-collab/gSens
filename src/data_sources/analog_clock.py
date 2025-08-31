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
                    parsed_alarms.append({'time': parts[0], 'enabled': parts[1].lower() == 'true'})
        return parsed_alarms

    def get_data(self):
        try:
            tz_str = self.config.get("timezone", "UTC")
            tz = pytz.timezone(tz_str)
            now = datetime.datetime.now(tz)
        except pytz.UnknownTimeZoneError:
            now = datetime.datetime.now(pytz.utc)

        # Alarm check
        is_alarm_ringing = False
        if now.second == 0:
            current_time_hm = now.strftime("%H:%M")
            active_alarms_now = {a['time'] for a in self._parse_alarms_from_config() if a['enabled'] and a['time'] == current_time_hm}
            
            newly_ringing = active_alarms_now - self._ringing_alarms
            if newly_ringing:
                self._ringing_alarms.update(newly_ringing)
                is_alarm_ringing = True
            
            if not active_alarms_now and self._ringing_alarms:
                 self._ringing_alarms.clear()
        
        if self._ringing_alarms: is_alarm_ringing = True

        # Timer check
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
            "timezone_str": tz_str,
            "is_alarm_ringing": is_alarm_ringing,
            "is_timer_running": self._timer_is_running,
            "is_timer_ringing": self._timer_is_ringing,
            "timer_remaining_seconds": timer_remaining,
            "active_alarms": [a for a in self._parse_alarms_from_config() if a['enabled']]
        }

    def get_primary_label_string(self, data):
        """Returns the formatted date string."""
        if not data or not data.get("datetime"): return ""
        dt_format = self.config.get("date_format", "%Y-%m-%d")
        return data["datetime"].strftime(dt_format)

    def get_secondary_display_string(self, data):
        """Returns the timezone string."""
        if not data: return ""
        return data.get("timezone_str", "UTC")

    def get_display_string(self, data):
        """Returns a formatted time string for use in other displayers."""
        if not data or not data.get("datetime"): return "N/A"
        
        now = data["datetime"]
        hour_format = self.config.get("hour_format", "24")
        show_seconds = str(self.config.get("show_seconds", "True")).lower() == 'true'
        
        time_format = ""
        if hour_format == "12":
            time_format = "%I:%M"
            if show_seconds: time_format += ":%S"
            time_format += " %p"
        else: # 24 hour
            time_format = "%H:%M"
            if show_seconds: time_format += ":%S"
            
        return now.strftime(time_format)

    def force_update(self):
        """Forces a re-check of alarms, typically after config changes."""
        self._ringing_alarms.clear()

    def stop_ringing_alarms(self):
        self._ringing_alarms.clear()

    @staticmethod
    def get_config_model():
        model = DataSource.get_config_model()
        model["Time & Date Formatting"] = [
            ConfigOption("timezone", "timezone_selector", "Timezone:", "UTC"),
            ConfigOption("date_format", "string", "Date Format:", "%Y-%m-%d", tooltip="Python strftime format codes"),
            ConfigOption("hour_format", "dropdown", "Hour Format:", "24", options_dict={"24 Hour": "24", "12 Hour": "12"}),
            ConfigOption("show_seconds", "bool", "Show Seconds:", "True")
        ]
        # Remove the generic alarm section as we have a custom implementation
        model.pop("Alarm", None)
        return model
        
    def get_configure_callback(self):
        """A custom callback to add a searchable timezone selector to the config dialog."""
        def setup_timezone_selector(dialog, content_box, widgets, available_sources, panel_config, prefix=None):
            try:
                tz_button = widgets["timezone_button"]
                tz_entry = widgets["timezone"]
            except KeyError:
                return

            def on_choose_timezone_clicked(button):
                tz_dialog = CustomDialog(parent=dialog, title="Select Timezone", modal=True)
                tz_dialog.set_default_size(400, 500)
                
                vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
                tz_dialog.get_content_area().append(vbox)

                search_entry = Gtk.SearchEntry(placeholder_text="Search timezones...")
                vbox.append(search_entry)
                
                scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
                vbox.append(scroll)
                
                list_box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
                scroll.set_child(list_box)
                
                all_rows = []
                for tz_name in sorted(pytz.common_timezones):
                    row = Gtk.ListBoxRow()
                    row.set_child(Gtk.Label(label=tz_name, xalign=0, margin_start=10, margin_end=10))
                    row.tz_name = tz_name
                    list_box.append(row)
                    all_rows.append(row)
                    if tz_name == tz_entry.get_text():
                        list_box.select_row(row)

                def filter_list(search_widget):
                    search_text = search_widget.get_text().lower()
                    for row in all_rows:
                        row.set_visible(search_text in row.tz_name.lower())
                
                search_entry.connect("search-changed", filter_list)

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

