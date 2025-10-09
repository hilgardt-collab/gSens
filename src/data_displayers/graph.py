# /data_displayers/graph.py
import gi
import time
import os
import cairo
import math
from data_displayer import DataDisplayer
from config_dialog import ConfigOption, build_ui_from_model
from utils import populate_defaults_from_model
from ui_helpers import build_background_config_ui, draw_cairo_background, get_background_config_model
from .text import TextDisplayer

gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gtk, Gdk, GLib, Pango, PangoCairo, GdkPixbuf

# Inherit from TextDisplayer to get all of its text rendering capabilities
class GraphDisplayer(TextDisplayer):
    """
    A highly configurable data displayer that shows a value as a line graph
    or bar chart, with a powerful multi-line text overlay system inherited
    from TextDisplayer.
    """
    def __init__(self, panel_ref, config):
        self.history = []
        self._cached_bg_pixbuf = None
        self._cached_image_path = None
        self.alarm_config_prefix = "data_"
        
        # Initialize the parent TextDisplayer, which sets up all text handling
        super().__init__(panel_ref, config)
        
        # Populate with any missing graph-specific defaults
        # The parent's __init__ already populates text defaults
        populate_defaults_from_model(self.config, self._get_graph_config_model_definition())

    # _create_widget is inherited from TextDisplayer, we just need to alias the widget
    @property
    def graph_area(self):
        return self.widget

    def update_display(self, value, **kwargs):
        """
        Updates both the graph history and the text lines for the overlay.
        """
        # Let the parent TextDisplayer handle updating the text lines based on its config
        super().update_display(value, **kwargs)

        # Now, handle the graph-specific data
        source = kwargs.get('source_override', self.panel_ref.data_source if self.panel_ref else None)
        if source is None: return
        
        # Store the alarm prefix from the specific source for this update cycle
        self.alarm_config_prefix = getattr(source, 'alarm_config_prefix', 'data_')

        num_val = source.get_numerical_value(value)
        
        max_hist = int(self.config.get("max_history_points", 100))
        if num_val is not None:
            self.history.append((time.time(), num_val))
            if len(self.history) > max_hist:
                self.history = self.history[-max_hist:]
            
        # The parent's update_display already queues a draw, so this is redundant
        # self.graph_area.queue_draw()

    @staticmethod
    def get_config_model():
        """
        Returns an empty model. All UI is built in the get_configure_callback
        to prevent the DataPanel from drawing a default UI.
        """
        return {}
        
    def get_all_style_keys(self):
        """
        Returns a combined set of style keys from the graph's own model
        and its parent TextDisplayer model.
        """
        # Get graph-specific keys from its internal model definition
        graph_model = self._get_graph_config_model_definition()
        graph_keys = {opt.key for section in graph_model.values() for opt in section}
        
        # Get all text-related keys from the parent class
        text_keys = super().get_all_style_keys()
        
        # Get background keys
        background_keys = {opt.key for section in get_background_config_model("graph_").values() for opt in section}
        
        # Combine them into a single set
        return graph_keys.union(text_keys).union(background_keys)

    @staticmethod
    def _get_graph_config_model_definition():
        """
        Internal static method to define the graph-specific config model.
        This is used by the configure callback to build the UI.
        """
        model = {}
        controller_key = "graph_type"

        model["Graph Visuals"] = [
            ConfigOption(controller_key, "dropdown", "Graph Type:", "line", 
                         options_dict={"Line Chart": "line", "Bar Chart": "bar"}),
            ConfigOption("graph_line_color", "color", "Line/Border Color:", "rgba(255,0,0,0.8)"),
            ConfigOption("graph_line_width", "spinner", "Line/Border Width:", 2.0, 0.5, 10.0, 0.5, 1),
            ConfigOption("graph_line_style", "dropdown", "Line Style:", "sharp", 
                         options_dict={"Sharp": "sharp", "Smooth": "smooth"},
                         dynamic_group=controller_key, dynamic_show_on="line"),
            ConfigOption("graph_fill_enabled", "bool", "Fill (Line/Bar):", "True"),
            ConfigOption("graph_fill_color", "color", "Fill Color:", "rgba(255,0,0,0.2)")
        ]
        model["Graph Data"] = [ConfigOption("max_history_points", "spinner", "History Points:", 100, 10, 1000, 10, 0)]
        model["Grid Lines"] = [
            ConfigOption("graph_grid_enabled", "bool", "Show Grid:", "False"),
            ConfigOption("graph_grid_x_divisions", "spinner", "Vertical Divisions:", 5, 1, 50, 1, 0),
            ConfigOption("graph_grid_y_divisions", "spinner", "Horizontal Divisions:", 4, 1, 50, 1, 0),
            ConfigOption("graph_grid_color", "color", "Grid Color:", "rgba(128,128,128,0.3)"),
            ConfigOption("graph_grid_width", "spinner", "Grid Line Width:", 1.0, 0.5, 5.0, 0.5, 1)
        ]
        return model

    def get_configure_callback(self):
        """
        Builds a combined configuration UI with a notebook for Graph Style,
        Text Overlay, and Background.
        """
        def build_dynamic_display_config(dialog, content_box, widgets, available_sources, panel_config, prefix=None):
            notebook = Gtk.Notebook()
            content_box.append(notebook)

            # --- Tab 1: Graph Style ---
            graph_page_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
            graph_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
            graph_page_scroll.set_child(graph_page)
            
            # Fetch the model definition locally
            graph_model = self._get_graph_config_model_definition()
            build_ui_from_model(graph_page, panel_config, graph_model, widgets)
            dialog.dynamic_models.append(graph_model)
            notebook.append_page(graph_page_scroll, Gtk.Label(label="Graph Style"))
            
            # --- Tab 2: Text Overlay ---
            text_page_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
            text_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
            text_page_scroll.set_child(text_page)
            
            # Get the config model and callback from the parent TextDisplayer class
            text_model = TextDisplayer.get_config_model()
            text_cb = TextDisplayer(None, panel_config).get_configure_callback()

            # Build the text UI using the parent's logic
            build_ui_from_model(text_page, panel_config, text_model, widgets)
            if text_cb:
                # The text_cb from TextDisplayer will build the per-line UI
                text_cb(dialog, text_page, widgets, available_sources, panel_config, prefix)
            
            dialog.dynamic_models.append(text_model)
            notebook.append_page(text_page_scroll, Gtk.Label(label="Text Overlay"))

            # --- Tab 3: Background ---
            bg_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
            build_background_config_ui(bg_page, panel_config, widgets, dialog, prefix="graph_", title="Graph Background")
            notebook.append_page(bg_page, Gtk.Label(label="Background"))

        return build_dynamic_display_config

    def apply_styles(self):
        # Call the parent (TextDisplayer) apply_styles first to handle text caches
        super().apply_styles()
        
        # Now handle graph-specific style updates
        image_path = self.config.get("graph_background_image_path", "")
        if self._cached_image_path != image_path:
            self._cached_image_path = image_path
            self._cached_bg_pixbuf = GdkPixbuf.Pixbuf.new_from_file(image_path) if image_path and os.path.exists(image_path) else None
        
        # The parent's apply_styles already queues a draw, so this is redundant

    def on_draw(self, area, ctx, width, height):
        if width <= 0 or height <= 0: return

        # --- 1. Draw Graph Background and Grid ---
        is_alarm = self.panel_ref is not None and self.panel_ref.is_in_alarm_state and self.panel_ref._alarm_flash_on
        if is_alarm:
            bg_color_str = self.config.get(self.alarm_config_prefix + "alarm_color", "rgba(255,0,0,0.6)")
            bg_rgba = Gdk.RGBA(); bg_rgba.parse(bg_color_str)
            ctx.set_source_rgba(bg_rgba.red, bg_rgba.green, bg_rgba.blue, bg_rgba.alpha)
            ctx.paint()
        else:
            draw_cairo_background(ctx, width, height, self.config, "graph_", self._cached_bg_pixbuf)

        if str(self.config.get("graph_grid_enabled", "False")).lower() == 'true':
            self._draw_grid(ctx, width, height)

        # --- 2. Draw Graph Data (Lines or Bars) ---
        if len(self.history) >= 2:
            self._draw_graph_data(ctx, width, height)
        
        # --- 3. Draw Text Overlay ---
        # Call the parent TextDisplayer's on_draw method to render the text on top
        super().on_draw(area, ctx, width, height)

    def _draw_grid(self, ctx, width, height):
        grid_rgba = Gdk.RGBA(); grid_rgba.parse(self.config.get("graph_grid_color"))
        ctx.set_source_rgba(grid_rgba.red, grid_rgba.green, grid_rgba.blue, grid_rgba.alpha)
        ctx.set_line_width(float(self.config.get("graph_grid_width", 1.0)))
        
        x_divs = int(self.config.get("graph_grid_x_divisions", 5))
        y_divs = int(self.config.get("graph_grid_y_divisions", 4))

        if x_divs > 0:
            x_step = width / x_divs
            for i in range(1, x_divs):
                ctx.move_to(i * x_step, 0); ctx.line_to(i * x_step, height); ctx.stroke()
        
        if y_divs > 0:
            y_step = height / y_divs
            for i in range(1, y_divs):
                ctx.move_to(0, i * y_step); ctx.line_to(width, i * y_step); ctx.stroke()

    def _draw_graph_data(self, ctx, width, height):
        timestamps, values = zip(*self.history)
        min_y, max_y = float(self.config.get("graph_min_value", 0.0)), float(self.config.get("graph_max_value", 100.0))
        y_range = max_y - min_y if max_y > min_y else 1
        
        max_hist = int(self.config.get("max_history_points", 100))
        num_points = len(values)
        
        x_step = width / (max_hist - 1) if max_hist > 1 else width
        start_x = width - ((num_points - 1) * x_step)

        points = [(start_x + (i * x_step), height - ((max(min_y, min(v, max_y)) - min_y) / y_range * height)) for i, v in enumerate(values)]

        graph_type = self.config.get("graph_type", "line")
        
        if graph_type == "bar":
            self._draw_bar_chart(ctx, points, x_step, height)
        else: # Line Chart
            self._draw_line_chart(ctx, points, height)

    def _draw_bar_chart(self, ctx, points, x_step, height):
        bar_width = x_step
        fill_rgba = Gdk.RGBA(); fill_rgba.parse(self.config.get("graph_fill_color"))
        line_rgba = Gdk.RGBA(); line_rgba.parse(self.config.get("graph_line_color"))
        line_width = float(self.config.get("graph_line_width", 2.0))

        for p in points:
            bar_x = p[0] - (bar_width / 2)
            if str(self.config.get("graph_fill_enabled", "False")).lower() == 'true':
                ctx.set_source_rgba(fill_rgba.red, fill_rgba.green, fill_rgba.blue, fill_rgba.alpha)
                ctx.rectangle(bar_x, p[1], bar_width, height - p[1]); ctx.fill()
            if line_width > 0:
                ctx.set_source_rgba(line_rgba.red, line_rgba.green, line_rgba.blue, line_rgba.alpha)
                ctx.set_line_width(line_width)
                ctx.rectangle(bar_x, p[1], bar_width, height - p[1]); ctx.stroke()

    def _draw_line_chart(self, ctx, points, height):
        ctx.new_path(); ctx.move_to(points[0][0], points[0][1])
        line_style = self.config.get("graph_line_style", "sharp")
        if line_style == "smooth" and len(points) > 2:
            for i in range(len(points) - 1):
                p0, p1, p2 = points[i-1] if i > 0 else points[i], points[i], points[i+1]
                p3 = points[i+2] if i < len(points) - 2 else p2
                cp1x, cp1y = p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6
                cp2x, cp2y = p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6
                ctx.curve_to(cp1x, cp1y, cp2x, cp2y, p2[0], p2[1])
        else: # Sharp
            for p in points[1:]: ctx.line_to(p[0], p[1])
        
        if str(self.config.get("graph_fill_enabled", "False")).lower() == 'true':
            fill_rgba = Gdk.RGBA(); fill_rgba.parse(self.config.get("graph_fill_color"))
            ctx.set_source_rgba(fill_rgba.red, fill_rgba.green, fill_rgba.blue, fill_rgba.alpha)
            ctx.line_to(points[-1][0], height); ctx.line_to(points[0][0], height); ctx.close_path(); ctx.fill_preserve()
        
        line_rgba = Gdk.RGBA(); line_rgba.parse(self.config.get("graph_line_color"))
        ctx.set_source_rgba(line_rgba.red, line_rgba.green, line_rgba.blue, line_rgba.alpha)
        ctx.set_line_width(float(self.config.get("graph_line_width", 2.0))); ctx.stroke()

