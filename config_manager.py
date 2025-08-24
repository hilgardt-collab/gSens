import configparser
import os
import uuid
from gi.repository import GLib # For XDG Base Directory Specification

config_home = GLib.get_user_config_dir()
if config_home:
    APP_CONFIG_DIR = os.path.join(config_home, "gtk-system-monitor")
else:
    APP_CONFIG_DIR = os.path.expanduser("~/.config/gtk-system-monitor")

DEFAULT_CONFIG_FILE = os.path.join(APP_CONFIG_DIR, "panel_settings.ini")


class ConfigManager:
    def __init__(self):
        os.makedirs(os.path.dirname(DEFAULT_CONFIG_FILE), exist_ok=True)
        self.config = configparser.ConfigParser(interpolation=None)
        self.config.optionxform = str # Preserve case for option names
        self.load() # Load default config on startup

    def load(self, filepath=None):
        """
        Loads configuration from the specified INI file, or the default if None.
        Args:
            filepath (str, optional): The path to the INI file to load. 
                                      Defaults to the application's standard config file.
        Returns:
            bool: True if loading was successful, False otherwise.
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
                self.config = current_config_backup # Restore backup on error
                if filepath: # If error was for a specific file, notify user
                     self._show_error_dialog(f"Could not parse layout file: {os.path.basename(load_path)}\n\n{e}")
                return False
        else:
            print(f"Config file {load_path} not found.")
            if filepath: # If a specific file was requested and not found
                self._show_error_dialog(f"Layout file not found: {os.path.basename(load_path)}")
                self.config = current_config_backup # Restore backup
                return False
            # If default config not found, it's fine, it will be created on save.
            print("A new default configuration will be created on save.")
            return True # Technically not a failure if default is missing for the first time

    def save(self, filepath=None):
        """
        Saves the current configuration to the specified INI file, or the default if None.
        Args:
            filepath (str, optional): The path to the INI file to save.
                                      Defaults to the application's standard config file.
        Returns:
            bool: True if saving was successful, False otherwise.
        """
        save_path = filepath if filepath else DEFAULT_CONFIG_FILE
        try:
            # Ensure directory exists if saving to a new custom path
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

    def is_valid_layout_file(self, filepath):
        """
        Checks if a given file is a valid INI layout file for this application.
        Basic check: parsable and contains a [window] section.
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
            # Could add more checks, e.g., at least one panel_* section, specific keys in [window]
            print(f"File {filepath} appears to be a valid layout file.")
            return True
        except configparser.Error as e:
            print(f"Validation Error: File {filepath} is not a valid INI file. Error: {e}")
            return False
        except Exception as e:
            print(f"Unexpected error validating file {filepath}: {e}")
            return False

    def _show_error_dialog(self, message, parent_window=None):
        """Helper to show a simple error dialog. (Currently just prints to console)"""
        # This ideally should be called from the UI thread or use GLib.idle_add
        # For now, just printing, but a real app would use a Gtk.MessageDialog
        print(f"ERROR DIALOG (simulated): {message}")

    def get_all_panel_configs(self):
        """Retrieves all panel configurations from the current self.config."""
        panels = []
        for section_name in self.config.sections():
            if section_name.startswith("panel_"): 
                panel_type = self.config.get(section_name, "type", fallback="unknown")
                config_dict = dict(self.config.items(section_name))
                config_dict["id"] = section_name # Ensure 'id' is in the dictionary as a key
                panels.append((panel_type, config_dict))
        return panels

    def add_panel_config(self, panel_type, panel_config_dict):
        """
        Adds a new panel configuration to self.config.
        Args:
            panel_type (str): The type of the panel.
            panel_config_dict (dict): Settings for the panel. 'id' will be generated if not present or invalid.
        Returns:
            str: The ID of the added panel.
        """
        panel_id = panel_config_dict.get("id")
        if not panel_id or not panel_id.startswith("panel_"):
            panel_id = f"panel_{uuid.uuid4().hex[:12]}" # Generate a unique ID if not provided or invalid
        
        panel_config_dict["id"] = panel_id 
        panel_config_dict["type"] = panel_type # Ensure the type is stored in the config

        if not self.config.has_section(panel_id):
            self.config.add_section(panel_id)
        
        # Store all key-value pairs as strings
        for key, value in panel_config_dict.items():
            self.config.set(panel_id, str(key), str(value)) 
        return panel_id

    def update_panel_config(self, panel_id, panel_config_dict):
        """Updates an existing panel's configuration in self.config."""
        if not panel_id or not panel_id.startswith("panel_"):
            print(f"Warning: Invalid panel_id '{panel_id}' for update. Skipping.")
            return

        if not self.config.has_section(panel_id):
            # Safeguard. If a section is being created via an update call
            # (which can happen during a panel recreate), it MUST have a valid type.
            if 'type' not in panel_config_dict or not panel_config_dict['type']:
                print(f"Error: Attempted to create panel '{panel_id}' during update without a valid 'type'. Aborting update.")
                return
            self.config.add_section(panel_id)

        # Update all key-value pairs
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
        return {} # Return empty dict if no window section

    def save_window_config(self, window_config_dict):
        """Saves general window configuration to self.config."""
        if not self.config.has_section("window"):
            self.config.add_section("window")
        for key, value in window_config_dict.items():
            self.config.set("window", str(key), str(value))


# Global instance of the configuration manager
config_manager = ConfigManager()

