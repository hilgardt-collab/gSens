# config_dialog.py
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gdk, GLib

class ConfigOption:
    """
    A data class to define a single configuration option.
    """
    def __init__(self, key, option_type, label, default,
                 min_val=None, max_val=None, step=None, digits=0, 
                 options_dict=None, tooltip=None, file_filters=None):
        self.key = key
        # Valid types: "string", "bool", "color", "font", "scale", "spinner", "dropdown", "file", "timezone_selector"
        self.type = option_type 
        self.label = label
        self.default = default
        self.min_val = min_val
        self.max_val = max_val
        self.step = step
        self.digits = digits
        self.options_dict = options_dict or {}
        self.tooltip = tooltip
        # A list of dicts, e.g., [{"name": "Audio", "patterns": ["*.mp3"]}]
        self.file_filters = file_filters or []

def build_ui_from_model(parent_box, config, model, widgets=None):
    """
    Populates a parent Gtk.Box with widgets based on a configuration model.
    Returns a dictionary of the created widgets, keyed by their config key.
    If a `widgets` dictionary is passed in, it will be updated with the new widgets.
    """
    if widgets is None:
        widgets = {}

    for section_title, options in model.items():
        if section_title:
            sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL, margin_top=10, margin_bottom=5)
            parent_box.append(sep)
            header_label = Gtk.Label(xalign=0)
            header_label.set_markup(f"<b>{GLib.markup_escape_text(section_title)}</b>")
            parent_box.append(header_label)

        for option in options:
            widget = None
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10, margin_bottom=4)
            
            if option.type == "scale":
                container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, margin_bottom=4)
                label_widget = Gtk.Label(label=option.label, xalign=0)
                container.append(label_widget)
            else:
                label_widget = Gtk.Label(label=option.label, xalign=0)
                row.append(label_widget)

            if option.type == "string":
                widget = Gtk.Entry(text=config.get(option.key, option.default), hexpand=True)
            elif option.type == "bool":
                widget = Gtk.Switch(active=str(config.get(option.key, str(option.default))).lower() == 'true', halign=Gtk.Align.END)
            elif option.type == "color":
                rgba = Gdk.RGBA()
                rgba.parse(str(config.get(option.key, option.default)))
                widget = Gtk.ColorButton.new_with_rgba(rgba)
                widget.set_use_alpha(True)
            elif option.type == "font":
                widget = Gtk.FontButton.new_with_font(str(config.get(option.key, option.default)))
            elif option.type == "scale":
                widget = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, option.min_val, option.max_val, option.step)
                widget.set_value(float(config.get(option.key, option.default)))
                widget.set_digits(option.digits)
                widget.set_draw_value(True)
                widget.set_hexpand(True)
            elif option.type == "spinner":
                adjustment = Gtk.Adjustment(
                    value=float(config.get(option.key, option.default)),
                    lower=option.min_val,
                    upper=option.max_val,
                    step_increment=option.step,
                    page_increment=10 * (option.step or 1.0)
                )
                widget = Gtk.SpinButton(adjustment=adjustment, digits=option.digits, numeric=True)
            elif option.type == "dropdown":
                widget = Gtk.ComboBoxText()
                for display_name, id_str in option.options_dict.items():
                    widget.append(id=str(id_str), text=display_name)
                
                current_value = str(config.get(option.key, option.default))
                
                if not widget.set_active_id(current_value):
                    print(f"[Warning] Could not set active ID '{current_value}' for '{option.key}'. Defaulting to first item.")
                    widget.set_active(0)
            
            elif option.type == "file":
                file_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, hexpand=True)
                
                widget = Gtk.Entry(text=config.get(option.key, option.default), hexpand=True)
                file_box.append(widget)
                
                choose_button = Gtk.Button(label="Choose…")
                
                def on_choose_file_clicked(_btn, entry_widget, current_option):
                    parent_window = _btn.get_ancestor(Gtk.Window)
                    file_chooser = Gtk.FileChooserNative.new(
                        "Select File",
                        parent_window,
                        Gtk.FileChooserAction.OPEN,
                        "_Open",
                        "_Cancel"
                    )
                    
                    if current_option.file_filters:
                        for filter_info in current_option.file_filters:
                            new_filter = Gtk.FileFilter.new()
                            if "name" in filter_info:
                                new_filter.set_name(filter_info["name"])
                            for mime_type in filter_info.get("mimetypes", []):
                                new_filter.add_mime_type(mime_type)
                            for pattern in filter_info.get("patterns", []):
                                new_filter.add_pattern(pattern)
                            file_chooser.add_filter(new_filter)
                    
                    def on_response(dialog, response):
                        if response == Gtk.ResponseType.ACCEPT:
                            file = dialog.get_file()
                            if file:
                                entry_widget.set_text(file.get_path() or "")
                        dialog.destroy()
                    
                    file_chooser.connect("response", on_response)
                    file_chooser.show()

                choose_button.connect("clicked", on_choose_file_clicked, widget, option)
                file_box.append(choose_button)
                
                row.append(file_box)

            elif option.type == "timezone_selector":
                tz_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, hexpand=True)
                
                widget = Gtk.Entry(text=config.get(option.key, option.default), hexpand=True, editable=False)
                tz_box.append(widget)
                
                choose_button = Gtk.Button(label="Choose…")
                widgets[f"{option.key}_button"] = choose_button # Store button for callback
                tz_box.append(choose_button)
                
                row.append(tz_box)


            if widget:
                if option.tooltip:
                    widget.set_tooltip_text(option.tooltip)
                
                if option.type == "scale":
                    container.append(widget)
                    parent_box.append(container)
                elif option.type not in ["file", "timezone_selector"]:
                    row.append(widget)

                if option.type != "scale":
                    parent_box.append(row)
                
                if option.key in widgets:
                     print(f"[WARNING] Duplicate widget key detected in build_ui_from_model: '{option.key}'. Overwriting.")
                widgets[option.key] = widget
    return widgets

def _get_all_options_from_model(model):
    """Recursively finds all ConfigOption objects within a model structure."""
    all_opts = []
    if not isinstance(model, dict):
        return []
    for val in model.values():
        if isinstance(val, list): # This is a list of ConfigOption objects
            all_opts.extend(val)
        elif isinstance(val, dict): # This is a nested model dictionary
            all_opts.extend(_get_all_options_from_model(val))
    return all_opts

def get_config_from_widgets(widgets, models_list):
    """
    Reads values from UI widgets based on a list of configuration models.
    """
    new_config = {}
    all_option_defs = {}
    for model in models_list:
        for option in _get_all_options_from_model(model):
            # Ensure it's a valid ConfigOption object before adding
            if hasattr(option, 'key') and isinstance(option.key, str):
                all_option_defs[option.key] = option

    for key, widget in widgets.items():
        # Skip derivative widgets like buttons
        if key.endswith("_button"):
            continue

        option_def = all_option_defs.get(key)
        
        if not option_def:
            continue

        if option_def.type in ["string", "file", "timezone_selector"]:
            new_config[key] = widget.get_text()
        elif option_def.type == "bool":
            new_config[key] = str(widget.get_active())
        elif option_def.type == "color":
            new_config[key] = widget.get_rgba().to_string()
        elif option_def.type == "font":
            new_config[key] = widget.get_font()
        elif option_def.type == "scale" or option_def.type == "spinner":
            new_config[key] = f"{widget.get_value():.{option_def.digits}f}"
        elif option_def.type == "dropdown":
            active_id = widget.get_active_id()
            if active_id is not None:
                new_config[key] = active_id
            else:
                new_config[key] = option_def.default
    return new_config
