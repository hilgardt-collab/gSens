# /data_displayers/lcars_combo.py
import gi
import time
from .combo_base import ComboBase
from utils import populate_defaults_from_model
from .level_bar import LevelBarDisplayer
from .graph import GraphDisplayer
from .static import StaticDisplayer
from .cpu_multicore import CpuMultiCoreDisplayer
from .lcars_config_helpers import get_full_config_model, build_display_ui_impl
from .lcars_draw import LcarsDrawMixin

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib

class LCARSComboDisplayer(ComboBase, LcarsDrawMixin):
    """
    A displayer that renders multiple data sources in the iconic LCARS style,
    featuring a highly configurable frame and a main content area.
    """
    def __init__(self, panel_ref, config):
        # Use a dictionary to hold unique instances for each slot
        self._drawer_instances = {}
        
        self._drawer_classes = {
            "level_bar": LevelBarDisplayer,
            "graph": GraphDisplayer,
            "static": StaticDisplayer,
            "cpu_multicore": CpuMultiCoreDisplayer
        }
        
        self._cached_primary_image = None
        self._cached_primary_image_path = None
        
        self._animation_timer_id = None
        
        # State for internal LCARS bars (simple rects)
        self._bar_values = {}
        
        # Text overlay data for graphs
        self._text_overlay_lines = {}

        # Caching for Pango Layouts
        self._static_layout_cache = {}

        super().__init__(panel_ref, config)
        populate_defaults_from_model(self.config, get_full_config_model())
        
        self.widget.connect("realize", self._start_animation_timer)
        self.widget.connect("unrealize", self._stop_animation_timer)

    @property
    def panel_ref(self):
        return self._panel_ref

    @panel_ref.setter
    def panel_ref(self, value):
        self._panel_ref = value
        for drawer in self._drawer_instances.values():
            drawer.panel_ref = value
        
    @staticmethod
    def get_config_model():
        return {}

    def get_configure_callback(self):
        """Builds the comprehensive UI for the Display tab."""
        return build_display_ui_impl

    def _ensure_drawers(self):
        """
        Ensures that for every active primary/secondary slot, a unique
        displayer instance of the correct type exists in self._drawer_instances.
        """
        num_primary = int(self.config.get("number_of_primary_sources", 1))
        num_secondary = int(self.config.get("number_of_secondary_sources", 4))
        
        needed_slots = []
        for i in range(1, num_primary + 1): needed_slots.append(f"primary{i}")
        for i in range(1, num_secondary + 1): needed_slots.append(f"secondary{i}")
        
        # 1. Cleanup unused slots
        existing_keys = list(self._drawer_instances.keys())
        for key in existing_keys:
            if key not in needed_slots:
                self._drawer_instances[key].close()
                del self._drawer_instances[key]
        
        # 2. Update/Create needed slots
        for slot in needed_slots:
            display_as = self.config.get(f"{slot}_display_as", "bar")
            
            # Skip simple types that don't need a drawer class
            if display_as in ["bar", "text"]:
                if slot in self._drawer_instances:
                    self._drawer_instances[slot].close()
                    del self._drawer_instances[slot]
                continue
            
            TargetClass = self._drawer_classes.get(display_as)
            if not TargetClass: continue
            
            # Check existing instance
            existing = self._drawer_instances.get(slot)
            if existing:
                if not isinstance(existing, TargetClass):
                    existing.close()
                    self._drawer_instances[slot] = TargetClass(self.panel_ref, self.config.copy())
                    if isinstance(self._drawer_instances[slot], GraphDisplayer):
                        self._drawer_instances[slot].is_drawer = True
                    # FIX: Force realization check to pass for embedded drawers
                    if hasattr(self._drawer_instances[slot], 'widget'):
                        self._drawer_instances[slot].widget.get_realized = lambda: True
            else:
                self._drawer_instances[slot] = TargetClass(self.panel_ref, self.config.copy())
                if isinstance(self._drawer_instances[slot], GraphDisplayer):
                    self._drawer_instances[slot].is_drawer = True
                # FIX: Force realization check to pass for embedded drawers
                if hasattr(self._drawer_instances[slot], 'widget'):
                    self._drawer_instances[slot].widget.get_realized = lambda: True

    def _update_drawer_configs(self):
        """Updates configuration for all active drawer instances."""
        for slot, drawer in self._drawer_instances.items():
            instance_config = self.config.copy()
            prefix = f"{slot}_"
            
            # Extract prefix-specific config
            for key, value in self.config.items():
                if key.startswith(prefix):
                    unprefixed_key = key[len(prefix):]
                    instance_config[unprefixed_key] = value
            
            drawer.config = instance_config
            drawer.apply_styles()
            
            # Force update for multi-core to recalculate layout targets if needed
            if isinstance(drawer, CpuMultiCoreDisplayer):
                 drawer._core_currents = [] 

    def apply_styles(self):
        super().apply_styles()
        self._static_layout_cache.clear()
        
        self._ensure_drawers()
        self._update_drawer_configs()
        
        self.widget.queue_draw()

    def update_display(self, value):
        super().update_display(value) 
        
        num_primary = int(self.config.get("number_of_primary_sources", 1))
        num_secondary = int(self.config.get("number_of_secondary_sources", 4))
        
        all_prefixes = [f"primary{i}" for i in range(1, num_primary + 1)] + \
                       [f"secondary{i}" for i in range(1, num_secondary + 1)]
        
        if "primary1_source" not in self.data_bundle and "primary_source" in self.data_bundle:
            self.data_bundle["primary1_source"] = self.data_bundle["primary_source"]

        for prefix in all_prefixes:
            source_key = f"{prefix}_source"
            data_packet = self.data_bundle.get(source_key, {})
            
            # 1. Update Manual Animation State (for simple Bars)
            bar_anim_key = f"{prefix}_bar"
            if bar_anim_key not in self._bar_values:
                self._bar_values[bar_anim_key] = {'current': 0.0, 'target': 0.0, 'first_update': True}

            num_val = data_packet.get('numerical_value')
            percent_val = 0.0
            if isinstance(num_val, (int, float)):
                min_v = data_packet.get('min_value', 0.0)
                max_v = data_packet.get('max_value', 100.0)
                v_range = max_v - min_v if max_v > min_v else 1
                percent_val = (min(max(num_val, min_v), max_v) - min_v) / v_range if v_range > 0 else 0.0
            
            if self._bar_values[bar_anim_key]['first_update']:
                self._bar_values[bar_anim_key]['current'] = percent_val
                self._bar_values[bar_anim_key]['first_update'] = False
            self._bar_values[bar_anim_key]['target'] = percent_val
            
            # 2. Update Drawer Instance (if exists)
            drawer = self._drawer_instances.get(prefix)
            if drawer:
                # Pass min/max from data source
                if 'min_value' in data_packet: drawer.config['graph_min_value'] = data_packet['min_value']
                if 'max_value' in data_packet: drawer.config['graph_max_value'] = data_packet['max_value']
                
                child_source = self.panel_ref.data_source.child_sources.get(source_key) if self.panel_ref else None
                caption = self.config.get(f"{prefix}_caption") or data_packet.get('primary_label', '')
                
                drawer.update_display(data_packet.get('raw_data'), source_override=child_source, caption=caption)

            # 3. Update Text Overlay Lines (for Graphs specifically)
            display_as = self.config.get(f"{prefix}_display_as", "bar")
            text_overlay_enabled = str(self.config.get(f"{prefix}_text_overlay_enabled", "False")).lower() == 'true'
            
            if display_as == "graph" and text_overlay_enabled:
                line_count = int(self.config.get(f"{prefix}_text_line_count", 2))
                self._text_overlay_lines[prefix] = []
                
                child_source = self.panel_ref.data_source.child_sources.get(source_key) if self.panel_ref else None
                
                for i in range(line_count):
                    line_num = i + 1
                    source_type = self.config.get(f"{prefix}_line{line_num}_source", "display_string")
                    text = "N/A"
                    if child_source and data_packet:
                        if source_type == "primary_label": text = child_source.get_primary_label_string(data_packet.get('raw_data'))
                        elif source_type == "secondary_label": text = child_source.get_secondary_display_string(data_packet.get('raw_data'))
                        elif source_type == "tooltip_string": text = child_source.get_tooltip_string(data_packet.get('raw_data'))
                        elif source_type == "custom_text": text = self.config.get(f"{prefix}_line{line_num}_custom_text", "")
                        else: text = child_source.get_display_string(data_packet.get('raw_data'))
                    self._text_overlay_lines[prefix].append(text or "")

    def _start_animation_timer(self, widget=None):
        self._stop_animation_timer(); self._animation_timer_id = GLib.timeout_add(16, self._animation_tick)
    def _stop_animation_timer(self, widget=None):
        if self._animation_timer_id is not None: GLib.source_remove(self._animation_timer_id); self._animation_timer_id = None

    def _animation_tick(self):
        if not self.widget.get_realized(): return GLib.SOURCE_REMOVE

        # Tick manual animations
        animation_enabled = str(self.config.get("lcars_animation_enabled", "True")).lower() == 'true'
        anim_speed = float(self.config.get("lcars_animation_speed", 0.1))
        needs_redraw = False

        for key, values in self._bar_values.items():
            diff = values['target'] - values['current']
            if not animation_enabled:
                if values['current'] != values['target']: values['current'] = values['target']; needs_redraw = True
                continue
            if abs(diff) < 0.001:
                if values['current'] != values['target']: values['current'] = values['target']; needs_redraw = True
            else:
                values['current'] += diff * anim_speed; needs_redraw = True
        
        # Tick child drawers
        for drawer in self._drawer_instances.values():
            if hasattr(drawer, '_animation_tick'):
                drawer._animation_tick()
        
        if needs_redraw or self._drawer_instances:
            self.widget.queue_draw()
            
        return GLib.SOURCE_CONTINUE

    def on_draw(self, area, ctx, width, height):
        if width <= 0 or height <= 0: return
        self._draw_frame_and_sidebar(ctx, width, height)
        self._draw_content_widgets(ctx, width, height)

    def _draw_secondary_graph(self, ctx, x, y, w, h, prefix, data):
        drawer = self._drawer_instances.get(prefix)
        if not drawer: return
        padding = 10
        ctx.save(); ctx.rectangle(x+padding, y, w-2*padding, h); ctx.clip(); ctx.translate(x+padding,y)
        
        lcars_bg_color = self.config.get(f"{prefix}_graph_lcars_bg_color", "rgba(0,0,0,1)")
        drawer.config['graph_bg_color'] = lcars_bg_color
        drawer.config['graph_bg_type'] = 'solid'

        drawer.on_draw(None, ctx, w-2*padding, h)
        
        text_overlay_enabled = str(self.config.get(f"{prefix}_text_overlay_enabled", "False")).lower() == 'true'
        if text_overlay_enabled and prefix in self._text_overlay_lines:
            self._draw_text_overlay(ctx, 0, 0, w-2*padding, h, prefix)
        ctx.restore()

    def close(self):
        """
        Safely stops all animations and closes sub-displayers to prevent leaks.
        """
        self._stop_animation_timer()
        
        # Close all sub-displayer instances
        if self._drawer_instances:
            for drawer in self._drawer_instances.values():
                if hasattr(drawer, 'close'):
                    drawer.close()
            self._drawer_instances.clear()
            
        super().close()
