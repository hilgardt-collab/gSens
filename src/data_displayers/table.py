# /data_displayers/table.py
import gi
import cairo
from data_displayer import DataDisplayer
from config_dialog import ConfigOption, build_ui_from_model
from utils import populate_defaults_from_model

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Pango, Gdk, GLib, PangoCairo

class TableDisplayer(DataDisplayer):
    """
    Displays list-based data in a custom-drawn table using a Cairo DrawingArea
    for complete, dynamic, and user-configurable styling control.
    """
    def __init__(self, panel_ref, config):
        self._process_data = []
        self._header_layout_cache = {} 
        # OPTIMIZATION: Reuse a single layout object for cell rendering to avoid thrashing
        self._reusable_cell_layout = None 
        super().__init__(panel_ref, config)
        populate_defaults_from_model(self.config, self.get_config_model())
        self._set_initial_defaults()
        self.apply_styles()

    def _set_initial_defaults(self):
        """Sets reasonable defaults for the first few columns if they don't exist."""
        # Default data sources for the first 5 columns
        default_sources = ["pid", "username", "cpu_percent", "memory_percent", "name"]
        for i in range(1, 6):
            self.config.setdefault(f"table_col_{i}_source", default_sources[i-1])

    def _create_widget(self):
        """Creates a DrawingArea for custom rendering."""
        drawing_area = Gtk.DrawingArea(hexpand=True, vexpand=True)
        drawing_area.set_draw_func(self.on_draw)
        return drawing_area

    def update_display(self, data):
        """Caches the new process data and queues a redraw."""
        if not isinstance(data, list):
            return
        self._process_data = data
        self.widget.queue_draw()

    def apply_styles(self):
        """Invalidates caches and triggers a redraw when styles change."""
        self._header_layout_cache.clear()
        # Clear the cell layout so it picks up new contexts/settings if needed
        self._reusable_cell_layout = None
        self.widget.queue_draw()

    def on_draw(self, area, ctx, width, height):
        """The main drawing function for rendering the entire table."""
        if width <= 0 or height <= 0: return

        # --- General Style Configuration ---
        row_font_default = self.config.get("table_row_font", "Sans 10")
        row_color_str1 = self.config.get("table_row_bg_color1", "rgba(0,0,0,0)")
        row_color_str2 = self.config.get("table_row_bg_color2", "rgba(255, 255, 255, 0.05)")
        show_alt_rows = str(self.config.get("table_show_alt_rows", "True")).lower() == 'true'
        padding = 4
        
        # --- Column Definitions from Config ---
        num_columns = int(self.config.get("table_column_count", 5))
        visible_cols = []
        data_source_map = {'pid': 'PID', 'username': 'User', 'cpu_percent': 'CPU %', 'memory_percent': 'Mem %', 'name': 'Command'}

        for i in range(1, num_columns + 1):
            source = self.config.get(f"table_col_{i}_source", "pid")
            header_override = self.config.get(f"table_col_{i}_header_override", "")
            
            col_info = {
                'source': source,
                'title': header_override or data_source_map.get(source, "N/A"),
                'width_weight': float(self.config.get(f"table_col_{i}_width_weight", 1.0)),
                'key': source # The key to get data from p_info
            }
            visible_cols.append(col_info)

        # Normalize width weights
        total_weight = sum(c['width_weight'] for c in visible_cols)
        for col in visible_cols:
            col['width'] = (col['width_weight'] / total_weight) * width if total_weight > 0 else 0

        # --- Draw Header ---
        header_font_default = self.config.get("table_header_font", "Sans Bold 10")
        
        header_height_layout = PangoCairo.create_layout(ctx)
        header_height_layout.set_font_description(Pango.FontDescription.from_string(header_font_default))
        header_height_layout.set_text("Tg", -1)
        header_height = header_height_layout.get_pixel_extents()[1].height + (padding * 2)

        current_x = 0
        for i, col in enumerate(visible_cols):
            col_num = i + 1
            header_bg_str = self.config.get(f"table_col_{col_num}_header_bg_color", "rgba(0,0,0,0.3)")
            header_bg_color = Gdk.RGBA(); header_bg_color.parse(header_bg_str)
            ctx.set_source_rgba(header_bg_color.red, header_bg_color.green, header_bg_color.blue, header_bg_color.alpha)
            ctx.rectangle(current_x, 0, col['width'], header_height); ctx.fill()
            
            header_font = self.config.get(f"table_col_{col_num}_header_font", header_font_default)
            header_color_str = self.config.get(f"table_col_{col_num}_header_color", "rgba(255,255,255,1)")
            header_color = Gdk.RGBA(); header_color.parse(header_color_str)
            ctx.set_source_rgba(header_color.red, header_color.green, header_color.blue, header_color.alpha)
            
            header_cache_key = f"{col['title']}_{header_font}"
            layout = self._header_layout_cache.get(header_cache_key)
            if not layout:
                layout = PangoCairo.create_layout(ctx)
                layout.set_font_description(Pango.FontDescription.from_string(header_font))
                layout.set_text(col['title'], -1)
                self._header_layout_cache[header_cache_key] = layout

            text_width, text_height = layout.get_pixel_extents()[1].width, layout.get_pixel_extents()[1].height
            
            align = self.config.get(f"table_col_{col_num}_header_align", "left")
            if align == "right": draw_x = current_x + col['width'] - text_width - padding
            elif align == "center": draw_x = current_x + (col['width'] - text_width) / 2
            else: draw_x = current_x + padding

            ctx.move_to(draw_x, (header_height - text_height) / 2)
            PangoCairo.show_layout(ctx, layout)
            current_x += col['width']

        # --- Draw Rows ---
        row_height_layout = PangoCairo.create_layout(ctx)
        row_height_layout.set_font_description(Pango.FontDescription.from_string(row_font_default))
        row_height_layout.set_text("Tg",-1)
        row_height = row_height_layout.get_pixel_extents()[1].height + (padding * 2)
        current_y = header_height

        row_bg1 = Gdk.RGBA(); row_bg1.parse(row_color_str1)
        row_bg2 = Gdk.RGBA(); row_bg2.parse(row_color_str2)
        
        # --- OPTIMIZATION: Create reusable layout once per draw call ---
        if self._reusable_cell_layout is None:
            self._reusable_cell_layout = PangoCairo.create_layout(ctx)
        elif self._reusable_cell_layout.get_context() != ctx:
            # If the Cairo context changed (e.g. window resized/moved), recreate layout
            self._reusable_cell_layout = PangoCairo.create_layout(ctx)
        
        cell_layout = self._reusable_cell_layout

        for i, p_info in enumerate(self._process_data):
            if current_y + row_height > height: break

            # Draw row background
            bg_color = row_bg2 if (show_alt_rows and i % 2 != 0) else row_bg1
            ctx.set_source_rgba(bg_color.red, bg_color.green, bg_color.blue, bg_color.alpha)
            ctx.rectangle(0, current_y, width, row_height); ctx.fill()
            
            current_x = 0
            for col_idx, col in enumerate(visible_cols):
                col_num = col_idx + 1
                
                # --- Get data and format it ---
                data_key = col['key']
                val = p_info.get(data_key)
                
                format_map = {'pid': '{:,}', 'cpu_percent': '{:.1f}', 'memory_percent': '{:.1f}'}
                fmt = format_map.get(data_key, '{}')
                text = fmt.format(val) if val is not None else 'N/A'
                
                # --- Get styles for this specific cell ---
                item_font = self.config.get(f"table_col_{col_num}_item_font", row_font_default)
                item_color_str = self.config.get(f"table_col_{col_num}_item_color", "rgba(220,220,220,1)")
                item_color = Gdk.RGBA(); item_color.parse(item_color_str)
                ctx.set_source_rgba(item_color.red, item_color.green, item_color.blue, item_color.alpha)

                # Reuse the layout by just updating properties
                cell_layout.set_font_description(Pango.FontDescription.from_string(item_font))
                cell_layout.set_text(text, -1)
                text_width, text_height = cell_layout.get_pixel_extents()[1].width, cell_layout.get_pixel_extents()[1].height
                
                align = self.config.get(f"table_col_{col_num}_item_align", "left")
                if align == "right": draw_x = current_x + col['width'] - text_width - padding
                elif align == "center": draw_x = current_x + (col['width'] - text_width) / 2
                else: draw_x = current_x + padding
                    
                ctx.move_to(draw_x, current_y + (row_height - text_height) / 2)
                PangoCairo.show_layout(ctx, cell_layout)
                current_x += col['width']
            
            current_y += row_height

    @staticmethod
    def get_config_model():
        """
        Returns an empty model, as all configuration UI for this complex
        displayer is built dynamically within its get_configure_callback.
        """
        return {}

    def get_configure_callback(self):
        """Dynamically build the config UI with a notebook for per-column settings."""
        def build_dynamic_ui(dialog, content_box, widgets, available_sources, panel_config, prefix=None):
            # --- Define the static model parts directly inside the callback ---
            general_model = {
                "General Layout": [
                    ConfigOption("table_column_count", "spinner", "Number of Columns:", 5, 1, 10, 1, 0)
                ],
                "Row Style": [
                    ConfigOption("table_show_alt_rows", "bool", "Use Alternating Row Colors:", "True"),
                    ConfigOption("table_row_bg_color1", "color", "Row Background Color 1 (Odd):", "rgba(0,0,0,0)"),
                    ConfigOption("table_row_bg_color2", "color", "Row Background Color 2 (Even):", "rgba(255, 255, 255, 0.05)"),
                ]
            }

            # --- General Section ---
            build_ui_from_model(content_box, panel_config, general_model, widgets)
            dialog.dynamic_models.append(general_model)

            # --- Per-Column Notebook ---
            content_box.append(Gtk.Separator(margin_top=10, margin_bottom=5))
            content_box.append(Gtk.Label(label="<b>Column Configuration</b>", use_markup=True, xalign=0))
            
            # Create a ScrolledWindow to hold the notebook
            notebook_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
            notebook_scroll.set_min_content_height(400) # Give it a minimum height
            
            notebook = Gtk.Notebook()
            notebook.set_scrollable(True)
            notebook_scroll.set_child(notebook) # Put the notebook inside the scrolled window
            content_box.append(notebook_scroll) # Add the scrolled window to the dialog

            column_count_spinner = widgets["table_column_count"]
            
            # Data sources available for columns
            data_source_opts = {"PID": "pid", "User": "username", "CPU %": "cpu_percent", "Memory %": "memory_percent", "Command": "name"}
            align_opts = {"Left": "left", "Center": "center", "Right": "right"}

            def _rebuild_column_tabs(spinner):
                # Clear previous state
                while notebook.get_n_pages() > 0:
                    notebook.remove_page(0)
                
                keys_to_remove = [k for k in widgets if k.startswith("table_col_")]
                for k in keys_to_remove: widgets.pop(k, None)
                
                dialog.dynamic_models = [m for m in dialog.dynamic_models if not any(opt.key.startswith("table_col_") for s in m.values() for opt in s)]
                
                count = spinner.get_value_as_int()
                for i in range(1, count + 1):
                    tab_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
                    tab_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
                    tab_scroll.set_child(tab_box)
                    notebook.append_page(tab_scroll, Gtk.Label(label=f"Column {i}"))
                    
                    col_model = {
                        "Data & Layout": [
                            ConfigOption(f"table_col_{i}_source", "dropdown", "Data Source:", "pid", options_dict=data_source_opts),
                            ConfigOption(f"table_col_{i}_width_weight", "spinner", "Width Weight:", 1.0, 0.1, 10.0, 0.1, 1, tooltip="Relative width of this column."),
                        ],
                        "Header Style": [
                            ConfigOption(f"table_col_{i}_header_override", "string", "Header Text:", "", tooltip="Leave blank for default."),
                            ConfigOption(f"table_col_{i}_header_font", "font", "Font:", "Sans Bold 10"),
                            ConfigOption(f"table_col_{i}_header_color", "color", "Text Color:", "rgba(255,255,255,1)"),
                            ConfigOption(f"table_col_{i}_header_bg_color", "color", "BG Color:", "rgba(0,0,0,0.3)"),
                            ConfigOption(f"table_col_{i}_header_align", "dropdown", "Align:", "left", options_dict=align_opts),
                        ],
                        "Item (Row) Style": [
                            ConfigOption(f"table_col_{i}_item_font", "font", "Font:", "Sans 10"),
                            ConfigOption(f"table_col_{i}_item_color", "color", "Text Color:", "rgba(220,220,220,1)"),
                            ConfigOption(f"table_col_{i}_item_align", "dropdown", "Align:", "left", options_dict=align_opts),
                        ]
                    }
                    build_ui_from_model(tab_box, panel_config, col_model, widgets)
                    dialog.dynamic_models.append(col_model)

            column_count_spinner.connect("value-changed", _rebuild_column_tabs)
            GLib.idle_add(_rebuild_column_tabs, column_count_spinner)
            
            # --- Dynamic visibility for alt row color picker ---
            alt_row_switch = widgets.get("table_show_alt_rows")
            alt_row_color_picker1 = widgets.get("table_row_bg_color1")
            alt_row_color_picker2 = widgets.get("table_row_bg_color2")

            if alt_row_switch and alt_row_color_picker1 and alt_row_color_picker2:
                row1 = alt_row_color_picker1.get_parent().get_parent()
                row2 = alt_row_color_picker2.get_parent().get_parent()

                def update_visibility(switch, gparam):
                    is_active = switch.get_active()
                    row1.set_visible(True) # Always show the first color picker
                    row2.set_visible(is_active)
                    
                    # Also change labels for clarity
                    label1 = row1.get_first_child()
                    if is_active:
                        label1.set_text("Row Background Color 1 (Odd):")
                    else:
                        label1.set_text("Row Background Color:")
                
                alt_row_switch.connect("notify::active", update_visibility)
                GLib.idle_add(update_visibility, alt_row_switch, None)

        return build_dynamic_ui
