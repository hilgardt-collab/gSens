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
                ConfigOption("dashboard_scale_factor", "spinner", "Overall Scale:", 1.0, 0.2, 3.0, 0.05, 2),
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
                ConfigOption(f"satellite_{i}_distance", "spinner", "Placement Distance (px):", 400, 20, 2000, 10, 0),
            ]

        return model

    def get_configure_callback(self):
        """Builds the comprehensive UI for the Display tab."""
        def build_display_ui(dialog, content_box, widgets, available_sources, panel_config):
            
            full_model = self._get_full_config_model()
            main_notebook = Gtk.Notebook(vexpand=True)
            content_box.append(main_notebook)

            # --- Tab 1: Layout ---
            layout_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
            layout_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
            layout_scroll.set_child(layout_box)
            layout_model = {"Layout": full_model["Layout"]}
            build_ui_from_model(layout_box, panel_config, layout_model, widgets)
            dialog.dynamic_models.append(layout_model)
            main_notebook.append_page(layout_scroll, Gtk.Label(label="Layout"))
            
            # --- Simplified UI builder for a single item's style ---
            def build_style_ui_for_item(parent_box, item_prefix):
                # Clear previous UI
                child = parent_box.get_first_child()
                while child:
                    parent_box.remove(child)
                    child = parent_box.get_first_child()

                # Get the currently selected displayer type for this item
                display_type_key = f"{item_prefix}_display_as"
                display_as = widgets.get(display_type_key).get_active_id()
                drawer_instance = self._drawers.get(display_as)
                if not drawer_instance: return
                
                # Build the model with the correct prefixes
                sub_model = {}
                drawer_model = drawer_instance.get_config_model()
                for s_title, s_opts in drawer_model.items():
                    prefixed_opts = []
                    for opt in s_opts:
                        new_key = f"{item_prefix}_{opt.key}"
                        new_dynamic_group = f"{item_prefix}_{opt.dynamic_group}" if opt.dynamic_group else None
                        prefixed_opts.append(ConfigOption(
                            new_key, opt.type, opt.label, opt.default, 
                            opt.min_val, opt.max_val, opt.step, opt.digits, 
                            opt.options_dict, opt.tooltip, opt.file_filters,
                            dynamic_group=new_dynamic_group, dynamic_show_on=opt.dynamic_show_on
                        ))
                    sub_model[s_title] = prefixed_opts
                
                # Build the main style UI
                build_ui_from_model(parent_box, panel_config, sub_model, widgets)
                dialog.dynamic_models.append(sub_model)
                
                # Build the background style UI with a fully unique prefix
                bg_prefixes = drawer_instance.get_config_key_prefixes()
                if bg_prefixes:
                    full_bg_prefix = f"{item_prefix}_{bg_prefixes[0]}"
                    build_background_config_ui(parent_box, panel_config, widgets, dialog, prefix=full_bg_prefix, title=f"Background Style")

                # Call the drawer's own custom callback if it has one
                custom_builder = drawer_instance.get_configure_callback()
                if custom_builder:
                    custom_builder(dialog, parent_box, widgets, available_sources, panel_config, prefix=item_prefix)

            # --- Tab 2: Center Styles ---
            center_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
            center_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
            center_scroll.set_child(center_box)
            center_notebook = Gtk.Notebook()
            center_box.append(center_notebook)
            main_notebook.append_page(center_scroll, Gtk.Label(label="Center Styles"))
            
            for i in range(1, 5):
                item_prefix = f"center_{i}"
                page_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
                page_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
                page_scroll.set_child(page_box)
                center_notebook.append_page(page_scroll, Gtk.Label(label=f"Center {i}"))
                
                # Build static controls (Display As, Width Ratio)
                static_model = {f"Center Display {i} Style": full_model[f"Center Display {i} Style"]}
                build_ui_from_model(page_box, panel_config, static_model, widgets)
                dialog.dynamic_models.append(static_model)
                
                # Create a placeholder for the dynamic style UI
                dynamic_style_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
                page_box.append(dynamic_style_box)
                
                display_as_combo = widgets.get(f"{item_prefix}_display_as")
                display_as_combo.connect("changed", lambda c, p=dynamic_style_box, pf=item_prefix: build_style_ui_for_item(p, pf))
                GLib.idle_add(build_style_ui_for_item, dynamic_style_box, item_prefix)

            # --- Tab 3: Satellite Styles (similar logic) ---
            satellite_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
            satellite_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
            satellite_scroll.set_child(satellite_box)
            satellite_notebook = Gtk.Notebook()
            satellite_box.append(satellite_notebook)
            main_notebook.append_page(satellite_scroll, Gtk.Label(label="Satellites"))

            for i in range(1, 13):
                item_prefix = f"satellite_{i}"
                page_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
                page_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
                page_scroll.set_child(page_box)
                satellite_notebook.append_page(page_scroll, Gtk.Label(label=f"Satellite {i}"))

                static_model = {
                    f"Satellite {i} Style": full_model[f"Satellite {i} Style"],
                    f"Satellite {i} Placement": full_model[f"Satellite {i} Placement"]
                }
                build_ui_from_model(page_box, panel_config, static_model, widgets)
                dialog.dynamic_models.append(static_model)

                dynamic_style_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
                page_box.append(dynamic_style_box)

                display_as_combo = widgets.get(f"{item_prefix}_display_as")
                display_as_combo.connect("changed", lambda c, p=dynamic_style_box, pf=item_prefix: build_style_ui_for_item(p, pf))
                GLib.idle_add(build_style_ui_for_item, dynamic_style_box, item_prefix)

        return build_display_ui

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
            
            # Populate with the base defaults for that drawer type
            drawer_model = drawer.get_config_model()
            populate_defaults_from_model(instance_config, drawer_model)
            
            # Populate with the defaults for any background options it might have
            bg_prefixes = drawer.get_config_key_prefixes()
            if bg_prefixes:
                full_bg_prefix = f"{prefix}_{bg_prefixes[0]}"
                # Create a temporary model with the full prefix to get defaults
                temp_model = get_background_config_model(full_bg_prefix)
                # Populate the instance_config, but strip the main prefix
                for section in temp_model.values():
                    for opt in section:
                        unprefixed_key = opt.key.replace(f"{prefix}_", "")
                        instance_config.setdefault(unprefixed_key, opt.default)

            # Override defaults with specific values from the main config
            for key, value in self.config.items():
                if key.startswith(f"{prefix}_"):
                    unprefixed_key = key[len(prefix) + 1:]
                    instance_config[unprefixed_key] = value
            
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
            distance_pixels = float(self.config.get(f"{prefix}_distance", 400))
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

