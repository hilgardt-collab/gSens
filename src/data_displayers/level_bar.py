# /data_displayers/level_bar.py
import gi
import time
import re
import math
import cairo
from data_displayer import DataDisplayer
from config_dialog import ConfigOption, build_ui_from_model
from utils import populate_defaults_from_model

gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gtk, Gdk, GLib, Pango, PangoCairo

class LevelBarDisplayer(DataDisplayer):
    """
    A highly configurable data displayer that shows a value as a custom-drawn,
    segmented bar with fully positionable, Cairo-drawn text labels.
    """
    def __init__(self, panel_ref, config):
        self.current_value, self.segment_states = 0.0, []
        self._animation_timer_id, self._last_segment_count = None, 0
        self.current_on_level, self.target_on_level = 0, 0
        
        # Caching State for performance optimization
        self._static_surface = None
        self._last_draw_width, self._last_draw_height = -1, -1
        
        self.primary_text = ""
        self.secondary_text = ""

        super().__init__(panel_ref, config)
        populate_defaults_from_model(self.config, self.get_config_model())
        self.widget.connect("realize", self._start_animation_timer)
        self.widget.connect("unrealize", self._stop_animation_timer)

    def _create_widget(self):
        self.drawing_area = Gtk.DrawingArea(vexpand=True, hexpand=True)
        self.drawing_area.set_draw_func(self.on_draw)
        return self.drawing_area

    def _start_animation_timer(self, widget=None):
        self._stop_animation_timer()
        fill_speed_ms = int(self.config.get("level_bar_fill_speed_ms", 15))
        self._animation_timer_id = GLib.timeout_add(fill_speed_ms, self._animation_tick)

    def _stop_animation_timer(self, widget=None):
        if self._animation_timer_id is not None:
            GLib.source_remove(self._animation_timer_id)
            self._animation_timer_id = None

    def _animation_tick(self):
        if not self.widget.get_realized():
            self._animation_timer_id = None
            return GLib.SOURCE_REMOVE
        
        needs_redraw = False
        
        if self.current_on_level < self.target_on_level:
            self.current_on_level += 1
            if self.current_on_level -1 < len(self.segment_states):
                 self.segment_states[self.current_on_level - 1]['is_on'] = True
            needs_redraw = True
        elif self.current_on_level > self.target_on_level:
             self.current_on_level = self.target_on_level
             needs_redraw = True

        if not needs_redraw:
            fade_enabled = str(self.config.get("level_bar_fade_enabled", "True")).lower() == 'true'
            pulse_enabled = str(self.config.get("level_bar_on_pulse_enabled", "False")).lower() == 'true'
            
            if pulse_enabled and self.current_on_level > 0:
                needs_redraw = True
            elif fade_enabled:
                now = time.monotonic()
                fade_duration_s = float(self.config.get("level_bar_fade_duration_ms", 500))/1000.0
                if any(not s['is_on'] and s['off_timestamp'] > 0 and (now - s['off_timestamp']) < fade_duration_s for s in self.segment_states):
                    needs_redraw = True
        
        if needs_redraw:
            self.widget.queue_draw()
            
        return GLib.SOURCE_CONTINUE

    def update_display(self, value):
        if self.panel_ref is None: return

        self._sync_state_with_config()

        self.current_value = self.panel_ref.data_source.get_numerical_value(value) or 0.0
        
        self.primary_text = self.panel_ref.data_source.get_primary_label_string(value)
        self.secondary_text = self.panel_ref.data_source.get_display_string(value)

        num_segments = int(self.config.get("level_bar_segment_count", 30))
        min_v, max_v = float(self.config.get("level_min_value", 0)), float(self.config.get("level_max_value", 100))
        v_range = max_v - min_v if max_v > min_v else 1
        self.target_on_level = int(round(((min(max(self.current_value, min_v), max_v) - min_v) / v_range) * num_segments))
        now = time.monotonic()
        for i in range(num_segments):
            if i < len(self.segment_states):
                if i >= self.target_on_level and self.segment_states[i]['is_on']:
                    self.segment_states[i]['is_on'] = False
                    self.segment_states[i]['off_timestamp'] = now
        
        self.panel_ref.set_tooltip_text(self.panel_ref.data_source.get_tooltip_string(value))

    @staticmethod
    def get_config_model():
        model = DataDisplayer.get_config_model()
        align_opts = {"Left": "left", "Center": "center", "Right": "right"}
        super_align_opts = {
            "Top Left": "top_left", "Top Center": "top_center", "Top Right": "top_right",
            "Middle Left": "middle_left", "Middle Center": "middle_center", "Middle Right": "middle_right",
            "Bottom Left": "bottom_left", "Bottom Center": "bottom_center", "Bottom Right": "bottom_right"
        }
        model["Level Bar Range"] = [ConfigOption("level_min_value", "spinner", "Min Value:", 0, -10000, 10000, 1, 1), ConfigOption("level_max_value", "spinner", "Max Value:", 100, -10000, 10000, 1, 1)]
        model["Level Bar Style"] = [ 
            ConfigOption("level_bar_orientation", "dropdown", "Orientation:", "vertical", options_dict={"Vertical": "vertical", "Horizontal": "horizontal"}), 
            ConfigOption("level_bar_background_color", "color", "Background Color:", "rgba(20,30,50,1)"), 
            ConfigOption("level_bar_on_color", "color", "Start 'On' Color:", "rgba(170,220,255,1)"), 
            ConfigOption("level_bar_off_color", "color", "Segment 'Off' Color:", "rgba(40,60,80,1)"), 
            ConfigOption("level_bar_segment_count", "spinner", "Number of Segments:", 30, 5, 100, 1, 0), 
            ConfigOption("level_bar_spacing", "spinner", "Segment Spacing (px):", 2, 0, 10, 1, 0),
            ConfigOption("level_bar_slant_px", "spinner", "Segment Slant (px):", 0, -50, 50, 1, 0)
        ]
        model["Level Bar Effects"] = [ 
            ConfigOption("level_bar_fill_speed_ms", "spinner", "Fill Speed (ms/bar):", 15, 1, 100, 1, 0),
            ConfigOption("level_bar_fade_enabled", "bool", "Enable 'Off' Fade Out:", "True"), 
            ConfigOption("level_bar_fade_duration_ms", "spinner", "'Off' Fade Duration (ms):", 500, 50, 2000, 50, 0),
            ConfigOption("level_bar_on_gradient_enabled", "bool", "Enable 'On' Color Gradient:", "False"),
            ConfigOption("level_bar_gradient_mode", "dropdown", "Gradient Mode:", "full", 
                         options_dict={"Over Full Bar": "full", "Over Active Segments": "active"}),
            ConfigOption("level_bar_on_color2", "color", "End 'On' Color:", "rgba(255,255,0,1)"),
            ConfigOption("level_bar_on_pulse_enabled", "bool", "Enable 'On' Color Pulse:", "False"),
            ConfigOption("level_bar_on_pulse_color1", "color", "Pulse Start Color:", "rgba(170,220,255,1)"),
            ConfigOption("level_bar_on_pulse_color2", "color", "Pulse End Color:", "rgba(255,255,255,1)"),
            ConfigOption("level_bar_on_pulse_duration_ms", "spinner", "Pulse Duration (ms):", 1000, 100, 5000, 100, 0)
        ]
        model["Labels & Layout"] = [
            ConfigOption("level_bar_text_layout", "dropdown", "Text Layout:", "superimposed", 
                         options_dict={"Superimposed": "superimposed", "Top": "top", "Bottom": "bottom", "Left": "left", "Right": "right"}),
            ConfigOption("level_bar_split_ratio", "scale", "Text/Bar Split Ratio:", "0.3", 0.1, 0.9, 0.05, 2,
                         tooltip="Proportion of space for text when not superimposed."),
            ConfigOption("level_bar_label_orientation", "dropdown", "Label Orientation:", "vertical", options_dict={"Vertical": "vertical", "Horizontal": "horizontal"}),
            ConfigOption("level_bar_superimposed_align", "dropdown", "Superimposed Align:", "middle_center", options_dict=super_align_opts),
            ConfigOption("level_bar_show_primary_label", "bool", "Show Primary Label:", "True"),
            ConfigOption("level_bar_primary_align", "dropdown", "Primary Text Align:", "center", options_dict=align_opts),
            ConfigOption("level_bar_primary_font", "font", "Primary Font:", "Sans Italic 9"),
            ConfigOption("level_bar_primary_color", "color", "Primary Color:", "rgba(200,200,200,1)"),
            ConfigOption("level_bar_show_secondary_label", "bool", "Show Secondary Label:", "True"),
            ConfigOption("level_bar_secondary_align", "dropdown", "Secondary Text Align:", "center", options_dict=align_opts),
            ConfigOption("level_bar_secondary_font", "font", "Secondary Font:", "Sans 10"),
            ConfigOption("level_bar_secondary_color", "color", "Secondary Color:", "rgba(220,220,220,1)")
        ]
        return model

    def get_configure_callback(self):
        """A custom callback to dynamically show/hide effect-specific and layout-specific options."""
        def setup_dynamic_options(dialog, content_box, widgets, available_sources, panel_config):
            try:
                grad_switch = widgets["level_bar_on_gradient_enabled"]
                pulse_switch = widgets["level_bar_on_pulse_enabled"]
                layout_combo = widgets["level_bar_text_layout"]
                split_ratio_scale = widgets["level_bar_split_ratio"]
                grad_end_color = widgets["level_bar_on_color2"].get_parent()
                grad_mode_combo = widgets["level_bar_gradient_mode"].get_parent()
                pulse_start_color = widgets["level_bar_on_pulse_color1"].get_parent()
                pulse_end_color = widgets["level_bar_on_pulse_color2"].get_parent()
                pulse_duration = widgets["level_bar_on_pulse_duration_ms"].get_parent()
            except KeyError:
                return

            def update_visibility(*args):
                is_grad = grad_switch.get_active()
                is_pulse = pulse_switch.get_active()
                grad_end_color.set_visible(is_grad)
                grad_mode_combo.set_visible(is_grad)
                pulse_start_color.set_visible(is_pulse)
                pulse_end_color.set_visible(is_pulse)
                pulse_duration.set_visible(is_pulse)
                
                is_superimposed = layout_combo.get_active_id() == "superimposed"
                split_ratio_scale.get_parent().set_visible(not is_superimposed)

            grad_switch.connect("notify::active", update_visibility)
            pulse_switch.connect("notify::active", update_visibility)
            layout_combo.connect("changed", update_visibility)
            GLib.idle_add(update_visibility)

        return setup_dynamic_options

    def _sync_state_with_config(self):
        """Ensures internal state like segment_states matches the current config."""
        num_segments = int(self.config.get("level_bar_segment_count", 30))
        if self._last_segment_count != num_segments:
            self.segment_states = [{'is_on': False, 'off_timestamp': 0} for _ in range(num_segments)]
            self._last_segment_count = num_segments

    def apply_styles(self):
        super().apply_styles()
        self._sync_state_with_config()
        
        # Invalidate the cache whenever styles change to apply new geometry/colors
        self._static_surface = None
        
        if self.widget.get_realized(): self._start_animation_timer()
        self.widget.queue_draw()

    def on_draw(self, area, ctx, width, height):
        if width <= 0 or height <= 0: return
        
        layout = self.config.get("level_bar_text_layout", "superimposed")

        if layout == "superimposed":
            self.draw_bar(ctx, 0, 0, width, height)
            
            show_primary = str(self.config.get("level_bar_show_primary_label", "True")).lower() == 'true'
            show_secondary = str(self.config.get("level_bar_show_secondary_label", "True")).lower() == 'true'
            layout_p = PangoCairo.create_layout(ctx) if show_primary else None
            layout_s = PangoCairo.create_layout(ctx) if show_secondary else None
            
            if layout_p:
                layout_p.set_font_description(Pango.FontDescription.from_string(self.config.get("level_bar_primary_font")))
                layout_p.set_text(self.primary_text or "", -1)
            if layout_s:
                layout_s.set_font_description(Pango.FontDescription.from_string(self.config.get("level_bar_secondary_font")))
                layout_s.set_text(self.secondary_text or "", -1)
            
            self._draw_superimposed_text(ctx, 0, 0, width, height, layout_p, layout_s)
        else:
            ratio = float(self.config.get("level_bar_split_ratio", 0.3))
            spacing = 4
            
            if layout in ["top", "bottom"]:
                text_h = (height * ratio) - (spacing / 2)
                bar_h = height * (1 - ratio) - (spacing / 2)
                text_w, bar_w = width, width
                bar_x, text_x = 0, 0
                if layout == "top":
                    text_y, bar_y = 0, text_h + spacing
                else: # bottom
                    bar_y, text_y = 0, bar_h + spacing
            else: # left, right
                text_w = (width * ratio) - (spacing / 2)
                bar_w = width * (1 - ratio) - (spacing / 2)
                text_h, bar_h = height, height
                bar_y, text_y = 0, 0
                if layout == "left":
                    text_x, bar_x = 0, text_w + spacing
                else: # right
                    bar_x, text_x = 0, bar_w + spacing

            self.draw_bar(ctx, bar_x, bar_y, bar_w, bar_h)
            
            show_primary = str(self.config.get("level_bar_show_primary_label", "True")).lower() == 'true'
            show_secondary = str(self.config.get("level_bar_show_secondary_label", "True")).lower() == 'true'
            layout_p = PangoCairo.create_layout(ctx) if show_primary else None
            layout_s = PangoCairo.create_layout(ctx) if show_secondary else None
            
            if layout_p:
                layout_p.set_font_description(Pango.FontDescription.from_string(self.config.get("level_bar_primary_font")))
                layout_p.set_text(self.primary_text or "", -1)
            if layout_s:
                layout_s.set_font_description(Pango.FontDescription.from_string(self.config.get("level_bar_secondary_font")))
                layout_s.set_text(self.secondary_text or "", -1)
            
            self._draw_label_set(ctx, text_x, text_y, text_w, text_h, layout_p, layout_s)


    def _draw_superimposed_text(self, ctx, bar_x, bar_y, bar_width, bar_height, layout_p, layout_s):
        align = self.config.get("level_bar_superimposed_align", "middle_center")
        show_primary, show_secondary = layout_p is not None, layout_s is not None
        orientation = self.config.get("level_bar_label_orientation", "vertical")
        spacing = 6

        p_width = layout_p.get_pixel_extents()[1].width if show_primary else 0
        p_height = layout_p.get_pixel_extents()[1].height if show_primary else 0
        s_width = layout_s.get_pixel_extents()[1].width if show_secondary else 0
        s_height = layout_s.get_pixel_extents()[1].height if show_secondary else 0
        
        total_text_width = p_width + s_width + (spacing if show_primary and show_secondary and orientation == "horizontal" else 0)
        total_text_height = p_height + s_height + (spacing if show_primary and show_secondary and orientation == "vertical" else 0)

        if "top" in align: y_start = bar_y + spacing
        elif "bottom" in align: y_start = bar_y + bar_height - total_text_height - spacing
        else: y_start = bar_y + (bar_height - total_text_height) / 2

        if "left" in align: x_start = bar_x + spacing
        elif "right" in align: x_start = bar_x + bar_width - total_text_width - spacing
        else: x_start = bar_x + (bar_width - total_text_width) / 2
        
        self._draw_label_set(ctx, x_start, y_start, total_text_width, total_text_height, layout_p, layout_s)

    def _draw_label_set(self, ctx, area_x, area_y, area_width, area_height, layout_p, layout_s):
        show_primary, show_secondary = layout_p is not None, layout_s is not None
        orientation = self.config.get("level_bar_label_orientation", "vertical")
        align_map = { "left": Pango.Alignment.LEFT, "center": Pango.Alignment.CENTER, "right": Pango.Alignment.RIGHT }
        spacing = 6

        if orientation == "vertical":
            current_y = area_y + (area_height - ( (layout_p.get_pixel_extents()[1].height if show_primary else 0) + 
                                                   (layout_s.get_pixel_extents()[1].height if show_secondary else 0) + 
                                                   (spacing if show_primary and show_secondary else 0) )) / 2
            
            if show_primary:
                align_str = self.config.get("level_bar_primary_align", "center")
                layout_p.set_width(area_width * Pango.SCALE); layout_p.set_alignment(align_map.get(align_str, Pango.Alignment.CENTER))
                color_p = Gdk.RGBA(); color_p.parse(self.config.get("level_bar_primary_color"))
                ctx.set_source_rgba(color_p.red, color_p.green, color_p.blue, color_p.alpha)
                ctx.move_to(area_x, current_y); PangoCairo.show_layout(ctx, layout_p)
                current_y += layout_p.get_pixel_extents()[1].height + spacing

            if show_secondary:
                align_str = self.config.get("level_bar_secondary_align", "center")
                layout_s.set_width(area_width * Pango.SCALE); layout_s.set_alignment(align_map.get(align_str, Pango.Alignment.CENTER))
                color_s = Gdk.RGBA(); color_s.parse(self.config.get("level_bar_secondary_color"))
                ctx.set_source_rgba(color_s.red, color_s.green, color_s.blue, color_s.alpha)
                ctx.move_to(area_x, current_y); PangoCairo.show_layout(ctx, layout_s)
        else: # Horizontal
            p_width, p_height = (layout_p.get_pixel_extents()[1].width, layout_p.get_pixel_extents()[1].height) if show_primary else (0,0)
            s_height = layout_s.get_pixel_extents()[1].height if show_secondary else 0
            
            total_text_width = p_width + (layout_s.get_pixel_extents()[1].width if show_secondary else 0) + (spacing if show_primary and show_secondary else 0)
            current_x = area_x + (area_width - total_text_width) / 2

            if show_primary:
                p_y = area_y + (area_height - p_height) / 2
                color_p = Gdk.RGBA(); color_p.parse(self.config.get("level_bar_primary_color"))
                ctx.set_source_rgba(color_p.red, color_p.green, color_p.blue, color_p.alpha)
                ctx.move_to(current_x, p_y); PangoCairo.show_layout(ctx, layout_p)
                current_x += p_width + spacing

            if show_secondary:
                s_y = area_y + (area_height - s_height) / 2
                color_s = Gdk.RGBA(); color_s.parse(self.config.get("level_bar_secondary_color"))
                ctx.set_source_rgba(color_s.red, color_s.green, color_s.blue, color_s.alpha)
                ctx.move_to(current_x, s_y); PangoCairo.show_layout(ctx, layout_s)

    def draw_bar(self, ctx, bar_x, bar_y, bar_width, bar_height):
        """Draws the main bar, accounting for slant and using a static cache."""
        if bar_width <= 0 or bar_height <= 0: return

        # Check if cache is invalid (size changed or style changed)
        if not self._static_surface or self._last_draw_width != bar_width or self._last_draw_height != bar_height:
            # Create a new surface for the static parts
            self._static_surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, int(bar_width), int(bar_height))
            static_ctx = cairo.Context(self._static_surface)
            # Draw the static elements (background, all 'off' segments) onto the cache
            self._draw_static_bar_elements(static_ctx, bar_width, bar_height, self.config)
            # Update cache dimensions
            self._last_draw_width, self._last_draw_height = bar_width, bar_height

        # Paint the cached static background onto the main context
        ctx.save()
        ctx.translate(bar_x, bar_y)
        ctx.set_source_surface(self._static_surface, 0, 0)
        ctx.paint()
        ctx.restore()
        
        # Draw only the dynamic elements (on/fading segments) on the main context
        ctx.save()
        ctx.translate(bar_x, bar_y)
        self._draw_dynamic_bar_elements(ctx, bar_width, bar_height, self.config, self.current_on_level, self.segment_states)
        ctx.restore()

    @staticmethod
    def _draw_static_bar_elements(ctx, bar_width, bar_height, config):
        """Draws elements that don't change frame-to-frame onto a surface."""
        slant = float(config.get("level_bar_slant_px", 0))
        orientation = config.get("level_bar_orientation", "vertical")
        
        ctx.save()

        # Apply transformations to handle slant without clipping
        if orientation == "vertical":
            rect_width, rect_height = bar_width - abs(slant), bar_height
            if rect_width <= 0: ctx.restore(); return
            offset_x = -slant if slant < 0 else 0
            ctx.translate(offset_x, 0)
            tan_angle = slant / rect_height if rect_height > 0 else 0
            ctx.transform(cairo.Matrix(1, 0, tan_angle, 1, 0, 0))
        else: # Horizontal
            rect_width, rect_height = bar_width, bar_height - abs(slant)
            if rect_height <= 0: ctx.restore(); return
            offset_y = -slant if slant < 0 else 0
            ctx.translate(0, offset_y)
            tan_angle = slant / rect_width if rect_width > 0 else 0
            ctx.transform(cairo.Matrix(1, tan_angle, 0, 1, 0, 0))

        # Draw main background
        bg_rgba = Gdk.RGBA(); bg_rgba.parse(config.get("level_bar_background_color"))
        ctx.set_source_rgba(bg_rgba.red, bg_rgba.green, bg_rgba.blue, bg_rgba.alpha)
        ctx.rectangle(0, 0, rect_width, rect_height); ctx.fill()

        # Draw all segments in their OFF state
        num_segments = int(config.get("level_bar_segment_count", 30))
        spacing = float(config.get("level_bar_spacing", 2))
        off_color = Gdk.RGBA(); off_color.parse(config.get("level_bar_off_color"))
        ctx.set_source_rgba(off_color.red, off_color.green, off_color.blue, off_color.alpha)

        if orientation == "vertical":
            segment_height = (rect_height - (num_segments - 1) * spacing) / num_segments if num_segments > 0 else 0
            if segment_height <= 0: ctx.restore(); return
        else: # Horizontal
            segment_width = (rect_width - (num_segments - 1) * spacing) / num_segments if num_segments > 0 else 0
            if segment_width <= 0: ctx.restore(); return

        for i in range(num_segments):
            if orientation == "vertical":
                seg_y = rect_height - (i + 1) * segment_height - i * spacing
                ctx.rectangle(0, seg_y, rect_width, segment_height)
            else:
                seg_x = i * (segment_width + spacing)
                ctx.rectangle(seg_x, 0, segment_width, rect_height)
            ctx.fill()
        
        ctx.restore()

    @staticmethod
    def _draw_dynamic_bar_elements(ctx, bar_width, bar_height, config, current_on_level, segment_states):
        """Draws elements that change frame-to-frame (on, fading, pulsing)."""
        slant = float(config.get("level_bar_slant_px", 0))
        orientation = config.get("level_bar_orientation", "vertical")
        
        ctx.save()

        # Apply the same transformations as the static part
        if orientation == "vertical":
            rect_width, rect_height = bar_width - abs(slant), bar_height
            if rect_width <= 0: ctx.restore(); return
            offset_x = -slant if slant < 0 else 0
            ctx.translate(offset_x, 0)
            tan_angle = slant / rect_height if rect_height > 0 else 0
            ctx.transform(cairo.Matrix(1, 0, tan_angle, 1, 0, 0))
        else: # Horizontal
            rect_width, rect_height = bar_width, bar_height - abs(slant)
            if rect_height <= 0: ctx.restore(); return
            offset_y = -slant if slant < 0 else 0
            ctx.translate(0, offset_y)
            tan_angle = slant / rect_width if rect_width > 0 else 0
            ctx.transform(cairo.Matrix(1, tan_angle, 0, 1, 0, 0))
        
        num_segments = int(config.get("level_bar_segment_count", 30))
        spacing = float(config.get("level_bar_spacing", 2))
        on_color1_str = config.get("level_bar_on_color")
        off_color_str = config.get("level_bar_off_color")
        fade_enabled = str(config.get("level_bar_fade_enabled", "True")).lower() == 'true'
        fade_duration_s = float(config.get("level_bar_fade_duration_ms", 500))/1000.0
        now = time.monotonic()
        on_grad_enabled = str(config.get("level_bar_on_gradient_enabled", "False")).lower() == 'true'
        on_pulse_enabled = str(config.get("level_bar_on_pulse_enabled", "False")).lower() == 'true'
        on_color2_str = config.get("level_bar_on_color2")
        pulse_color1_str = config.get("level_bar_on_pulse_color1")
        pulse_color2_str = config.get("level_bar_on_pulse_color2")

        if orientation == "vertical":
            segment_height = (rect_height - (num_segments - 1) * spacing) / num_segments if num_segments > 0 else 0
        else: # Horizontal
            segment_width = (rect_width - (num_segments - 1) * spacing) / num_segments if num_segments > 0 else 0

        for i in range(num_segments):
            is_on_segment = i < current_on_level
            state = segment_states[i]
            is_fading_segment = fade_enabled and not state['is_on'] and state['off_timestamp'] > 0 and (now - state['off_timestamp']) < fade_duration_s

            if not (is_on_segment or is_fading_segment): continue

            base_color_str = on_color1_str
            if is_on_segment:
                if on_grad_enabled:
                    grad_mode = config.get("level_bar_gradient_mode", "full")
                    if grad_mode == 'full' and num_segments > 1:
                        denominator = num_segments - 1
                    elif current_on_level > 1: # 'active' mode
                        denominator = current_on_level - 1
                    else:
                        denominator = 1 # Avoid division by zero

                    factor = i / denominator if denominator > 0 else 0.0
                    base_color_str = DataDisplayer._interpolate_color(None, factor, on_color1_str, on_color2_str).to_string()
                
                color_to_use = base_color_str
                if on_pulse_enabled:
                    pulse_duration_s = float(config.get("level_bar_on_pulse_duration_ms", 1000)) / 1000.0
                    if pulse_duration_s > 0:
                        fade_factor = (math.sin(now * (2 * math.pi) / pulse_duration_s) + 1) / 2.0
                        pulse_target_color_str = pulse_color1_str
                        if on_grad_enabled: # Apply same logic to pulse target
                            grad_mode = config.get("level_bar_gradient_mode", "full")
                            if grad_mode == 'full' and num_segments > 1: denominator = num_segments - 1
                            elif current_on_level > 1: denominator = current_on_level - 1
                            else: denominator = 1
                            factor = i / denominator if denominator > 0 else 0.0
                            pulse_target_color_str = DataDisplayer._interpolate_color(None, factor, pulse_color1_str, pulse_color2_str).to_string()

                        color_to_use = DataDisplayer._interpolate_color(None, fade_factor, base_color_str, pulse_target_color_str).to_string()
            
            elif is_fading_segment:
                color_to_use = DataDisplayer._interpolate_color(None, (now - state['off_timestamp'])/fade_duration_s, on_color1_str, off_color_str).to_string()
            else:
                continue
            
            color_rgba = Gdk.RGBA(); color_rgba.parse(color_to_use)
            ctx.set_source_rgba(color_rgba.red, color_rgba.green, color_rgba.blue, color_rgba.alpha)
            
            if orientation == "vertical":
                seg_y = rect_height - (i + 1) * segment_height - i * spacing
                ctx.rectangle(0, seg_y, rect_width, segment_height)
            else:
                seg_x = i * (segment_width + spacing)
                ctx.rectangle(seg_x, 0, segment_width, rect_height)
            ctx.fill()
        
        ctx.restore()

    def close(self):
        self._stop_animation_timer(); super().close()

