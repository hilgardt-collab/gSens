import gi
import math
import cairo
from data_displayer import DataDisplayer
from config_dialog import ConfigOption, build_ui_from_model, get_config_from_widgets
from utils import populate_defaults_from_model

gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gtk, Gdk, GLib, Pango, PangoCairo

class IndicatorDisplayer(DataDisplayer):
    """
    Displays a value as a solid color, interpolated from a user-defined
    gradient with 2 to 10 color stops, with fully configurable text.
    The indicator can be displayed as a variety of shapes.
    """
    def __init__(self, panel_ref, config):
        self.current_value = 0.0
        self.primary_text = ""
        self.main_text = ""
        self.secondary_text = ""
        self._layout_primary = None
        self._layout_main = None
        self._layout_secondary = None
        super().__init__(panel_ref, config)
        populate_defaults_from_model(self.config, self.get_config_model())

    def _create_widget(self):
        drawing_area = Gtk.DrawingArea(hexpand=True, vexpand=True)
        drawing_area.set_draw_func(self.on_draw)
        return drawing_area

    def update_display(self, value, **kwargs):
        source = kwargs.get('source_override', self.panel_ref.data_source if self.panel_ref else None)
        if not source: return

        self.current_value = source.get_numerical_value(value) or 0.0
        
        self.primary_text = kwargs.get('caption', source.get_primary_label_string(value))
        self.main_text = source.get_display_string(value)
        self.secondary_text = source.get_secondary_display_string(value)

        self.widget.queue_draw()

    @staticmethod
    def get_config_model():
        model = DataDisplayer.get_config_model()
        
        model["Indicator Shape"] = [
            ConfigOption("indicator_shape", "dropdown", "Shape:", "full_panel", 
                         options_dict={"Full Panel": "full_panel", "Circle": "circle", 
                                       "Square": "square", "Polygon": "polygon"}),
            ConfigOption("indicator_shape_padding", "spinner", "Padding (px):", 10, 0, 100, 1, 0),
            ConfigOption("indicator_square_keep_aspect", "bool", "Keep Aspect Ratio:", "True",
                         tooltip="If unchecked, the square will stretch to fill the available space."),
            ConfigOption("indicator_polygon_sides", "spinner", "Number of Sides:", 6, 3, 12, 1, 0)
        ]

        color_stops = [
            ConfigOption("indicator_color_count", "spinner", "Number of Colors:", 3, 2, 10, 1, 0)
        ]
        default_colors = [
            "rgba(0,128,255,1)", "rgba(255,255,0,1)", "rgba(255,0,0,1)",
            "rgba(0,255,0,1)", "rgba(128,0,128,1)", "rgba(255,165,0,1)",
            "rgba(0,255,255,1)", "rgba(255,105,180,1)", "rgba(100,149,237,1)", "rgba(255,255,255,1)"
        ]
        for i in range(1, 11):
            label_suffix = " (Min)" if i == 1 else ""
            default_val = (i-1) * (100 / 9) if i > 1 else 0
            color_stops.extend([
                ConfigOption(f"indicator_percent{i}", "spinner", f"Percent for Color {i}{label_suffix}:", f"{default_val:.1f}", 0, 100, 1, 1),
                ConfigOption(f"indicator_color{i}", "color", f"Color {i}:", default_colors[i-1]),
            ])

        model["Indicator Colors & Stops"] = color_stops
        
        align_opts = {"Left": "left", "Center": "center", "Right": "right"}
        model["Text Layout"] = [
            ConfigOption("indicator_text_vertical_align", "dropdown", "Vertical Align:", "center", options_dict={"Top": "start", "Center": "center", "Bottom": "end"}),
            ConfigOption("indicator_text_spacing", "spinner", "Spacing (px):", 4, 0, 50, 1, 0)
        ]
        model["Primary Text Style"] = [
            ConfigOption("indicator_primary_show", "bool", "Show Primary Text:", "True"),
            ConfigOption("indicator_primary_align", "dropdown", "Align:", "center", options_dict=align_opts),
            ConfigOption("indicator_primary_font", "font", "Font:", "Sans Italic 12"),
            ConfigOption("indicator_primary_color", "color", "Color:", "rgba(220,220,220,1)"),
        ]
        model["Main Text Style"] = [
            ConfigOption("indicator_main_show", "bool", "Show Main Text:", "True"),
            ConfigOption("indicator_main_align", "dropdown", "Align:", "center", options_dict=align_opts),
            ConfigOption("indicator_main_font", "font", "Font:", "Sans Bold 18"),
            ConfigOption("indicator_main_color", "color", "Color:", "rgba(255,255,255,1)"),
        ]
        model["Secondary Text Style"] = [
            ConfigOption("indicator_secondary_show", "bool", "Show Secondary Text:", "False"),
            ConfigOption("indicator_secondary_align", "dropdown", "Align:", "center", options_dict=align_opts),
            ConfigOption("indicator_secondary_font", "font", "Font:", "Sans 10"),
            ConfigOption("indicator_secondary_color", "color", "Color:", "rgba(200,200,200,1)"),
        ]
        return model

    def get_configure_callback(self):
        """A custom callback to dynamically show/hide shape and color stop widgets."""
        def setup_dynamic_options(dialog, content_box, widgets, available_sources, panel_config):
            # --- Color Stop Logic ---
            color_count_spinner = widgets.get("indicator_color_count")
            if color_count_spinner:
                stop_widgets = []
                for i in range(1, 11): 
                    val_widget = widgets.get(f"indicator_percent{i}")
                    col_widget = widgets.get(f"indicator_color{i}")
                    if val_widget and col_widget:
                        stop_widgets.append({
                            "value_row": val_widget.get_parent(),
                            "color_row": col_widget.get_parent().get_parent(),
                        })

                def on_color_count_changed(spinner):
                    count = spinner.get_value_as_int()
                    for i, widget_group in enumerate(stop_widgets, 1):
                        is_visible = i <= count
                        widget_group["value_row"].set_visible(is_visible)
                        widget_group["color_row"].set_visible(is_visible)
                        value_widget = widget_group["value_row"].get_first_child()
                        if i == 1: value_widget.set_text(f"Percent for Color 1 (Min):")
                        elif i == count: value_widget.set_text(f"Percent for Color {i} (Max):")
                        else: value_widget.set_text(f"Percent for Color {i}:")

                color_count_spinner.connect("value-changed", on_color_count_changed)
                GLib.idle_add(on_color_count_changed, color_count_spinner)

            # --- Shape Logic ---
            shape_combo = widgets.get("indicator_shape")
            if shape_combo:
                aspect_widget = widgets.get("indicator_square_keep_aspect")
                sides_widget = widgets.get("indicator_polygon_sides")
                
                def on_shape_changed(combo):
                    shape = combo.get_active_id()
                    if aspect_widget: aspect_widget.get_parent().set_visible(shape == "square")
                    if sides_widget: sides_widget.get_parent().set_visible(shape == "polygon")

                shape_combo.connect("changed", on_shape_changed)
                GLib.idle_add(on_shape_changed, shape_combo)

        return setup_dynamic_options

    def apply_styles(self):
        super().apply_styles()
        self._layout_primary = None
        self._layout_main = None
        self._layout_secondary = None
        self.widget.queue_draw()

    def on_draw(self, area, ctx, width, height):
        if width <= 0 or height <= 0: return

        # --- Calculate Color ---
        min_v = float(self.config.get("graph_min_value", 0.0))
        max_v = float(self.config.get("graph_max_value", 100.0))
        v_range = max_v - min_v if max_v > min_v else 1.0

        num_stops = int(self.config.get("indicator_color_count", 3))
        stops = []
        for i in range(1, num_stops + 1):
            try:
                percent = float(self.config.get(f"indicator_percent{i}"))
                val = min_v + (v_range * (percent / 100.0))
                col = self.config.get(f"indicator_color{i}")
                stops.append({'val': val, 'col': col})
            except (ValueError, TypeError): continue
        stops.sort(key=lambda s: s['val'])

        final_color_str = "rgba(0,0,0,1)"
        if stops:
            if self.current_value <= stops[0]['val']: final_color_str = stops[0]['col']
            elif self.current_value >= stops[-1]['val']: final_color_str = stops[-1]['col']
            else:
                for i in range(len(stops) - 1):
                    s1, s2 = stops[i], stops[i+1]
                    if s1['val'] <= self.current_value < s2['val']:
                        stop_v_range = s2['val'] - s1['val']
                        factor = (self.current_value - s1['val']) / stop_v_range if stop_v_range > 0 else 0
                        inter_color = self._interpolate_color(factor, s1['col'], s2['col'])
                        final_color_str = inter_color.to_string()
                        break
        
        current_c = Gdk.RGBA(); current_c.parse(final_color_str)
        ctx.set_source_rgba(current_c.red, current_c.green, current_c.blue, current_c.alpha)

        # --- Draw Shape ---
        shape = self.config.get("indicator_shape", "full_panel")
        padding = float(self.config.get("indicator_shape_padding", 10))

        if shape == "full_panel":
            ctx.rectangle(0, 0, width, height); ctx.fill()
        elif shape == "circle":
            radius = (min(width, height) / 2) - padding
            if radius > 0:
                ctx.arc(width / 2, height / 2, radius, 0, 2 * math.pi); ctx.fill()
        elif shape == "square":
            keep_aspect = str(self.config.get("indicator_square_keep_aspect", "True")).lower() == 'true'
            if keep_aspect:
                size = min(width, height) - (2 * padding)
                if size > 0:
                    rect_x = (width - size) / 2
                    rect_y = (height - size) / 2
                    ctx.rectangle(rect_x, rect_y, size, size); ctx.fill()
            else:
                rect_x, rect_y = padding, padding
                rect_w, rect_h = width - 2 * padding, height - 2 * padding
                if rect_w > 0 and rect_h > 0:
                    ctx.rectangle(rect_x, rect_y, rect_w, rect_h); ctx.fill()
        elif shape == "polygon":
            sides = int(self.config.get("indicator_polygon_sides", 6))
            if sides >= 3:
                radius = (min(width, height) / 2) - padding
                if radius > 0:
                    cx, cy = width / 2, height / 2
                    ctx.new_path()
                    for i in range(sides):
                        angle = (i / sides) * 2 * math.pi - (math.pi / 2)
                        x = cx + radius * math.cos(angle)
                        y = cy + radius * math.sin(angle)
                        if i == 0: ctx.move_to(x, y)
                        else: ctx.line_to(x, y)
                    ctx.close_path(); ctx.fill()
        
        # --- Draw Text ---
        self._draw_text_block(ctx, width, height)

    def _draw_text_block(self, ctx, width, height):
        """Draws the primary, main, and secondary text block."""
        spacing = int(self.config.get("indicator_text_spacing", 4))
        
        text_elements = []
        if str(self.config.get("indicator_primary_show", "True")).lower() == 'true' and self.primary_text:
            text_elements.append({"type": "primary", "text": self.primary_text})
        if str(self.config.get("indicator_main_show", "True")).lower() == 'true' and self.main_text:
            text_elements.append({"type": "main", "text": self.main_text})
        if str(self.config.get("indicator_secondary_show", "True")).lower() == 'true' and self.secondary_text:
            text_elements.append({"type": "secondary", "text": self.secondary_text})
        
        if not text_elements: return
        
        total_text_height = 0
        
        for element in text_elements:
            layout_cache_attr = f"_layout_{element['type']}"
            layout = getattr(self, layout_cache_attr, None)
            if layout is None:
                layout = self.widget.create_pango_layout("")
                setattr(self, layout_cache_attr, layout)

            font_str = self.config.get(f"indicator_{element['type']}_font")
            layout.set_font_description(Pango.FontDescription.from_string(font_str))
            layout.set_text(element['text'], -1)
            element['layout'] = layout
            element['height'] = layout.get_pixel_extents()[1].height
            total_text_height += element['height']
        
        if len(text_elements) > 1:
            total_text_height += (len(text_elements) - 1) * spacing
            
        v_align = self.config.get("indicator_text_vertical_align", "center")
        if v_align == "start": current_y = 0
        elif v_align == "end": current_y = height - total_text_height
        else: current_y = (height - total_text_height) / 2
        
        for element in text_elements:
            layout = element['layout']
            
            rgba = Gdk.RGBA()
            color_str = self.config.get(f"indicator_{element['type']}_color")
            rgba.parse(color_str)
            ctx.set_source_rgba(rgba.red, rgba.green, rgba.blue, rgba.alpha)
            
            align_str = self.config.get(f"indicator_{element['type']}_align", "center")
            text_width = layout.get_pixel_extents()[1].width
            
            if align_str == "left": current_x = 0
            elif align_str == "right": current_x = width - text_width
            else: current_x = (width - text_width) / 2
            
            ctx.move_to(current_x, current_y)
            PangoCairo.show_layout(ctx, layout)
            
            current_y += element['height'] + spacing

