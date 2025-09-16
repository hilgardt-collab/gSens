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
                    alarms.append({'time': time_part, 'enabled': enabled_part.lower() == 'true'})
        except Exception as e:
            print(f"Error parsing alarms string '{alarms_str}': {e}")
        return alarms

    def get_active_alarms(self):
        return [a for a in self._parse_alarms_from_config() if a.get('enabled')]

    def force_update(self):
        self.get_data()

    def get_data(self):
        try:
            tz = pytz.timezone(self.config.get("timezone", "UTC"))
            now = datetime.datetime.now(tz)
        except pytz.UnknownTimeZoneError:
            tz = pytz.timezone("UTC")
            now = datetime.datetime.now(tz)

        current_time_hm = now.strftime("%H:%M")
        active_alarms = self.get_active_alarms()
        
        is_ringing = False
        for alarm in active_alarms:
            if alarm['time'] == current_time_hm:
                is_ringing = True
                self._ringing_alarms.add(alarm['time'])
        
        if not is_ringing and current_time_hm in self._ringing_alarms:
             self._ringing_alarms.remove(current_time_hm)

        # Timer logic
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
            "is_alarm_ringing": bool(self._ringing_alarms),
            "is_timer_running": self._timer_is_running,
            "is_timer_ringing": self._timer_is_ringing,
            "timer_remaining_seconds": timer_remaining
        }
    
    def stop_ringing_alarms(self):
        self._ringing_alarms.clear()

    def get_display_string(self, data):
        """Returns the formatted time string for text displays."""
        if data and data.get("datetime"):
            now = data["datetime"]
            hour_format = self.config.get("hour_format", "24")
            show_seconds = str(self.config.get("show_seconds", "True")).lower() == 'true'
            
            if hour_format == "12":
                format_str = "%I:%M:%S %p" if show_seconds else "%I:%M %p"
            else:
                format_str = "%H:%M:%S" if show_seconds else "%H:%M"
            
            return now.strftime(format_str)
        return "..."

    def get_primary_label_string(self, data):
        if data and data.get("datetime"):
            return data["datetime"].strftime(self.config.get("date_format", "%Y-%m-%d"))
        return "N/A"

    def get_secondary_display_string(self, data):
        if data and data.get("datetime"):
            return data["datetime"].strftime("%Z %z")
        return ""

    @staticmethod
    def get_config_model():
        model = DataSource.get_config_model()
        model["Clock Settings"] = [
            ConfigOption("timezone", "timezone_selector", "Timezone:", "UTC"),
            ConfigOption("date_format", "string", "Date Format:", "%Y-%m-%d", tooltip="Python strftime format codes."),
            ConfigOption("hour_format", "dropdown", "Hour Format:", "24", options_dict={"24-hour": "24", "12-hour": "12"}),
            ConfigOption("show_seconds", "bool", "Show Seconds Hand:", "True"),
        ]
        model.pop("Alarm", None)
        model["Data Source & Update"] = []
        return model

    def get_configure_callback(self):
        def setup_timezone_selector(dialog, content_box, widgets, available_sources, panel_config, prefix=None):
            tz_entry = widgets.get("timezone")
            tz_button = widgets.get("timezone_button")
            if not tz_entry or not tz_button: return

            def on_choose_timezone_clicked(btn):
                tz_dialog = CustomDialog(parent=dialog, title="Select Timezone", modal=True)
                tz_dialog.set_default_size(400, 600)
                
                vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
                tz_dialog.get_content_area().append(vbox)
                
                search_entry = Gtk.SearchEntry(placeholder_text="Search timezones...")
                vbox.append(search_entry)
                
                scrolled_window = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
                vbox.append(scrolled_window)
                
                store = Gio.ListStore.new(Gtk.StringObject)
                for tz_name in sorted(pytz.all_timezones):
                    store.append(Gtk.StringObject.new(tz_name))
                
                def filter_func(item):
                    search_text = search_entry.get_text().lower()
                    if not search_text:
                        return True
                    tz_name = item.get_string()
                    return search_text in tz_name.lower().replace("_", " ")

                search_filter = Gtk.CustomFilter.new(filter_func)
                filter_model = Gtk.FilterListModel.new(store, search_filter)
                
                list_box = Gtk.ListBox()
                list_box.bind_model(filter_model, self._create_tz_row)
                scrolled_window.set_child(list_box)

                def on_search_changed(entry):
                    search_filter.changed(Gtk.FilterChange.DIFFERENT)
                
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
                        # BUG FIX: Retrieve the timezone name from the row's custom attribute
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
        # BUG FIX: Attach the raw timezone name directly to the row widget
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

