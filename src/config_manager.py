import configparser
import os
import uuid
import threading
from gi.repository import GLib

config_home = GLib.get_user_config_dir()
if config_home:
    APP_CONFIG_DIR = os.path.join(config_home, "gSens")
else:
    APP_CONFIG_DIR = os.path.expanduser("~/.config/gSens")

DEFAULT_CONFIG_FILE = os.path.join(APP_CONFIG_DIR, "panel_settings.ini")
# --- NEW: Define a separate theme file ---
THEME_CONFIG_FILE = os.path.join(APP_CONFIG_DIR, "theme.ini")


class ConfigManager:
    def __init__(self):
        os.makedirs(os.path.dirname(DEFAULT_CONFIG_FILE), exist_ok=True)
        self.config = configparser.ConfigParser(interpolation=None)
        self.config.optionxform = str 
        self.load() 
        
        # --- NEW: Load the theme configuration ---
        self.theme_config = configparser.ConfigParser(interpolation=None)
        self.theme_config.optionxform = str
        if os.path.exists(THEME_CONFIG_FILE):
            self.theme_config.read(THEME_CONFIG_FILE, encoding='utf-8')
            
        # --- Debounce State ---
        self._save_timer = None
        self._save_lock = threading.Lock()

    def load(self, filepath=None):
        load_path = filepath if filepath else DEFAULT_CONFIG_FILE
        current_config_backup = self.config 
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

    def save(self, filepath=None, immediate=False):
        """
        Saves configuration. 
        If immediate=False, debounces the save to prevent disk thrashing.
        """
        if filepath:
            # Always save immediately if a specific path is provided (Save As...)
            return self._write_to_disk(filepath)
        
        if immediate:
            with self._save_lock:
                if self._save_timer:
                    self._save_timer.cancel()
                    self._save_timer = None
            return self._write_to_disk(DEFAULT_CONFIG_FILE)
            
        # Debounce logic for default file
        with self._save_lock:
            if self._save_timer:
                self._save_timer.cancel()
            self._save_timer = threading.Timer(1.0, self._write_to_disk, args=[DEFAULT_CONFIG_FILE])
            self._save_timer.start()
        return True

    def _write_to_disk(self, save_path):
        """Helper to perform the actual synchronous write operation."""
        try:
            os.makedirs(os.path.dirname(save_path), exist_ok=True)
            with open(save_path, "w", encoding='utf-8') as f:
                self.config.write(f)
            print(f"Configuration saved to {save_path}")
            return True
        except IOError as e:
            print(f"Error writing config file {save_path}: {e}")
            return False

    def is_valid_layout_file(self, filepath):
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
        panels = []
        for section_name in self.config.sections():
            if section_name.startswith("panel_"): 
                panel_type = self.config.get(section_name, "type", fallback="unknown")
                config_dict = dict(self.config.items(section_name))
                config_dict["id"] = section_name 
                panels.append((panel_type, config_dict))
        return panels

    def add_panel_config(self, panel_type, panel_config_dict):
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
        if self.config.has_section(panel_id):
            self.config.remove_section(panel_id)
            return True
        return False

    def remove_all_panel_configs(self):
        sections_to_remove = [s for s in self.config.sections() if s.startswith("panel_")]
        for section_name in sections_to_remove:
            self.config.remove_section(section_name)
        print("All panel configurations removed from memory (current config object).")


    def get_window_config(self):
        if self.config.has_section("window"):
            return dict(self.config.items("window"))
        return {} 

    def save_window_config(self, window_config_dict):
        if not self.config.has_section("window"):
            self.config.add_section("window")
        for key, value in window_config_dict.items():
            self.config.set("window", str(key), str(value))

    # --- NEW AND MODIFIED THEME METHODS ---

    def get_displayer_defaults(self, displayer_key):
        """Gets the default style configuration for a given displayer type."""
        section_name = f"defaults_{displayer_key}"
        if self.theme_config.has_section(section_name):
            return dict(self.theme_config.items(section_name))
        return {}

    def save_displayer_defaults(self, displayer_key, panel_config, displayer_class):
        """
        Saves the relevant style settings from a panel's config as the new
        default for that displayer type.
        """
        if not displayer_key or not displayer_class:
            return False

        defaults_to_save = {}
        
        if 'width' in panel_config: defaults_to_save['width'] = panel_config['width']
        if 'height' in panel_config: defaults_to_save['height'] = panel_config['height']

        displayer_model = displayer_class.get_config_model()
        for section in displayer_model.values():
            for option in section:
                if option.key in panel_config:
                    defaults_to_save[option.key] = panel_config[option.key]
        
        bg_keys = [
            'panel_bg_type', 'panel_bg_color',
            'panel_gradient_linear_color1', 'panel_gradient_linear_color2', 'panel_gradient_linear_angle_deg',
            'panel_gradient_radial_color1', 'panel_gradient_radial_color2',
            'panel_background_image_path', 'panel_background_image_style', 'panel_background_image_alpha'
        ]
        for key in bg_keys:
            if key in panel_config:
                defaults_to_save[key] = panel_config[key]
        
        # --- FIX: Only use prefixes explicitly provided by the displayer class ---
        prefixes_to_check = []
        if hasattr(displayer_class, 'get_config_key_prefixes'):
            prefixes_to_check = displayer_class.get_config_key_prefixes()

        # Use the collected prefixes to find all relevant dynamic keys
        if prefixes_to_check:
            for key, value in panel_config.items():
                for prefix in set(prefixes_to_check): # Use set to avoid duplicates
                    if key.startswith(prefix):
                        defaults_to_save[key] = value
                        break # Move to next key once matched

        section_name = f"defaults_{displayer_key}"
        if self.theme_config.has_section(section_name):
            self.theme_config.remove_section(section_name)
        self.theme_config.add_section(section_name)
        
        for key, value in defaults_to_save.items():
            self.theme_config.set(section_name, str(key), str(value))

        try:
            with open(THEME_CONFIG_FILE, "w", encoding='utf-8') as f:
                self.theme_config.write(f)
            print(f"Theme saved to {THEME_CONFIG_FILE}")
            return True
        except IOError as e:
            print(f"Error writing theme file {THEME_CONFIG_FILE}: {e}")
            return False

config_manager = ConfigManager()
