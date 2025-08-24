# data_displayers/level_bar.py
import gi
import time
import re
from data_displayer import DataDisplayer
from config_dialog import ConfigOption
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
        
        # Text to be drawn on the canvas
        self.primary_text = ""
        self.secondary_text = ""

        super().__init__(panel_ref, config)
        populate_defaults_from_model(self.config, self.get_config_model())
        self.widget.connect("realize", self._start_animation_timer)
        self.widget.connect("unrealize", self._stop_animation_timer)

    def _create_widget(self):
        """Creates a single drawing area for the entire displayer."""
        drawing_area = Gtk.DrawingArea(vexpand=True, hexpand=True)
        drawing_area.set_draw_func(self.on_draw)
        return drawing_area

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
        if self.current_on_level < self.target_on_level:
            self.current_on_level += 1
            if self.current_on_level -1 < len(self.segment_states):
                 self.segment_states[self.current_on_level - 1]['is_on'] = True
        elif self.current_on_level > self.target_on_level:
             self.current_on_level = self.target_on_level
        self.widget.queue_draw()
        return GLib.SOURCE_CONTINUE

    def update_display(self, value):
        if not self.panel_ref: return # Guard against race condition on close

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
        model["Level Bar Range"] = [ConfigOption("level_min_value", "spinner", "Min Value:", 0, -10000, 10000, 1, 1), ConfigOption("level_max_value", "spinner", "Max Value:", 100, -10000, 10000, 1, 1)]
        model["Level Bar Style"] = [ ConfigOption("level_bar_orientation", "dropdown", "Orientation:", "vertical", options_dict={"Vertical": "vertical", "Horizontal": "horizontal"}), ConfigOption("level_bar_background_color", "color", "Background Color:", "rgba(20,30,50,1)"), ConfigOption("level_bar_on_color", "color", "Segment 'On' Color:", "rgba(170,220,255,1)"), ConfigOption("level_bar_off_color", "color", "Segment 'Off' Color:", "rgba(40,60,80,1)"), ConfigOption("level_bar_segment_count", "spinner", "Number of Segments:", 30, 5, 100, 1, 0), ConfigOption("level_bar_spacing", "spinner", "Segment Spacing (px):", 2, 0, 10, 1, 0) ]
        model["Level Bar Effects"] = [ ConfigOption("level_bar_fade_enabled", "bool", "Enable Fade Out:", "True"), ConfigOption("level_bar_fade_duration_ms", "spinner", "Fade Duration (ms):", 500, 50, 2000, 50, 0), ConfigOption("level_bar_fill_speed_ms", "spinner", "Fill Speed (ms/bar):", 15, 1, 100, 1, 0) ]
        model["Labels & Layout"] = [
            ConfigOption("level_bar_text_position", "dropdown", "Text Position:", "superimposed", 
                         options_dict={"Superimposed": "superimposed", "Top": "top", "Bottom": "bottom", "Left": "left", "Right": "right"}),
            ConfigOption("level_bar_show_primary_label", "bool", "Show Primary Label:", "True"),
            ConfigOption("level_bar_primary_align", "dropdown", "Primary Text Align:", "center", options_dict=align_opts),
            ConfigOption("level_bar_primary_font", "font", "Primary Font:", "Sans Italic 9"),
            ConfigOption("level_bar_primary_color", "color", "Primary Color:", "rgba(200,200,200,1)"),
            ConfigOption("level_bar_show_secondary_label", "bool", "Show Secondary Label:", "True"),
            ConfigOption("level_bar_secondary_align", "dropdown", "Secondary Text Align:", "center", options_dict=align_opts),
            ConfigOption("level_bar_secondary_font", "font", "Secondary Font:", "Sans Bold 12"),
            ConfigOption("level_bar_secondary_color", "color", "Secondary Color:", "rgba(220,220,220,1)")
        ]
        return model

    def apply_styles(self):
        super().apply_styles()
        num_segments = int(self.config.get("level_bar_segment_count", 30))
        if self._last_segment_count != num_segments:
            self.segment_states = [{'is_on': False, 'off_timestamp': 0} for _ in range(num_segments)]
            self._last_segment_count = num_segments
        
        if self.widget.get_realized(): self._start_animation_timer()
        self.widget.queue_draw()

    def on_draw(self, area, ctx, width, height):
        if width <= 0 or height <= 0: return
        
        # --- 1. Prepare Text and Calculate Space ---
        show_primary = str(self.config.get("level_bar_show_primary_label", "True")).lower() == 'true'
        show_secondary = str(self.config.get("level_bar_show_secondary_label", "True")).lower() == 'true'
        text_pos = self.config.get("level_bar_text_position", "superimposed")

        layout_p = PangoCairo.create_layout(ctx) if show_primary else None
        layout_s = PangoCairo.create_layout(ctx) if show_secondary else None
        
        text_block_width = 0
        text_block_height = 0

        if show_primary:
            font_p = Pango.FontDescription.from_string(self.config.get("level_bar_primary_font"))
            layout_p.set_font_description(font_p)
            layout_p.set_text(self.primary_text or "", -1)
            text_block_width = max(text_block_width, layout_p.get_pixel_extents()[1].width)
            text_block_height += layout_p.get_pixel_extents()[1].height

        if show_secondary:
            font_s = Pango.FontDescription.from_string(self.config.get("level_bar_secondary_font"))
            layout_s.set_font_description(font_s)
            layout_s.set_text(self.secondary_text or "", -1)
            text_block_width = max(text_block_width, layout_s.get_pixel_extents()[1].width)
            text_block_height += layout_s.get_pixel_extents()[1].height

        # --- 2. Calculate Bar Geometry based on Text ---
        padding = 4
        bar_x, bar_y, bar_width, bar_height = padding, padding, width - 2*padding, height - 2*padding

        if text_pos == "top":
            bar_y += text_block_height + padding
            bar_height -= text_block_height + padding
        elif text_pos == "bottom":
            bar_height -= text_block_height + padding
        elif text_pos == "left":
            bar_x += text_block_width + padding
            bar_width -= text_block_width + padding
        elif text_pos == "right":
            bar_width -= text_block_width + padding
        
        # --- 3. Draw the Bar ---
        self.draw_bar(ctx, bar_x, bar_y, bar_width, bar_height)

        # --- 4. Draw the Text ---
        text_area_x, text_area_y, text_area_width, text_area_height = 0, 0, 0, 0
        if text_pos == "top":
            text_area_x, text_area_y, text_area_width, text_area_height = padding, padding, width - 2*padding, text_block_height
        elif text_pos == "bottom":
            text_area_x, text_area_y, text_area_width, text_area_height = padding, height - text_block_height - padding, width - 2*padding, text_block_height
        elif text_pos == "left":
            text_area_x, text_area_y, text_area_width, text_area_height = padding, (height - text_block_height)/2, text_block_width, text_block_height
        elif text_pos == "right":
            text_area_x, text_area_y, text_area_width, text_area_height = width - text_block_width - padding, (height - text_block_height)/2, text_block_width, text_block_height
        elif text_pos == "superimposed":
            text_area_x, text_area_y, text_area_width, text_area_height = bar_x, (height - text_block_height)/2, bar_width, text_block_height
        
        current_y = text_area_y
        align_map = { "left": Pango.Alignment.LEFT, "center": Pango.Alignment.CENTER, "right": Pango.Alignment.RIGHT }
        
        if show_primary:
            align_str = self.config.get("level_bar_primary_align", "center")
            layout_p.set_width(text_area_width * Pango.SCALE)
            layout_p.set_alignment(align_map.get(align_str, Pango.Alignment.CENTER))
            
            color_p = Gdk.RGBA(); color_p.parse(self.config.get("level_bar_primary_color"))
            ctx.set_source_rgba(color_p.red, color_p.green, color_p.blue, color_p.alpha)
            ctx.move_to(text_area_x, current_y)
            PangoCairo.show_layout(ctx, layout_p)
            current_y += layout_p.get_pixel_extents()[1].height

        if show_secondary:
            align_str = self.config.get("level_bar_secondary_align", "center")
            layout_s.set_width(text_area_width * Pango.SCALE)
            layout_s.set_alignment(align_map.get(align_str, Pango.Alignment.CENTER))
            
            color_s = Gdk.RGBA(); color_s.parse(self.config.get("level_bar_secondary_color"))
            ctx.set_source_rgba(color_s.red, color_s.green, color_s.blue, color_s.alpha)
            ctx.move_to(text_area_x, current_y)
            PangoCairo.show_layout(ctx, layout_s)

    def draw_bar(self, ctx, bar_x, bar_y, bar_width, bar_height):
        """Draws only the segmented bar within the provided rectangle."""
        if bar_width <= 0 or bar_height <= 0: return
        bg_rgba = Gdk.RGBA(); bg_rgba.parse(self.config.get("level_bar_background_color")); ctx.set_source_rgba(bg_rgba.red,bg_rgba.green,bg_rgba.blue,bg_rgba.alpha)
        ctx.rectangle(bar_x, bar_y, bar_width, bar_height); ctx.fill()
        
        num_segments, spacing = int(self.config.get("level_bar_segment_count", 30)), float(self.config.get("level_bar_spacing", 2))
        on_color_str, off_color_str = self.config.get("level_bar_on_color"), self.config.get("level_bar_off_color")
        fade_enabled, fade_duration_s, now = str(self.config.get("level_bar_fade_enabled", "True")).lower() == 'true', float(self.config.get("level_bar_fade_duration_ms", 500))/1000.0, time.monotonic()
        orientation = self.config.get("level_bar_orientation", "vertical")

        if orientation == "vertical":
            total_spacing = (num_segments - 1) * spacing
            segment_height = (bar_height - total_spacing) / num_segments if num_segments > 0 else 0
            if segment_height <= 0: return
        else: # Horizontal
            total_spacing = (num_segments - 1) * spacing
            segment_width = (bar_width - total_spacing) / num_segments if num_segments > 0 else 0
            if segment_width <= 0: return

        for i in range(num_segments):
            if i < self.current_on_level: color_to_use = on_color_str
            else:
                state = self.segment_states[i]
                if fade_enabled and not state['is_on'] and state['off_timestamp'] > 0:
                    elapsed = now - state['off_timestamp']
                    if elapsed < fade_duration_s: color_to_use = self._interpolate_color(elapsed/fade_duration_s, on_color_str, off_color_str).to_string()
                    else: color_to_use = off_color_str
                else: color_to_use = off_color_str
            
            color_rgba = Gdk.RGBA(); color_rgba.parse(color_to_use)
            ctx.set_source_rgba(color_rgba.red, color_rgba.green, color_rgba.blue, color_rgba.alpha)
            
            if orientation == "vertical":
                seg_y = bar_y + bar_height - (i + 1) * segment_height - i * spacing
                ctx.rectangle(bar_x, seg_y, bar_width, segment_height)
            else:
                seg_x = bar_x + i * (segment_width + spacing)
                ctx.rectangle(seg_x, bar_y, segment_width, bar_height)
            ctx.fill()

    def close(self):
        self._stop_animation_timer(); super().close()
