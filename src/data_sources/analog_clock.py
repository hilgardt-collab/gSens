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
        """Returns a list of all enabled alarms."""
        return [a for a in self._parse_alarms_from_config() if a['enabled']]

    def get_data(self):
        try:
            tz = pytz.timezone(self.config.get("timezone", "UTC"))
            now = datetime.datetime.now(tz)
        except pytz.UnknownTimeZoneError:
            tz = pytz.timezone("UTC")
            now = datetime.datetime.now(tz)
        
        current_time_hm = now.strftime("%H:%M")
        is_alarm_ringing = False
        
        # Check for new alarms to ring
        for alarm in self.get_active_alarms():
            if alarm['time'] == current_time_hm and alarm['time'] not in self._ringing_alarms:
                self._ringing_alarms.add(alarm['time'])
        
        if self._ringing_alarms:
            is_alarm_ringing = True

        # Check timer state
        if self._timer_is_running and self._timer_end_time is not None:
            remaining = self._timer_end_time - time.monotonic()
            if remaining <= 0:
                self._timer_is_running = False
                self._timer_is_ringing = True
                remaining = 0
        else:
            remaining = 0
            
        return {
            "datetime": now,
            "timezone": tz,
            "is_alarm_ringing": is_alarm_ringing,
            "is_timer_running": self._timer_is_running,
            "is_timer_ringing": self._timer_is_ringing,
            "timer_remaining_seconds": remaining
        }

    def get_primary_label_string(self, data):
        dt = data.get("datetime")
        return dt.strftime(self.config.get("date_format", "%Y-%m-%d")) if dt else ""

    def get_secondary_display_string(self, data):
        return str(data.get("timezone")) if data else ""

    def force_update(self):
        """Forces a re-evaluation of alarms, e.g., after config change."""
        self._ringing_alarms.clear()
        self.get_data()

    def stop_ringing_alarms(self):
        self._ringing_alarms.clear()
        
    @staticmethod
    def get_config_model():
        model = DataSource.get_config_model()
        model.pop("Alarm", None) # Remove generic alarm section
        model["Time & Date"] = [
            ConfigOption("timezone", "timezone_selector", "Timezone:", "UTC"),
            ConfigOption("date_format", "string", "Date Format:", "%Y-%m-%d", tooltip="Uses Python's strftime format codes."),
        ]
        # The displayer will add its own alarm/timer settings in its config dialog
        return model

    def get_configure_callback(self):
        # --- BUG FIX: Add 'prefix=None' to accept the optional argument from combo panels ---
        def setup_timezone_selector(dialog, content_box, widgets, available_sources, panel_config, prefix=None):
            tz_entry = widgets.get("timezone")
            tz_button = widgets.get("timezone_button")

            if not tz_entry or not tz_button:
                return

            def on_choose_timezone_clicked(_):
                tz_dialog = CustomDialog(parent=dialog, title="Select Timezone", modal=True)
                tz_dialog.set_default_size(300, 500)
                
                tz_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
                tz_dialog.get_content_area().append(tz_vbox)

                search_entry = Gtk.SearchEntry(margin_top=5, margin_bottom=5, margin_start=5, margin_end=5)
                tz_vbox.append(search_entry)

                scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
                tz_vbox.append(scroll)
                
                list_box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
                scroll.set_child(list_box)
                
                all_tzs = sorted(pytz.common_timezones)
                for tz_name in all_tzs:
                    row = Gtk.ListBoxRow()
                    row.set_child(Gtk.Label(label=tz_name, xalign=0, margin_start=5, margin_end=5))
                    row.tz_name = tz_name
                    list_box.append(row)
                    if tz_name == tz_entry.get_text():
                        list_box.select_row(row)
                
                def filter_func(row):
                    search_text = search_entry.get_text().lower()
                    return search_text in row.tz_name.lower()

                list_box.set_filter_func(filter_func)
                search_entry.connect("search-changed", lambda s: list_box.invalidate_filter())

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

