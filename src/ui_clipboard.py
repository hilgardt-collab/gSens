# /ui_clipboard.py
# A unified module for managing global clipboards for UI elements like fonts and colors.

class FontClipboard:
    """
    A singleton to manage a global font clipboard for the application.
    It is initialized with a default font to ensure it's never empty.
    """
    _instance = None
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(FontClipboard, cls).__new__(cls)
            # Initialize with a default font
            cls._instance.clipboard_font = "Sans 12"
        return cls._instance

    def copy_font(self, font_string):
        """Copies a font string to the clipboard."""
        self.clipboard_font = font_string

    def get_font(self):
        """Retrieves the font string from the clipboard."""
        return self.clipboard_font

class ColorClipboard:
    """
    A singleton to manage a global color clipboard for the application.
    It is initialized with a default color to ensure it's never empty.
    """
    _instance = None
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ColorClipboard, cls).__new__(cls)
            # Initialize with a default color (white)
            cls._instance.clipboard_color = "rgba(255,255,255,1)"
        return cls._instance

    def copy_color(self, rgba_string):
        """Copies a color RGBA string to the clipboard."""
        self.clipboard_color = rgba_string

    def get_color(self):
        """Retrieves the color RGBA string from the clipboard."""
        return self.clipboard_color

# Global instances
font_clipboard = FontClipboard()
color_clipboard = ColorClipboard()
