# data_displayers/level_bar_combo.py
import gi
import math
import cairo
import time
from .combo_base import ComboBase
from config_dialog import ConfigOption, build_ui_from_model
from utils import populate_defaults_from_model
from .level_bar import LevelBarDisplayer # Import to reuse drawing logic

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gdk, GLib, Pango, PangoCairo

class LevelBarComboDisplayer(ComboBase):
    """
    A displayer that arranges a configurable number of animated level bars,
    each tied to a different data source, with individual styling for each bar.
    """
    def __init__(self, panel_ref, config):
        self._animation_timer_id = None
        self._bar_values = {}
        # Create a dummy LevelBarDisplayer instance to borrow its drawing logic
        self._drawer = LevelBarDisplayer(panel_ref, config)

        super().__init__(panel_ref, config)
        populate_defaults_from_model(self.config, self.get_config_model())
        
        self.widget.connect("realize", self._start_animation_timer)
        self.widget.connect("unrealize", self._stop_animation_timer)

    def update_display(self, value):
        super().update_display(value) # Stores data_bundle and queues draw

        num_bars = int(self.config.get("number_of_bars", 3))
        for i in range(1, num_bars + 1):
            bar_key = f"bar{i}"
            source_key = f"{bar_key}_source"
            
            if bar_key not in self._bar_values:
                self._bar_values[bar_key] = {'current': 0.0, 'target': 0.0, 'first_update': True}

            new_value = 0.0
            data_packet = self.data_bundle.get(source_key, {})
            num_val = data_packet.get('numerical_value')
            if isinstance(num_val, (int, float)):
                new_value = num_val
            
            if self._bar_values[bar_key]['first_update']:
                self._bar_values[bar_key]['current'] = new_value
                self._bar_values[bar_key]['first_update'] = False

            self._bar_values[bar_key]['target'] = new_value

    def reset_state(self):
        self._bar_values.clear()
        super().reset_state()

    @staticmethod
    def get_config_model():
        # --- BUG FIX: Return an empty model here. ---
        # The entire UI for this complex displayer is built by the custom
        # configure_callback to prevent duplicate widget creation by the DataPanel.
        return {}

    def get_configure_callback(self):
        """Builds the UI for the Display tab with per-bar styling."""
        def build_display_ui(dialog, content_box, widgets, available_sources, panel_config):
            # --- BUG FIX: Define the model INSIDE the callback ---
            # This ensures it's only built once, by this callback.
            model = {
                "Overall Layout": [
                    ConfigOption("combo_bar_orientation", "dropdown", "Bar Orientation:", "vertical", 
                                 options_dict={"Vertical": "vertical", "Horizontal": "horizontal"}),
                    ConfigOption("combo_bar_spacing", "spinner", "Spacing Between Bars (px):", 10, 0, 50, 1, 0),
                    ConfigOption("combo_animation_enabled", "bool", "Enable Bar Animation:", "True")
                ]
            }

            # 1. Build the static layout controls
            dialog.dynamic_models.append(model)
            build_ui_from_model(content_box, panel_config, model, widgets)
            
            content_box.append(Gtk.Separator(margin_top=15, margin_bottom=5))
            content_box.append(Gtk.Label(label="<b>Individual Bar Styles</b>", use_markup=True, xalign=0))

            # 2. Create a notebook for per-bar styles
            style_notebook = Gtk.Notebook()
            content_box.append(style_notebook)

            # 3. Helper function to create the model for a single bar's style tab
            def get_bar_style_model(i):
                base_model = LevelBarDisplayer.get_config_model()
                prefixed_model = {}
                for section, options in base_model.items():
                    # We don't need these per-bar, they are data-driven
                    if section in ["Level Bar Range"]:
                        continue
                    
                    prefixed_options = []
                    for opt in options:
                        prefixed_options.append(ConfigOption(
                            f"bar{i}_{opt.key}", opt.type, opt.label, opt.default, 
                            opt.min_val, opt.max_val, opt.step, opt.digits, 
                            opt.options_dict, opt.tooltip, opt.file_filters
                        ))
                    prefixed_model[section] = prefixed_options
                return prefixed_model

            # 4. Function to dynamically create/remove style tabs
            def build_bar_style_tabs(spinner):
                count = spinner.get_value_as_int()
                
                # Remove old models to prevent key conflicts
                # dialog.dynamic_models = [m for m in dialog.dynamic_models if not any(opt.key.startswith("bar") for s in m.values() for opt in s)]
                
                while style_notebook.get_n_pages() > count:
                    style_notebook.remove_page(-1)
                
                for i in range(1, count + 1):
                    if i > style_notebook.get_n_pages():
                        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
                        tab_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
                        scroll.set_child(tab_box)
                        style_notebook.append_page(scroll, Gtk.Label(label=f"Style {i}"))
                        
                        bar_model = get_bar_style_model(i)
                        populate_defaults_from_model(panel_config, bar_model)
                        build_ui_from_model(tab_box, panel_config, bar_model, widgets)
                        dialog.dynamic_models.append(bar_model)

            # 5. Connect to the 'number_of_bars' spinner from the Data Source tab
            bar_count_spinner = widgets.get("number_of_bars")
            if bar_count_spinner:
                bar_count_spinner.connect("value-changed", build_bar_style_tabs)
                GLib.idle_add(build_bar_style_tabs, bar_count_spinner)

        return build_display_ui

    def apply_styles(self):
        super().apply_styles()
        self.widget.queue_draw()

    def _start_animation_timer(self, widget=None):
        self._stop_animation_timer()
        self._animation_timer_id = GLib.timeout_add(16, self._animation_tick)

    def _stop_animation_timer(self, widget=None):
        if self._animation_timer_id is not None:
            GLib.source_remove(self._animation_timer_id)
            self._animation_timer_id = None

    def _animation_tick(self):
        if not self.widget.get_realized():
            self._animation_timer_id = None
            return GLib.SOURCE_REMOVE

        animation_enabled = str(self.config.get("combo_animation_enabled", "True")).lower() == 'true'
        needs_redraw = False

        if not animation_enabled:
            for bar_key, values in self._bar_values.items():
                if values['current'] != values['target']:
                    values['current'] = values['target']
                    needs_redraw = True
        else:
            for bar_key, values in self._bar_values.items():
                diff = values['target'] - values['current']
                if abs(diff) < 0.01:
                    if values['current'] != values['target']:
                        values['current'] = values['target']
                        needs_redraw = True
                    continue
                values['current'] += diff * 0.1
                needs_redraw = True

        if needs_redraw:
            self.widget.queue_draw()
            
        return GLib.SOURCE_CONTINUE

    def on_draw(self, area, ctx, width, height):
        num_bars = int(self.config.get("number_of_bars", 3))
        if num_bars == 0: return

        orientation = self.config.get("combo_bar_orientation", "vertical")
        spacing = float(self.config.get("combo_bar_spacing", 10))
        total_spacing = (num_bars - 1) * spacing
        
        bar_x, bar_y = 0, 0
        
        if orientation == "vertical":
            bar_width = width
            bar_height = (height - total_spacing) / num_bars
        else: # horizontal
            bar_width = (width - total_spacing) / num_bars
            bar_height = height

        if bar_width <= 0 or bar_height <= 0: return

        for i in range(1, num_bars + 1):
            bar_key = f"bar{i}"
            source_key = f"{bar_key}_source"
            data_packet = self.data_bundle.get(source_key, {})
            
            # --- BUG FIX: Populate a clean config with defaults first ---
            drawer_config = {}
            populate_defaults_from_model(drawer_config, LevelBarDisplayer.get_config_model())

            # Then, override with per-bar settings from the main config
            bar_prefix = f"bar{i}_"
            for key, value in self.config.items():
                if key.startswith(bar_prefix):
                    drawer_config[key.replace(bar_prefix, '')] = value
            
            drawer_config['level_min_value'] = data_packet.get('min_value', 0.0)
            drawer_config['level_max_value'] = data_packet.get('max_value', 100.0)

            self._drawer.config = drawer_config
            self._drawer._sync_state_with_config()

            self._drawer.primary_text = self.config.get(f"bar{i}_caption") or data_packet.get('primary_label', '')
            self._drawer.secondary_text = data_packet.get('display_string', '')
            
            current_animated_val = self._bar_values.get(bar_key, {}).get('current', 0.0)
            self._drawer.current_value = current_animated_val
            
            min_v, max_v = drawer_config.get('level_min_value', 0.0), drawer_config.get('level_max_value', 100.0)
            v_range = max_v - min_v if max_v > min_v else 1
            num_segments = int(drawer_config.get("level_bar_segment_count", 30))
            
            self._drawer.target_on_level = int(round(((min(max(current_animated_val, min_v), max_v) - min_v) / v_range) * num_segments))
            self._drawer.current_on_level = self._drawer.target_on_level

            ctx.save()
            ctx.translate(bar_x, bar_y)
            self._drawer.on_draw(area, ctx, bar_width, bar_height)
            ctx.restore()

            if orientation == "vertical":
                bar_y += bar_height + spacing
            else:
                bar_x += bar_width + spacing
                
    def close(self):
        self._stop_animation_timer()
        if self._drawer:
            self._drawer.close()
            self._drawer = None
        super().close()

