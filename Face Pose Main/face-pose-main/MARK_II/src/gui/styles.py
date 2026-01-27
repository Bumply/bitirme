"""
Dark Theme Styling for MARK II GUI
Modern, sleek dark theme optimized for Raspberry Pi 7" touchscreen
"""

# Color palette
COLORS = {
    'background': '#1a1a2e',
    'surface': '#16213e',
    'surface_light': '#1f3460',
    'primary': '#0f3460',
    'primary_light': '#1a5276',
    'accent': '#e94560',
    'accent_green': '#00d26a',
    'accent_orange': '#ff9500',
    'text': '#eaeaea',
    'text_secondary': '#a0a0a0',
    'border': '#2a2a4a',
    'success': '#00d26a',
    'warning': '#ff9500',
    'error': '#e94560',
    'disabled': '#4a4a6a'
}

# Main stylesheet
DARK_THEME_STYLESHEET = f"""
/* Main Window */
QMainWindow {{
    background-color: {COLORS['background']};
}}

QWidget {{
    background-color: {COLORS['background']};
    color: {COLORS['text']};
    font-family: 'Segoe UI', 'Roboto', sans-serif;
    font-size: 14px;
}}

/* Buttons */
QPushButton {{
    background-color: {COLORS['primary']};
    color: {COLORS['text']};
    border: 2px solid {COLORS['border']};
    border-radius: 12px;
    padding: 15px 25px;
    font-size: 16px;
    font-weight: bold;
    min-height: 50px;
}}

QPushButton:hover {{
    background-color: {COLORS['primary_light']};
    border-color: {COLORS['accent']};
}}

QPushButton:pressed {{
    background-color: {COLORS['surface']};
}}

QPushButton:disabled {{
    background-color: {COLORS['disabled']};
    color: {COLORS['text_secondary']};
}}

/* Green button (Enable/Calibrate) */
QPushButton[class="success"] {{
    background-color: #1a5d3a;
    border-color: {COLORS['success']};
}}

QPushButton[class="success"]:hover {{
    background-color: #248a55;
}}

/* Red button (Exit/Stop) */
QPushButton[class="danger"] {{
    background-color: #5d1a2a;
    border-color: {COLORS['error']};
}}

QPushButton[class="danger"]:hover {{
    background-color: #8a2444;
}}

/* Labels */
QLabel {{
    color: {COLORS['text']};
    font-size: 14px;
}}

QLabel[class="title"] {{
    font-size: 20px;
    font-weight: bold;
    color: {COLORS['text']};
}}

QLabel[class="subtitle"] {{
    font-size: 16px;
    color: {COLORS['text_secondary']};
}}

QLabel[class="status"] {{
    font-size: 12px;
    color: {COLORS['text_secondary']};
    padding: 5px;
}}

/* Frames and Containers */
QFrame {{
    background-color: {COLORS['surface']};
    border: 1px solid {COLORS['border']};
    border-radius: 10px;
}}

QFrame[class="camera"] {{
    background-color: #000000;
    border: 2px solid {COLORS['border']};
    border-radius: 10px;
}}

/* Progress Bar */
QProgressBar {{
    background-color: {COLORS['surface']};
    border: 2px solid {COLORS['border']};
    border-radius: 8px;
    height: 25px;
    text-align: center;
    color: {COLORS['text']};
    font-weight: bold;
}}

QProgressBar::chunk {{
    background-color: {COLORS['accent']};
    border-radius: 6px;
}}

/* Combo Box (Dropdowns) */
QComboBox {{
    background-color: {COLORS['surface']};
    color: {COLORS['text']};
    border: 2px solid {COLORS['border']};
    border-radius: 8px;
    padding: 10px 15px;
    min-height: 40px;
    font-size: 14px;
}}

QComboBox:hover {{
    border-color: {COLORS['accent']};
}}

QComboBox::drop-down {{
    border: none;
    width: 30px;
}}

QComboBox QAbstractItemView {{
    background-color: {COLORS['surface']};
    color: {COLORS['text']};
    selection-background-color: {COLORS['primary']};
    border: 1px solid {COLORS['border']};
}}

/* Scroll Area */
QScrollArea {{
    border: none;
    background-color: transparent;
}}

/* Status Bar */
QStatusBar {{
    background-color: {COLORS['surface']};
    color: {COLORS['text_secondary']};
    border-top: 1px solid {COLORS['border']};
    font-size: 12px;
}}

/* Group Box */
QGroupBox {{
    background-color: {COLORS['surface']};
    border: 2px solid {COLORS['border']};
    border-radius: 10px;
    margin-top: 10px;
    padding-top: 15px;
    font-weight: bold;
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    left: 15px;
    padding: 0 10px;
    color: {COLORS['text']};
}}

/* Line Edit (Text Input) */
QLineEdit {{
    background-color: {COLORS['surface']};
    color: {COLORS['text']};
    border: 2px solid {COLORS['border']};
    border-radius: 8px;
    padding: 10px 15px;
    font-size: 14px;
}}

QLineEdit:focus {{
    border-color: {COLORS['accent']};
}}

/* Message Box */
QMessageBox {{
    background-color: {COLORS['background']};
}}

QMessageBox QLabel {{
    color: {COLORS['text']};
    font-size: 14px;
}}
"""

# Status indicator colors
STATUS_COLORS = {
    'enabled': COLORS['success'],
    'disabled': COLORS['error'],
    'calibrating': COLORS['warning'],
    'connected': COLORS['success'],
    'disconnected': COLORS['error']
}


def apply_dark_theme(app):
    """
    Apply dark theme to the entire application
    
    Args:
        app: QApplication instance
    """
    app.setStyleSheet(DARK_THEME_STYLESHEET)


def get_status_color(status: str) -> str:
    """
    Get color for a status indicator
    
    Args:
        status: Status name (enabled, disabled, etc.)
        
    Returns:
        Hex color code
    """
    return STATUS_COLORS.get(status, COLORS['text_secondary'])


def get_button_style(button_type: str) -> str:
    """
    Get additional style for specific button types
    
    Args:
        button_type: 'success', 'danger', 'warning'
        
    Returns:
        Style string
    """
    styles = {
        'success': f"background-color: #1a5d3a; border-color: {COLORS['success']};",
        'danger': f"background-color: #5d1a2a; border-color: {COLORS['error']};",
        'warning': f"background-color: #5d4d1a; border-color: {COLORS['warning']};"
    }
    return styles.get(button_type, "")
