# /data_displayers/cpu_multicore.py
import gi
import cairo
import math
import time
from data_displayer import DataDisplayer
from config_dialog import ConfigOption, build_ui_from_model
from utils import populate_defaults_from_model

gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gtk, Gdk, GLib, Pango, PangoCairo

class CpuMultiCoreDisplayer(DataDisplayer):
    """
    A specialized displayer that renders metrics for multiple CPU cores simultaneously.
    """
    def __init__(self, panel_ref, config):
        self._core_targets = []
        self._core_currents = []
        self._animation_timer_id = None
        
        self._cached_layout = None
        self._layout_caption = None
        self._layout_num = None 
        self._caption_text = ""

        super().__init__(panel_ref, config)
        populate_defaults_from_model(self.config, self.get_config_model())
        
        self.widget.connect("realize", self._start_animation_timer)
        self.widget.connect("unrealize", self._stop_animation_timer)

    def _create_widget(self):
        drawing_area = Gtk.DrawingArea(hexpand=True, vexpand=True)
        drawing_area.set_draw_func(self.on_draw)
        return drawing_area

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

        animation_enabled = str(self.config.get("multicore_animation_enabled", "True")).lower() == 'true'
        speed = float(self.config.get("multicore_animation_speed", 0.2))
        needs_redraw = False
        
        if len(self._core_currents) != len(self._core_targets):
             self._core_currents = list(self._core_targets)
             needs_redraw = True

        if not animation_enabled:
            if self._core_currents != self._core_targets:
                self._core_currents = list(self._core_targets)
                needs_redraw = True
        else:
            for i in range(len(self._core_currents)):
                diff = self._core_targets[i] - self._core_currents[i]
                if abs(diff) < 0.005:
                    if self._core_currents[i] != self._core_targets[i]:
                        self._core_currents[i] = self._core_targets[i]
                        needs_redraw = True
                else:
                    self._core_currents[i] += diff * speed
                    needs_redraw = True

        if needs_redraw:
            self.widget.queue_draw()
            
        return GLib.SOURCE_CONTINUE

    def update_display(self, data, **kwargs):
        source = kwargs.get('source_override', self.panel_ref.data_source if self.panel_ref else None)
        
        config_caption = self.config.get("multicore_caption_text")
        
        if config_caption is not None and config_caption.strip() != "":
            self._caption_text = config_caption
        elif 'caption' in kwargs and kwargs['caption']:
             self._caption_text = kwargs['caption']
        elif source:
             self._caption_text = source.get_primary_label_string(data)

        if not isinstance(data, dict):
            return

        metric = self.config.get("multicore_metric", "usage")
        raw_list = []

        if metric == "usage":
            usage_data = data.get("usage", {})
            if isinstance(usage_data, dict):
                raw_list = usage_data.get("per_core", [])
        elif metric == "frequency":
            freq_data = data.get("frequency", {})
            if isinstance(freq_data, dict):
                raw_list = freq_data.get("per_core", [])
        
        if not raw_list:
            self._core_targets = []
            return

        start_idx = int(self.config.get("multicore_start_index", 0))
        requested_count = int(self.config.get("multicore_count", 8))
        
        # --- FIX: Cap displayed cores to available data ---
        available_len = len(raw_list)
        if start_idx >= available_len:
            start_idx = 0 
        
        actual_count = min(requested_count, available_len - start_idx)
        sliced_data = raw_list[start_idx : start_idx + actual_count]
        
        min_v = float(self.config.get("graph_min_value", 0.0))
        max_v = float(self.config.get("graph_max_value", 100.0))
        v_range = max_v - min_v if max_v > min_v else 1.0

        new_targets = []
        for val in sliced_data:
            if val is None: val = min_v
            normalized = (min(max(val, min_v), max_v) - min_v) / v_range
            new_targets.append(normalized)
            
        self._core_targets = new_targets
        
        if not self._core_currents:
             self._core_currents = list(self._core_targets)
             self.widget.queue_draw()

    def on_draw(self, area, ctx, width, height):
        if width <= 0 or height <= 0 or not self._core_currents:
            return
            
        # --- Draw Main Caption ---
        show_caption = str(self.config.get("multicore_show_caption", "True")).lower() == 'true'
        caption_height = 0
        
        if show_caption and self._caption_text:
            if self._layout_caption is None:
                self._layout_caption = self.widget.create_pango_layout("")
            
            font_desc = Pango.FontDescription.from_string(self.config.get("multicore_caption_font", "Sans 10"))
            self._layout_caption.set_font_description(font_desc)
            self._layout_caption.set_text(self._caption_text, -1)
            
            cap_color = Gdk.RGBA()
            cap_color.parse(self.config.get("multicore_caption_color", "rgba(255,255,255,1)"))
            ctx.set_source_rgba(cap_color.red, cap_color.green, cap_color.blue, cap_color.alpha)
            
            _, log_rect = self._layout_caption.get_pixel_extents()
            caption_height = log_rect.height + 4
            
            ctx.move_to(0, 0)
            PangoCairo.show_layout(ctx, self._layout_caption)
            
            ctx.translate(0, caption_height)
            height -= caption_height

        if height <= 0: return

        orientation = self.config.get("multicore_orientation", "vertical")
        style = self.config.get("multicore_style", "segments")
        spacing = float(self.config.get("multicore_spacing", 2))
        bar_count = len(self._core_currents)
        
        show_nums = str(self.config.get("multicore_show_nums", "False")).lower() == 'true'
        num_pos = self.config.get("multicore_num_position", "bottom")
        start_idx = int(self.config.get("multicore_start_index", 0))
        
        # Calculate max label width for consistent horizontal alignment
        max_num_w = 0
        if show_nums:
            if self._layout_num is None:
                self._layout_num = self.widget.create_pango_layout("")
            
            num_font_desc = Pango.FontDescription.from_string(self.config.get("multicore_num_font", "Sans 8"))
            self._layout_num.set_font_description(num_font_desc)
            num_color = Gdk.RGBA(); num_color.parse(self.config.get("multicore_num_color", "rgba(200,200,200,1)"))
            
            if orientation == "horizontal" and num_pos in ["left", "right"]:
                for i in range(bar_count):
                    self._layout_num.set_text(str(start_idx + i), -1)
                    _, num_log = self._layout_num.get_pixel_extents()
                    if num_log.width > max_num_w: max_num_w = num_log.width

        # Calculate cell dimensions
        if orientation == "vertical":
            cell_width = (width - (spacing * (bar_count - 1))) / bar_count
            cell_height = height
        else:
            cell_width = width
            cell_height = (height - (spacing * (bar_count - 1))) / bar_count

        if cell_width <= 0 or cell_height <= 0: return

        bg_color = Gdk.RGBA(); bg_color.parse(self.config.get("multicore_bg_color", "rgba(40,40,40,0.5)"))
        color_mode = self.config.get("multicore_color_mode", "gradient")
        
        # --- FIX: Parse custom colors for use in gradient mode too ---
        custom_colors = []
        custom_count = int(self.config.get("multicore_custom_color_count", 1))
        for i in range(1, custom_count + 1):
            try:
                c_str = self.config.get(f"multicore_custom_color_{i}", "rgba(255,255,255,1)")
                c = Gdk.RGBA(); c.parse(c_str)
                custom_colors.append(c)
            except: pass

        colors = []
        if color_mode == "single":
            c = Gdk.RGBA(); c.parse(self.config.get("multicore_color_single", "rgba(0,200,255,1)"))
            colors = [c]
        elif color_mode == "gradient":
            # Check if we should use custom sequence for gradient
            if len(custom_colors) >= 2:
                 colors = custom_colors
            else:
                c_start = Gdk.RGBA(); c_start.parse(self.config.get("multicore_fg_color_start", "rgba(0,200,255,1)"))
                c_end = Gdk.RGBA(); c_end.parse(self.config.get("multicore_fg_color_end", "rgba(0,100,255,1)"))
                colors = [c_start, c_end]
        elif color_mode == "custom":
            colors = custom_colors
            if not colors: colors = [Gdk.RGBA()] 

        for i, percent in enumerate(self._core_currents):
            if orientation == "vertical":
                cell_x, cell_y = i * (cell_width + spacing), 0
            else:
                cell_x, cell_y = 0, i * (cell_height + spacing)

            bar_x, bar_y, bar_w, bar_h = cell_x, cell_y, cell_width, cell_height
            
            if show_nums:
                self._layout_num.set_text(str(start_idx + i), -1)
                _, num_log = self._layout_num.get_pixel_extents()
                num_w, num_h = num_log.width, num_log.height
                
                txt_x, txt_y = cell_x, cell_y 
                
                if num_pos == "superimposed":
                    txt_x = cell_x + (cell_width - num_w) / 2
                    txt_y = cell_y + (cell_height - num_h) / 2
                elif num_pos == "bottom":
                    bar_h = max(0, cell_height - num_h - 2)
                    txt_x = cell_x + (cell_width - num_w) / 2
                    txt_y = cell_y + bar_h + 2
                elif num_pos == "top":
                    bar_h = max(0, cell_height - num_h - 2)
                    bar_y = cell_y + num_h + 2
                    txt_x = cell_x + (cell_width - num_w) / 2
                    txt_y = cell_y
                elif num_pos == "left":
                    label_space = max_num_w if max_num_w > 0 else num_w
                    bar_w = max(0, cell_width - label_space - 4)
                    bar_x = cell_x + label_space + 4
                    txt_x = cell_x + (label_space - num_w)
                    txt_y = cell_y + (cell_height - num_h) / 2
                elif num_pos == "right":
                    label_space = max_num_w if max_num_w > 0 else num_w
                    bar_w = max(0, cell_width - label_space - 4)
                    txt_x = cell_x + bar_w + 4
                    txt_y = cell_y + (cell_height - num_h) / 2

            # Background
            ctx.set_source_rgba(bg_color.red, bg_color.green, bg_color.blue, bg_color.alpha)
            ctx.rectangle(bar_x, bar_y, bar_w, bar_h)
            ctx.fill()

            # Foreground Color
            if color_mode == "single":
                c = colors[0]
                ctx.set_source_rgba(c.red, c.green, c.blue, c.alpha)
            elif color_mode == "gradient":
                # Interpolate across ALL colors in the list
                total_stops = len(colors)
                if total_stops < 2:
                     c = colors[0]
                     ctx.set_source_rgba(c.red, c.green, c.blue, c.alpha)
                else:
                    global_progress = i / (bar_count - 1) if bar_count > 1 else 0
                    
                    # Find which two colors we are between
                    # If 3 colors: 0.0-0.5 uses col 0-1, 0.5-1.0 uses col 1-2
                    segment_size = 1.0 / (total_stops - 1)
                    segment_idx = int(global_progress / segment_size)
                    if segment_idx >= total_stops - 1: segment_idx = total_stops - 2
                    
                    local_progress = (global_progress - (segment_idx * segment_size)) / segment_size
                    
                    c1, c2 = colors[segment_idx], colors[segment_idx + 1]
                    inter = self._interpolate_color(local_progress, c1, c2)
                    ctx.set_source_rgba(inter.red, inter.green, inter.blue, inter.alpha)
                    
            elif color_mode == "custom":
                c = colors[i % len(colors)]
                ctx.set_source_rgba(c.red, c.green, c.blue, c.alpha)

            # Draw Active Bar
            if style == "segments":
                seg_spacing = 1
                if orientation == "vertical":
                    num_segs = int(bar_h / 4) 
                    if num_segs > 0:
                        seg_h = (bar_h - (num_segs-1)*seg_spacing) / num_segs
                        active_segs = int(percent * num_segs)
                        for s in range(active_segs):
                            sy = bar_y + bar_h - ((s+1) * seg_h + s * seg_spacing)
                            ctx.rectangle(bar_x, sy, bar_w, seg_h)
                            ctx.fill()
                else:
                    num_segs = int(bar_w / 4)
                    if num_segs > 0:
                        seg_w = (bar_w - (num_segs-1)*seg_spacing) / num_segs
                        active_segs = int(percent * num_segs)
                        for s in range(active_segs):
                            sx = bar_x + (s * seg_w + s * seg_spacing)
                            ctx.rectangle(sx, bar_y, seg_w, bar_h)
                            ctx.fill()
            else: # Solid
                if orientation == "vertical":
                    fill_h = bar_h * percent
                    ctx.rectangle(bar_x, bar_y + bar_h - fill_h, bar_w, fill_h)
                else:
                    fill_w = bar_w * percent
                    ctx.rectangle(bar_x, bar_y, fill_w, bar_h)
                ctx.fill()
                
            if show_nums:
                ctx.set_source_rgba(num_color.red, num_color.green, num_color.blue, num_color.alpha)
                ctx.move_to(txt_x, txt_y)
                PangoCairo.show_layout(ctx, self._layout_num)

    def _interpolate_color(self, factor, c1, c2):
        res = Gdk.RGBA()
        res.red = c1.red + factor * (c2.red - c1.red)
        res.green = c1.green + factor * (c2.green - c1.green)
        res.blue = c1.blue + factor * (c2.blue - c1.blue)
        res.alpha = c1.alpha + factor * (c2.alpha - c1.alpha)
        return res

    @staticmethod
    def get_config_model():
        metric_opts = {"Usage": "usage", "Frequency": "frequency"}
        orientation_opts = {"Vertical Bars": "vertical", "Horizontal Bars": "horizontal"}
        style_opts = {"Segments": "segments", "Solid": "solid"}
        color_mode_opts = {"Single Color": "single", "Gradient": "gradient", "Custom Sequence": "custom"}
        num_pos_opts = {"Bottom": "bottom", "Top": "top", "Left": "left", "Right": "right", "Superimposed": "superimposed"}
        
        nums_controller = "multicore_show_nums"

        model = {
            "Data Source": [
                ConfigOption("multicore_metric", "dropdown", "Metric:", "usage", options_dict=metric_opts),
                ConfigOption("multicore_start_index", "spinner", "Start Core Index:", 0, 0, 256, 1, 0),
                ConfigOption("multicore_count", "spinner", "Number of Cores:", 8, 1, 128, 1, 0),
            ],
            "Appearance": [
                ConfigOption("multicore_orientation", "dropdown", "Orientation:", "vertical", options_dict=orientation_opts),
                ConfigOption("multicore_style", "dropdown", "Bar Style:", "segments", options_dict=style_opts),
                ConfigOption("multicore_spacing", "spinner", "Spacing (px):", 2, 0, 20, 1, 0),
                ConfigOption("multicore_bg_color", "color", "Background Color:", "rgba(40,40,40,0.5)"),
            ],
            "Colors": [
                ConfigOption("multicore_color_mode", "dropdown", "Color Mode:", "gradient", options_dict=color_mode_opts),
                
                ConfigOption("multicore_color_single", "color", "Bar Color:", "rgba(0,200,255,1)"),
                             
                ConfigOption("multicore_fg_color_start", "color", "Gradient Start Color:", "rgba(0,200,255,1)"),
                ConfigOption("multicore_fg_color_end", "color", "Gradient End Color:", "rgba(0,100,255,1)"),
                             
                ConfigOption("multicore_custom_color_count", "spinner", "Sequence Length:", 2, 1, 16, 1, 0,
                             tooltip="Set length > 1 to define custom colors. If mode is 'Gradient', these colors will be used as stops."),
            ],
            "Core Labels": [
                ConfigOption(nums_controller, "bool", "Show Core Numbers:", "False"),
                
                ConfigOption("multicore_num_position", "dropdown", "Position:", "bottom", options_dict=num_pos_opts),
                ConfigOption("multicore_num_font", "font", "Font:", "Sans 8"),
                ConfigOption("multicore_num_color", "color", "Color:", "rgba(200,200,200,1)"),
            ],
            "Animation": [
                ConfigOption("multicore_animation_enabled", "bool", "Enable Animation:", "True"),
                ConfigOption("multicore_animation_speed", "spinner", "Speed (0.1-1.0):", 0.2, 0.01, 1.0, 0.05, 2),
            ],
            "Caption": [
                ConfigOption("multicore_show_caption", "bool", "Show Caption:", "True"),
                ConfigOption("multicore_caption_font", "font", "Font:", "Sans 10"),
                ConfigOption("multicore_caption_color", "color", "Color:", "rgba(200,200,200,1)"),
                ConfigOption("multicore_caption_text", "string", "Override Text:", "", tooltip="Leave blank to use default label."),
            ]
        }
        
        for i in range(1, 17):
            model["Colors"].append(ConfigOption(f"multicore_custom_color_{i}", "color", f"Color {i}:", "rgba(255,255,255,1)"))
            
        return model
    
    @staticmethod
    def get_config_key_prefixes():
        return ["multicore_"]

    def get_configure_callback(self):
        def build_multicore_config(dialog, content_box, widgets, available_sources, panel_config, prefix=None):
            key_prefix = f"{prefix}_" if prefix else ""
            
            # --- 1. Dynamic Visibility for Colors ---
            color_mode_combo = widgets.get(f"{key_prefix}multicore_color_mode")
            count_spinner = widgets.get(f"{key_prefix}multicore_custom_color_count")
            
            single_row = widgets.get(f"{key_prefix}multicore_color_single").get_parent().get_parent()
            start_row = widgets.get(f"{key_prefix}multicore_fg_color_start").get_parent().get_parent()
            end_row = widgets.get(f"{key_prefix}multicore_fg_color_end").get_parent().get_parent()
            count_row = count_spinner.get_parent() if count_spinner else None

            def update_color_visibility(combo=None):
                mode = color_mode_combo.get_active_id()
                count = int(count_spinner.get_value()) if count_spinner else 0
                has_custom = count >= 2
                
                if single_row: single_row.set_visible(mode == "single")
                
                # Show simple start/end ONLY if gradient mode AND no custom sequence defined
                is_simple_gradient = (mode == "gradient" and not has_custom)
                if start_row: start_row.set_visible(is_simple_gradient)
                if end_row: end_row.set_visible(is_simple_gradient)
                
                # Show count row if custom or gradient (to allow defining gradient stops)
                if count_row: count_row.set_visible(mode == "custom" or mode == "gradient")
                
                # Handle custom color rows
                # Show them if mode is custom OR (mode is gradient AND we have custom colors enabled by count > 1)
                show_custom_rows = (mode == "custom") or (mode == "gradient" and has_custom)
                
                for i in range(1, 17):
                    w = widgets.get(f"{key_prefix}multicore_custom_color_{i}")
                    if w:
                        row = w.get_parent().get_parent()
                        should_show = show_custom_rows and (i <= count)
                        if row: row.set_visible(should_show)

            if color_mode_combo:
                color_mode_combo.connect("changed", update_color_visibility)
                if count_spinner:
                    count_spinner.connect("value-changed", lambda s: update_color_visibility())
                
                GLib.idle_add(update_color_visibility)

            # --- 2. Dynamic Visibility for Labels ---
            nums_switch = widgets.get(f"{key_prefix}multicore_show_nums")
            pos_row = widgets.get(f"{key_prefix}multicore_num_position").get_parent()
            font_row = widgets.get(f"{key_prefix}multicore_num_font").get_parent()
            color_row = widgets.get(f"{key_prefix}multicore_num_color").get_parent().get_parent()

            def update_label_visibility(switch, gparam=None):
                is_active = switch.get_active()
                if pos_row: pos_row.set_visible(is_active)
                if font_row: font_row.set_visible(is_active)
                if color_row: color_row.set_visible(is_active)

            if nums_switch:
                nums_switch.connect("notify::active", update_label_visibility)
                GLib.idle_add(update_label_visibility, nums_switch, None)

        return build_multicore_config
