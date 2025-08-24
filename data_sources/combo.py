# data_sources/combo.py
import gi
import threading
from functools import partial
from data_source import DataSource
from config_dialog import ConfigOption, build_ui_from_model, get_config_from_widgets
from utils import populate_defaults_from_model

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib

class PrefixedConfig:
    """
    A wrapper around a config dictionary that automatically prefixes keys.
    This allows child data sources to read and write to a shared config
    without key collisions.
    """
    def __init__(self, main_config, prefix):
        self._main_config = main_config
        self._prefix = prefix

    def get(self, key, default=None):
        prefixed_key = f"{self._prefix}{key}"
        return self._main_config.get(prefixed_key, default)

    def setdefault(self, key, default=None):
        prefixed_key = f"{self._prefix}{key}"
        return self._main_config.setdefault(prefixed_key, default)

    def __getitem__(self, key):
        prefixed_key = f"{self._prefix}{key}"
        return self._main_config[prefixed_key]

    def __setitem__(self, key, value):
        prefixed_key = f"{self._prefix}{key}"
        self._main_config[prefixed_key] = value

class ComboDataSource(DataSource):
    """
    A special data source that acts as a container for other data sources.
    It creates and manages its own child source instances based on its configuration.
    """
    def __init__(self, config):
        super().__init__(config)
        self.child_sources = {}
        self.lock = threading.Lock()

    def setup_child_sources(self, available_sources):
        """Creates and configures all child data sources based on the panel config."""
        print(f"[DEBUG] ComboDataSource setup_child_sources for panel {self.config.get('id')}")
        with self.lock:
            self.child_sources.clear()
            
            source_map = {info['key']: info['class'] for info in available_sources.values()}
            
            num_arcs = int(self.config.get("combo_arc_count", 5))
            for i in range(1, num_arcs + 1):
                prefix = f"arc{i}_"
                source_key = self.config.get(f"arc{i}_source")
                if source_key and source_key != "none":
                    SourceClass = source_map.get(source_key)
                    if SourceClass:
                        prefixed_config = PrefixedConfig(self.config, f"{prefix}opt_")
                        self.child_sources[f"arc{i}_source"] = SourceClass(config=prefixed_config)
                        print(f"[DEBUG]   - Created source for Arc {i}: {source_key}")
            
            # Center Source
            center_key = self.config.get("center_source")
            print(f"[DEBUG]   - Center source key from config: '{center_key}'")
            if center_key and center_key != "none":
                SourceClass = source_map.get(center_key)
                if SourceClass:
                    prefixed_config = PrefixedConfig(self.config, "center_opt_")
                    self.child_sources["center_source"] = SourceClass(config=prefixed_config)
                    print(f"[DEBUG]   - Created source for Center: {center_key}")
        print(f"[DEBUG] ComboDataSource: Child source setup complete. Total sources: {len(self.child_sources)}")


    def get_data(self):
        """
        Fetches data from all child sources and returns it in a single bundle.
        """
        data_bundle = {}
        with self.lock:
            for key, source in self.child_sources.items():
                data = source.get_data()
                data_bundle[key] = {
                    "data": data,
                    "display_string": source.get_display_string(data),
                    "name": source.config.get("title_text", key)
                }
        return data_bundle

    def get_numerical_value(self, data):
        return None # Not applicable for the container itself

    @staticmethod
    def get_config_model():
        model = DataSource.get_config_model()
        model["Alarm"] = [] # Remove standard alarm section for this container
        model["Combo Panel Configuration"] = [
            ConfigOption("combo_arc_count", "spinner", "Number of Arcs:", 5, 1, 10, 1, 0)
        ]
        return model

    def get_configure_callback(self):
        """Builds the complex configuration UI for selecting and configuring child sources."""
        def build_combo_config(dialog, content_box, widgets, available_sources, panel_config):
            source_opts = {"None": "none", **{info['name']: info['key'] for info in available_sources.values()}}

            def rebuild_slot_config_ui(source_key, parent_box, prefix, all_widgets, slot_key_name):
                # --- BUG FIX: More precise cleanup ---
                # 1. Find all widget keys associated with this slot's SUB-OPTIONS.
                #    Crucially, this EXCLUDES the main dropdown selector itself.
                sub_option_prefix = f"{prefix}opt_"
                keys_to_remove = [key for key in all_widgets if key.startswith(sub_option_prefix)]
                
                # 2. Remove them from the master widget dictionary.
                if keys_to_remove:
                    print(f"[DEBUG] Clearing {len(keys_to_remove)} old sub-option widgets for prefix '{prefix}'")
                for key in keys_to_remove:
                    del all_widgets[key]

                # 3. Clear the UI container for sub-options.
                child = parent_box.get_first_child()
                while child:
                    parent_box.remove(child)
                    child = parent_box.get_first_child()
                
                # 4. Rebuild the UI for the new source's sub-options.
                if source_key and source_key != "none":
                    print(f"[DEBUG] Rebuilding config UI for source '{source_key}' with prefix '{prefix}'")
                    SourceClass = next((s['class'] for s in available_sources.values() if s['key'] == source_key), None)
                    if SourceClass:
                        prefixed_config = PrefixedConfig(panel_config, sub_option_prefix)
                        model = SourceClass.get_config_model()
                        populate_defaults_from_model(prefixed_config, model)
                        
                        prefixed_model = {}
                        for section, options in model.items():
                            prefixed_options = []
                            for opt in options:
                                new_opt = ConfigOption(f"{sub_option_prefix}{opt.key}", opt.type, opt.label, opt.default, opt.min_val, opt.max_val, opt.step, opt.digits, opt.options_dict, opt.tooltip, opt.file_filters)
                                prefixed_options.append(new_opt)
                            prefixed_model[section] = prefixed_options
                        
                        build_ui_from_model(parent_box, panel_config, prefixed_model, all_widgets)
                        dialog.dynamic_models.append(prefixed_model)

                        # --- BUG FIX: After building the UI, get and call the custom callback ---
                        # This is necessary for sources like CPU/GPU that have dynamic sub-options.
                        temp_instance = SourceClass(config=prefixed_config)
                        custom_callback = temp_instance.get_configure_callback()
                        if custom_callback:
                            print(f"[DEBUG] Found and calling custom configure callback for {SourceClass.__name__}")
                            custom_callback(dialog, parent_box, all_widgets, available_sources, panel_config)


            notebook = Gtk.Notebook()
            content_box.append(notebook)

            # --- Center Source Tab ---
            center_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
            center_tab_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
            center_scroll.set_child(center_tab_box)
            notebook.append_page(center_scroll, Gtk.Label(label="Center"))
            
            center_source_model = {"Center Data Source": [ConfigOption("center_source", "dropdown", "Source:", "none", options_dict=source_opts)]}
            build_ui_from_model(center_tab_box, panel_config, center_source_model, widgets)
            dialog.dynamic_models.append(center_source_model)
            center_sub_config_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_start=20)
            center_tab_box.append(center_sub_config_box)

            # --- Arc Sources Tabs ---
            def create_or_update_arc_tabs(spinner):
                arc_count = spinner.get_value_as_int()
                while notebook.get_n_pages() > arc_count + 1:
                    notebook.remove_page(-1)
                
                for i in range(1, arc_count + 1):
                    if i + 1 > notebook.get_n_pages():
                        tab_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
                        tab_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
                        tab_scroll.set_child(tab_box)
                        notebook.append_page(tab_scroll, Gtk.Label(label=f"Arc {i}"))
                        
                        prefix = f"arc{i}_"
                        slot_key = f"arc{i}_source"
                        
                        arc_source_model = {
                            f"Arc {i} Data Source": [
                                ConfigOption(slot_key, "dropdown", "Source:", "none", options_dict=source_opts),
                                ConfigOption(f"{prefix}caption", "string", "Caption:", "", tooltip="Overrides the default source name.")
                            ]
                        }
                        build_ui_from_model(tab_box, panel_config, arc_source_model, widgets)
                        dialog.dynamic_models.append(arc_source_model)

                        sub_config_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_start=20)
                        tab_box.append(sub_config_box)

                        arc_combo = widgets[slot_key]
                        
                        callback = partial(rebuild_slot_config_ui, parent_box=sub_config_box, prefix=prefix, all_widgets=widgets, slot_key_name=slot_key)
                        arc_combo.connect("changed", lambda c, cb=callback: cb(source_key=c.get_active_id()))
                        rebuild_slot_config_ui(panel_config.get(slot_key, "none"), sub_config_box, prefix, widgets, slot_key)

            center_combo = widgets["center_source"]
            center_combo.connect("changed", lambda c: rebuild_slot_config_ui(c.get_active_id(), center_sub_config_box, "center_", widgets, "center_source"))
            rebuild_slot_config_ui(panel_config.get("center_source", "none"), center_sub_config_box, "center_", widgets, "center_source")

            arc_count_spinner = widgets["combo_arc_count"]
            arc_count_spinner.connect("value-changed", create_or_update_arc_tabs)
            create_or_update_arc_tabs(arc_count_spinner)

        return build_combo_config
