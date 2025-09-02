#data_sources/fan_speed.py
from data_source import DataSource
from config_dialog import ConfigOption
import psutil
import threading
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import GLib

# --- BUG FIX ---
# Import the global sensor cache directly to avoid a circular dependency with main.py.
from sensor_cache import SENSOR_CACHE

class FanSpeedDataSource(DataSource):
    """Data source for fetching fan RPM using psutil for efficiency."""
    def __init__(self, config):
        super().__init__(config)
        self._available_fans_cache = None

    @staticmethod
    def _discover_fans_statically():
        """Statically discovers available fans using psutil, creating robust keys."""
        if not hasattr(psutil, "sensors_fans"):
            return {"": {"display_name": "psutil fans not supported"}}
            
        fans = {}
        try:
            fan_data = psutil.sensors_fans()
            if not fan_data:
                return {"": {"display_name": "No fans found by psutil"}}
            
            for chip, entries in fan_data.items():
                for i, fan in enumerate(entries):
                    unique_key = f"{chip}::{i}"
                    label = fan.label if fan.label else f"Fan {i+1}"
                    display_name = f"{chip} / {label}"
                    fans[unique_key] = {"display_name": display_name}
        except Exception as e:
            print(f"FanSpeedDataSource: Error discovering fans with psutil: {e}")
            return {"": {"display_name": "Error reading fan data"}}
        return fans

    def get_data(self):
        """Fetches the current RPM for the selected fan using an index-based key."""
        if not hasattr(psutil, "sensors_fans"):
            return {"rpm": None}

        selected_key = self.config.get("selected_fan_key", "")
        if '::' not in selected_key:
            return {"rpm": None}
            
        try:
            chip, index_str = selected_key.split('::', 1)
            index = int(index_str)
            
            fan_data = psutil.sensors_fans()
            if chip in fan_data and 0 <= index < len(fan_data[chip]):
                return {"rpm": fan_data[chip][index].current}
        except (ValueError, IndexError, Exception) as e:
            print(f"FanSpeedDataSource: Could not read RPM for key '{selected_key}': {e}")

        return {"rpm": None}

    def get_display_string(self, data):
        if not isinstance(data, dict):
            if isinstance(data, (int, float)):
                return f"{data:.0f} RPM"
            return "N/A"

        if data.get('rpm') is None:
            return "N/A"
        return f"{data.get('rpm'):.0f} RPM"

    def get_numerical_value(self, data): 
        """Returns the raw RPM value from the data dictionary."""
        if data is None:
            return None
        return data.get("rpm")
    
    @staticmethod
    def get_config_model():
        # --- FIX: Read discovered sensors from the global cache instead of re-discovering. ---
        discovered_fans = SENSOR_CACHE.get('fan_speed', {"": {"display_name": "Scanning..."}})
        opts = {v['display_name']: k for k, v in sorted(discovered_fans.items(), key=lambda i:i[1]['display_name'])}
        
        model = DataSource.get_config_model()
        model["Fan Selection"] = [ConfigOption("selected_fan_key", "dropdown", "Monitored Fan:", "", options_dict=opts, tooltip="Which fan to monitor.\\nNote: After updating, you may need to re-select your fan here.")]
        model["Alarm"][1] = ConfigOption(f"data_alarm_high_value", "scale", "Alarm High RPM:", "3000.0", 0.0, 10000.0, 100.0, 0)
        model["Graph Range"] = [
            ConfigOption("graph_min_value", "spinner", "Graph Min RPM:", "0.0", 0.0, 5000.0, 10.0, 0),
            ConfigOption("graph_max_value", "spinner", "Graph Max RPM:", "3000.0", 100.0, 10000.0, 100.0, 0)
        ]
        return model
    
    @staticmethod
    def get_alarm_unit(): return "RPM"

    def get_configure_callback(self):
        
        def _repopulate_sensor_dropdown(widgets, panel_config, prefix):
            """Helper to fill the sensor dropdown once data is available."""
            key_prefix = f"{prefix}opt_" if prefix else ""
            try:
                sensor_combo = widgets.get(f"{key_prefix}selected_fan_key")
                spinner = widgets.get(f"{key_prefix}fan_spinner")
                if not sensor_combo: return

                if spinner: spinner.get_parent().set_visible(False)

                model = sensor_combo.get_model()
                model.clear()
                
                fans = SENSOR_CACHE.get('fan_speed', {})
                if not fans or all(k == "" for k in fans):
                    model.append(id="", text="No fans found")
                else:
                    sorted_fans = sorted(fans.items(), key=lambda i: i[1]['display_name'])
                    for key, data in sorted_fans:
                        model.append(id=key, text=data['display_name'])

                current_selection = panel_config.get(f"{key_prefix}selected_fan_key")
                if current_selection and sensor_combo.set_active_id(current_selection):
                    pass
                else:
                    sensor_combo.set_active(0)

            except KeyError as e:
                print(f"FanSpeedDataSource _repopulate_sensor_dropdown KeyError: {e}")

        def setup_auto_title_logic(dialog, content_box, widgets, available_sources, panel_config, prefix=None):
            is_combo_child = prefix is not None
            key_prefix = f"{prefix}opt_" if is_combo_child else ""
            
            try: 
                fan_combo = widgets[f"{key_prefix}selected_fan_key"]
                title_entry = widgets[f"title_text"] if not is_combo_child else widgets.get(f"{prefix}caption")
                if not title_entry: return
            except KeyError as e:
                print(f"FanSpeedDataSource configure_callback KeyError: {e}. Could not find a required widget.")
                return
                
            def on_fan_changed(combo):
                display_name = combo.get_active_text()
                if not title_entry.get_text() or title_entry.get_text() == "Fan Speed":
                    if display_name and "No fans" not in display_name and "not supported" not in display_name:
                        simple_name = display_name.split('/')[-1].strip()
                        title_entry.set_text(f"Fan: {simple_name}")
                    else:
                        title_entry.set_text("Fan Speed")
            
            fan_combo.connect("changed", on_fan_changed)
            GLib.idle_add(on_fan_changed, fan_combo)

            # --- NEW SENSOR POPULATION LOGIC ---
            try:
                row, spinner = fan_combo.get_parent(), Gtk.Spinner(spinning=True)
                widgets[f"{key_prefix}fan_spinner"] = spinner
                row.append(spinner)
                parent_window = dialog.get_ancestor(Gtk.Window)
                if parent_window and hasattr(parent_window, 'sensors_ready_event'):
                    ready_event = parent_window.sensors_ready_event
                    if ready_event.is_set():
                        _repopulate_sensor_dropdown(widgets, panel_config, prefix)
                    else:
                        def wait_and_repopulate():
                            ready_event.wait()
                            GLib.idle_add(_repopulate_sensor_dropdown, widgets, panel_config, prefix)
                        threading.Thread(target=wait_and_repopulate, daemon=True).start()
                else:
                    spinner.get_parent().set_visible(False)
            except Exception as e:
                print(f"FanSpeedDataSource configure_callback sensor logic error: {e}")

        return setup_auto_title_logic
