# /data_displayers/level_bar_combo.py
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
        self._drawer = LevelBarDisplayer(None, config)

        super().__init__(panel_ref, config)
        populate_defaults_from_model(self.config, self.get_config_model())
        
        self.widget.connect("realize", self._start_animation_timer)
        self.widget.connect("unrealize", self._stop_animation_timer)

    @property
    def panel_ref(self):
        return self._panel_ref

    @panel_ref.setter
    def panel_ref(self, value):
        self._panel_ref = value
        if self._drawer:
            self._drawer.panel_ref = value

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
        return {}

    def get_configure_callback(self):
        """Builds the UI for the Display tab with per-bar styling."""
        def build_display_ui(dialog, content_box, widgets, available_sources, panel_config):
            display_notebook = Gtk.Notebook()
            content_box.append(display_notebook)

            # --- Layout Tab ---
            layout_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
            model = {
                "Overall Layout": [
                    ConfigOption("combo_bar_orientation", "dropdown", "Bar Orientation:", "vertical", 
                                 options_dict={"Vertical": "vertical", "Horizontal": "horizontal"}),
                    ConfigOption("combo_bar_spacing", "spinner", "Spacing Between Bars (px):", 10, 0, 50, 1, 0),
                    ConfigOption("combo_animation_enabled", "bool", "Enable Bar Animation:", "True")
                ]
            }
            dialog.dynamic_models.append(model)
            build_ui_from_model(layout_box, panel_config, model, widgets)
            display_notebook.append_page(layout_box, Gtk.Label(label="Layout"))

            # --- Styles Tab ---
            styles_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
            style_notebook = Gtk.Notebook()
            style_notebook.set_scrollable(True)
            styles_box.append(style_notebook)
            display_notebook.append_page(styles_box, Gtk.Label(label="Styles"))

            # --- Effects Tab ---
            effects_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_top=15, margin_bottom=15, margin_start=15, margin_end=15)
            display_notebook.append_page(effects_box, Gtk.Label(label="Effects"))
            
            # Effect 1: Copy Style
            effects_box.append(Gtk.Label(label="<b>Copy Bar Style</b>", xalign=0, use_markup=True))
            copy_grid = Gtk.Grid(column_spacing=10, row_spacing=10)
            effects_box.append(copy_grid)
            source_bar_combo = Gtk.ComboBoxText()
            copy_grid.attach(Gtk.Label(label="Source Bar:", xalign=1), 0, 0, 1, 1); copy_grid.attach(source_bar_combo, 1, 0, 1, 1)
            copy_checkboxes = { "Bar Style": Gtk.CheckButton(label="Bar Style (Colors, Geometry)"), "Effects": Gtk.CheckButton(label="Effects (Animation, Fades)"), "Layout": Gtk.CheckButton(label="Text Layout"), "Primary Label": Gtk.CheckButton(label="Primary Label Style"), "Secondary Label": Gtk.CheckButton(label="Secondary Label Style") }
            for i, (key, chk) in enumerate(copy_checkboxes.items()):
                chk.set_active(True); copy_grid.attach(chk, 0, i + 1, 2, 1)
            apply_style_button = Gtk.Button(label="Apply Selected Style to All Other Bars")
            copy_grid.attach(apply_style_button, 0, len(copy_checkboxes) + 2, 2, 1)
            
            # Effect 2: Gradient Color
            effects_box.append(Gtk.Separator(margin_top=15, margin_bottom=10))
            effects_box.append(Gtk.Label(label="<b>Apply Color Gradient</b>", xalign=0, use_markup=True))
            grad_grid = Gtk.Grid(column_spacing=10, row_spacing=10)
            effects_box.append(grad_grid)
            grad_start_bar_combo = Gtk.ComboBoxText(); grad_end_bar_combo = Gtk.ComboBoxText()
            grad_start_color = Gtk.ColorButton(); grad_end_color = Gtk.ColorButton()
            grad_target_on = Gtk.CheckButton(label="'On' Color"); grad_target_on.set_active(True)
            grad_target_off = Gtk.CheckButton(label="'Off' Color")
            grad_target_bg = Gtk.CheckButton(label="Background Color")
            apply_gradient_button = Gtk.Button(label="Apply Gradient to Bar Range")
            grad_grid.attach(Gtk.Label(label="Start Bar:", xalign=1), 0, 0, 1, 1); grad_grid.attach(grad_start_bar_combo, 1, 0, 1, 1)
            grad_grid.attach(Gtk.Label(label="End Bar:", xalign=1), 0, 1, 1, 1); grad_grid.attach(grad_end_bar_combo, 1, 1, 1, 1)
            grad_grid.attach(Gtk.Label(label="Start Color:", xalign=1), 0, 2, 1, 1); grad_grid.attach(grad_start_color, 1, 2, 1, 1)
            grad_grid.attach(Gtk.Label(label="End Color:", xalign=1), 0, 3, 1, 1); grad_grid.attach(grad_end_color, 1, 3, 1, 1)
            grad_grid.attach(grad_target_on, 0, 4, 2, 1); grad_grid.attach(grad_target_off, 0, 5, 2, 1); grad_grid.attach(grad_target_bg, 0, 6, 2, 1)
            grad_grid.attach(apply_gradient_button, 0, 7, 2, 1)

            def _interpolate_rgba(factor, c1, c2):
                inter = Gdk.RGBA(); inter.red=c1.red+factor*(c2.red-c1.red); inter.green=c1.green+factor*(c2.green-c1.green); inter.blue=c1.blue+factor*(c2.blue-c1.blue); inter.alpha=c1.alpha+factor*(c2.alpha-c1.alpha); return inter

            def on_apply_gradient_clicked(button):
                start_id_str, end_id_str = grad_start_bar_combo.get_active_id(), grad_end_bar_combo.get_active_id()
                if not start_id_str or not end_id_str: return
                start_index, end_index = int(start_id_str), int(end_id_str)
                if start_index > end_index: start_index, end_index = end_index, start_index
                start_rgba, end_rgba = grad_start_color.get_rgba(), grad_end_color.get_rgba()
                steps = end_index - start_index
                for i in range(start_index, end_index + 1):
                    factor = (i - start_index) / steps if steps > 0 else 0.0
                    inter_color = _interpolate_rgba(factor, start_rgba, end_rgba)
                    if grad_target_on.get_active():
                        w = widgets.get(f"bar{i}_level_bar_on_color"); w.set_rgba(inter_color)
                        w2 = widgets.get(f"bar{i}_level_bar_on_color2"); w2.set_rgba(inter_color)
                    if grad_target_off.get_active(): widgets.get(f"bar{i}_level_bar_off_color").set_rgba(inter_color)
                    if grad_target_bg.get_active(): widgets.get(f"bar{i}_level_bar_background_color").set_rgba(inter_color)
            apply_gradient_button.connect("clicked", on_apply_gradient_clicked)

            base_model = LevelBarDisplayer.get_config_model()
            property_map = {
                "Bar Style": [opt.key for opt in base_model.get("Level Bar Style", [])],
                "Effects": [opt.key for opt in base_model.get("Level Bar Effects", [])],
                "Layout": [opt.key for opt in base_model.get("Labels & Layout", []) if "label" not in opt.key],
                "Primary Label": [opt.key for opt in base_model.get("Labels & Layout", []) if "primary" in opt.key],
                "Secondary Label": [opt.key for opt in base_model.get("Labels & Layout", []) if "secondary" in opt.key],
            }

            def on_apply_same_style_clicked(button):
                bar_count = widgets["number_of_bars"].get_value_as_int()
                source_id_str = source_bar_combo.get_active_id()
                if not source_id_str: return
                source_index = int(source_id_str)
                keys_to_copy = []
                for key, chk in copy_checkboxes.items():
                    if chk.get_active(): keys_to_copy.extend(property_map.get(key, []))
                for i in range(1, bar_count + 1):
                    if i == source_index: continue
                    for key_suffix in keys_to_copy:
                        source_widget = widgets.get(f"bar{source_index}_{key_suffix}")
                        dest_widget = widgets.get(f"bar{i}_{key_suffix}")
                        if source_widget and dest_widget:
                            if isinstance(source_widget, (Gtk.SpinButton, Gtk.Scale)): dest_widget.set_value(source_widget.get_value())
                            elif isinstance(source_widget, Gtk.ColorButton): dest_widget.set_rgba(source_widget.get_rgba())
                            elif isinstance(source_widget, Gtk.FontButton): dest_widget.set_font(source_widget.get_font())
                            elif isinstance(source_widget, Gtk.ComboBoxText): dest_widget.set_active_id(source_widget.get_active_id())
                            elif isinstance(source_widget, Gtk.Switch): dest_widget.set_active(source_widget.get_active())
            apply_style_button.connect("clicked", on_apply_same_style_clicked)

            bar_tabs_content = []
            for i in range(1, 13):
                scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
                tab_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
                scroll.set_child(tab_box)
                style_notebook.append_page(scroll, Gtk.Label(label=f"Style {i}"))
                bar_tabs_content.append(scroll)
                
                prefixed_model = {}
                for section, options in base_model.items():
                    if section in ["Level Bar Range"]: continue
                    prefixed_options = [ConfigOption(f"bar{i}_{opt.key}", opt.type, opt.label, opt.default, opt.min_val, opt.max_val, opt.step, opt.digits, opt.options_dict, opt.tooltip, opt.file_filters) for opt in options]
                    prefixed_model[section] = prefixed_options
                
                populate_defaults_from_model(panel_config, prefixed_model)
                build_ui_from_model(tab_box, panel_config, prefixed_model, widgets)
                dialog.dynamic_models.append(prefixed_model)

            def on_bar_count_changed(spinner):
                count = spinner.get_value_as_int()
                source_bar_combo.remove_all(); grad_start_bar_combo.remove_all(); grad_end_bar_combo.remove_all()
                for i in range(1, count + 1):
                    source_bar_combo.append(id=str(i), text=f"Bar {i}")
                    grad_start_bar_combo.append(id=str(i), text=f"Bar {i}")
                    grad_end_bar_combo.append(id=str(i), text=f"Bar {i}")
                source_bar_combo.set_active(0); grad_start_bar_combo.set_active(0)
                if count > 0: grad_end_bar_combo.set_active(count-1)
                
                for i, content_widget in enumerate(bar_tabs_content):
                    content_widget.set_visible(i < count)

            bar_count_spinner = widgets.get("number_of_bars")
            if bar_count_spinner:
                bar_count_spinner.connect("value-changed", on_bar_count_changed)
                GLib.idle_add(on_bar_count_changed, bar_count_spinner)

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
            bar_height = (height - total_spacing) / num_bars if num_bars > 0 else 0
        else: # horizontal
            bar_width = (width - total_spacing) / num_bars if num_bars > 0 else 0
            bar_height = height

        if bar_width <= 0 or bar_height <= 0: return

        for i in range(1, num_bars + 1):
            bar_key = f"bar{i}"
            source_key = f"{bar_key}_source"
            data_packet = self.data_bundle.get(source_key, {})
            
            drawer_config = {}
            populate_defaults_from_model(drawer_config, LevelBarDisplayer.get_config_model())

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

