import gi
import datetime
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
                if len(parts) == 2 and re.match(r'^\d{2}:\d{2}$', parts[0].strip()):
                    parsed_alarms.append({"time": parts[0].strip(), "enabled": parts[1].strip().lower() == 'true'})
        return parsed_alarms

    def get_active_alarms(self):
        return [a for a in self._parse_alarms_from_config() if a['enabled']]

    def get_data(self):
        try:
            tz = pytz.timezone(self.config.get("timezone", "UTC"))
            now = datetime.datetime.now(tz)
            
            # --- Alarm Logic ---
            is_alarm_ringing = False
            active_alarms = self.get_active_alarms()
            current_time_hm = now.strftime("%H:%M")

            for alarm in active_alarms:
                if alarm['time'] == current_time_hm:
                    if alarm['time'] not in self._ringing_alarms:
                        self._ringing_alarms.add(alarm['time'])
                        is_alarm_ringing = True
                else:
                    if alarm['time'] in self._ringing_alarms:
                        self._ringing_alarms.remove(alarm['time'])
            
            # --- Timer Logic ---
            timer_remaining_seconds = None
            if self._timer_is_running and self._timer_end_time:
                if now >= self._timer_end_time:
                    self._timer_is_running = False
                    self._timer_is_ringing = True
                else:
                    timer_remaining_seconds = (self._timer_end_time - now).total_seconds()

            return {
                "datetime": now, 
                "is_alarm_ringing": is_alarm_ringing,
                "is_timer_running": self._timer_is_running,
                "is_timer_ringing": self._timer_is_ringing,
                "timer_remaining_seconds": timer_remaining_seconds
            }
        except pytz.UnknownTimeZoneError:
            return {"datetime": datetime.datetime.now(pytz.utc), "error": "Unknown Timezone", "is_alarm_ringing": False, "is_timer_running": False, "is_timer_ringing": False, "timer_remaining_seconds": None}

    def get_display_string(self, data):
        dt = data.get("datetime")
        if not dt: return "N/A"
        
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
            
        return dt.strftime(time_format)

    def get_secondary_display_string(self, data):
        dt = data.get("datetime")
        if not dt: return ""
        date_format_str = self.config.get("date_format", "%Y-%m-%d")
        return dt.strftime(date_format_str)

    def get_timezone_display_string(self, data):
        dt = data.get("datetime")
        return dt.tzname() if dt else ""

    def get_numerical_value(self, data):
        return None # Not applicable for a clock

    def force_update(self):
        """Forces a re-evaluation of alarms."""
        self.get_data()

    def stop_ringing_alarms(self):
        self._ringing_alarms.clear()
        
    def start_timer(self, duration_seconds):
        if duration_seconds > 0:
            self._timer_end_time = datetime.datetime.now(pytz.timezone(self.config.get("timezone", "UTC"))) + datetime.timedelta(seconds=duration_seconds)
            self._timer_is_running = True
            self._timer_is_ringing = False

    def cancel_timer(self):
        self._timer_end_time = None
        self._timer_is_running = False
        self._timer_is_ringing = False

    def stop_ringing_timer(self):
        self._timer_is_ringing = False

    @staticmethod
    def get_config_model():
        # This model is now only used by the Displayer's config tab.
        # The data source itself has no configurable options besides the timezone.
        return {
            "Data Source & Update": [
                ConfigOption("update_interval_seconds", "scale", "Update Interval (sec):", "1.0", 0.1, 60, 0.1, 1),
            ],
            "Time & Date Formatting": [
                ConfigOption("hour_format", "dropdown", "Hour Format:", "24", options_dict={"24-Hour": "24", "12-Hour": "12"}),
                ConfigOption("show_seconds", "bool", "Show Seconds:", "True"),
                ConfigOption("date_format", "string", "Date Format:", "%Y-%m-%d", tooltip="Uses standard strftime format codes.\n%Y=Year, %m=Month, %d=Day, %A=Weekday, %B=Month Name")
            ]
        }

    def get_configure_callback(self):
        """Callback to add the 'Choose Timezone' button."""
        def add_timezone_chooser(dialog, content_box, widgets, available_sources, panel_config):
            sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL, margin_top=10, margin_bottom=5)
            content_box.append(sep)
            
            header_label = Gtk.Label(xalign=0)
            header_label.set_markup("<b>Timezone</b>")
            content_box.append(header_label)

            self._temp_tz = panel_config.get("timezone", "UTC")
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10, margin_bottom=4)
            content_box.append(row)
            
            row.append(Gtk.Label(label="Current Timezone:", xalign=0))
            
            widgets["current_tz_label"] = Gtk.Label(label=self._temp_tz, xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.MIDDLE)
            row.append(widgets["current_tz_label"])
            
            widgets["choose_tz_button"] = Gtk.Button(label="Choose…")
            widgets["choose_tz_button"].connect("clicked", self._show_tz_chooser, dialog, widgets)
            row.append(widgets["choose_tz_button"])
            
            # This function will be called by the dialog to get custom values
            dialog.custom_value_getter = lambda: {"timezone": self._temp_tz}

        return add_timezone_chooser

    def _show_tz_chooser(self, btn, parent_dlg, widgets):
        tz_label = widgets["current_tz_label"]
        dlg=CustomDialog(parent=parent_dlg, title="Choose Timezone", modal=True)
        dlg.set_default_size(400,500)
        vbox=Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
        dlg.get_content_area().append(vbox)
        
        search=Gtk.SearchEntry(placeholder_text="Search for a timezone...")
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
                self._temp_tz = selected_row.get_child().get_text()
                tz_label.set_text(self._temp_tz)
        dlg.destroy()
