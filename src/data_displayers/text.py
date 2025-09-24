# data_displayers/text.py
import gi
import math
import cairo
from data_displayer import DataDisplayer
from config_dialog import ConfigOption, build_ui_from_model
from utils import populate_defaults_from_model

gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gtk, Gdk, GLib, Pango, PangoCairo

class TextDisplayer(DataDisplayer):
    """
    A highly configurable displayer that renders multiple lines of text directly
    onto a Cairo surface for maximum control over layout and appearance.
    """
    def __init__(self, panel_ref, config):
        self._text_lines = []
        self._layout_cache = []
        self._last_data = None
        super().__init__(panel_ref, config)
        populate_defaults_from_model(self.config, self.get_config_model())

        line_count = int(self.config.get("text_line_count", "2"))
        for i in range(1, line_count + 1):
            self.config.setdefault(f"line{i}_source", "primary_label" if i == 1 else "display_string")
            self.config.setdefault(f"line{i}_custom_text", "")
            self.config.setdefault(f"line{i}_align", "center")
            self.config.setdefault(f"line{i}_font", "Sans Italic 12" if i == 1 else "Sans Bold 18")
            self.config.setdefault(f"line{i}_color", "rgba(220,220,220,1)")
            self.config.setdefault(f"line{i}_slant", "0")
            self.config.setdefault(f"line{i}_rotation", "0") 
        
        self._initialize_text_lines()

    def _create_widget(self):
        """Creates a single drawing area for the entire displayer."""
        drawing_area = Gtk.DrawingArea(vexpand=True, hexpand=True)
        drawing_area.set_draw_func(self.on_draw)
        return drawing_area

    def _initialize_text_lines(self):
        """Pre-populates the text line data structure based on config."""
        line_count = int(self.config.get("text_line_count", "2"))
        self._text_lines = [""] * line_count
        self._layout_cache = [None] * line_count

    def update_display(self, data, **kwargs):
        """Updates the text content for each line and queues a redraw."""
        source = kwargs.get('source_override', self.panel_ref.data_source if self.panel_ref else None)
        if source is None: return

        if data is not None:
            self._last_data = data
        
        data_to_use = data if data is not None else self._last_data
        
        line_count = int(self.config.get("text_line_count", "2"))
        if len(self._text_lines) != line_count:
            self._initialize_text_lines()

        for i in range(line_count):
            line_num = i + 1
            source_key = self.config.get(f"line{line_num}_source", "display_string")
            
            text = "N/A"
            if data_to_use is not None:
                if source_key == "primary_label":
                    text = kwargs.get('caption', source.get_primary_label_string(data_to_use))
                elif source_key == "secondary_label":
                    text = source.get_secondary_display_string(data_to_use)
                elif source_key == "tooltip_string":
                    text = source.get_tooltip_string(data_to_use)
                elif source_key == "custom_text":
                    text = self.config.get(f"line{line_num}_custom_text", "")
                else: # display_string
                    text = source.get_display_string(data_to_use)
            
            self._text_lines[i] = text or ""
        
        if self.panel_ref and data_to_use is not None:
            self.panel_ref.set_tooltip_text(source.get_tooltip_string(data_to_use))
        
        self.widget.queue_draw()

    @staticmethod
    def get_config_model():
        """Returns the static configuration options for the layout."""
        model = DataDisplayer.get_config_model()
        align_opts = {"Left": "left", "Center": "center", "Right": "right"}
        model["Layout"] = [
            ConfigOption("text_line_count", "spinner", "Number of Lines:", "2", 1, 10, 1, 0),
            ConfigOption("text_vertical_align", "dropdown", "Vertical Align:", "center", 
                         options_dict={"Top": "start", "Center": "center", "Bottom": "end"}),
            ConfigOption("text_spacing", "spinner", "Spacing (px):", 4, 0, 50, 1, 0)
        ]
        return model

    @staticmethod
    def get_config_key_prefixes():
        """
        Returns the unique prefixes used for theme saving, including dynamically
        generated prefixes for each possible line.
        """
        return ["text_"] + [f"line{i}_" for i in range(1, 11)]

    def get_configure_callback(self):
        """A custom callback to dynamically build the UI for each text line."""
        def build_dynamic_line_configs(dialog, content_box, widgets, available_sources, panel_config, prefix=None):
            prefix_ = f"{prefix}_" if prefix else ""
            line_count_spinner = widgets.get(f"{prefix_}text_line_count")
            if not line_count_spinner: return

            lines_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            content_box.append(lines_container)

            def _rebuild_line_ui(spinner):
                child = lines_container.get_first_child()
                while child: lines_container.remove(child); child = lines_container.get_first_child()
                
                keys_to_remove = [k for k in widgets if k.startswith(f"{prefix_}line")]
                for k in keys_to_remove: widgets.pop(k, None)
                
                dialog.dynamic_models = [m for m in dialog.dynamic_models if not any(opt.key.startswith(f"{prefix_}line") for s in m.values() for opt in s)]

                count = spinner.get_value_as_int()
                for i in range(1, count + 1):
                    frame = Gtk.Frame(label=f"Line {i} Settings", margin_top=6)
                    lines_container.append(frame)
                    
                    line_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, 
                                       margin_top=5, margin_bottom=5, margin_start=5, margin_end=5)
                    frame.set_child(line_box)
                    
                    source_opts = {"Main Display String": "display_string", "Primary Label": "primary_label", "Secondary Label": "secondary_label", "Tooltip Text": "tooltip_string", "Custom Static Text": "custom_text"}
                    align_opts = {"Left": "left", "Center": "center", "Right": "right"}

                    line_model = {"": [
                        ConfigOption(f"{prefix_}line{i}_source", "dropdown", "Text Source:", "display_string", options_dict=source_opts),
                        ConfigOption(f"{prefix_}line{i}_custom_text", "string", "Custom Text:", ""),
                        ConfigOption(f"{prefix_}line{i}_align", "dropdown", "Align:", "center", options_dict=align_opts),
                        ConfigOption(f"{prefix_}line{i}_font", "font", "Font:", "Sans 12"),
                        ConfigOption(f"{prefix_}line{i}_color", "color", "Color:", "rgba(220,220,220,1)"),
                        ConfigOption(f"{prefix_}line{i}_slant", "spinner", "Slant (deg):", 0, -45, 45, 1, 0),
                        ConfigOption(f"{prefix_}line{i}_rotation", "spinner", "Rotation (deg):", 0, -180, 180, 5, 0),
                    ]}
                    
                    build_ui_from_model(line_box, panel_config, line_model, widgets)
                    dialog.dynamic_models.append(line_model)
                    
                    source_combo = widgets[f"{prefix_}line{i}_source"]
                    custom_text_row = widgets[f"{prefix_}line{i}_custom_text"].get_parent()
                    
                    def on_source_changed(combo, row):
                        row.set_visible(combo.get_active_id() == "custom_text")
                    
                    source_combo.connect("changed", on_source_changed, custom_text_row)
                    GLib.idle_add(on_source_changed, source_combo, custom_text_row)

            line_count_spinner.connect("value-changed", _rebuild_line_ui)
            GLib.idle_add(_rebuild_line_ui, line_count_spinner)

        return build_dynamic_line_configs

    def apply_styles(self):
        """Forces a redraw when styles change and ensures text line buffer is correct."""
        super().apply_styles()
        
        self.update_display(None)

    def on_draw(self, area, ctx, width, height):
        """Draws all configured text lines onto the Cairo context."""
        if width <= 0 or height <= 0: return

        line_count = int(self.config.get("text_line_count", "2"))
        spacing = int(self.config.get("text_spacing", 4))
        
        layouts_to_draw = []
        total_text_height = 0
        
        for i in range(min(line_count, len(self._text_lines))):
            layout = self._layout_cache[i]
            if layout is None:
                layout = self.widget.create_pango_layout("")
                self._layout_cache[i] = layout

            line_num = i + 1
            font_str = self.config.get(f"line{line_num}_font", "Sans 12")
            layout.set_font_description(Pango.FontDescription.from_string(font_str))
            layout.set_text(self._text_lines[i], -1)
            layouts_to_draw.append(layout)
            total_text_height += layout.get_pixel_extents()[1].height
        
        if len(layouts_to_draw) > 1:
            total_text_height += (len(layouts_to_draw) - 1) * spacing

        v_align = self.config.get("text_vertical_align", "center")
        if v_align == "start":
            current_y = 0
        elif v_align == "end":
            current_y = height - total_text_height
        else: # center
            current_y = (height - total_text_height) / 2

        for i, layout in enumerate(layouts_to_draw):
            line_num = i + 1
            
            ctx.save()

            rgba = Gdk.RGBA()
            color_str = self.config.get(f"line{line_num}_color", "rgba(220,220,220,1)")
            rgba.parse(color_str)
            ctx.set_source_rgba(rgba.red, rgba.green, rgba.blue, rgba.alpha)

            align_str = self.config.get(f"line{line_num}_align", "center")
            text_width = layout.get_pixel_extents()[1].width
            text_height = layout.get_pixel_extents()[1].height
            
            if align_str == "left":
                current_x = 0
            elif align_str == "right":
                current_x = width - text_width
            else: # center
                current_x = (width - text_width) / 2
            
            slant_deg = float(self.config.get(f"line{line_num}_slant", "0"))
            rotation_deg = float(self.config.get(f"line{line_num}_rotation", "0"))

            ctx.translate(current_x + text_width / 2, current_y + text_height / 2)
            
            if rotation_deg != 0:
                ctx.rotate(math.radians(rotation_deg))
            
            if slant_deg != 0:
                slant_rad = math.radians(slant_deg)
                matrix = cairo.Matrix(1, 0, math.tan(slant_rad), 1, 0, 0)
                ctx.transform(matrix)

            ctx.move_to(-text_width / 2, -text_height / 2)
            PangoCairo.show_layout(ctx, layout)
            
            ctx.restore()
            
            current_y += text_height + spacing

