# data_sources/level_bar_combo_source.py
import gi
import threading
from functools import partial
from data_source import DataSource
from config_dialog import ConfigOption, build_ui_from_model
from utils import populate_defaults_from_model

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib

class PrefixedConfig:
    """A wrapper to allow child sources to use a shared config without key collisions."""
    def __init__(self, main_config, prefix):
        self._main_config = main_config
        self._prefix = prefix

    def get(self, key, default=None):
        return self._main_config.get(f"{self._prefix}{key}", default)

    def setdefault(self, key, default=None):
        return self._main_config.setdefault(f"{self._prefix}{key}", default)

class LevelBarComboDataSource(DataSource):
    """A container data source that manages multiple child sources for a level bar array."""
    def __init__(self, config):
        super().__init__(config)
        self.child_sources = {}
        self.lock = threading.Lock()

    def setup_child_sources(self, available_sources):
        with self.lock:
            self.child_sources.clear()
            source_map = {info['key']: info['class'] for info in available_sources.values()}
            num_bars = int(self.config.get("number_of_bars", 3))
            for i in range(1, num_bars + 1):
                prefix = f"bar{i}_"
                source_key = self.config.get(f"{prefix}source")
                if source_key and source_key != "none":
                    SourceClass = source_map.get(source_key)
                    if SourceClass:
                        prefixed_config = PrefixedConfig(self.config, f"{prefix}opt_")
                        self.child_sources[f"bar{i}_source"] = SourceClass(config=prefixed_config)

    def get_data(self):
        data_bundle = {}
        with self.lock:
            for key, source in self.child_sources.items():
                data = source.get_data()
                data_bundle[key] = {
                    "data": data,
                    "display_string": source.get_display_string(data),
                    "primary_label": source.get_primary_label_string(data)
                }
        return data_bundle

    @staticmethod
    def get_config_model():
        model = DataSource.get_config_model()
        model["Alarm"] = []  # No standard alarm for this container
        model["Level Bar Combo Configuration"] = [
            ConfigOption("number_of_bars", "spinner", "Number of Bars:", 3, 1, 16, 1, 0)
        ]
        return model

    def get_configure_callback(self):
        def build_config(dialog, content_box, widgets, available_sources, panel_config):
            source_opts = {"None": "none", **{info['name']: info['key'] for info in available_sources.values()}}

            def get_bar_style_model(i):
                prefix = f"bar{i}_"
                return {
                    "Bar Style": [
                        ConfigOption(f"{prefix}on_color", "color", "Segment 'On' Color:", "rgba(170,220,255,1)"),
                        ConfigOption(f"{prefix}off_color", "color", "Segment 'Off' Color:", "rgba(40,60,80,1)")
                    ],
                    "Labels": [
                        ConfigOption(f"{prefix}caption", "string", "Caption:", f"Bar {i}"),
                        ConfigOption(f"{prefix}label_content", "dropdown", "Label Content:", "both",
                                     options_dict={"Caption Only": "caption", "Value Only": "value", "Caption and Value": "both", "None": "none"}),
                        ConfigOption(f"{prefix}label_position", "dropdown", "Label Position:", "middle",
                                     options_dict={"Start": "start", "Middle": "middle", "End": "end"}),
                        ConfigOption(f"{prefix}label_font", "font", "Label Font:", "Sans Bold 10"),
                        ConfigOption(f"{prefix}label_color", "color", "Label Color:", "rgba(220,220,220,1)")
                    ]
                }

            def rebuild_slot_ui(source_key, parent_box, prefix, all_widgets, slot_key_name):
                sub_opt_prefix = f"{prefix}opt_"
                keys_to_remove = [k for k in all_widgets if k.startswith(sub_opt_prefix)]
                for k in keys_to_remove: del all_widgets[k]
                
                child = parent_box.get_first_child()
                while child: parent_box.remove(child); child = parent_box.get_first_child()

                if source_key and source_key != "none":
                    SourceClass = next((s['class'] for s in available_sources.values() if s['key'] == source_key), None)
                    if SourceClass:
                        prefixed_config = PrefixedConfig(panel_config, sub_opt_prefix)
                        model = SourceClass.get_config_model()
                        populate_defaults_from_model(prefixed_config, model)
                        
                        prefixed_model = {}
                        for section, options in model.items():
                            prefixed_options = [ConfigOption(f"{sub_opt_prefix}{opt.key}", opt.type, opt.label, opt.default, opt.min_val, opt.max_val, opt.step, opt.digits, opt.options_dict, opt.tooltip, opt.file_filters) for opt in options]
                            prefixed_model[section] = prefixed_options
                        
                        build_ui_from_model(parent_box, panel_config, prefixed_model, all_widgets)
                        dialog.dynamic_models.append(prefixed_model)
                        
                        temp_instance = SourceClass(config=prefixed_config)
                        custom_cb = temp_instance.get_configure_callback()
                        if custom_cb:
                            custom_cb(dialog, parent_box, all_widgets, available_sources, panel_config)

            notebook = Gtk.Notebook()
            content_box.append(notebook)

            def create_tabs(spinner):
                count = spinner.get_value_as_int()
                while notebook.get_n_pages() > count: notebook.remove_page(-1)
                
                for i in range(1, count + 1):
                    if i > notebook.get_n_pages():
                        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
                        tab_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
                        scroll.set_child(tab_box)
                        notebook.append_page(scroll, Gtk.Label(label=f"Bar {i}"))
                        
                        prefix = f"bar{i}_"
                        slot_key = f"{prefix}source"
                        caption_key = f"{prefix}caption"
                        
                        # Build Data Source UI
                        model = {f"Bar {i} Data Source": [ConfigOption(slot_key, "dropdown", "Source:", "none", options_dict=source_opts)]}
                        build_ui_from_model(tab_box, panel_config, model, widgets)
                        dialog.dynamic_models.append(model)

                        # Build Style UI
                        style_model = get_bar_style_model(i)
                        populate_defaults_from_model(panel_config, style_model)
                        build_ui_from_model(tab_box, panel_config, style_model, widgets)
                        dialog.dynamic_models.append(style_model)

                        # Build Sub-config UI container
                        sub_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_start=20)
                        tab_box.append(sub_box)

                        combo = widgets[slot_key]
                        caption_entry = widgets[caption_key]

                        def on_source_changed(c, cap_entry):
                            display_name = c.get_active_text()
                            if display_name and "None" not in display_name:
                                cap_entry.set_text(display_name)

                        combo.connect("changed", on_source_changed, caption_entry)
                        
                        callback = partial(rebuild_slot_ui, parent_box=sub_box, prefix=prefix, all_widgets=widgets, slot_key_name=slot_key)
                        combo.connect("changed", lambda c, cb=callback: cb(source_key=c.get_active_id()))
                        rebuild_slot_ui(panel_config.get(slot_key, "none"), sub_box, prefix, widgets, slot_key)

            bar_count_spinner = widgets["number_of_bars"]
            bar_count_spinner.connect("value-changed", create_tabs)
            create_tabs(bar_count_spinner)

        return build_config
