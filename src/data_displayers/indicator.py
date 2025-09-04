# data_displayers/indicator.py
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
    """
    def __init__(self, panel_ref, config):
        self.current_value = 0.0
        self.primary_text = ""
        self.main_text = ""
        self.secondary_text = ""
        super().__init__(panel_ref, config)
        populate_defaults_from_model(self.config, self.get_config_model())

    def _create_widget(self):
        drawing_area = Gtk.DrawingArea(hexpand=True, vexpand=True)
        drawing_area.set_draw_func(self.on_draw_indicator)
        return drawing_area

    def update_display(self, value):
        if not self.panel_ref: return # Guard against race condition on close
        self.current_value = self.panel_ref.data_source.get_numerical_value(value) or 0.0
        
        self.primary_text = self.panel_ref.data_source.get_primary_label_string(value)
        self.main_text = self.panel_ref.data_source.get_display_string(value)
        self.secondary_text = self.panel_ref.data_source.get_secondary_display_string(value)

        self.widget.queue_draw()

    @staticmethod
    def get_config_model():
        model = DataDisplayer.get_config_model()
        
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
                ConfigOption(f"indicator_value{i}", "spinner", f"Value for Color {i}{label_suffix}:", f"{default_val:.1f}", -10000, 10000, 1, 1),
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
        """A custom callback to dynamically show/hide color stop widgets."""
        def setup_dynamic_color_stops(dialog, content_box, widgets, available_sources, panel_config):
            color_count_spinner = widgets.get("indicator_color_count")
            if not color_count_spinner:
                return

            stop_widgets = []
            for i in range(1, 11): 
                val_widget = widgets.get(f"indicator_value{i}")
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
                    if i == 1:
                        value_widget.set_text(f"Value for Color 1 (Min):")
                    elif i == count:
                        value_widget.set_text(f"Value for Color {i} (Max):")
                    else:
                        value_widget.set_text(f"Value for Color {i}:")

            color_count_spinner.connect("value-changed", on_color_count_changed)
            GLib.idle_add(on_color_count_changed, color_count_spinner)

        return setup_dynamic_color_stops

    def apply_styles(self):
        super().apply_styles()
        self.widget.queue_draw()

    def on_draw_indicator(self, area, ctx, width, height):
        if width <= 0 or height <= 0: return

        num_stops = int(self.config.get("indicator_color_count", 3))
        stops = []
        for i in range(1, num_stops + 1):
            try:
                val = float(self.config.get(f"indicator_value{i}"))
                # --- FIX: Removed the extra closing parenthesis ---
                col = self.config.get(f"indicator_color{i}")
                stops.append({'val': val, 'col': col})
            except (ValueError, TypeError):
                continue
        
        stops.sort(key=lambda s: s['val'])

        final_color_str = "rgba(0,0,0,1)"
        
        if not stops:
            pass
        elif self.current_value <= stops[0]['val']:
            final_color_str = stops[0]['col']
        elif self.current_value >= stops[-1]['val']:
            final_color_str = stops[-1]['col']
        else:
            for i in range(len(stops) - 1):
                s1, s2 = stops[i], stops[i+1]
                if s1['val'] <= self.current_value < s2['val']:
                    v_range = s2['val'] - s1['val']
                    factor = (self.current_value - s1['val']) / v_range if v_range > 0 else 0
                    inter_color = self._interpolate_color(factor, s1['col'], s2['col'])
                    final_color_str = inter_color.to_string()
                    break
        
        current_c = Gdk.RGBA()
        current_c.parse(final_color_str)
        ctx.set_source_rgba(current_c.red, current_c.green, current_c.blue, current_c.alpha)
        ctx.rectangle(0, 0, width, height)
        ctx.fill()
        
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
            layout = PangoCairo.create_layout(ctx)
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

