# /data_displayers/dashboard_combo.py
import gi
import math
import cairo
import os
import time
from .combo_base import ComboBase
from config_dialog import ConfigOption, build_ui_from_model
from utils import populate_defaults_from_model
from .level_bar import LevelBarDisplayer
from .graph import GraphDisplayer
from .speedometer import SpeedometerDisplayer
from .arc_gauge import ArcGaugeDisplayer
from .indicator import IndicatorDisplayer
from .bar import BarDisplayer
from .text import TextDisplayer
from ui_helpers import build_background_config_ui, get_background_config_model

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gdk, GLib, Pango, PangoCairo, GdkPixbuf

class DashboardComboDisplayer(ComboBase):
    """
    A displayer that arranges multiple sub-displayers (gauges, bars, etc.)
    in a configurable dashboard layout.
    """
    def __init__(self, panel_ref, config):
        self._drawers = {
            "speedometer": SpeedometerDisplayer(None, config),
            "arc_gauge": ArcGaugeDisplayer(None, config),
            "bar": BarDisplayer(None, config),
            "level_bar": LevelBarDisplayer(None, config),
            "indicator": IndicatorDisplayer(None, config),
            "graph": GraphDisplayer(None, config),
            "text": TextDisplayer(None, config),
        }
        # Mark drawers that are controlled by this parent
        if self._drawers.get("level_bar"):
            self._drawers["level_bar"].is_drawer = True

        self._animation_timer_id = None
        self._drawer_configs = {}
        self._animation_values = {}

        super().__init__(panel_ref, config)
        populate_defaults_from_model(self.config, self._get_full_config_model())
        
        self.widget.connect("realize", self._start_animation_timer)
        self.widget.connect("unrealize", self._stop_animation_timer)

    @property
    def panel_ref(self):
        return self._panel_ref

    @panel_ref.setter
    def panel_ref(self, value):
        self._panel_ref = value
        for drawer in self._drawers.values():
            if drawer:
                drawer.panel_ref = value
    
    @staticmethod
    def get_config_model():
        return {}
    
    @classmethod
    def _get_full_config_model(cls):
        model = {
            "Layout": [
                ConfigOption("dashboard_center_arrangement", "dropdown", "Center Arrangement:", "horizontal",
                             options_dict={"Horizontal": "horizontal", "Vertical": "vertical", "2x2 Grid": "grid_2x2"}),
                ConfigOption("dashboard_h_translate", "spinner", "Horizontal Translation (px):", 0, -500, 500, 5, 0),
                ConfigOption("dashboard_v_translate", "spinner", "Vertical Translation (px):", 0, -500, 500, 5, 0),
                ConfigOption("dashboard_scale_factor", "scale", "Overall Scale:", 1.0, 0.2, 3.0, 0.05, 2),
            ]
        }
        for i in range(1, 5):
            model[f"Center Display {i} Style"] = [
                ConfigOption(f"center_{i}_display_as", "dropdown", "Display Type:", "speedometer", 
                             options_dict={"Speedometer": "speedometer", "Arc Gauge": "arc_gauge"}),
                ConfigOption(f"center_{i}_width_ratio", "scale", "Width (% of available space):", 1.0, 0.1, 1.0, 0.05, 2),
            ]
        
        sat_display_opts = {
            "Arc Gauge": "arc_gauge", "Speedometer": "speedometer", "Bar": "bar",
            "Level Bar": "level_bar", "Indicator": "indicator", "Graph": "graph", "Text": "text"
        }
        for i in range(1, 13):
            model[f"Satellite {i} Style"] = [
                ConfigOption(f"satellite_{i}_display_as", "dropdown", "Display Type:", "arc_gauge", options_dict=sat_display_opts),
                ConfigOption(f"satellite_{i}_size", "spinner", "Size (px):", 100, 20, 1000, 10, 0),
                ConfigOption(f"satellite_{i}_level_bar_width", "spinner", "Width (px, for Level Bar):", 100, 20, 1000, 10, 0),
                ConfigOption(f"satellite_{i}_level_bar_height", "spinner", "Height (px, for Level Bar):", 100, 20, 1000, 10, 0),
            ]
            model[f"Satellite {i} Placement"] = [
                ConfigOption(f"satellite_{i}_angle", "spinner", "Placement Angle (°):", 180 + (i-1)*20, -360, 360, 5, 0),
                ConfigOption(f"satellite_{i}_distance", "scale", "Placement Distance (%):", 0.7, 0.1, 2.0, 0.05, 2),
            ]

        return model

    def get_configure_callback(self):
        def build_ui(dialog, content_box, widgets, available_sources, panel_config):
            full_model = self._get_full_config_model()
            
            main_notebook = Gtk.Notebook()
            content_box.append(main_notebook)

            layout_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
            layout_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
            layout_scroll.set_child(layout_box)
            layout_model = {"Layout": full_model["Layout"]}
            build_ui_from_model(layout_box, panel_config, layout_model, widgets)
            dialog.dynamic_models.append(layout_model)
            main_notebook.append_page(layout_scroll, Gtk.Label(label="Layout"))

            def setup_dynamic_style_ui(parent_box, prefix, display_type_key):
                display_type_combo = widgets.get(display_type_key)
                if not display_type_combo: return

                style_sections = {}
                for key, drawer_class in self._drawers.items():
                    section_title = f"Style for {key.replace('_', ' ').title()}"
                    style_sections[key] = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
                    
                    sub_model = {}
                    for s_title, s_opts in drawer_class.get_config_model().items():
                        prefixed_opts = [ConfigOption(f"{prefix}_{opt.key}", opt.type, opt.label, opt.default, opt.min_val, opt.max_val, opt.step, opt.digits, opt.options_dict, opt.tooltip, opt.file_filters) for opt in s_opts]
                        sub_model[s_title] = prefixed_opts

                    build_ui_from_model(style_sections[key], panel_config, sub_model, widgets)
                    
                    bg_prefixes = drawer_class.get_config_key_prefixes()
                    if bg_prefixes:
                        full_bg_prefix = f"{prefix}_{bg_prefixes[0]}"
                        build_background_config_ui(style_sections[key], panel_config, widgets, dialog, prefix=full_bg_prefix, title=f"{key.replace('_',' ').title()} Background")
                    
                    dialog.dynamic_models.append(sub_model)
                    parent_box.append(style_sections[key])

                lb_width_widget = widgets.get(f"{prefix}_level_bar_width")
                lb_height_widget = widgets.get(f"{prefix}_level_bar_height")
                size_widget = widgets.get(f"{prefix}_size")

                def on_display_type_changed(combo):
                    active_id = combo.get_active_id()
                    for key, section in style_sections.items():
                        section.set_visible(key == active_id)
                    
                    is_level_bar = active_id == "level_bar"
                    if lb_width_widget: lb_width_widget.get_parent().set_visible(is_level_bar)
                    if lb_height_widget: lb_height_widget.get_parent().set_visible(is_level_bar)
                    if size_widget: size_widget.get_parent().set_visible(not is_level_bar)

                display_type_combo.connect("changed", on_display_type_changed)
                GLib.idle_add(on_display_type_changed, display_type_combo)

            center_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
            center_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
            center_scroll.set_child(center_box)
            center_notebook = Gtk.Notebook()
            center_box.append(center_notebook)
            main_notebook.append_page(center_scroll, Gtk.Label(label="Center Styles"))
            
            center_tabs = []
            for i in range(1, 5):
                page_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
                center_style_model = {f"Center Display {i} Style": full_model[f"Center Display {i} Style"]}
                build_ui_from_model(page_box, panel_config, center_style_model, widgets)
                dialog.dynamic_models.append(center_style_model)
                setup_dynamic_style_ui(page_box, f"center_{i}", f"center_{i}_display_as")
                page_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
                page_scroll.set_child(page_box)
                page_num = center_notebook.append_page(page_scroll, Gtk.Label(label=f"Center {i}"))
                center_tabs.append(center_notebook.get_nth_page(page_num))

            satellite_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
            satellite_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
            satellite_scroll.set_child(satellite_box)
            satellite_notebook = Gtk.Notebook()
            satellite_box.append(satellite_notebook)
            main_notebook.append_page(satellite_scroll, Gtk.Label(label="Satellites"))

            satellite_tabs = []
            for i in range(1, 13):
                page_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
                sat_model = {
                    f"Satellite {i} Style": full_model[f"Satellite {i} Style"],
                    f"Satellite {i} Placement": full_model[f"Satellite {i} Placement"]
                }
                build_ui_from_model(page_box, panel_config, sat_model, widgets)
                dialog.dynamic_models.append(sat_model)
                setup_dynamic_style_ui(page_box, f"satellite_{i}", f"satellite_{i}_display_as")
                page_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
                page_scroll.set_child(page_box)
                page_num = satellite_notebook.append_page(page_scroll, Gtk.Label(label=f"Satellite {i}"))
                satellite_tabs.append(satellite_notebook.get_nth_page(page_num))

            def update_tab_visibility():
                center_count = int(panel_config.get("dashboard_center_count", 1))
                for i, tab in enumerate(center_tabs):
                    tab.set_visible(i < center_count)
                sat_count = int(panel_config.get("dashboard_satellite_count", 4))
                for i, tab in enumerate(satellite_tabs):
                    tab.set_visible(i < sat_count)

            if hasattr(dialog, 'apply_button') and dialog.apply_button:
                dialog.apply_button.connect("clicked", lambda w: GLib.idle_add(update_tab_visibility))
            
            GLib.idle_add(update_tab_visibility)
            
        return build_ui

    def _update_drawer_configs(self):
        """
        Builds and caches a specific configuration dictionary for each component.
        This runs only when styles are applied, not on every draw call.
        """
        self._drawer_configs.clear()
        all_prefixes = [f"center_{i}" for i in range(1, 5)] + [f"satellite_{i}" for i in range(1, 13)]
        
        for prefix in all_prefixes:
            display_as = self.config.get(f"{prefix}_display_as")
            drawer = self._drawers.get(display_as)
            if not drawer: continue

            instance_config = {}
            
            drawer_model = drawer.get_config_model()
            populate_defaults_from_model(instance_config, drawer_model)
            
            bg_prefixes = drawer.get_config_key_prefixes()
            if bg_prefixes:
                full_bg_prefix = f"{prefix}_{bg_prefixes[0]}"
                bg_model = get_background_config_model(full_bg_prefix)
                populate_defaults_from_model(instance_config, bg_model)

            for section in drawer_model.values():
                for option in section:
                    prefixed_key = f"{prefix}_{option.key}"
                    if prefixed_key in self.config:
                        instance_config[option.key] = self.config[prefixed_key]
            
            if bg_prefixes:
                full_bg_prefix = f"{prefix}_{bg_prefixes[0]}"
                bg_model = get_background_config_model(full_bg_prefix)
                for section in bg_model.values():
                    for option in section:
                        if option.key in self.config:
                            instance_config[option.key] = self.config[option.key]
            
            self._drawer_configs[prefix] = instance_config

    def apply_styles(self):
        super().apply_styles()
        self._update_drawer_configs()
        self.widget.queue_draw()

    def update_display(self, value):
        super().update_display(value)
        if not isinstance(value, dict) or not self.panel_ref: return

        all_prefixes = [f"center_{i}" for i in range(1,5)] + [f"satellite_{i}" for i in range(1,13)]
        for prefix in all_prefixes:
            source_key = f"{prefix}_source"
            data_packet = self.data_bundle.get(source_key, {})
            num_val = data_packet.get('numerical_value', 0.0) or 0.0
            
            if prefix not in self._animation_values:
                self._animation_values[prefix] = {'current': num_val, 'target': num_val, 'current_level': 0, 'target_level': 0}
            
            self._animation_values[prefix]['target'] = num_val
            
            display_as = self.config.get(f"{prefix}_display_as")
            if display_as == "level_bar":
                drawer_config = self._drawer_configs.get(prefix, {})
                num_segments = int(drawer_config.get("level_bar_segment_count", 30))
                min_v = float(data_packet.get('min_value', 0.0))
                max_v = float(data_packet.get('max_value', 100.0))
                v_range = max_v - min_v if max_v > min_v else 1
                target_level = int(round(((min(max(num_val, min_v), max_v) - min_v) / v_range) * num_segments))
                self._animation_values[prefix]['target_level'] = target_level

    def on_draw(self, area, ctx, width, height):
        width, height = int(width), int(height)
        if width <= 0 or height <= 0: return
        
        scale = float(self.config.get("dashboard_scale_factor", 1.0))
        h_trans = float(self.config.get("dashboard_h_translate", 0.0))
        v_trans = float(self.config.get("dashboard_v_translate", 0.0))

        ctx.save()
        ctx.translate(width/2 + h_trans, height/2 + v_trans)
        ctx.scale(scale, scale)
        ctx.translate(-width/2, -height/2)

        center_positions = self._calculate_center_positions(width, height)
        satellite_positions = self._calculate_satellite_positions(width, height, center_positions)
        
        for prefix, pos in center_positions.items():
            self._draw_sub_display(ctx, pos['x'], pos['y'], pos['w'], pos['h'], prefix, self.data_bundle)

        for prefix, pos in satellite_positions.items():
            self._draw_sub_display(ctx, pos['x'], pos['y'], pos['w'], pos['h'], prefix, self.data_bundle)
            
        ctx.restore()

    def _calculate_center_positions(self, width, height):
        positions = {}
        count = int(self.config.get("dashboard_center_count", 1))
        arrangement = self.config.get("dashboard_center_arrangement", "horizontal")

        items = []
        for i in range(1, count + 1):
            items.append({'prefix': f"center_{i}", 'w_ratio': float(self.config.get(f"center_{i}_width_ratio", 1.0))})
        
        if arrangement == "grid_2x2" and count > 1:
            rows, cols = (2, 2) if count > 2 else (1, count)
            cell_w, cell_h = width / cols, height / rows
            for i, item in enumerate(items):
                row, col = divmod(i, cols)
                item_w = cell_w * item['w_ratio']
                item_h = cell_h * item['w_ratio']
                positions[item['prefix']] = {'x': col * cell_w + (cell_w - item_w)/2, 'y': row * cell_h + (cell_h - item_h)/2, 'w': item_w, 'h': item_h}
        elif arrangement == "vertical" and count > 1:
            cell_h = height / count
            for i, item in enumerate(items):
                item_h = cell_h * item['w_ratio']
                item_w = item_h 
                positions[item['prefix']] = {'x': (width - item_w)/2, 'y': i * cell_h + (cell_h - item_h)/2, 'w': item_w, 'h': item_h}
        else: # Horizontal default
            cell_w = width / count
            for i, item in enumerate(items):
                item_w = cell_w * item['w_ratio']
                item_h = item_w 
                positions[item['prefix']] = {'x': i * cell_w + (cell_w - item_w)/2, 'y': (height - item_h)/2, 'w': item_w, 'h': item_h}

        return positions

    def _calculate_satellite_positions(self, width, height, center_positions):
        positions = {}
        count = int(self.config.get("dashboard_satellite_count", 4))
        if count == 0 or not center_positions: return {}
        
        avg_center_x = sum(p['x'] + p['w']/2 for p in center_positions.values()) / len(center_positions)
        avg_center_y = sum(p['y'] + p['h']/2 for p in center_positions.values()) / len(center_positions)
        
        for i in range(1, count + 1):
            prefix = f"satellite_{i}"
            display_as = self.config.get(f"{prefix}_display_as")
            if display_as == "level_bar":
                size_w = float(self.config.get(f"{prefix}_level_bar_width", 100))
                size_h = float(self.config.get(f"{prefix}_level_bar_height", 100))
            else:
                size_w = float(self.config.get(f"{prefix}_size", 100))
                size_h = size_w

            angle_deg = float(self.config.get(f"{prefix}_angle", 180))
            distance_percent = float(self.config.get(f"{prefix}_distance", 0.7))
            distance_pixels = distance_percent * min(width, height) / 2
            angle_rad = math.radians(angle_deg)
            x = avg_center_x + math.cos(angle_rad) * distance_pixels - size_w/2
            y = avg_center_y + math.sin(angle_rad) * distance_pixels - size_h/2
            positions[prefix] = {'x': x, 'y': y, 'w': size_w, 'h': size_h}
        return positions

    def _draw_sub_display(self, ctx, x, y, w, h, prefix, data_bundle):
        display_as = self.config.get(f"{prefix}_display_as")
        drawer = self._drawers.get(display_as)
        if not drawer: return

        drawer.config = self._drawer_configs.get(prefix, {})
        
        source_key = f"{prefix}_source"
        data_packet = data_bundle.get(source_key, {})
        child_source_instance = self.panel_ref.data_source.child_sources.get(source_key)
        caption_text = self.config.get(f"bar{prefix.split('_')[1]}_caption") or data_packet.get('primary_label', '')
        
        drawer.config['graph_min_value'] = data_packet.get('min_value', drawer.config.get('graph_min_value', 0.0))
        drawer.config['graph_max_value'] = data_packet.get('max_value', drawer.config.get('graph_max_value', 100.0))
        
        drawer.apply_styles()

        anim_state = self._animation_values.get(prefix, {})
        drawer._current_display_value = anim_state.get('current', 0.0)
        
        if display_as == "level_bar":
            drawer.current_on_level = anim_state.get('current_level', 0)

        drawer.update_display(data_packet.get('raw_data'), source_override=child_source_instance, caption=caption_text)
        
        ctx.save()
        ctx.translate(x, y)
        drawer.on_draw(None, ctx, w, h)
        ctx.restore()

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
        
        needs_redraw = False
        for prefix, values in self._animation_values.items():
            diff = values['target'] - values['current']
            if abs(diff) < 0.01:
                if values['current'] != values['target']:
                    values['current'] = values['target']; needs_redraw = True
            else:
                values['current'] += diff * 0.1; needs_redraw = True
            
            level_diff = values.get('target_level', 0) - values.get('current_level', 0)
            if level_diff > 0:
                values['current_level'] += 1; needs_redraw = True
            elif level_diff < 0:
                values['current_level'] = values['target_level']; needs_redraw = True

        if needs_redraw:
            self.widget.queue_draw()
        return GLib.SOURCE_CONTINUE

    def close(self):
        self._stop_animation_timer()
        for drawer in self._drawers.values():
            if drawer:
                drawer.close()
        self._drawers.clear()
        super().close()

