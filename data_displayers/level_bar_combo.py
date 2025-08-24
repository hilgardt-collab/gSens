# data_displayers/level_bar_combo.py
import gi
import time
import math
from data_displayer import DataDisplayer
from config_dialog import ConfigOption
from utils import populate_defaults_from_model

gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gtk, Gdk, GLib, Pango, PangoCairo

class LevelBarComboDisplayer(DataDisplayer):
    """A displayer that shows multiple level bars in a single panel."""
    def __init__(self, panel_ref, config):
        self.data_bundle = {}
        self.bar_states = {}
        self._animation_timer_id = None
        super().__init__(panel_ref, config)
        populate_defaults_from_model(self.config, self.get_config_model())
        self.widget.connect("realize", self._start_animation_timer)
        self.widget.connect("unrealize", self._stop_animation_timer)

    def _create_widget(self):
        drawing_area = Gtk.DrawingArea(vexpand=True, hexpand=True)
        drawing_area.set_draw_func(self.on_draw)
        return drawing_area

    def _start_animation_timer(self, widget=None):
        self._stop_animation_timer()
        self._animation_timer_id = GLib.timeout_add(16, self._animation_tick) # ~60fps

    def _stop_animation_timer(self, widget=None):
        if self._animation_timer_id:
            GLib.source_remove(self._animation_timer_id)
            self._animation_timer_id = None

    def _animation_tick(self):
        if not self.widget.get_realized():
            self._animation_timer_id = None
            return GLib.SOURCE_REMOVE
        
        needs_redraw = False
        for i in range(1, int(self.config.get("number_of_bars", 3)) + 1):
            state = self.bar_states.get(i, {'current': 0.0, 'target': 0.0})
            diff = state['target'] - state['current']
            if abs(diff) > 0.001:
                state['current'] += diff * 0.1 # Simple easing
                needs_redraw = True
            elif state['current'] != state['target']:
                state['current'] = state['target']
                needs_redraw = True
        
        if needs_redraw:
            self.widget.queue_draw()
        return GLib.SOURCE_CONTINUE

    def update_display(self, value):
        if not self.panel_ref: return
        self.data_bundle = value
        
        # Update target values for animation
        num_bars = int(self.config.get("number_of_bars", 3))
        for i in range(1, num_bars + 1):
            if i not in self.bar_states:
                self.bar_states[i] = {'current': 0.0, 'target': 0.0}
            
            prefix = f"bar{i}_"
            source_key = f"{prefix}source"
            bundle = self.data_bundle.get(source_key, {})
            data = bundle.get("data")
            
            if data:
                child_source = self.panel_ref.data_source.child_sources.get(source_key)
                if child_source:
                    num_val = child_source.get_numerical_value(data) or 0.0
                    min_v = float(self.config.get(f"{prefix}opt_level_min_value", 0))
                    max_v = float(self.config.get(f"{prefix}opt_level_max_value", 100))
                    v_range = max_v - min_v if max_v > min_v else 1
                    self.bar_states[i]['target'] = (min(max(num_val, min_v), max_v) - min_v) / v_range
            else:
                self.bar_states[i]['target'] = 0.0

    @staticmethod
    def get_config_model():
        model = DataDisplayer.get_config_model()
        model["Layout & Style"] = [
            ConfigOption("orientation", "dropdown", "Orientation:", "vertical", options_dict={"Vertical": "vertical", "Horizontal": "horizontal"}),
            ConfigOption("bar_spacing", "spinner", "Space Between Bars (px):", 5, 0, 50, 1, 0),
            ConfigOption("segment_count", "spinner", "Segments per Bar:", 20, 5, 100, 1, 0),
            ConfigOption("segment_spacing", "spinner", "Segment Spacing (px):", 2, 0, 10, 1, 0),
        ]
        return model

    def on_draw(self, area, ctx, width, height):
        if width <= 0 or height <= 0: return

        num_bars = int(self.config.get("number_of_bars", 3))
        if num_bars == 0: return

        orientation = self.config.get("orientation", "vertical")
        bar_spacing = int(self.config.get("bar_spacing", 5))

        if orientation == "vertical":
            total_spacing = (num_bars - 1) * bar_spacing
            bar_width = (width - total_spacing) / num_bars if num_bars > 0 else 0
            bar_height = height
            if bar_width <= 0: return
        else: # Horizontal
            total_spacing = (num_bars - 1) * bar_spacing
            bar_height = (height - total_spacing) / num_bars if num_bars > 0 else 0
            bar_width = width
            if bar_height <= 0: return

        for i in range(num_bars):
            if orientation == "vertical":
                bar_x = i * (bar_width + bar_spacing)
                bar_y = 0
            else:
                bar_x = 0
                bar_y = i * (bar_height + bar_spacing)

            self._draw_single_bar(ctx, i + 1, bar_x, bar_y, bar_width, bar_height)

    def _draw_single_bar(self, ctx, bar_index, x, y, w, h):
        prefix = f"bar{bar_index}_"
        source_key = f"{prefix}source"
        bundle = self.data_bundle.get(source_key, {})
        
        num_segments = int(self.config.get("segment_count", 20))
        segment_spacing = int(self.config.get("segment_spacing", 2))
        orientation = self.config.get("orientation", "vertical")

        state = self.bar_states.get(bar_index, {'current': 0.0})
        on_level_ratio = state['current']
        on_level = int(round(on_level_ratio * num_segments))

        on_color = Gdk.RGBA(); on_color.parse(self.config.get(f"{prefix}on_color", "rgba(170,220,255,1)"))
        off_color = Gdk.RGBA(); off_color.parse(self.config.get(f"{prefix}off_color", "rgba(40,60,80,1)"))

        if segment_spacing == 0: # Draw solid bar
            if orientation == "vertical":
                fill_h = h * on_level_ratio
                ctx.set_source_rgba(off_color.red, off_color.green, off_color.blue, off_color.alpha)
                ctx.rectangle(x, y, w, h - fill_h)
                ctx.fill()
                ctx.set_source_rgba(on_color.red, on_color.green, on_color.blue, on_color.alpha)
                ctx.rectangle(x, y + h - fill_h, w, fill_h)
                ctx.fill()
            else: # Horizontal
                fill_w = w * on_level_ratio
                ctx.set_source_rgba(off_color.red, off_color.green, off_color.blue, off_color.alpha)
                ctx.rectangle(x + fill_w, y, w - fill_w, h)
                ctx.fill()
                ctx.set_source_rgba(on_color.red, on_color.green, on_color.blue, on_color.alpha)
                ctx.rectangle(x, y, fill_w, h)
                ctx.fill()
        else: # Draw segmented bar
            if orientation == "vertical":
                total_seg_spacing = (num_segments - 1) * segment_spacing
                seg_h = (h - total_seg_spacing) / num_segments if num_segments > 0 else 0
                if seg_h <= 0: return

                for i_seg in range(num_segments):
                    color_to_use = on_color if i_seg < on_level else off_color
                    ctx.set_source_rgba(color_to_use.red, color_to_use.green, color_to_use.blue, color_to_use.alpha)
                    seg_y = y + h - (i_seg + 1) * seg_h - i_seg * segment_spacing
                    ctx.rectangle(x, seg_y, w, seg_h)
                    ctx.fill()
            else: # Horizontal
                total_seg_spacing = (num_segments - 1) * segment_spacing
                seg_w = (w - total_seg_spacing) / num_segments if num_segments > 0 else 0
                if seg_w <= 0: return

                for i_seg in range(num_segments):
                    color_to_use = on_color if i_seg < on_level else off_color
                    ctx.set_source_rgba(color_to_use.red, color_to_use.green, color_to_use.blue, color_to_use.alpha)
                    seg_x = x + i_seg * (seg_w + segment_spacing)
                    ctx.rectangle(seg_x, y, seg_w, h)
                    ctx.fill()

        # Draw Labels
        label_content_type = self.config.get(f"{prefix}label_content", "both")
        if label_content_type != "none":
            caption = self.config.get(f"{prefix}caption", f"Bar {bar_index}")
            value_str = bundle.get("display_string", "")
            
            label_text = ""
            if label_content_type == "caption": label_text = caption
            elif label_content_type == "value": label_text = value_str
            elif label_content_type == "both": label_text = f"{caption}: {value_str}"
            
            layout = PangoCairo.create_layout(ctx)
            layout.set_font_description(Pango.FontDescription.from_string(self.config.get(f"{prefix}label_font", "Sans Bold 10")))
            layout.set_text(label_text, -1)
            _, log = layout.get_pixel_extents()
            color = Gdk.RGBA(); color.parse(self.config.get(f"{prefix}label_color", "rgba(220,220,220,1)"))
            ctx.set_source_rgba(color.red, color.green, color.blue, color.alpha)
            
            pos = self.config.get(f"{prefix}label_position", "middle")
            
            ctx.save()
            if orientation == "vertical":
                ctx.translate(x + w/2, y + h/2)
                ctx.rotate(-math.pi / 2)
                
                if pos == "start": text_x = -h/2 + log.height/2
                elif pos == "end": text_x = h/2 - log.width - log.height/2
                else: text_x = -log.width / 2
                
                ctx.move_to(text_x, -log.height/2)

            else: # Horizontal
                if pos == "start": text_x = x + 5
                elif pos == "end": text_x = x + w - log.width - 5
                else: text_x = x + (w - log.width)/2
                
                ctx.move_to(text_x, y + (h - log.height)/2)

            PangoCairo.show_layout(ctx, layout)
            ctx.restore()
