# /data_sources/combo_source.py
import gi
import threading
import time
from functools import partial
from data_source import DataSource
from config_dialog import ConfigOption, build_ui_from_model, get_config_from_widgets
from utils import populate_defaults_from_model

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib

class ComboDataSource(DataSource):
    """
    A unified container data source for panels that display multiple child sources.
    It now relies on the UpdateManager for all scheduling.
    """
    def __init__(self, config):
        super().__init__(config)
        self.child_sources = {}
        self.lock = threading.Lock()

    @property
    def is_clock_source(self):
        with self.lock:
            return any(source.is_clock_source for source in self.child_sources.values())

    @property
    def needs_second_updates(self):
        with self.lock:
            return any(source.needs_second_updates for source in self.child_sources.values())

    def setup_child_sources(self, available_sources):
        """
        Initializes child sources based on the panel's configuration.
        """
        with self.lock:
            self.child_sources.clear()
            
            sources_iterable = available_sources.values() if isinstance(available_sources, dict) else available_sources
            source_map = {info['key']: info['class'] for info in sources_iterable}
            
            mode = self.config.get('combo_mode', 'arc')

            def create_child(slot_prefix):
                opt_prefix = f"{slot_prefix}opt_"
                source_key = self.config.get(f"{slot_prefix}source")
                
                if source_key and source_key != "none":
                    SourceClass = source_map.get(source_key)
                    if SourceClass:
                        child_config = {}
                        populate_defaults_from_model(child_config, SourceClass.get_config_model())
                        
                        for key, value in self.config.items():
                            if key.startswith(opt_prefix):
                                unprefixed_key = key[len(opt_prefix):]
                                child_config[unprefixed_key] = value
                        
                        child_config['caption_override'] = self.config.get(f"{slot_prefix}caption", "")
                        
                        child_instance = SourceClass(config=child_config.copy())
                        instance_key = f"{slot_prefix}source"
                        self.child_sources[instance_key] = child_instance

            if mode == 'level_bar':
                num_bars = int(self.config.get("number_of_bars", 3))
                for i in range(1, num_bars + 1): create_child(f"bar{i}_")
            elif mode == 'lcars':
                create_child("primary_")
                num_secondary = int(self.config.get("number_of_secondary_sources", 4))
                for i in range(1, num_secondary + 1): create_child(f"secondary{i}_")
            elif mode == 'dashboard':
                num_center = int(self.config.get("dashboard_center_count", 1))
                for i in range(1, num_center + 1): create_child(f"center_{i}_")
                num_satellite = int(self.config.get("dashboard_satellite_count", 4))
                for i in range(1, num_satellite + 1): create_child(f"satellite_{i}_")
            else: # 'arc' mode
                create_child("center_")
                num_arcs = int(self.config.get("combo_arc_count", 5))
                for i in range(1, num_arcs + 1): create_child(f"arc{i}_")

    def get_data(self):
        """
        Fetches fresh data from all configured child sources.
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
        # Get the base model which includes the update interval
        model = DataSource.get_config_model()
        # Only remove the alarm section, as it doesn't apply to the combo as a whole
        model.pop("Alarm", None) 
        return model


    def get_configure_callback(self):
        """
        Returns a function that builds a robust configuration UI by creating all
        possible widgets upfront and managing their visibility.
        """
        def _build_slot_config_ui(source_key, parent_box, prefix, dialog, widgets, available_sources, panel_config):
            """Clears and rebuilds the configuration UI for a single data source slot."""
            sub_opt_prefix = f"{prefix}opt_"
            
            keys_to_remove = [k for k in widgets if k.startswith(sub_opt_prefix)]
            for k in keys_to_remove: widgets.pop(k, None)
            dialog.dynamic_models = [m for m in dialog.dynamic_models if not any(opt.key.startswith(sub_opt_prefix) for s in m.values() for opt in s)]
            
            child = parent_box.get_first_child()
            while child: parent_box.remove(child); child = parent_box.get_first_child()

            if source_key and source_key != "none":
                sources_iterable = available_sources.values() if isinstance(available_sources, dict) else available_sources
                SourceClass = next((s['class'] for s in sources_iterable if s['key'] == source_key), None)
                if SourceClass:
                    model = SourceClass.get_config_model()
                    child_config = {}
                    populate_defaults_from_model(child_config, model)
                    for key, option in [(opt.key, opt) for section in model.values() for opt in section]:
                        prefixed_key = f"{sub_opt_prefix}{key}"
                        if prefixed_key in panel_config:
                            child_config[key] = panel_config[prefixed_key]
                    
                    unprefixed_widgets = {}
                    build_ui_from_model(parent_box, child_config, model, unprefixed_widgets)
                    for key, widget in unprefixed_widgets.items():
                        widgets[f"{sub_opt_prefix}{key}"] = widget

                    prefixed_model = {s: [ConfigOption(f"{sub_opt_prefix}{o.key}", o.type, o.label, o.default, o.min_val, o.max_val, o.step, o.digits, o.options_dict, o.tooltip, o.file_filters,
                                                       dynamic_group=f"{sub_opt_prefix}{o.dynamic_group}" if o.dynamic_group else None,
                                                       dynamic_show_on=o.dynamic_show_on) 
                                           for o in opts] 
                                    for s, opts in model.items()}
                    dialog.dynamic_models.append(prefixed_model)
                    
                    custom_cb = SourceClass(config=child_config).get_configure_callback()
                    if custom_cb:
                        custom_cb(dialog, parent_box, widgets, available_sources, panel_config, prefix)

        def _build_arc_config_ui(dialog, content_box, widgets, available_sources, panel_config, source_opts):
            arc_count_model = {"": [ConfigOption("combo_arc_count", "spinner", "Number of Arcs:", 5, 0, 16, 1, 0)]}
            build_ui_from_model(content_box, panel_config, arc_count_model, widgets)
            dialog.dynamic_models.append(arc_count_model)
            
            content_box.append(Gtk.Label(label="<b>Center Data Source</b>", use_markup=True, xalign=0, margin_top=10))
            center_source_model = {"": [ ConfigOption("center_source", "dropdown", "Source:", "none", options_dict=source_opts), ConfigOption("center_caption", "string", "Label Override:", "", tooltip="Overrides the default source name.") ]}
            build_ui_from_model(content_box, panel_config, center_source_model, widgets)
            dialog.dynamic_models.append(center_source_model)
            center_sub_config_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_start=20); content_box.append(center_sub_config_box)
            
            content_box.append(Gtk.Separator(margin_top=15, margin_bottom=5))
            content_box.append(Gtk.Label(label="<b>Arc Data Sources</b>", use_markup=True, xalign=0))
            arc_notebook = Gtk.Notebook(); arc_notebook.set_scrollable(True); content_box.append(arc_notebook)
            
            arc_tabs_content = []
            for i in range(1, 17):
                scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True, min_content_height=300)
                tab_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10); scroll.set_child(tab_box)
                arc_notebook.append_page(scroll, Gtk.Label(label=f"Arc {i}")); arc_tabs_content.append(scroll)
                
                prefix, slot_key = f"arc{i}_", f"arc{i}_source"
                arc_source_model = {f"Arc {i}": [ ConfigOption(slot_key, "dropdown", "Source:", "none", options_dict=source_opts), ConfigOption(f"{prefix}caption", "string", "Label Override:", "") ]}
                build_ui_from_model(tab_box, panel_config, arc_source_model, widgets); dialog.dynamic_models.append(arc_source_model)
                sub_config_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_start=20); tab_box.append(sub_config_box)
                
                arc_combo = widgets[slot_key]
                callback = partial(_build_slot_config_ui, parent_box=sub_config_box, prefix=prefix, dialog=dialog, widgets=widgets, available_sources=available_sources, panel_config=panel_config)
                arc_combo.connect("changed", lambda c, cb=callback: cb(source_key=c.get_active_id()))
                GLib.idle_add(_build_slot_config_ui, panel_config.get(slot_key, "none"), sub_config_box, prefix, dialog, widgets, available_sources, panel_config)

            def on_arc_count_changed(spinner):
                count = spinner.get_value_as_int()
                for i, content_widget in enumerate(arc_tabs_content): content_widget.set_visible(i < count)
            
            arc_count_spinner = widgets["combo_arc_count"]; arc_count_spinner.connect("value-changed", on_arc_count_changed); GLib.idle_add(on_arc_count_changed, arc_count_spinner)
            center_combo = widgets["center_source"]
            callback = partial(_build_slot_config_ui, parent_box=center_sub_config_box, prefix="center_", dialog=dialog, widgets=widgets, available_sources=available_sources, panel_config=panel_config)
            center_combo.connect("changed", lambda c, cb=callback: cb(source_key=c.get_active_id()))
            GLib.idle_add(_build_slot_config_ui, panel_config.get("center_source", "none"), center_sub_config_box, "center_", dialog, widgets, available_sources, panel_config)

        def _build_level_bar_config_ui(dialog, content_box, widgets, available_sources, panel_config, source_opts):
            bar_count_model = {"": [ConfigOption("number_of_bars", "spinner", "Number of Bars:", 3, 1, 12, 1, 0)]}
            build_ui_from_model(content_box, panel_config, bar_count_model, widgets); dialog.dynamic_models.append(bar_count_model)
            
            content_box.append(Gtk.Separator(margin_top=15, margin_bottom=5))
            content_box.append(Gtk.Label(label="<b>Bar Data Sources</b>", use_markup=True, xalign=0))
            bar_notebook = Gtk.Notebook(); bar_notebook.set_scrollable(True); content_box.append(bar_notebook)

            bar_tabs_content = []
            for i in range(1, 13):
                scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True, min_content_height=300)
                tab_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10); scroll.set_child(tab_box)
                bar_notebook.append_page(scroll, Gtk.Label(label=f"Bar {i}")); bar_tabs_content.append(scroll)
                
                prefix, slot_key = f"bar{i}_", f"bar{i}_source"
                bar_source_model = {f"Bar {i}": [ConfigOption(slot_key, "dropdown", "Source:", "none", options_dict=source_opts), ConfigOption(f"{prefix}caption", "string", "Label Override:", "")]}
                build_ui_from_model(tab_box, panel_config, bar_source_model, widgets); dialog.dynamic_models.append(bar_source_model)
                sub_config_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_start=20); tab_box.append(sub_config_box)
                
                bar_combo = widgets[slot_key]
                callback = partial(_build_slot_config_ui, parent_box=sub_config_box, prefix=prefix, dialog=dialog, widgets=widgets, available_sources=available_sources, panel_config=panel_config)
                bar_combo.connect("changed", lambda c, cb=callback: cb(source_key=c.get_active_id()))
                GLib.idle_add(_build_slot_config_ui, panel_config.get(slot_key, "none"), sub_config_box, prefix, dialog, widgets, available_sources, panel_config)
            
            def on_bar_count_changed(spinner):
                count = spinner.get_value_as_int()
                for i, content_widget in enumerate(bar_tabs_content): content_widget.set_visible(i < count)
            
            bar_count_spinner = widgets["number_of_bars"]; bar_count_spinner.connect("value-changed", on_bar_count_changed); GLib.idle_add(on_bar_count_changed, bar_count_spinner)

        def _build_lcars_config_ui(dialog, content_box, widgets, available_sources, panel_config, source_opts):
            content_box.append(Gtk.Label(label="<b>Primary Data Source</b>", use_markup=True, xalign=0, margin_top=10))
            primary_model = {"": [ConfigOption("primary_source", "dropdown", "Source:", "none", options_dict=source_opts), ConfigOption("primary_caption", "string", "Label Override:", "")]}
            build_ui_from_model(content_box, panel_config, primary_model, widgets); dialog.dynamic_models.append(primary_model)
            primary_sub_config_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_start=20); content_box.append(primary_sub_config_box)
            
            sec_count_model = {"": [ConfigOption("number_of_secondary_sources", "spinner", "Secondary Items:", 4, 1, 16, 1, 0)]}
            build_ui_from_model(content_box, panel_config, sec_count_model, widgets); dialog.dynamic_models.append(sec_count_model)

            content_box.append(Gtk.Separator(margin_top=15, margin_bottom=5))
            content_box.append(Gtk.Label(label="<b>Secondary Data Sources</b>", use_markup=True, xalign=0))
            sec_notebook = Gtk.Notebook(); sec_notebook.set_scrollable(True); content_box.append(sec_notebook)
            
            secondary_tabs_content = []
            for i in range(1, 17):
                scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True, min_content_height=300)
                tab_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10); scroll.set_child(tab_box)
                sec_notebook.append_page(scroll, Gtk.Label(label=f"Item {i}")); secondary_tabs_content.append(scroll)
                
                prefix, slot_key = f"secondary{i}_", f"secondary{i}_source"
                sec_source_model = {f"Item {i}": [ConfigOption(slot_key, "dropdown", "Source:", "none", options_dict=source_opts), ConfigOption(f"{prefix}caption", "string", "Label Override:", "")]}
                build_ui_from_model(tab_box, panel_config, sec_source_model, widgets); dialog.dynamic_models.append(sec_source_model)
                sub_config_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_start=20); tab_box.append(sub_config_box)

                combo = widgets[slot_key]
                callback = partial(_build_slot_config_ui, parent_box=sub_config_box, prefix=prefix, dialog=dialog, widgets=widgets, available_sources=available_sources, panel_config=panel_config)
                combo.connect("changed", lambda c, cb=callback: cb(source_key=c.get_active_id()))
                GLib.idle_add(_build_slot_config_ui, panel_config.get(slot_key, "none"), sub_config_box, prefix, dialog, widgets, available_sources, panel_config)

            def on_secondary_count_changed(spinner):
                count = spinner.get_value_as_int()
                for i, content_widget in enumerate(secondary_tabs_content): content_widget.set_visible(i < count)

            sec_count_spinner = widgets["number_of_secondary_sources"]; sec_count_spinner.connect("value-changed", on_secondary_count_changed); GLib.idle_add(on_secondary_count_changed, sec_count_spinner)
            
            primary_combo = widgets["primary_source"]
            callback = partial(_build_slot_config_ui, parent_box=primary_sub_config_box, prefix="primary_", dialog=dialog, widgets=widgets, available_sources=available_sources, panel_config=panel_config)
            primary_combo.connect("changed", lambda c, cb=callback: cb(source_key=c.get_active_id()))
            GLib.idle_add(_build_slot_config_ui, panel_config.get("primary_source", "none"), primary_sub_config_box, "primary_", dialog, widgets, available_sources, panel_config)

        def _build_dashboard_config_ui(dialog, content_box, widgets, available_sources, panel_config, source_opts):
            """Builds the configuration UI for the Dashboard Combo's data sources."""
            # --- Center Displays ---
            center_count_model = {"": [ConfigOption("dashboard_center_count", "spinner", "Number of Center Displays:", 1, 1, 4, 1, 0)]}
            build_ui_from_model(content_box, panel_config, center_count_model, widgets)
            dialog.dynamic_models.append(center_count_model)
            
            content_box.append(Gtk.Label(label="<b>Center Display Sources</b>", use_markup=True, xalign=0, margin_top=10))
            center_notebook = Gtk.Notebook(); center_notebook.set_scrollable(True); content_box.append(center_notebook)
            center_tabs = []
            for i in range(1, 5):
                scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True, min_content_height=300)
                tab_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10); scroll.set_child(tab_box)
                page_num = center_notebook.append_page(scroll, Gtk.Label(label=f"Center {i}")); center_tabs.append(center_notebook.get_nth_page(page_num))
                prefix, slot_key = f"center_{i}_", f"center_{i}_source"
                model = {f"Center {i}": [ ConfigOption(slot_key, "dropdown", "Source:", "none", options_dict=source_opts), ConfigOption(f"{prefix}caption", "string", "Label Override:", "") ]}
                build_ui_from_model(tab_box, panel_config, model, widgets); dialog.dynamic_models.append(model)
                sub_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_start=20); tab_box.append(sub_box)
                combo = widgets[slot_key]
                cb = partial(_build_slot_config_ui, parent_box=sub_box, prefix=prefix, dialog=dialog, widgets=widgets, available_sources=available_sources, panel_config=panel_config)
                combo.connect("changed", lambda c, callback=cb: callback(source_key=c.get_active_id()))
                GLib.idle_add(_build_slot_config_ui, panel_config.get(slot_key, "none"), sub_box, prefix, dialog, widgets, available_sources, panel_config)

            def on_center_count_changed(spinner):
                for i, tab in enumerate(center_tabs): tab.set_visible(i < spinner.get_value_as_int())
            
            center_count_spinner = widgets["dashboard_center_count"]; center_count_spinner.connect("value-changed", on_center_count_changed); GLib.idle_add(on_center_count_changed, center_count_spinner)

            # --- Satellite Displays ---
            content_box.append(Gtk.Separator(margin_top=15, margin_bottom=5))
            satellite_count_model = {"": [ConfigOption("dashboard_satellite_count", "spinner", "Number of Satellite Displays:", 4, 0, 12, 1, 0)]}
            build_ui_from_model(content_box, panel_config, satellite_count_model, widgets)
            dialog.dynamic_models.append(satellite_count_model)
            
            content_box.append(Gtk.Label(label="<b>Satellite Display Sources</b>", use_markup=True, xalign=0, margin_top=10))
            satellite_notebook = Gtk.Notebook(); satellite_notebook.set_scrollable(True); content_box.append(satellite_notebook)
            satellite_tabs = []
            for i in range(1, 13):
                scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True, min_content_height=300)
                tab_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10); scroll.set_child(tab_box)
                page_num = satellite_notebook.append_page(scroll, Gtk.Label(label=f"Satellite {i}")); satellite_tabs.append(satellite_notebook.get_nth_page(page_num))
                prefix, slot_key = f"satellite_{i}_", f"satellite_{i}_source"
                model = {f"Satellite {i}": [ ConfigOption(slot_key, "dropdown", "Source:", "none", options_dict=source_opts), ConfigOption(f"{prefix}caption", "string", "Label Override:", "") ]}
                build_ui_from_model(tab_box, panel_config, model, widgets); dialog.dynamic_models.append(model)
                sub_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_start=20); tab_box.append(sub_box)
                combo = widgets[slot_key]
                cb = partial(_build_slot_config_ui, parent_box=sub_box, prefix=prefix, dialog=dialog, widgets=widgets, available_sources=available_sources, panel_config=panel_config)
                combo.connect("changed", lambda c, callback=cb: callback(source_key=c.get_active_id()))
                GLib.idle_add(_build_slot_config_ui, panel_config.get(slot_key, "none"), sub_box, prefix, dialog, widgets, available_sources, panel_config)

            def on_satellite_count_changed(spinner):
                for i, tab in enumerate(satellite_tabs): tab.set_visible(i < spinner.get_value_as_int())
            
            satellite_count_spinner = widgets["dashboard_satellite_count"]; satellite_count_spinner.connect("value-changed", on_satellite_count_changed); GLib.idle_add(on_satellite_count_changed, satellite_count_spinner)

        def build_main_config_ui(dialog, content_box, widgets, available_sources, panel_config):
            sources_iterable = available_sources.values() if isinstance(available_sources, dict) else available_sources
            source_opts = {"None": "none", **{info['name']: info['key'] for info in sources_iterable if info['key'] != 'combo'}}
            mode = panel_config.get('combo_mode', 'arc')
            
            if mode == 'level_bar':
                _build_level_bar_config_ui(dialog, content_box, widgets, available_sources, panel_config, source_opts)
            elif mode == 'lcars':
                _build_lcars_config_ui(dialog, content_box, widgets, available_sources, panel_config, source_opts)
            elif mode == 'dashboard':
                _build_dashboard_config_ui(dialog, content_box, widgets, available_sources, panel_config, source_opts)
            else: # Default to arc
                _build_arc_config_ui(dialog, content_box, widgets, available_sources, panel_config, source_opts)

        return build_main_config_ui

