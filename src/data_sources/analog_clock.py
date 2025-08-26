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
            tz = pytz.utc
            now = datetime.datetime.now(tz)
        
        is_ringing = False
        active_alarms = self.get_active_alarms()
        current_time_str = now.strftime("%H:%M")
        if current_time_str in active_alarms and now.second == 0:
            self._ringing_alarms.add(current_time_str)
        
        if self._ringing_alarms:
            is_ringing = True

        # Timer logic
        if self._timer_is_running:
            remaining = self._timer_end_time - time.monotonic()
            if remaining <= 0:
                self._timer_is_running = False
                self._timer_is_ringing = True
        
        return {
            "datetime": now, 
            "is_alarm_ringing": is_ringing,
            "is_timer_running": self._timer_is_running,
            "is_timer_ringing": self._timer_is_ringing,
            "timer_remaining_seconds": self._timer_end_time - time.monotonic() if self._timer_is_running else 0
        }

    def get_active_alarms(self):
        return {a['time'] for a in self._parse_alarms_from_config() if a['enabled']}

    def stop_ringing_alarms(self):
        self._ringing_alarms.clear()
        
    def start_timer(self, seconds):
        self._timer_end_time = time.monotonic() + seconds
        self._timer_is_running = True
        self._timer_is_ringing = False

    def cancel_timer(self):
        self._timer_is_running = False
        self._timer_is_ringing = False
        self._timer_end_time = None

    def stop_ringing_timer(self):
        self._timer_is_ringing = False

    def force_update(self):
        # This can be called by the displayer to force a re-read of the config
        pass

    def get_display_string(self, data):
        if not isinstance(data, dict) or "datetime" not in data: return "N/A"
        now = data["datetime"]
        hour_format = self.config.get("hour_format", "24")
        show_seconds = str(self.config.get("show_seconds", "True")).lower() == 'true'
        
        time_format = ""
        if hour_format == "12":
            time_format = "%I:%M"
            if show_seconds: time_format += ":%S"
            time_format += " %p"
        else:
            time_format = "%H:%M"
            if show_seconds: time_format += ":%S"
            
        return now.strftime(time_format)

    def get_secondary_display_string(self, data):
        if not isinstance(data, dict) or "datetime" not in data: return ""
        return data["datetime"].strftime(self.config.get("date_format", "%Y-%m-%d"))
    
    # --- FIX: Override get_primary_label_string for better combo display ---
    def get_primary_label_string(self, data):
        # In the combo panel, the "primary" label is the smaller one.
        # We want the date to be the smaller text.
        return self.get_secondary_display_string(data)

    def get_timezone_display_string(self, data):
        if not isinstance(data, dict) or "datetime" not in data: return ""
        return data["datetime"].tzname()

    @staticmethod
    def get_config_model():
        model = DataSource.get_config_model()
        model.pop("Alarm", None) # Alarms are handled by the clock displayer
        model["Time & Date"] = [
            ConfigOption("hour_format", "dropdown", "Hour Format:", "24", options_dict={"24 Hour": "24", "12 Hour": "12"}),
            ConfigOption("show_seconds", "bool", "Show Seconds Hand/Text:", "True"),
            ConfigOption("date_format", "string", "Date Format:", "%Y-%m-%d", tooltip="Python strftime format codes.\\n%Y-%m-%d -> 2023-10-27\\n%a, %b %d -> Fri, Oct 27")
        ]
        return model

    def get_configure_callback(self):
        """Callback to add the timezone chooser button."""
        # --- FIX: Add 'prefix=None' to make the argument optional ---
        def add_timezone_chooser(dialog, content_box, widgets, available_sources, panel_config, prefix=None):
            self._temp_tz = panel_config.get("timezone", "UTC")
            
            sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL, margin_top=10, margin_bottom=5)
            content_box.append(sep)
            
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            content_box.append(row)
            
            row.append(Gtk.Label(label="Timezone:", xalign=0))
            
            tz_label = Gtk.Label(label=self._temp_tz, xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.MIDDLE)
            row.append(tz_label)
            
            choose_button = Gtk.Button(label="Choose…")
            choose_button.connect("clicked", self._show_tz_chooser, dialog, tz_label, panel_config)
            row.append(choose_button)

        return add_timezone_chooser
        
    def _show_tz_chooser(self, btn, parent_dlg, tz_label_widget, panel_config):
        dlg=CustomDialog(parent=parent_dlg, title="Choose Timezone", modal=True)
        dlg.set_default_size(400, 500)
        
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
        dlg.get_content_area().append(vbox)
        
        search = Gtk.SearchEntry(placeholder_text="Search for a timezone...")
        vbox.append(search)
        
        scroll=Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        vbox.append(scroll)
        list_box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        scroll.set_child(list_box)
        
        all_tzs = sorted(pytz.all_timezones)
        
        def populate(term=None):
            for c in list(list_box): list_box.remove(c)
            for tz in [t for t in all_tzs if not term or term in t.lower()]:
                row=Gtk.ListBoxRow(); label=Gtk.Label(label=tz,xalign=0,margin_start=5,margin_end=5); row.set_child(label); list_box.append(row)
                if tz == self._temp_tz: list_box.select_row(row)
        
        search.connect("search-changed", lambda e: populate(e.get_text().lower()))
        populate()
        
        dlg.add_styled_button("_Cancel", Gtk.ResponseType.CANCEL)
        choose_btn = dlg.add_styled_button("_Choose", Gtk.ResponseType.OK, style_class="suggested-action", is_default=True)
        choose_btn.set_sensitive(list_box.get_selected_row() is not None)
        list_box.connect("row-selected", lambda l,r: choose_btn.set_sensitive(r is not None))
        
        if dlg.run() == Gtk.ResponseType.OK:
            selected_row = list_box.get_selected_row()
            if selected_row:
                new_tz = selected_row.get_child().get_text()
                self._temp_tz = new_tz
                panel_config["timezone"] = new_tz # Update the config dict directly
                tz_label_widget.set_text(new_tz)
        dlg.destroy()
