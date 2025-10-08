# /data_sources/static_source.py
from data_source import DataSource
from config_dialog import ConfigOption
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib

class StaticDataSource(DataSource):
    """
    A simple data source for the StaticDisplayer. It provides either
    user-configured text or a marker for an image.
    """
    def get_data(self):
        """
        Returns a dictionary containing the configured static content.
        The content type is used by the displayer to decide how to render.
        """
        content_type = self.config.get("static_content_type", "text")
        text_content = self.config.get("static_text_content", "Hello, World!")
        return {"content_type": content_type, "text": text_content}

    def get_display_string(self, data):
        """
        If the data dictionary contains 'text', return it. This is the primary
        way the TextDisplayer gets its content.
        """
        if isinstance(data, dict):
            return data.get("text", "")
        return "Static Panel"

    def get_primary_label_string(self, data):
        """
        Returns the text content if the source is custom text, otherwise returns an empty string.
        This allows lines configured as 'Primary Label' to show the static text.
        """
        if isinstance(data, dict) and self.config.get("static_content_type") == "text":
             # We check the config here to ensure we only return the text when the source is in text mode
            return data.get("text", "")
        return ""

    def get_secondary_display_string(self, data):
        """This source has no secondary display string."""
        return ""

    @staticmethod
    def get_config_model():
        """Returns the configuration model for this data source."""
        model = DataSource.get_config_model()
        model.pop("Alarm", None)  # No alarms for static content
        
        controller_key = "static_content_type"
        
        image_file_filters = [
            {"name": "Image Files", "patterns": ["*.png", "*.jpg", "*.jpeg", "*.bmp", "*.svg"]},
            {"name": "All Files", "patterns": ["*"]}
        ]
        
        model["Content"] = [
            ConfigOption(controller_key, "dropdown", "Content Type:", "text",
                         options_dict={"Text": "text", "Image": "image"}),
            # Dynamic option for Text
            ConfigOption("static_text_content", "multiline", "Text:", "Hello, World!",
                         dynamic_group=controller_key, dynamic_show_on="text"),
            # Dynamic option for Image
            ConfigOption("static_image_path", "file", "Image File:", "",
                         file_filters=image_file_filters,
                         dynamic_group=controller_key, dynamic_show_on="image"),
        ]
        return model

