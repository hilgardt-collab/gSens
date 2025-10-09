# style_manager.py
# A singleton manager for handling displayer style operations like copy, paste, save, and load.

import configparser
import os
from gi.repository import GLib

class StyleManager:
    """
    Manages a clipboard for displayer styles and handles saving/loading
    styles to/from .gss (gSens Style Sheet) files.
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(StyleManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self.style_clipboard = {}
        self._initialized = True

    def _extract_style_keys(self, panel):
        """Extracts all relevant style keys from a panel's configuration."""
        if not hasattr(panel, 'data_displayer') or not panel.data_displayer:
            return {}

        style_dict = {}
        displayer = panel.data_displayer
        config = panel.config
        
        # Use the new get_all_style_keys method for a comprehensive list
        model_keys = displayer.get_all_style_keys()
        
        # Get keys based on registered prefixes. This is still useful for complex
        # displayers that might not list every single dynamic key.
        if hasattr(displayer, 'get_config_key_prefixes'):
            prefixes = displayer.get_config_key_prefixes()
            for key in config:
                for prefix in prefixes:
                    if key.startswith(prefix):
                        model_keys.add(key)
                        break
        
        # Add general panel background keys
        bg_keys = [
            'panel_bg_type', 'panel_bg_color', 'panel_gradient_linear_color1', 
            'panel_gradient_linear_color2', 'panel_gradient_linear_angle_deg',
            'panel_gradient_radial_color1', 'panel_gradient_radial_color2',
            'panel_background_image_path', 'panel_background_image_style', 
            'panel_background_image_alpha'
        ]
        model_keys.update(bg_keys)

        # Populate the style dictionary with current values from the panel config
        for key in model_keys:
            if key in config:
                style_dict[key] = config[key]
        
        return style_dict

    def copy_style(self, panel):
        """Copies a panel's style configuration to the internal clipboard."""
        displayer_key = panel.config.get('displayer_type')
        if not displayer_key:
            print("Cannot copy style: Displayer type not found.")
            return

        styles = self._extract_style_keys(panel)
        self.style_clipboard = {
            'displayer_type': displayer_key,
            'styles': styles
        }
        print(f"Style for '{displayer_key}' copied to clipboard.")

    def paste_style(self, panel, config_manager_ref):
        """Pastes the clipboard style to a panel if the displayer type matches."""
        if not self.style_clipboard:
            print("Cannot paste: Style clipboard is empty.")
            return

        target_displayer = panel.config.get('displayer_type')
        clipboard_displayer = self.style_clipboard.get('displayer_type')

        if target_displayer != clipboard_displayer:
            print(f"Cannot paste: Style is for '{clipboard_displayer}', panel is '{target_displayer}'.")
            return

        panel.config.update(self.style_clipboard['styles'])
        panel.apply_all_configurations()
        config_manager_ref.update_panel_config(panel.config["id"], panel.config)
        print(f"Style pasted to panel '{panel.config.get('id')}'.")

    def save_style_to_file(self, filepath, panel):
        """Saves a panel's style to a .gss file."""
        displayer_key = panel.config.get('displayer_type')
        if not displayer_key:
            print("Cannot save style: Displayer type not found.")
            return False

        styles = self._extract_style_keys(panel)
        
        style_parser = configparser.ConfigParser()
        style_parser.optionxform = str
        style_parser.add_section('Style')
        style_parser.set('Style', 'displayer_type', displayer_key)
        
        style_parser.add_section('Keys')
        for key, value in styles.items():
            style_parser.set('Keys', key, str(value))
            
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                style_parser.write(f)
            print(f"Style for '{displayer_key}' saved to {filepath}")
            return True
        except IOError as e:
            print(f"Error saving style file: {e}")
            return False

    def load_style_from_file(self, filepath, panel, config_manager_ref):
        """Loads a style from a .gss file and applies it to a panel."""
        if not os.path.exists(filepath):
            print(f"Error: Style file not found at {filepath}")
            return

        style_parser = configparser.ConfigParser(interpolation=None)
        style_parser.optionxform = str
        
        try:
            style_parser.read(filepath, encoding='utf-8')
            
            file_displayer_type = style_parser.get('Style', 'displayer_type')
            panel_displayer_type = panel.config.get('displayer_type')

            if file_displayer_type != panel_displayer_type:
                print(f"Cannot load style: File is for '{file_displayer_type}', panel is '{panel_displayer_type}'.")
                return

            if style_parser.has_section('Keys'):
                styles_to_load = dict(style_parser.items('Keys'))
                panel.config.update(styles_to_load)
                panel.apply_all_configurations()
                config_manager_ref.update_panel_config(panel.config["id"], panel.config)
                print(f"Style from {os.path.basename(filepath)} applied to panel '{panel.config.get('id')}'.")

        except (configparser.Error, KeyError) as e:
            print(f"Error reading style file {filepath}: {e}")

# Global instance
style_manager = StyleManager()
