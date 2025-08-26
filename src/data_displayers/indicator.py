# data_displayers/indicator.py
import gi
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
    gradient with 2 to 6 color stops.
    """
    def __init__(self, panel_ref, config):
        self.current_value = 0.0
        self.display_text = ""
        super().__init__(panel_ref, config)
        populate_defaults_from_model(self.config, self.get_config_model())

    def _create_widget(self):
        drawing_area = Gtk.DrawingArea(hexpand=True, vexpand=True)
        drawing_area.set_draw_func(self.on_draw_indicator)
        return drawing_area

    def update_display(self, value):
        if not self.panel_ref: return # Guard against race condition on close
        self.current_value = self.panel_ref.data_source.get_numerical_value(value) or 0.0
        self.display_text = self.panel_ref.data_source.get_display_string(value)
        self.widget.queue_draw()

    @staticmethod
    def get_config_model():
        model = DataDisplayer.get_config_model()
        model["Indicator Colors & Stops"] = [
            ConfigOption("indicator_color_count", "spinner", "Number of Colors:", 3, 2, 6, 1, 0),
            ConfigOption("indicator_value1", "spinner", "Value for Color 1 (Min):", 0, -10000, 10000, 1, 1),
            ConfigOption("indicator_color1", "color", "Color 1:", "rgba(0,128,255,1)"),
            ConfigOption("indicator_value2", "spinner", "Value for Color 2:", 50, -10000, 10000, 1, 1),
            ConfigOption("indicator_color2", "color", "Color 2:", "rgba(255,255,0,1)"),
            ConfigOption("indicator_value3", "spinner", "Value for Color 3 (Max):", 100, -10000, 10000, 1, 1),
            ConfigOption("indicator_color3", "color", "Color 3:", "rgba(255,0,0,1)"),
            ConfigOption("indicator_value4", "spinner", "Value for Color 4:", 100, -10000, 10000, 1, 1),
            ConfigOption("indicator_color4", "color", "Color 4:", "rgba(255,255,255,1)"),
            ConfigOption("indicator_value5", "spinner", "Value for Color 5:", 100, -10000, 10000, 1, 1),
            ConfigOption("indicator_color5", "color", "Color 5:", "rgba(255,255,255,1)"),
            ConfigOption("indicator_value6", "spinner", "Value for Color 6:", 100, -10000, 10000, 1, 1),
            ConfigOption("indicator_color6", "color", "Color 6:", "rgba(255,255,255,1)"),
        ]
        model["Indicator Text"] = [
            ConfigOption("indicator_show_text", "bool", "Show Text Value:", "True"),
            ConfigOption("indicator_text_font", "font", "Text Font:", "Sans 12"),
            ConfigOption("indicator_text_color", "color", "Text Color:", "rgba(255,255,255,1)")
        ]
        return model

    def get_configure_callback(self):
        """A custom callback to dynamically show/hide color stop widgets."""
        def setup_dynamic_color_stops(dialog, content_box, widgets, available_sources, panel_config):
            # The standard UI is now built by data_panel.py before this callback is called.

            color_count_spinner = widgets.get("indicator_color_count")
            if not color_count_spinner:
                return

            # Find the parent boxes of the optional color stop widgets
            stop_widgets = []
            for i in range(3, 7): # Stops 3, 4, 5, 6 are optional
                val_widget = widgets.get(f"indicator_value{i}")
                if val_widget:
                    # The parent of the value spinner is the Gtk.Box row for that stop
                    stop_widgets.append(val_widget.get_parent())

            def on_color_count_changed(spinner):
                count = spinner.get_value_as_int()
                
                # Update the label of the last visible stop to say "(Max)"
                for i in range(2, 7):
                    value_widget = widgets.get(f"indicator_value{i}")
                    if value_widget:
                        label = value_widget.get_parent().get_first_child()
                        if i == count:
                            label.set_text(f"Value for Color {i} (Max):")
                        else:
                            label.set_text(f"Value for Color {i}:")

                # Show/hide the optional stop rows
                for i, box in enumerate(stop_widgets, 3):
                    box.set_visible(i <= count)

            color_count_spinner.connect("value-changed", on_color_count_changed)
            # Run once to set the initial state
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
                col = self.config.get(f"indicator_color{i}")
                stops.append({'val': val, 'col': col})
            except (ValueError, TypeError):
                continue
        
        stops.sort(key=lambda s: s['val'])

        final_color_str = "rgba(0,0,0,1)"
        
        if not stops:
            pass # Keep default black color if no stops are configured
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
        
        if str(self.config.get("indicator_show_text", "True")).lower() == 'true':
            layout = PangoCairo.create_layout(ctx)
            layout.set_font_description(Pango.FontDescription.from_string(self.config.get("indicator_text_font")))
            layout.set_text(self.display_text, -1)
            _, log = layout.get_pixel_extents()
            text_c = Gdk.RGBA()
            text_c.parse(self.config.get("indicator_text_color"))
            ctx.set_source_rgba(text_c.red, text_c.green, text_c.blue, text_c.alpha)
            ctx.move_to((width - log.width) / 2, (height - log.height) / 2)
            PangoCairo.show_layout(ctx, layout)
