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
            tz_str = self.config.get("timezone", "UTC")
            tz = pytz.timezone(tz_str)
            now = datetime.datetime.now(tz)
        except pytz.UnknownTimeZoneError:
            tz_str = "UTC"
            tz = pytz.timezone(tz_str)
            now = datetime.datetime.now(tz)

        is_alarm_ringing = False
        current_time_hm = now.strftime("%H:%M")
        for alarm in self.get_active_alarms():
            if alarm['time'] == current_time_hm:
                if alarm['time'] not in self._ringing_alarms:
                    self._ringing_alarms.add(alarm['time'])
                is_alarm_ringing = True

        is_timer_running = False
        is_timer_ringing = False
        timer_remaining_seconds = None
        if self._timer_end_time is not None:
            remaining = self._timer_end_time - time.monotonic()
            if remaining > 0:
                is_timer_running = True
                timer_remaining_seconds = remaining
            else:
                is_timer_ringing = True
                timer_remaining_seconds = 0
                if not self._timer_is_ringing: # First tick of ringing
                    self._timer_is_ringing = True
        
        return {
            "datetime": now, 
            "tz_str": now.strftime('%Z'),
            "is_alarm_ringing": is_alarm_ringing,
            "is_timer_running": is_timer_running,
            "is_timer_ringing": is_timer_ringing,
            "timer_remaining_seconds": timer_remaining_seconds
        }

    def stop_ringing_alarms(self):
        self._ringing_alarms.clear()

    def get_display_string(self, data):
        now = data.get("datetime")
        if not now: return "N/A"
        
        h_format = "%H" if self.config.get("hour_format", "24") == "24" else "%I"
        s_format = ":%S" if str(self.config.get("show_seconds", "True")).lower() == 'true' else ""
        ampm_format = "" if self.config.get("hour_format", "24") == "24" else " %p"
        
        return now.strftime(f"{h_format}:%M{s_format}{ampm_format}")

    def get_primary_label_string(self, data):
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
        return {
            "Time & Date": [
                ConfigOption("timezone", "timezone_selector", "Timezone:", "UTC"),
                ConfigOption("date_format", "string", "Date Format:", "%Y-%m-%d", tooltip="Python strftime format codes"),
                ConfigOption("hour_format", "dropdown", "Hour Format:", "24", options_dict={"24 Hour": "24", "12 Hour": "12"}),
                ConfigOption("show_seconds", "bool", "Show Seconds:", "True")
            ]
        }
        
    def get_configure_callback(self):
        """Callback to handle the custom timezone selector dialog."""
        def setup_timezone_selector(dialog, content_box, widgets, available_sources, panel_config, prefix=None):
            tz_button = widgets.get("timezone_button")
            tz_entry = widgets.get("timezone")
            if not tz_button or not tz_entry:
                return

            def on_choose_timezone_clicked(button):
                tz_dialog = CustomDialog(parent=dialog, title="Select Timezone", modal=True)
                tz_dialog.set_default_size(350, 500)
                
                tz_content = tz_dialog.get_content_area()
                tz_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
                tz_content.append(tz_vbox)
                
                search_entry = Gtk.SearchEntry(placeholder_text="Search timezones...")
                tz_vbox.append(search_entry)
                
                scrolled_window = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
                list_box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
                scrolled_window.set_child(list_box)
                tz_vbox.append(scrolled_window)
                
                all_timezones = sorted(pytz.common_timezones)
                for tz_name in all_timezones:
                    row = Gtk.ListBoxRow()
                    row.set_child(Gtk.Label(label=tz_name, xalign=0, margin_start=5, margin_end=5))
                    row.tz_name = tz_name
                    list_box.append(row)

                def on_search_changed(entry):
                    search_text = entry.get_text().lower()
                    for row in list_box:
                        row.set_visible(search_text in row.tz_name.lower())
                search_entry.connect("search-changed", on_search_changed)

                def on_row_activated(lb, row):
                    if row:
                        tz_dialog.respond(Gtk.ResponseType.ACCEPT)
                list_box.connect("row-activated", on_row_activated)

                tz_dialog.add_styled_button("_Cancel", Gtk.ResponseType.CANCEL)
                select_button = tz_dialog.add_styled_button("_Select", Gtk.ResponseType.ACCEPT, "suggested-action", is_default=True)
                select_button.set_sensitive(False)

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
