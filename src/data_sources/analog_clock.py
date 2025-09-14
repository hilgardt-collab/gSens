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

    @property
    def is_clock_source(self):
        return True

    @property
    def needs_second_updates(self):
        return str(self.config.get("show_seconds", "False")).lower() == 'true'

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
        
        current_time_hm = now.strftime("%H:%M")
        is_alarm_ringing = False
        active_alarms = self._parse_alarms_from_config()
        for alarm in active_alarms:
            if alarm["enabled"] and alarm["time"] == current_time_hm:
                if alarm["time"] not in self._ringing_alarms:
                    self._ringing_alarms.add(alarm["time"])
                    is_alarm_ringing = True
            elif alarm["time"] in self._ringing_alarms:
                self._ringing_alarms.remove(alarm["time"])
        
        if self._timer_is_running and time.monotonic() >= self._timer_end_time:
            self._timer_is_running = False
            self._timer_is_ringing = True

        timer_remaining = 0
        if self._timer_end_time and (self._timer_is_running or self._timer_is_ringing):
             timer_remaining = max(0, self._timer_end_time - time.monotonic())

        return {
            "datetime": now, 
            "is_alarm_ringing": is_alarm_ringing or bool(self._ringing_alarms),
            "is_timer_running": self._timer_is_running,
            "is_timer_ringing": self._timer_is_ringing,
            "timer_remaining_seconds": timer_remaining,
            "any_alarm_set": any(a['enabled'] for a in active_alarms),
        }

    def get_display_string(self, data):
        """Returns a formatted time string for text-based displayers."""
        if not data or not data.get("datetime"):
            return "N/A"
        
        now = data["datetime"]
        hour_format = self.config.get("hour_format", "24")
        show_seconds = str(self.config.get("show_seconds", "True")).lower() == 'true'

        if hour_format == "12":
            time_format = "%I:%M"
            if show_seconds:
                time_format += ":%S"
            time_format += " %p"
        else:
            time_format = "%H:%M"
            if show_seconds:
                time_format += ":%S"
        
        return now.strftime(time_format)

    def get_primary_label_string(self, data):
        if not data or not data.get("datetime"):
            return "N/A"
        date_format = self.config.get("date_format", "%Y-%m-%d")
        return data["datetime"].strftime(date_format)

    def get_secondary_display_string(self, data):
        if not data or not data.get("datetime"):
            return ""
        return data["datetime"].tzname() or ""
        
    def get_numerical_value(self, data):
        if not data or not data.get("datetime"):
            return None
        return data["datetime"].timestamp()

    def stop_ringing_alarms(self):
        self._ringing_alarms.clear()
        
    def force_update(self):
        self.get_data()

    @staticmethod
    def get_config_model():
        model = DataSource.get_config_model()
        model["Time & Date"] = [
            ConfigOption("timezone", "timezone_selector", "Timezone:", "UTC"),
            ConfigOption("date_format", "string", "Date Format:", "%Y-%m-%d", tooltip="See strftime format codes."),
            ConfigOption("hour_format", "dropdown", "Hour Format:", "24", options_dict={"24 Hour": "24", "12 Hour": "12"}),
            ConfigOption("show_seconds", "bool", "Show Seconds (in text):", "True"),
        ]
        model.pop("Alarm")
        model.pop("Data Source & Update")
        return model
        
    def get_configure_callback(self):
        def setup_timezone_selector(dialog, content_box, widgets, available_sources, panel_config, prefix=None):
            opt_prefix = f"{prefix}opt_" if prefix else ""
            tz_key = f"{opt_prefix}timezone"
            tz_entry = widgets.get(tz_key)
            tz_button = widgets.get(f"{tz_key}_button")
            if not tz_entry or not tz_button:
                return

            def on_choose_timezone_clicked(btn):
                tz_dialog = CustomDialog(parent=dialog, title="Select Timezone", modal=True)
                tz_dialog.set_default_size(400, 600)
                
                search_entry = Gtk.SearchEntry(margin_bottom=5)
                list_box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE, activate_on_single_click=True)
                scrolled = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
                scrolled.set_child(list_box)
                
                vbox = tz_dialog.get_content_area()
                vbox.append(search_entry)
                vbox.append(scrolled)
                
                model = Gtk.ListStore(str)
                for tz in sorted(pytz.common_timezones): model.append([tz])
                
                filter_model = model.filter_new()
                
                def filter_func(model, iter, data):
                    search_text = data.get_text()
                    if not search_text: return True
                    return search_text.lower() in model[iter][0].lower()
                
                filter_model.set_visible_func(filter_func, search_entry)
                
                def on_search_changed(entry):
                    filter_model.refilter()
                search_entry.connect("search-changed", on_search_changed)
                
                for row_data in filter_model:
                    row = Gtk.ListBoxRow()
                    label = Gtk.Label(label=row_data[0], xalign=0, margin_start=5, margin_end=5)
                    row.set_child(label)
                    row.tz_name = row_data[0]
                    list_box.append(row)
                    if row.tz_name == tz_entry.get_text():
                        list_box.select_row(row)
                
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

