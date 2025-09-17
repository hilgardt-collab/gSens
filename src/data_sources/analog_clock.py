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
from gi.repository import Gtk, Pango, GLib, Gio

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
        alarms_str = self.config.get("alarms", "")
        alarms = []
        if not alarms_str: return alarms
        try:
            for part in alarms_str.split(';'):
                if ',' in part:
                    time_part, enabled_part = part.split(',', 1)
                    if re.match(r'^\d{2}:\d{2}$', time_part):
                        alarms.append({
                            "time": time_part,
                            "enabled": enabled_part.lower() == 'true'
                        })
        except Exception as e:
            print(f"Error parsing alarms string '{alarms_str}': {e}")
        return alarms

    def get_data(self):
        try:
            tz = pytz.timezone(self.config.get("timezone", "UTC"))
            now = datetime.datetime.now(tz)
        except pytz.UnknownTimeZoneError:
            tz = pytz.timezone("UTC")
            now = datetime.datetime.now(tz)
            self.config["timezone"] = "UTC"

        active_alarms = self.get_active_alarms()
        
        current_time_hm = now.strftime("%H:%M")
        is_ringing = any(a['time'] == current_time_hm for a in active_alarms)
        if is_ringing: self._ringing_alarms.add(current_time_hm)

        timer_remaining = None
        if self._timer_is_running and self._timer_end_time:
            remaining = self._timer_end_time - time.monotonic()
            if remaining <= 0:
                self._timer_is_running = False
                self._timer_is_ringing = True
                timer_remaining = 0
            else:
                timer_remaining = remaining
        elif self._timer_is_ringing:
            timer_remaining = 0


        return {
            "datetime": now,
            "active_alarms": active_alarms,
            "is_alarm_ringing": bool(self._ringing_alarms),
            "timer_remaining_seconds": timer_remaining,
            "is_timer_running": self._timer_is_running,
            "is_timer_ringing": self._timer_is_ringing
        }

    def get_display_string(self, data):
        if not data or not data.get("datetime"): return "N/A"
        now = data["datetime"]
        
        h_format = self.config.get("hour_format", "24")
        show_secs = str(self.config.get("show_seconds", "True")).lower() == 'true'
        
        time_format = "%H:%M"
        if h_format == "12":
            time_format = "%I:%M %p"
        if show_secs:
            time_format = time_format.replace("%M", "%M:%S")
            
        return now.strftime(time_format)

    def get_primary_label_string(self, data):
        if not data or not data.get("datetime"): return ""
        return data["datetime"].strftime(self.config.get("date_format", "%Y-%m-%d"))

    def get_secondary_display_string(self, data):
        if not data or not data.get("datetime"): return ""
        return data["datetime"].strftime("%Z")
        
    def force_update(self):
        self._parse_alarms_from_config()

    def get_active_alarms(self):
        return [a for a in self._parse_alarms_from_config() if a['enabled']]

    def stop_ringing_alarms(self):
        self._ringing_alarms.clear()

    @staticmethod
    def get_config_model():
        model = DataSource.get_config_model()
        model.pop("Alarm", None)
        model["Time & Date"] = [
            ConfigOption("timezone", "timezone_selector", "Timezone:", "UTC"),
            ConfigOption("date_format", "string", "Date Format:", "%Y-%m-%d", tooltip="Python strftime format codes"),
            ConfigOption("hour_format", "dropdown", "Hour Format:", "24", options_dict={"24-hour": "24", "12-hour": "12"}),
            ConfigOption("show_seconds", "bool", "Show Seconds Hand:", "True"),
        ]
        return model
        
    def get_configure_callback(self):
        """Callback to provide a custom timezone selection dialog."""
        def setup_timezone_selector(dialog, content_box, widgets, available_sources, panel_config, prefix=None):
            key_prefix = f"{prefix}opt_" if prefix else ""
            
            tz_entry_key = f"{key_prefix}timezone"
            tz_button_key = f"{key_prefix}timezone_button"
            
            tz_entry = widgets.get(tz_entry_key)
            tz_button = widgets.get(tz_button_key)
            
            if not tz_entry or not tz_button:
                print(f"Warning: Could not find timezone widgets ('{tz_entry_key}', '{tz_button_key}')")
                return

            def on_choose_timezone_clicked(button):
                # BUG FIX: Make the timezone dialog modal to the main config dialog
                tz_dialog = CustomDialog(parent=dialog, title="Select Timezone", modal=True)
                tz_dialog.set_default_size(400, 600)
                
                scrolled = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
                tz_dialog.get_content_area().append(scrolled)
                
                list_box = Gtk.ListBox()
                list_box.set_selection_mode(Gtk.SelectionMode.SINGLE)
                
                all_timezones = sorted(pytz.all_timezones, key=str.lower)
                
                string_list = Gio.ListStore.new(Gtk.StringObject)
                for tz in all_timezones:
                    string_list.append(Gtk.StringObject.new(tz))
                
                filter_model = Gtk.FilterListModel.new(string_list, None)
                list_box.bind_model(filter_model, self._create_tz_row)
                
                search_entry = Gtk.SearchEntry(margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
                tz_dialog.get_content_area().prepend(search_entry)

                def on_filter_changed(entry):
                    query = entry.get_text().lower()
                    if not query:
                        filter_model.set_filter(None)
                    else:
                        custom_filter = Gtk.CustomFilter.new(lambda item, q=query: q in item.get_string().lower())
                        filter_model.set_filter(custom_filter)
                search_entry.connect("search-changed", on_filter_changed)
                scrolled.set_child(list_box)
                
                tz_dialog.add_styled_button("_Cancel", Gtk.ResponseType.CANCEL)
                accept_btn = tz_dialog.add_styled_button("_Accept", Gtk.ResponseType.ACCEPT, "suggested-action", True)
                accept_btn.set_sensitive(False)

                def on_selection_changed(lb, row):
                    accept_btn.set_sensitive(lb.get_selected_row() is not None)
                list_box.connect("row-selected", on_selection_changed)

                response = tz_dialog.run()
                if response == Gtk.ResponseType.ACCEPT:
                    selected_row = list_box.get_selected_row()
                    if selected_row:
                        tz_entry.set_text(selected_row.tz_name)
                tz_dialog.destroy()

            tz_button.connect("clicked", on_choose_timezone_clicked)

        return setup_timezone_selector

    def _create_tz_row(self, string_object):
        """Factory function to create a ListBoxRow for a timezone string."""
        tz_name = string_object.get_string()
        label = Gtk.Label(label=tz_name, xalign=0, margin_start=5, margin_end=5)
        row = Gtk.ListBoxRow()
        row.set_child(label)
        row.tz_name = tz_name
        return row

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
