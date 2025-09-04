import configparser
import os
import uuid
from gi.repository import GLib

config_home = GLib.get_user_config_dir()
if config_home:
    APP_CONFIG_DIR = os.path.join(config_home, "gSens")
else:
    APP_CONFIG_DIR = os.path.expanduser("~/.config/gSens")

DEFAULT_CONFIG_FILE = os.path.join(APP_CONFIG_DIR, "panel_settings.ini")
# --- NEW: Add a separate file for theme/default settings ---
THEME_CONFIG_FILE = os.path.join(APP_CONFIG_DIR, "theme.ini")


class ConfigManager:
    def __init__(self):
        os.makedirs(os.path.dirname(DEFAULT_CONFIG_FILE), exist_ok=True)
        self.config = configparser.ConfigParser(interpolation=None)
        self.config.optionxform = str # Preserve case for option names
        
        # --- NEW: Initialize a separate parser for the theme ---
        self.theme_config = configparser.ConfigParser(interpolation=None)
        self.theme_config.optionxform = str

        self.load() # Load default config on startup
        self.load_theme() # Load theme on startup

    def load(self, filepath=None):
        """
        Loads layout configuration from the specified INI file, or the default if None.
        """
        load_path = filepath if filepath else DEFAULT_CONFIG_FILE
        current_config_backup = self.config # Keep a backup in case loading new file fails
        self.config = configparser.ConfigParser(interpolation=None)
        self.config.optionxform = str
        
        if os.path.exists(load_path):
            try:
                self.config.read(load_path, encoding='utf-8')
                print(f"Configuration loaded from {load_path}")
                return True
            except configparser.Error as e:
                print(f"Error reading config file {load_path}: {e}. Restoring previous config (if any).")
                self.config = current_config_backup 
                if filepath:
                     self._show_error_dialog(f"Could not parse layout file: {os.path.basename(load_path)}\n\n{e}")
                return False
        else:
            print(f"Config file {load_path} not found.")
            if filepath:
                self._show_error_dialog(f"Layout file not found: {os.path.basename(load_path)}")
                self.config = current_config_backup 
                return False
            print("A new default configuration will be created on save.")
            return True

    def save(self, filepath=None):
        """
        Saves the current layout configuration to the specified INI file, or the default if None.
        """
        save_path = filepath if filepath else DEFAULT_CONFIG_FILE
        try:
            if filepath:
                os.makedirs(os.path.dirname(save_path), exist_ok=True)

            with open(save_path, "w", encoding='utf-8') as f:
                self.config.write(f)
            print(f"Configuration saved to {save_path}")
            return True
        except IOError as e:
            print(f"Error writing config file {save_path}: {e}")
            if filepath:
                self._show_error_dialog(f"Could not save layout to file: {os.path.basename(save_path)}\n\n{e}")
            return False

    # --- NEW: Method to load the theme file ---
    def load_theme(self):
        """Loads theme/defaults from the theme.ini file."""
        if os.path.exists(THEME_CONFIG_FILE):
            try:
                self.theme_config.read(THEME_CONFIG_FILE, encoding='utf-8')
                print(f"Theme loaded from {THEME_CONFIG_FILE}")
                return True
            except configparser.Error as e:
                print(f"Error reading theme file {THEME_CONFIG_FILE}: {e}")
                return False
        return True # Not an error if it doesn't exist yet

    # --- NEW: Method to save the theme file ---
    def save_theme(self):
        """Saves the current theme/defaults to the theme.ini file."""
        try:
            with open(THEME_CONFIG_FILE, "w", encoding='utf-8') as f:
                self.theme_config.write(f)
            print(f"Theme saved to {THEME_CONFIG_FILE}")
            return True
        except IOError as e:
            print(f"Error writing theme file {THEME_CONFIG_FILE}: {e}")
            return False

    # --- NEW: Method to get the default style for a displayer ---
    def get_displayer_defaults(self, displayer_key):
        """
        Retrieves the saved default configuration for a specific displayer type.
        """
        section_name = f"defaults_{displayer_key}"
        if self.theme_config.has_section(section_name):
            return dict(self.theme_config.items(section_name))
        return {}

    # --- NEW: Method to save the default style for a displayer ---
    def save_displayer_defaults(self, displayer_key, panel_config, displayer_class):
        """
        Saves the style-related options from a panel's config as the new default
        for its displayer type.
        """
        section_name = f"defaults_{displayer_key}"
        if not self.theme_config.has_section(section_name):
            self.theme_config.add_section(section_name)

        # 1. Get all style keys from the displayer's own model
        style_keys = set()
        if displayer_class and hasattr(displayer_class, 'get_config_model'):
            # Create a temporary instance to call the static method
            displayer_model = displayer_class.get_config_model()
            for section in displayer_model.values():
                for option in section:
                    style_keys.add(option.key)
        
        # 2. Add general panel style keys
        panel_style_keys = [
            "panel_bg_type", "panel_bg_color", "panel_gradient_linear_color1", 
            "panel_gradient_linear_color2", "panel_gradient_linear_angle_deg",
            "panel_gradient_radial_color1", "panel_gradient_radial_color2",
            "panel_background_image_path", "panel_background_image_style", 
            "panel_background_image_alpha", "show_title", "title_font", "title_color"
        ]
        style_keys.update(panel_style_keys)
        
        # 3. Save the current value for each style key to the theme config
        for key in style_keys:
            if key in panel_config:
                self.theme_config.set(section_name, key, str(panel_config[key]))

        return self.save_theme()


    def is_valid_layout_file(self, filepath):
        """
        Checks if a given file is a valid INI layout file for this application.
        """
        if not filepath or not os.path.exists(filepath):
            return False
        
        temp_parser = configparser.ConfigParser(interpolation=None)
        temp_parser.optionxform = str
        try:
            temp_parser.read(filepath, encoding='utf-8')
            if not temp_parser.has_section("window"):
                print(f"Validation Error: File {filepath} is missing [window] section.")
                return False
            print(f"File {filepath} appears to be a valid layout file.")
            return True
        except configparser.Error as e:
            print(f"Validation Error: File {filepath} is not a valid INI file. Error: {e}")
            return False
        except Exception as e:
            print(f"Unexpected error validating file {filepath}: {e}")
            return False

    def _show_error_dialog(self, message, parent_window=None):
        print(f"ERROR DIALOG (simulated): {message}")

    def get_all_panel_configs(self):
        """Retrieves all panel configurations from the current self.config."""
        panels = []
        for section_name in self.config.sections():
            if section_name.startswith("panel_"): 
                panel_type = self.config.get(section_name, "type", fallback="unknown")
                config_dict = dict(self.config.items(section_name))
                config_dict["id"] = section_name
                panels.append((panel_type, config_dict))
        return panels

    def add_panel_config(self, panel_type, panel_config_dict):
        """
        Adds a new panel configuration to self.config.
        """
        panel_id = panel_config_dict.get("id")
        if not panel_id or not panel_id.startswith("panel_"):
            panel_id = f"panel_{uuid.uuid4().hex[:12]}"
        
        panel_config_dict["id"] = panel_id 
        panel_config_dict["type"] = panel_type

        if not self.config.has_section(panel_id):
            self.config.add_section(panel_id)
        
        for key, value in panel_config_dict.items():
            self.config.set(panel_id, str(key), str(value)) 
        return panel_id

    def update_panel_config(self, panel_id, panel_config_dict):
        """Updates an existing panel's configuration in self.config."""
        if not panel_id or not panel_id.startswith("panel_"):
            print(f"Warning: Invalid panel_id '{panel_id}' for update. Skipping.")
            return

        if not self.config.has_section(panel_id):
            if 'type' not in panel_config_dict or not panel_config_dict['type']:
                print(f"Error: Attempted to create panel '{panel_id}' during update without a valid 'type'. Aborting update.")
                return
            self.config.add_section(panel_id)

        for key, value in panel_config_dict.items():
            self.config.set(panel_id, str(key), str(value))
        
    def remove_panel_config(self, panel_id):
        """Removes a single panel's configuration from self.config."""
        if self.config.has_section(panel_id):
            self.config.remove_section(panel_id)
            return True
        return False

    def remove_all_panel_configs(self):
        """Removes all panel configurations from self.config. Window config is kept."""
        sections_to_remove = [s for s in self.config.sections() if s.startswith("panel_")]
        for section_name in sections_to_remove:
            self.config.remove_section(section_name)
        print("All panel configurations removed from memory (current config object).")

    def get_window_config(self):
        """Gets general window configuration from self.config."""
        if self.config.has_section("window"):
            return dict(self.config.items("window"))
        return {}

    def save_window_config(self, window_config_dict):
        """Saves general window configuration to self.config."""
        if not self.config.has_section("window"):
            self.config.add_section("window")
        for key, value in window_config_dict.items():
            self.config.set("window", str(key), str(value))

config_manager = ConfigManager()
