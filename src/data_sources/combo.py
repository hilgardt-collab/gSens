# /data_sources/combo.py
import gi
import threading
from functools import partial
from data_source import DataSource
from config_dialog import ConfigOption, build_ui_from_model, get_config_from_widgets
from utils import populate_defaults_from_model

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib

class ComboDataSource(DataSource):
    """
    A unified container data source for panels that display multiple child sources,
    such as the Arc Combo or the Level Bar Combo. It adapts its configuration
    and child source management based on a 'combo_mode' setting.
    """
    def __init__(self, config):
        super().__init__(config)
        self.child_sources = {}
        self.lock = threading.Lock()

    def setup_child_sources(self, available_sources):
        """
        Initializes child sources by creating dedicated, unprefixed config dictionaries
        for each one from the main panel config.
        """
        with self.lock:
            self.child_sources.clear()
            source_map = {info['key']: info['class'] for info in available_sources.values()}
            
            mode = self.config.get('combo_mode', 'arc')

            def create_child(slot_prefix):
                opt_prefix = f"{slot_prefix}opt_"
                source_key = self.config.get(f"{slot_prefix}source")
                if source_key and source_key != "none":
                    SourceClass = source_map.get(source_key)
                    if SourceClass:
                        child_config = {}
                        child_config['caption_override'] = self.config.get(f"{slot_prefix}caption", "")
                        for key, value in self.config.items():
                            if key.startswith(opt_prefix):
                                unprefixed_key = key[len(opt_prefix):]
                                child_config[unprefixed_key] = value
                        
                        self.child_sources[f"{slot_prefix}source"] = SourceClass(config=child_config)

            if mode == 'level_bar':
                num_bars = int(self.config.get("number_of_bars", 3))
                for i in range(1, num_bars + 1):
                    create_child(f"bar{i}_")
            elif mode == 'lcars':
                create_child("primary_")
                num_secondary = int(self.config.get("number_of_secondary_sources", 4))
                for i in range(1, num_secondary + 1):
                    create_child(f"secondary{i}_")
            else: # 'arc' mode
                create_child("center_")
                num_arcs = int(self.config.get("combo_arc_count", 5))
                for i in range(1, num_arcs + 1):
                    create_child(f"arc{i}_")

    def get_data(self):
        """
        Fetches data from all child sources and bundles it into a rich dictionary (view model)
        that includes all necessary information for rendering.
        """
        data_bundle = {}
        with self.lock:
            if not self.child_sources:
                return {}
            
            for key, source in self.child_sources.items():
                raw_data = source.get_data()
                
                min_val = float(source.config.get("graph_min_value", 0.0))
                max_val = float(source.config.get("graph_max_value", 100.0))
                
                override = source.config.get('caption_override', '')
                
                data_bundle[key] = {
                    "raw_data": raw_data,
                    "numerical_value": source.get_numerical_value(raw_data),
                    "display_string": source.get_display_string(raw_data),
                    "primary_label": override or source.get_primary_label_string(raw_data),
                    "min_value": min_val,
                    "max_value": max_val,
                }
        return data_bundle

    @staticmethod
    def get_config_model():
        model = DataSource.get_config_model()
        model.pop("Alarm", None) 
        model.pop("Data Source & Update", None)
        return model


    def get_configure_callback(self):
        """
        Returns a function that builds the appropriate complex configuration UI 
        based on the panel's 'combo_mode'.
        """

        def _rebuild_slot_config_ui(source_key, parent_box, prefix, dialog, widgets, available_sources, panel_config):
            # Refresh the panel_config with live data from widgets
            all_models = [ *dialog.dynamic_models ]
            if hasattr(dialog, 'ui_models'): all_models.extend(dialog.ui_models.values())
            latest_config_values = get_config_from_widgets(widgets, all_models)
            panel_config.update(latest_config_values)
            
            sub_opt_prefix = f"{prefix}opt_"
            
            keys_to_remove = [k for k in widgets if k.startswith(sub_opt_prefix)]
            for k in keys_to_remove: widgets.pop(k, None)
            dialog.dynamic_models = [m for m in dialog.dynamic_models if not any(opt.key.startswith(sub_opt_prefix) for section in m.values() for opt in section)]
            
            child = parent_box.get_first_child()
            while child: parent_box.remove(child); child = parent_box.get_first_child()

            if source_key and source_key != "none":
                SourceClass = next((s['class'] for s in available_sources.values() if s['key'] == source_key), None)
                if SourceClass:
                    model = SourceClass.get_config_model()
                    valid_keys = set()
                    for section in model.values():
                        for option in section:
                            valid_keys.add(option.key)
                    
                    child_config = {}
                    for key in valid_keys:
                        prefixed_key = f"{sub_opt_prefix}{key}"
                        if prefixed_key in panel_config:
                            child_config[key] = panel_config[prefixed_key]
                    
                    populate_defaults_from_model(child_config, model)
                    
                    unprefixed_widgets = {}
                    build_ui_from_model(parent_box, child_config, model, unprefixed_widgets)
                    
                    for key, widget in unprefixed_widgets.items():
                        widgets[f"{sub_opt_prefix}{key}"] = widget

                    prefixed_model = {}
                    for section, options in model.items():
                        prefixed_options = [ConfigOption(f"{sub_opt_prefix}{opt.key}", opt.type, opt.label, opt.default, opt.min_val, opt.max_val, opt.step, opt.digits, opt.options_dict, opt.tooltip, opt.file_filters) for opt in options]
                        prefixed_model[section] = prefixed_options
                    dialog.dynamic_models.append(prefixed_model)
                    
                    temp_instance = SourceClass(config=child_config)
                    custom_cb = temp_instance.get_configure_callback()
                    if custom_cb:
                        custom_cb(dialog, parent_box, unprefixed_widgets, available_sources, child_config, prefix)

        def _build_arc_config_ui(dialog, content_box, widgets, available_sources, panel_config, source_opts):
            arc_count_model = {"": [ConfigOption("combo_arc_count", "spinner", "Number of Arcs:", 5, 0, 16, 1, 0)]}
            build_ui_from_model(content_box, panel_config, arc_count_model, widgets)
            dialog.dynamic_models.append(arc_count_model)
            
            center_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
            center_scroll.set_min_content_height(300)
            
            center_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
            center_scroll.set_child(center_box)
            content_box.append(Gtk.Label(label="<b>Center Data Source</b>", use_markup=True, xalign=0, margin_top=10))
            content_box.append(center_scroll)
            center_source_model = {"": [
                ConfigOption("center_source", "dropdown", "Source:", "none", options_dict=source_opts),
                ConfigOption("center_caption", "string", "Label Override:", "", tooltip="Overrides the default source name.")
            ]}
            build_ui_from_model(center_box, panel_config, center_source_model, widgets)
            dialog.dynamic_models.append(center_source_model)
            center_sub_config_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_start=20)
            center_box.append(center_sub_config_box)
            arc_notebook = Gtk.Notebook()
            content_box.append(Gtk.Separator(margin_top=15, margin_bottom=5))
            content_box.append(Gtk.Label(label="<b>Arc Data Sources</b>", use_markup=True, xalign=0))
            content_box.append(arc_notebook)
            center_combo = widgets["center_source"]
            center_combo.connect("changed", lambda c: _rebuild_slot_config_ui(c.get_active_id(), center_sub_config_box, "center_", dialog, widgets, available_sources, panel_config))
            _rebuild_slot_config_ui(panel_config.get("center_source", "none"), center_sub_config_box, "center_", dialog, widgets, available_sources, panel_config)
            arc_count_spinner = widgets["combo_arc_count"]
            arc_count_spinner.connect("value-changed", lambda s: _create_or_update_arc_tabs(s, arc_notebook, dialog, widgets, available_sources, panel_config, source_opts))
            _create_or_update_arc_tabs(arc_count_spinner, arc_notebook, dialog, widgets, available_sources, panel_config, source_opts)

        def _create_or_update_arc_tabs(spinner, notebook, dialog, widgets, available_sources, panel_config, source_opts):
            count = spinner.get_value_as_int()
            dialog.dynamic_models = [m for m in dialog.dynamic_models if not any(opt.key.startswith("arc") for section in m.values() for opt in section)]
            while notebook.get_n_pages() > count: notebook.remove_page(-1)
            for i in range(1, count + 1):
                if i > notebook.get_n_pages():
                    scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
                    scroll.set_min_content_height(300)
                    
                    tab_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
                    scroll.set_child(tab_box)
                    notebook.append_page(scroll, Gtk.Label(label=f"Arc {i}"))
                    prefix, slot_key = f"arc{i}_", f"arc{i}_source"
                    
                    arc_source_model = {
                        f"Arc {i} Data Source": [
                            ConfigOption(slot_key, "dropdown", "Source:", "none", options_dict=source_opts),
                            ConfigOption(f"{prefix}caption", "string", "Label Override:", "", tooltip="Overrides the default source name.")
                        ]
                    }
                    build_ui_from_model(tab_box, panel_config, arc_source_model, widgets)
                    dialog.dynamic_models.append(arc_source_model)
                    sub_config_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_start=20)
                    tab_box.append(sub_config_box)
                    
                    arc_combo = widgets[slot_key]
                    caption_entry = widgets[f"{prefix}caption"]
                    
                    def on_source_changed(combo, entry):
                        if not entry.get_text():
                            display_name = combo.get_active_text()
                            if display_name and "None" not in display_name:
                                entry.set_text(display_name)
                    
                    arc_combo.connect("changed", on_source_changed, caption_entry)
                    
                    callback = partial(_rebuild_slot_config_ui, parent_box=sub_config_box, prefix=prefix, dialog=dialog, widgets=widgets, available_sources=available_sources, panel_config=panel_config)
                    arc_combo.connect("changed", lambda c, cb=callback: cb(source_key=c.get_active_id()))
                    _rebuild_slot_config_ui(panel_config.get(slot_key, "none"), sub_config_box, prefix, dialog, widgets, available_sources, panel_config)

        def _build_level_bar_config_ui(dialog, content_box, widgets, available_sources, panel_config, source_opts):
            """Builds the configuration UI for the Level Bar Combo mode."""
            bar_count_model = {"": [ConfigOption("number_of_bars", "spinner", "Number of Bars:", 3, 1, 12, 1, 0)]}
            build_ui_from_model(content_box, panel_config, bar_count_model, widgets)
            dialog.dynamic_models.append(bar_count_model)
            
            bar_notebook = Gtk.Notebook()
            content_box.append(Gtk.Separator(margin_top=15, margin_bottom=5))
            content_box.append(Gtk.Label(label="<b>Bar Data Sources</b>", use_markup=True, xalign=0))
            content_box.append(bar_notebook)

            bar_count_spinner = widgets["number_of_bars"]
            bar_count_spinner.connect("value-changed", lambda s: _create_or_update_bar_tabs(s, bar_notebook, dialog, widgets, available_sources, panel_config, source_opts))
            _create_or_update_bar_tabs(bar_count_spinner, bar_notebook, dialog, widgets, available_sources, panel_config, source_opts)

        def _create_or_update_bar_tabs(spinner, notebook, dialog, widgets, available_sources, panel_config, source_opts):
            """Dynamically adds or removes configuration tabs for each bar."""
            count = spinner.get_value_as_int()
            
            while notebook.get_n_pages() > count: notebook.remove_page(-1)
            
            for i in range(1, count + 1):
                if i > notebook.get_n_pages():
                    scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
                    scroll.set_min_content_height(300)
                    
                    tab_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
                    scroll.set_child(tab_box)
                    notebook.append_page(scroll, Gtk.Label(label=f"Bar {i}"))
                    prefix, slot_key = f"bar{i}_", f"bar{i}_source"
                    
                    bar_source_model = {
                        f"Bar {i} Data Source": [
                            ConfigOption(slot_key, "dropdown", "Source:", "none", options_dict=source_opts),
                            ConfigOption(f"{prefix}caption", "string", "Label Override:", "", tooltip="Overrides the default source name.")
                        ]
                    }
                    build_ui_from_model(tab_box, panel_config, bar_source_model, widgets)
                    dialog.dynamic_models.append(bar_source_model)
                    sub_config_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_start=20)
                    tab_box.append(sub_config_box)
                    
                    bar_combo = widgets[slot_key]
                    caption_entry = widgets[f"{prefix}caption"]
                    
                    def on_source_changed(combo, entry):
                        if not entry.get_text():
                            display_name = combo.get_active_text()
                            if display_name and "None" not in display_name:
                                entry.set_text(display_name)
                    
                    bar_combo.connect("changed", on_source_changed, caption_entry)
                    
                    callback = partial(_rebuild_slot_config_ui, parent_box=sub_config_box, prefix=prefix, dialog=dialog, widgets=widgets, available_sources=available_sources, panel_config=panel_config)
                    bar_combo.connect("changed", lambda c, cb=callback: cb(source_key=c.get_active_id()))
                    _rebuild_slot_config_ui(panel_config.get(slot_key, "none"), sub_config_box, prefix, dialog, widgets, available_sources, panel_config)
        
        def _build_lcars_config_ui(dialog, content_box, widgets, available_sources, panel_config, source_opts):
            """Builds the configuration UI for the LCARS Combo mode."""
            content_box.append(Gtk.Label(label="<b>Primary Data Source</b>", use_markup=True, xalign=0, margin_top=10))
            primary_source_model = {"": [
                ConfigOption("primary_source", "dropdown", "Source:", "none", options_dict=source_opts),
                ConfigOption("primary_caption", "string", "Label Override:", "", tooltip="Overrides the default source name.")
            ]}
            build_ui_from_model(content_box, panel_config, primary_source_model, widgets)
            dialog.dynamic_models.append(primary_source_model)
            primary_sub_config_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_start=20)
            content_box.append(primary_sub_config_box)
            
            primary_combo = widgets["primary_source"]
            primary_combo.connect("changed", lambda c: _rebuild_slot_config_ui(c.get_active_id(), primary_sub_config_box, "primary_", dialog, widgets, available_sources, panel_config))
            _rebuild_slot_config_ui(panel_config.get("primary_source", "none"), primary_sub_config_box, "primary_", dialog, widgets, available_sources, panel_config)

            sec_count_model = {"": [ConfigOption("number_of_secondary_sources", "spinner", "Number of Secondary Sources:", 4, 1, 10, 1, 0)]}
            build_ui_from_model(content_box, panel_config, sec_count_model, widgets)
            dialog.dynamic_models.append(sec_count_model)

            sec_notebook = Gtk.Notebook()
            content_box.append(Gtk.Separator(margin_top=15, margin_bottom=5))
            content_box.append(Gtk.Label(label="<b>Secondary Data Sources</b>", use_markup=True, xalign=0))
            content_box.append(sec_notebook)
            
            sec_count_spinner = widgets["number_of_secondary_sources"]
            sec_count_spinner.connect("value-changed", lambda s: _create_or_update_secondary_tabs(s, sec_notebook, dialog, widgets, available_sources, panel_config, source_opts))
            _create_or_update_secondary_tabs(sec_count_spinner, sec_notebook, dialog, widgets, available_sources, panel_config, source_opts)


        def _create_or_update_secondary_tabs(spinner, notebook, dialog, widgets, available_sources, panel_config, source_opts):
            count = spinner.get_value_as_int()
            dialog.dynamic_models = [m for m in dialog.dynamic_models if not any(opt.key.startswith("secondary") for section in m.values() for opt in section)]
            while notebook.get_n_pages() > count: notebook.remove_page(-1)
            
            for i in range(1, count + 1):
                if i > notebook.get_n_pages():
                    scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
                    tab_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
                    scroll.set_child(tab_box)
                    notebook.append_page(scroll, Gtk.Label(label=f"Item {i}"))
                    prefix, slot_key = f"secondary{i}_", f"secondary{i}_source"
                    
                    sec_source_model = {
                        f"Secondary Item {i}": [
                            ConfigOption(slot_key, "dropdown", "Source:", "none", options_dict=source_opts),
                            ConfigOption(f"{prefix}caption", "string", "Label Override:", "", tooltip="Overrides the default source name.")
                        ]
                    }
                    build_ui_from_model(tab_box, panel_config, sec_source_model, widgets)
                    dialog.dynamic_models.append(sec_source_model)
                    
                    sub_config_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_start=20)
                    tab_box.append(sub_config_box)
                    callback = partial(_rebuild_slot_config_ui, parent_box=sub_config_box, prefix=prefix, dialog=dialog, widgets=widgets, available_sources=available_sources, panel_config=panel_config)
                    combo = widgets[slot_key]
                    combo.connect("changed", lambda c, cb=callback: cb(source_key=c.get_active_id()))
                    _rebuild_slot_config_ui(panel_config.get(slot_key, "none"), sub_config_box, prefix, dialog, widgets, available_sources, panel_config)

        def build_main_config_ui(dialog, content_box, widgets, available_sources, panel_config):
            source_opts = {"None": "none", **{info['name']: info['key'] for info in available_sources.values() if info['key'] != 'combo'}}
            mode = panel_config.get('combo_mode', 'arc')
            
            update_interval_model = {
                "Update Interval": [
                    ConfigOption("update_interval_seconds", "scale", "Update Interval (sec):", "2.0", 0.1, 60, 0.1, 1)
                ]
            }
            build_ui_from_model(content_box, panel_config, update_interval_model, widgets)
            dialog.dynamic_models.append(update_interval_model)
            content_box.append(Gtk.Separator(margin_top=10, margin_bottom=5))

            dialog.custom_value_getters = []
            def get_all_custom_values():
                all_values = {}
                if hasattr(dialog, 'custom_value_getters'):
                    for getter in dialog.custom_value_getters:
                        custom_values = getter()
                        all_values.update(custom_values)
                return all_values
            dialog.custom_value_getter = get_all_custom_values
            
            if mode == 'level_bar':
                _build_level_bar_config_ui(dialog, content_box, widgets, available_sources, panel_config, source_opts)
            elif mode == 'lcars':
                _build_lcars_config_ui(dialog, content_box, widgets, available_sources, panel_config, source_opts)
            else: # Default to arc
                _build_arc_config_ui(dialog, content_box, widgets, available_sources, panel_config, source_opts)

        return build_main_config_ui

