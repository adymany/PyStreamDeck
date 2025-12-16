"""
PyStreamDeck Pro - PyQt6 Version (Single Window Navigation)
A modern macro pad application with mobile remote control
"""

import sys
import os
import json
import time
import threading
import socket
from functools import partial

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QPushButton, QLabel, QComboBox, QFrame,
    QLineEdit, QMessageBox, QScrollArea, QMenu, QStackedWidget,
    QInputDialog, QSizePolicy, QDialog, QSystemTrayIcon, QStyle
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap, QAction, QIcon

from flask import Flask, render_template_string, jsonify
from pynput.keyboard import Key, Controller, Listener
import qrcode
from io import BytesIO

# ==========================================
# FLASK WEB SERVER (Mobile Remote)
# ==========================================
flask_app = Flask(__name__)
APP_INSTANCE = None

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>PyStreamDeck</title>
    <meta name="viewport" content="width=device-width, initial-scale=1, user-scalable=no">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { 
            font-family: 'Segoe UI', sans-serif; 
            background: linear-gradient(135deg, #0f0f1a 0%, #1a1a2e 100%); 
            color: #fff; 
            min-height: 100vh;
            padding: 20px;
        }
        .header { text-align: center; padding: 20px 0; margin-bottom: 20px; }
        .header h1 {
            font-size: 24px;
            background: linear-gradient(90deg, #00d2ff, #3a7bd5);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 12px;
        }
        .header-buttons { display: flex; justify-content: center; gap: 10px; flex-wrap: wrap; }
        .profile-btn, .fullscreen-btn {
            background: rgba(0, 210, 255, 0.1);
            border: 1px solid #00d2ff;
            padding: 10px 20px;
            border-radius: 25px;
            font-size: 14px;
            color: #00d2ff;
            cursor: pointer;
            transition: all 0.2s ease;
            font-weight: 600;
        }
        .profile-btn:active, .fullscreen-btn:active {
            background: #00d2ff;
            color: #000;
            transform: scale(0.95);
        }
        .fullscreen-btn { border-color: #ff9500; color: #ff9500; background: rgba(255, 149, 0, 0.1); }
        .fullscreen-btn:active, .fullscreen-btn.active { background: #ff9500; color: #000; }
        .grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 15px; max-width: 400px; margin: 0 auto; }
        .btn { 
            background: linear-gradient(145deg, #252540, #1e1e35);
            border: 1px solid #3a3a5c;
            color: #e0e0e0;
            padding: 15px 10px;
            border-radius: 16px;
            cursor: pointer;
            user-select: none;
            font-weight: 600;
            font-size: 14px;
            box-shadow: 0 8px 20px rgba(0,0,0,0.4);
            transition: all 0.2s ease;
            text-align: center;
            min-height: 100px;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .btn:active { 
            background: linear-gradient(145deg, #00d2ff, #3a7bd5);
            color: #000;
            transform: scale(0.95);
        }
        .wake-indicator { position: fixed; bottom: 15px; right: 15px; font-size: 12px; color: #ff9500; opacity: 0; transition: opacity 0.3s; }
        .wake-indicator.visible { opacity: 1; }
    </style>
</head>
<body>
    <div class="header">
        <h1>⌨️ PyStreamDeck</h1>
        <div class="header-buttons">
            <button class="profile-btn" onclick="cycleProfile()">📁 <span id="profile-name">{{ current_profile }}</span></button>
            <button class="fullscreen-btn" id="fs-btn" onclick="toggleFullscreen()">⛶ Fullscreen</button>
        </div>
    </div>
    <div class="grid">
        {% for btn in buttons %}
        <div class="btn" id="btn-{{ btn.id }}" onclick="fetch('/trigger/{{ btn.id }}')" style="color: {{ '#00ff88' if btn.has_macro else '#e0e0e0' }}">{{ btn.name }}</div>
        {% endfor %}
    </div>
    <div class="wake-indicator" id="wake-indicator">🔆 Screen Wake Lock Active</div>
    <script>
        const profiles = {{ profiles | tojson }};
        let currentIndex = profiles.indexOf("{{ current_profile }}");
        let wakeLock = null;
        function cycleProfile() {
            currentIndex = (currentIndex + 1) % profiles.length;
            const newProfile = profiles[currentIndex];
            document.getElementById('profile-name').textContent = newProfile;
            fetch('/set_profile/' + encodeURIComponent(newProfile))
                .then(r => r.ok ? fetch('/get_buttons') : Promise.reject())
                .then(r => r.json())
                .then(data => {
                    data.forEach(btn => {
                        const el = document.getElementById('btn-' + btn.id);
                        el.textContent = btn.name;
                        el.style.color = btn.has_macro ? '#00ff88' : '#e0e0e0';
                    });
                });
        }
        async function toggleFullscreen() {
            const fsBtn = document.getElementById('fs-btn');
            if (!document.fullscreenElement) {
                try { await document.documentElement.requestFullscreen(); fsBtn.textContent = '✕ Exit'; fsBtn.classList.add('active'); await requestWakeLock(); }
                catch (err) { console.log(err); }
            } else {
                await document.exitFullscreen(); fsBtn.textContent = '⛶ Fullscreen'; fsBtn.classList.remove('active'); releaseWakeLock();
            }
        }
        async function requestWakeLock() {
            try { if ('wakeLock' in navigator) { wakeLock = await navigator.wakeLock.request('screen'); document.getElementById('wake-indicator').classList.add('visible'); } } catch (err) {}
        }
        function releaseWakeLock() { if (wakeLock) { wakeLock.release(); wakeLock = null; } document.getElementById('wake-indicator').classList.remove('visible'); }
        document.addEventListener('fullscreenchange', () => { if (!document.fullscreenElement) { document.getElementById('fs-btn').textContent = '⛶ Fullscreen'; document.getElementById('fs-btn').classList.remove('active'); releaseWakeLock(); } });
    </script>
</body>
</html>
"""

PROFILES = ["General", "Video Editing", "Photo Editing", "Gaming", "Productivity"]

@flask_app.route('/')
def index():
    if not APP_INSTANCE: return "App not running", 503
    buttons_data = []
    for i in range(9):
        name, has_macro = f"M{i+1}", False
        if i in APP_INSTANCE.macros:
            macro_data = APP_INSTANCE.macros[i]
            if isinstance(macro_data, dict):
                name = macro_data.get('name', f"M{i+1}")
            has_macro = True
        buttons_data.append({'id': i, 'name': name, 'has_macro': has_macro})
    return render_template_string(HTML_TEMPLATE, profile=APP_INSTANCE.current_profile, current_profile=APP_INSTANCE.current_profile, profiles=PROFILES, buttons=buttons_data)

@flask_app.route('/set_profile/<profile_name>')
def set_profile_web(profile_name):
    if APP_INSTANCE and profile_name in PROFILES:
        APP_INSTANCE.change_profile(profile_name)
        return "OK", 200
    return "Error", 400

@flask_app.route('/get_buttons')
def get_buttons_json():
    if not APP_INSTANCE: return jsonify([])
    buttons_data = []
    for i in range(9):
        name, has_macro = f"M{i+1}", False
        if i in APP_INSTANCE.macros:
            macro_data = APP_INSTANCE.macros[i]
            if isinstance(macro_data, dict):
                name = macro_data.get('name', f"M{i+1}")
            has_macro = True
        buttons_data.append({'id': i, 'name': name, 'has_macro': has_macro})
    return jsonify(buttons_data)

@flask_app.route('/trigger/<int:btn_id>')
def trigger_macro_web(btn_id):
    if APP_INSTANCE:
        APP_INSTANCE.play_macro(btn_id)
        return "OK", 200
    return "Error", 500

def run_flask():
    flask_app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)

# ==========================================
# MACRO ENGINE
# ==========================================
class MacroEngine:
    def __init__(self):
        self.controller = Controller()
        
    def play(self, event_list):
        for action, key_str, delay in event_list:
            time.sleep(delay)
            key_obj = self._str_to_key(key_str)
            if action == 'press':
                self.controller.press(key_obj)
            elif action == 'release':
                self.controller.release(key_obj)

    def _str_to_key(self, key_str):
        if key_str.startswith("Key."):
            try: return getattr(Key, key_str.split(".")[1])
            except: return Key.esc
        return key_str.strip("'")

class KeyEditorDialog(QDialog):
    def __init__(self, parent=None, key_val="", action_val="press", delay_val=0.05):
        super().__init__(parent)
        self.setWindowTitle("Edit Key Event")
        self.setFixedSize(500, 450)
        self.setStyleSheet("""
            QDialog { background: #0f0f1a; }
            QLabel { color: #e0e0e0; font-size: 12px; }
            QLineEdit { background: #252540; border: 1px solid #3a3a5c; border-radius: 6px; color: #fff; padding: 8px; font-size: 13px; }
            QComboBox { background: #252540; border: 1px solid #3a3a5c; border-radius: 6px; color: #00d2ff; padding: 8px; }
            QPushButton { background: #3a3a5c; border: none; border-radius: 6px; color: #e0e0e0; padding: 8px; min-width: 60px; }
            QPushButton:hover { background: #00d2ff; color: #000; }
            QPushButton#save { background: #00ff88; color: #000; font-weight: bold; padding: 10px 30px; }
            QPushButton#cancel { background: #ff4466; color: #fff; font-weight: bold; }
        """)
        
        self.key_val = key_val
        self.action_val = action_val
        self.delay_val = delay_val
        self.result_data = None
        
        self.init_ui()
        
    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        
        # KEY INPUT
        key_group = QWidget()
        k_layout = QVBoxLayout(key_group)
        k_layout.setContentsMargins(0,0,0,0)
        k_layout.addWidget(QLabel("Key / String to Type:"))
        
        self.key_input = QLineEdit(self.key_val)
        self.key_input.setPlaceholderText("e.g. 'a', 'Key.enter', or 'hello'")
        k_layout.addWidget(self.key_input)
        
        # SPECIAL KEYS GRID
        grid_group = QWidget()
        g_layout = QGridLayout(grid_group)
        g_layout.setSpacing(8)
        
        special_keys = [
            ("Enter", "Key.enter"), ("Tab", "Key.tab"), ("Space", "Key.space"), ("Bksp", "Key.backspace"),
            ("Shift", "Key.shift"), ("Ctrl", "Key.ctrl"), ("Alt", "Key.alt"), ("Esc", "Key.esc"),
            ("Delete", "Key.delete"), ("Home", "Key.home"), ("End", "Key.end"), ("Ins", "Key.insert"),
            ("↑", "Key.up"), ("↓", "Key.down"), ("←", "Key.left"), ("→", "Key.right")
        ]
        
        for i, (label, code) in enumerate(special_keys):
            btn = QPushButton(label)
            btn.clicked.connect(partial(self.set_key_text, code))
            row, col = divmod(i, 4)
            g_layout.addWidget(btn, row, col)
            
        k_layout.addWidget(grid_group)
        layout.addWidget(key_group)
        
        # ACTION & DELAY ROW
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0,0,0,0)
        
        # Action code
        ac_layout = QVBoxLayout()
        ac_layout.addWidget(QLabel("Action:"))
        self.action_combo = QComboBox()
        self.action_combo.addItems(["press", "release"])
        self.action_combo.setCurrentText(self.action_val)
        ac_layout.addWidget(self.action_combo)
        row_layout.addLayout(ac_layout)
        
        # Delay code
        dl_layout = QVBoxLayout()
        dl_layout.addWidget(QLabel("Delay (ms):"))
        self.delay_input = QLineEdit(str(int(self.delay_val * 1000)))
        dl_layout.addWidget(self.delay_input)
        row_layout.addLayout(dl_layout)
        
        layout.addWidget(row_widget)
        
        # Note
        note = QLabel("Note: Typing a word (e.g. 'hello') creates a sequence.")
        note.setStyleSheet("color: #888; font-style: italic;")
        layout.addWidget(note)
        
        # BUTTONS
        btn_layout = QHBoxLayout()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("cancel")
        cancel_btn.clicked.connect(self.reject)
        
        save_btn = QPushButton("Add / Update")
        save_btn.setObjectName("save")
        save_btn.clicked.connect(self.save)
        
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(save_btn)
        layout.addLayout(btn_layout)
        
    def set_key_text(self, text):
        self.key_input.setText(text)
        self.key_input.setFocus()
        
    def save(self):
        k = self.key_input.text().strip()
        if not k:
            QMessageBox.warning(self, "Error", "Key cannot be empty")
            return
            
        try:
            d = float(self.delay_input.text()) / 1000.0
        except ValueError:
            QMessageBox.warning(self, "Error", "Invalid delay")
            return
            
        self.result_data = (self.action_combo.currentText(), k, d)
        self.accept()

# ==========================================
# MAIN WINDOW WITH STACKED NAVIGATION
# ==========================================
def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

class StreamDeckWindow(QMainWindow):
    status_signal = pyqtSignal(str, str)
    
    def __init__(self):
        super().__init__()
        global APP_INSTANCE
        APP_INSTANCE = self
        
        self.engine = MacroEngine()
        self.current_profile = "General"
        self.macros = {}
        self.is_recording = False
        self.is_playing = False
        self.buttons = []
        self.current_edit_btn_id = None
        self.current_edit_events = None
        
        # System Tray logic
        self.tray_icon = None
        self.can_exit = False
        self.init_tray()
        
        self.init_ui()
        self.load_macros()
        self.status_signal.connect(self.update_status)

    def init_tray(self):
        self.tray_icon = QSystemTrayIcon(self)
        
        # Use logo.png if exists, else standard system icon
        logo_path = resource_path("logo.png")
        if os.path.exists(logo_path):
            icon = QIcon(logo_path)
        else:
            icon = self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        
        self.tray_icon.setIcon(icon)
        self.tray_icon.setToolTip("PyStreamDeck Pro")
        
        # Tray Menu
        menu = QMenu()
        
        show_action = QAction("Show", self)
        show_action.triggered.connect(self.show)
        menu.addAction(show_action)
        
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self.quit_app)
        menu.addAction(quit_action)
        
        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(self.on_tray_activate)
        self.tray_icon.show()
        
    def on_tray_activate(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.isVisible():
                self.hide()
            else:
                self.show()
                self.activateWindow()
    
    def quit_app(self):
        self.can_exit = True
        QApplication.quit()
        
    def init_ui(self):
        self.setWindowTitle("PyStreamDeck Pro")
        logo_path = resource_path("logo.png")
        if os.path.exists(logo_path):
            self.setWindowIcon(QIcon(logo_path))
        self.setMinimumSize(520, 620)
        self.resize(520, 620)
        self.setStyleSheet("QMainWindow { background-color: #0f0f1a; }")
        
        # Central widget with stacked pages
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)
        
        # Create pages
        self.main_page = self.create_main_page()
        self.qr_page = self.create_qr_page()
        self.editor_page = self.create_editor_page()
        
        self.stack.addWidget(self.main_page)
        self.stack.addWidget(self.qr_page)
        self.stack.addWidget(self.editor_page)
        
        self.stack.setCurrentIndex(0)
    
    def create_main_page(self):
        page = QWidget()
        page.setStyleSheet("background: #0f0f1a;")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 25, 30, 20)
        layout.setSpacing(15)
        
        # Header
        title = QLabel("⌨️ PyStreamDeck Pro")
        title.setStyleSheet("color: #00d2ff; font-size: 24px; font-weight: bold;")
        layout.addWidget(title)
        
        connect_btn = QPushButton("📱 Connect Mobile")
        connect_btn.setStyleSheet("background: #252540; border: none; border-radius: 8px; color: #00d2ff; font-size: 10px; padding: 6px 12px;")
        connect_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        connect_btn.clicked.connect(self.show_qr_page)
        connect_btn.setFixedWidth(130)
        layout.addWidget(connect_btn)
        
        # Profile selector
        profile_label = QLabel("PROFILE")
        profile_label.setStyleSheet("color: #8888a0; font-size: 11px;")
        layout.addWidget(profile_label)
        
        self.profile_combo = QComboBox()
        self.profile_combo.addItems(PROFILES)
        self.profile_combo.setStyleSheet("""
            QComboBox { background: #252540; border: 1px solid #3a3a5c; border-radius: 8px; color: #00d2ff; padding: 8px 12px; font-size: 12px; min-width: 150px; }
            QComboBox:hover { border-color: #00d2ff; }
            QComboBox::drop-down { border: none; width: 30px; }
            QComboBox QAbstractItemView { background: #1a1a2e; border: 1px solid #3a3a5c; color: #e0e0e0; selection-background-color: #00d2ff; selection-color: #000; }
        """)
        self.profile_combo.currentTextChanged.connect(self.on_profile_change)
        layout.addWidget(self.profile_combo)
        
        # Macro grid
        grid_container = QFrame()
        grid_container.setStyleSheet("background: #1a1a2e; border-radius: 16px; padding: 15px;")
        grid_layout = QGridLayout(grid_container)
        grid_layout.setSpacing(12)
        
        for i in range(9):
            btn = QPushButton(f"M{i+1}\n---\nEmpty")
            btn.setMinimumSize(100, 80)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(partial(self.play_macro, i))
            btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            btn.customContextMenuRequested.connect(partial(self.show_context_menu, i))
            btn.setStyleSheet(self.get_button_style(False))
            row, col = divmod(i, 3)
            grid_layout.addWidget(btn, row, col)
            self.buttons.append(btn)
        
        # Make grid expand evenly
        for r in range(3): grid_layout.setRowStretch(r, 1)
        for c in range(3): grid_layout.setColumnStretch(c, 1)
        
        layout.addWidget(grid_container, 1)
        
        # Status
        self.status_label = QLabel("💡 Left-click to play • Right-click for options")
        self.status_label.setStyleSheet("color: #8888a0; font-size: 11px;")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)
        
        tray_info = QLabel("✕ Close button exits the app")
        tray_info.setStyleSheet("color: #8888a0; font-size: 9px;")
        tray_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(tray_info)
        
        layout.addStretch()
        return page
    
    def create_qr_page(self):
        page = QWidget()
        page.setStyleSheet("background: #0f0f1a;")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 25, 30, 20)
        
        # Back button
        back_btn = QPushButton("← Back")
        back_btn.setStyleSheet("background: transparent; border: none; color: #00d2ff; font-size: 14px; font-weight: bold; text-align: left;")
        back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        back_btn.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        layout.addWidget(back_btn)
        
        layout.addStretch()
        
        # QR container
        self.qr_label = QLabel()
        self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr_label.setStyleSheet("background: #ffffff; border-radius: 16px; padding: 20px;")
        self.qr_label.setFixedSize(250, 250)
        layout.addWidget(self.qr_label, alignment=Qt.AlignmentFlag.AlignCenter)
        
        title = QLabel("Scan to Connect")
        title.setStyleSheet("color: #ffffff; font-size: 18px; font-weight: bold; margin-top: 20px;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        self.url_label = QLabel("")
        self.url_label.setStyleSheet("color: #00d2ff; font-size: 12px;")
        self.url_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.url_label)
        
        layout.addStretch()
        return page
    
    def create_editor_page(self):
        page = QWidget()
        page.setStyleSheet("background: #0a0a0a;")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 25, 30, 20)
        
        # Header with back button
        header = QHBoxLayout()
        
        back_btn = QPushButton("← Back")
        back_btn.setStyleSheet("background: transparent; border: none; color: #00d2ff; font-size: 14px; font-weight: bold;")
        back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        back_btn.clicked.connect(self.close_editor)
        header.addWidget(back_btn)
        
        header.addStretch()
        
        save_btn = QPushButton("💾 Save")
        save_btn.setStyleSheet("background: #00ff88; border: none; border-radius: 8px; color: #000; font-weight: bold; padding: 8px 20px;")
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.clicked.connect(self.save_editor)
        header.addWidget(save_btn)
        
        layout.addLayout(header)
        
        # Title
        self.editor_title = QLabel("Macro Editor")
        self.editor_title.setStyleSheet("color: #ffffff; font-size: 28px; font-weight: bold; margin-top: 10px;")
        layout.addWidget(self.editor_title)
        
        subtitle = QLabel("Click key to edit • Right-click to delete")
        subtitle.setStyleSheet("color: #888888; font-size: 11px;")
        layout.addWidget(subtitle)
        
        # Timeline scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("background: transparent; border: none;")
        scroll.setFixedHeight(150)
        
        self.timeline_widget = QWidget()
        self.timeline_layout = QHBoxLayout(self.timeline_widget)
        self.timeline_layout.setSpacing(10)
        self.timeline_layout.setContentsMargins(0, 20, 0, 20)
        
        scroll.setWidget(self.timeline_widget)
        layout.addWidget(scroll)
        
        layout.addStretch()
        return page
    
    def show_qr_page(self):
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
        url = f"http://{local_ip}:5000"
        
        qr = qrcode.QRCode(version=1, box_size=6, border=4)
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)
        
        pixmap = QPixmap()
        pixmap.loadFromData(buffer.read())
        self.qr_label.setPixmap(pixmap.scaled(200, 200, Qt.AspectRatioMode.KeepAspectRatio))
        self.url_label.setText(url)
        
        self.stack.setCurrentIndex(1)
    
    def show_editor_page(self, btn_id):
        if btn_id not in self.macros:
            QMessageBox.information(self, "No Macro", f"Slot M{btn_id+1} is empty.")
            return
        
        macro_data = self.macros[btn_id]
        if isinstance(macro_data, list):
            events = list(macro_data)
            name = f"M{btn_id+1}"
        else:
            events = list(macro_data.get('events', []))
            name = macro_data.get('name', f"M{btn_id+1}")
        
        if not events:
            QMessageBox.information(self, "No Events", f"Slot '{name}' has no recorded events.")
            return
        
        self.current_edit_btn_id = btn_id
        self.current_edit_events = events
        self.editor_title.setText(name)
        
        self.refresh_timeline()
        self.stack.setCurrentIndex(2)
    
    def refresh_timeline(self):
        # Clear existing
        while self.timeline_layout.count():
            child = self.timeline_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        
        events = self.current_edit_events
        btn_id = self.current_edit_btn_id
        
        for i, (action, key_str, delay) in enumerate(events):
            # Key block
            key_block = QWidget()
            key_block.setFixedWidth(80) 
            key_block.setFixedHeight(100)
            key_layout = QVBoxLayout(key_block)
            key_layout.setSpacing(2)
            key_layout.setContentsMargins(0, 0, 0, 0)
            
            if key_str.startswith("Key."):
                key_display = key_str.split(".")[1].replace("_", " ").title()
            else:
                key_display = key_str.upper() if len(key_str) == 1 else key_str
            
            top_arrow = QLabel("▲" if action == "release" else "")
            top_arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
            top_arrow.setStyleSheet("font-size: 14px; color: #ffffff;")
            top_arrow.setFixedHeight(20)
            key_layout.addWidget(top_arrow)
            
            key_btn = QPushButton(key_display)
            key_btn.setStyleSheet("background: #8b2942; border: none; border-radius: 8px; color: #fff; font-weight: bold; padding: 10px 5px;")
            key_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            key_btn.setFixedHeight(45)
            key_btn.clicked.connect(partial(self.edit_key_inline, i))
            key_btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            key_btn.customContextMenuRequested.connect(partial(self.delete_key_event, i))
            key_layout.addWidget(key_btn)
            
            bottom_arrow = QLabel("▼" if action == "press" else "")
            bottom_arrow.setAlignment(Qt.AlignmentFlag.AlignCenter)
            bottom_arrow.setStyleSheet("font-size: 14px; color: #ffffff;")
            bottom_arrow.setFixedHeight(20)
            key_layout.addWidget(bottom_arrow)
            
            self.timeline_layout.addWidget(key_block)
            
            # Delay block (inserted AFTER key)
            delay_block = QWidget()
            delay_block.setFixedWidth(50)
            delay_block.setFixedHeight(100)
            delay_layout = QVBoxLayout(delay_block)
            delay_layout.setContentsMargins(0, 0, 0, 0)
            delay_layout.setSpacing(0)
            
            # Use stretch to center vertically
            delay_layout.addStretch()
            
            delay_ms = int(delay * 1000)
            delay_btn = QPushButton(f"{delay_ms}\nms")
            delay_btn.setFixedSize(40, 40)
            delay_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            delay_btn.setStyleSheet("""
                QPushButton { background: #3a1520; border: 1px solid #8b2942; border-radius: 6px; color: #fff; font-size: 10px; line-height: 1.2; }
                QPushButton:hover { background: #8b2942; }
            """)
            delay_btn.clicked.connect(partial(self.edit_delay_inline, i))
            delay_layout.addWidget(delay_btn, alignment=Qt.AlignmentFlag.AlignCenter)
            
            delay_layout.addStretch()
            self.timeline_layout.addWidget(delay_block)
        
        # Add button container
        add_container = QWidget()
        add_container.setFixedHeight(100)
        add_container_layout = QVBoxLayout(add_container)
        add_container_layout.setContentsMargins(0, 0, 0, 0)
        add_container_layout.addStretch()
        
        add_btn = QPushButton("+")
        add_btn.setStyleSheet("background: #3a3a3a; border: none; border-radius: 8px; color: #fff; font-size: 20px; font-weight: bold;")
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.setFixedSize(50, 45)
        add_btn.clicked.connect(self.add_key_inline)
        add_container_layout.addWidget(add_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        
        add_container_layout.addStretch()
        self.timeline_layout.addWidget(add_container)
        self.timeline_layout.addStretch()
    
    def edit_key_inline(self, idx):
        action, key_str, delay = self.current_edit_events[idx]
        display_key = key_str  # Use exact key string for editing
        
        dialog = KeyEditorDialog(self, key_val=display_key, action_val=action, delay_val=delay)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_action, new_key, new_delay = dialog.result_data
            self.current_edit_events[idx] = (new_action, new_key, new_delay)
            self.refresh_timeline()
    
    def edit_delay_inline(self, idx):
        action, key, delay = self.current_edit_events[idx]
        current_ms = int(delay * 1000)
        new_delay_str, ok = QInputDialog.getText(self, "Edit Delay", "Delay (ms):", text=str(current_ms))
        if ok:
            try:
                new_delay = float(new_delay_str) / 1000.0
                self.current_edit_events[idx] = (action, key, new_delay)
                self.refresh_timeline()
            except ValueError:
                QMessageBox.warning(self, "Invalid", "Delay must be a number.")
    
    def delete_key_event(self, idx, pos):
        if len(self.current_edit_events) <= 1:
            QMessageBox.warning(self, "Cannot Delete", "Macro must have at least one event.")
            return
        del self.current_edit_events[idx]
        self.refresh_timeline()
    
    def add_key_inline(self):
        dialog = KeyEditorDialog(self, key_val="", action_val="press", delay_val=0.05)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            action, new_key, delay = dialog.result_data
            
            # Check for multi-char string (not special key)
            if len(new_key) > 1 and not new_key.startswith("Key."):
                for char in new_key:
                    self.current_edit_events.append(('press', char, delay))
                    self.current_edit_events.append(('release', char, delay))
            else:
                self.current_edit_events.append((action, new_key, delay))
                
            self.refresh_timeline()
    
    def save_editor(self):
        btn_id = self.current_edit_btn_id
        if isinstance(self.macros[btn_id], dict):
            self.macros[btn_id]['events'] = self.current_edit_events
        else:
            self.macros[btn_id] = self.current_edit_events
        self.save_macros()
        self.status_signal.emit("✅ Macro saved", "#00ff88")
        self.stack.setCurrentIndex(0)
    
    def close_editor(self):
        self.stack.setCurrentIndex(0)
    
    def update_status(self, message, color):
        self.status_label.setText(message)
        self.status_label.setStyleSheet(f"color: {color}; font-size: 11px;")
    
    def show_context_menu(self, btn_id, pos):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background: #1a1a2e; border: 1px solid #3a3a5c; border-radius: 8px; padding: 5px; }
            QMenu::item { padding: 8px 20px; color: #e0e0e0; }
            QMenu::item:selected { background: #00d2ff; color: #000; border-radius: 4px; }
        """)
        
        record_action = QAction("🔴 Record Macro", self)
        record_action.triggered.connect(lambda: self.start_recording(btn_id))
        menu.addAction(record_action)
        
        view_action = QAction("👁️ View Macro", self)
        view_action.triggered.connect(lambda: self.show_editor_page(btn_id))
        menu.addAction(view_action)
        
        rename_action = QAction("✏️ Rename Slot", self)
        rename_action.triggered.connect(lambda: self.rename_slot(btn_id))
        menu.addAction(rename_action)
        
        clear_action = QAction("🗑️ Clear Slot", self)
        clear_action.triggered.connect(lambda: self.clear_slot(btn_id))
        menu.addAction(clear_action)
        
        menu.exec(self.buttons[btn_id].mapToGlobal(pos))
    
    def rename_slot(self, btn_id):
        current_name = f"M{btn_id+1}"
        if btn_id in self.macros and isinstance(self.macros[btn_id], dict):
            current_name = self.macros[btn_id].get('name', current_name)
        
        new_name, ok = QInputDialog.getText(self, "Rename Slot", "Enter new name:", text=current_name)
        if ok and new_name:
            if btn_id not in self.macros:
                self.macros[btn_id] = {'events': [], 'name': new_name}
            elif isinstance(self.macros[btn_id], list):
                self.macros[btn_id] = {'events': self.macros[btn_id], 'name': new_name}
            else:
                self.macros[btn_id]['name'] = new_name
            self.save_macros()
            self.refresh_button(btn_id)
    
    def clear_slot(self, btn_id):
        if btn_id in self.macros:
            del self.macros[btn_id]
            self.save_macros()
            self.refresh_button(btn_id)
    
    def refresh_button(self, btn_id):
        btn = self.buttons[btn_id]
        if btn_id in self.macros:
            data = self.macros[btn_id]
            if isinstance(data, list):
                name, status = f"M{btn_id+1}", "Loaded"
            else:
                name = data.get('name', f"M{btn_id+1}")
                status = "Ready" if data.get('events') else "Empty"
            btn.setText(f"{name}\n---\n{status}")
            btn.setStyleSheet(self.get_button_style(True))
        else:
            btn.setText(f"M{btn_id+1}\n---\nEmpty")
            btn.setStyleSheet(self.get_button_style(False))
    
    def get_button_style(self, active):
        if active:
            return '''
                QPushButton { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #00cc77, stop:1 #00ff88); border: 2px solid #00ff88; border-radius: 12px; color: #000; font-weight: bold; font-size: 12px; }
                QPushButton:hover { background: #00ff88; }
                QPushButton:pressed { background: #00cc77; }
            '''
        else:
            return '''
                QPushButton { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #252540, stop:1 #1e1e35); border: 1px solid #3a3a5c; border-radius: 12px; color: #e0e0e0; font-weight: bold; font-size: 12px; }
                QPushButton:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #3a7bd5, stop:1 #00d2ff); border-color: #00d2ff; }
                QPushButton:pressed { background: #00d2ff; color: #000; }
            '''
    
    def change_profile(self, profile_name):
        self.profile_combo.setCurrentText(profile_name)
    
    def on_profile_change(self, profile_name):
        if not profile_name: return
        self.save_macros()
        self.current_profile = profile_name
        self.macros = {}
        for i in range(9):
            self.buttons[i].setText(f"M{i+1}\n---\nEmpty")
            self.buttons[i].setStyleSheet(self.get_button_style(False))
        self.load_macros()
        self.status_signal.emit(f"📁 Switched to: {self.current_profile}", "#8888a0")
    
    def get_file_path(self):
        base_dir = os.path.join(os.path.expanduser("~"), ".macro")
        if not os.path.exists(base_dir): os.makedirs(base_dir)
        safe_name = self.current_profile.lower().replace(" ", "_")
        return os.path.join(base_dir, f"macros_{safe_name}.json")
    
    def start_recording(self, btn_id):
        if self.is_recording: return
        threading.Thread(target=self.record_macro, args=(btn_id,), daemon=True).start()
    
    def record_macro(self, btn_id):
        self.is_recording = True
        btn = self.buttons[btn_id]
        
        current_name = f"M{btn_id+1}"
        if btn_id in self.macros and isinstance(self.macros[btn_id], dict):
            current_name = self.macros[btn_id]['name']
        
        btn.setText(f"{current_name}\n🔴\nREC...")
        self.status_signal.emit("🔴 Recording... Press ESC to stop", "#ff4466")
        
        captured_events = []
        last_time = time.time()

        # Default fixed delay of 50ms (0.05s) as requested
        DEFAULT_DELAY = 0.05

        def on_press(key):
            captured_events.append(('press', str(key).strip("'"), DEFAULT_DELAY))

        def on_release(key):
            captured_events.append(('release', str(key).strip("'"), DEFAULT_DELAY))
            if key == Key.esc: return False

        with Listener(on_press=on_press, on_release=on_release) as listener:
            listener.join()

        clean_events = [e for e in captured_events if "Key.esc" not in e[1]]
        
        name = current_name
        if btn_id in self.macros and isinstance(self.macros[btn_id], dict):
            name = self.macros[btn_id].get('name', name)
            
        self.macros[btn_id] = {'events': clean_events, 'name': name}
        self.save_macros()
        self.refresh_button(btn_id)
        self.status_signal.emit("✅ Macro saved!", "#00ff88")
        self.is_recording = False
    
    def play_macro(self, btn_id):
        if self.is_playing:
            self.status_signal.emit("⚠️ A macro is already running", "#ffaa00")
            return

        if str(btn_id) in self.macros: btn_id = str(btn_id)
        elif int(btn_id) in self.macros: btn_id = int(btn_id)
        else:
            self.status_signal.emit(f"⚠️ Slot M{int(btn_id)+1} is empty", "#8888a0")
            return

        macro_data = self.macros[btn_id]
        events = macro_data if isinstance(macro_data, list) else macro_data.get('events', [])
        if not events:
            self.status_signal.emit(f"⚠️ Slot M{int(btn_id)+1} has no events", "#8888a0")
            return

        self.status_signal.emit(f"▶️ Playing M{int(btn_id)+1}...", "#00d2ff")
        self.is_playing = True
        
        def _run():
            try:
                self.engine.play(events)
                self.status_signal.emit("✅ Playback complete", "#00ff88")
            except Exception as e:
                self.status_signal.emit(f"❌ Error: {e}", "#ff4466")
            finally:
                self.is_playing = False
                
        threading.Thread(target=_run, daemon=True).start()
    
    def save_macros(self):
        with open(self.get_file_path(), 'w') as f:
            json.dump(self.macros, f)
    
    def get_default_macros(self):
        """Return default macros for current profile"""
        defaults = {
            "General": {
                0: {'name': 'Copy', 'events': [('press', 'Key.ctrl', 0.05), ('press', 'c', 0.05), ('release', 'c', 0.05), ('release', 'Key.ctrl', 0.05)]},
                1: {'name': 'Cut', 'events': [('press', 'Key.ctrl', 0.05), ('press', 'x', 0.05), ('release', 'x', 0.05), ('release', 'Key.ctrl', 0.05)]},
                2: {'name': 'Paste', 'events': [('press', 'Key.ctrl', 0.05), ('press', 'v', 0.05), ('release', 'v', 0.05), ('release', 'Key.ctrl', 0.05)]},
                3: {'name': 'Undo', 'events': [('press', 'Key.ctrl', 0.05), ('press', 'z', 0.05), ('release', 'z', 0.05), ('release', 'Key.ctrl', 0.05)]},
                4: {'name': 'Redo', 'events': [('press', 'Key.ctrl', 0.05), ('press', 'y', 0.05), ('release', 'y', 0.05), ('release', 'Key.ctrl', 0.05)]},
                5: {'name': 'Select All', 'events': [('press', 'Key.ctrl', 0.05), ('press', 'a', 0.05), ('release', 'a', 0.05), ('release', 'Key.ctrl', 0.05)]},
                6: {'name': 'Find', 'events': [('press', 'Key.ctrl', 0.05), ('press', 'f', 0.05), ('release', 'f', 0.05), ('release', 'Key.ctrl', 0.05)]},
                7: {'name': 'Save', 'events': [('press', 'Key.ctrl', 0.05), ('press', 's', 0.05), ('release', 's', 0.05), ('release', 'Key.ctrl', 0.05)]},
                8: {'name': 'Print', 'events': [('press', 'Key.ctrl', 0.05), ('press', 'p', 0.05), ('release', 'p', 0.05), ('release', 'Key.ctrl', 0.05)]}
            },
            "Video Editing": {
                0: {'name': 'Play/Pause', 'events': [('press', 'Key.space', 0.05), ('release', 'Key.space', 0.05)]},
                1: {'name': 'Cut', 'events': [('press', 'Key.ctrl', 0.05), ('press', 'k', 0.05), ('release', 'k', 0.05), ('release', 'Key.ctrl', 0.05)]},
                2: {'name': 'Razor Tool', 'events': [('press', 'c', 0.05), ('release', 'c', 0.05)]},
                3: {'name': 'Selection', 'events': [('press', 'v', 0.05), ('release', 'v', 0.05)]},
                4: {'name': 'Zoom In', 'events': [('press', 'Key.ctrl', 0.05), ('press', '=', 0.05), ('release', '=', 0.05), ('release', 'Key.ctrl', 0.05)]},
                5: {'name': 'Zoom Out', 'events': [('press', 'Key.ctrl', 0.05), ('press', '-', 0.05), ('release', '-', 0.05), ('release', 'Key.ctrl', 0.05)]},
                6: {'name': 'Mark In', 'events': [('press', 'i', 0.05), ('release', 'i', 0.05)]},
                7: {'name': 'Mark Out', 'events': [('press', 'o', 0.05), ('release', 'o', 0.05)]},
                8: {'name': 'Export', 'events': [('press', 'Key.ctrl', 0.05), ('press', 'm', 0.05), ('release', 'm', 0.05), ('release', 'Key.ctrl', 0.05)]}
            },
            "Photo Editing": {
                0: {'name': 'Brush', 'events': [('press', 'b', 0.05), ('release', 'b', 0.05)]},
                1: {'name': 'Eraser', 'events': [('press', 'e', 0.05), ('release', 'e', 0.05)]},
                2: {'name': 'Move Tool', 'events': [('press', 'v', 0.05), ('release', 'v', 0.05)]},
                3: {'name': 'Crop', 'events': [('press', 'c', 0.05), ('release', 'c', 0.05)]},
                4: {'name': 'New Layer', 'events': [('press', 'Key.ctrl', 0.05), ('press', 'Key.shift', 0.05), ('press', 'n', 0.05), ('release', 'n', 0.05), ('release', 'Key.shift', 0.05), ('release', 'Key.ctrl', 0.05)]},
                5: {'name': 'Merge Down', 'events': [('press', 'Key.ctrl', 0.05), ('press', 'e', 0.05), ('release', 'e', 0.05), ('release', 'Key.ctrl', 0.05)]},
                6: {'name': 'Zoom In', 'events': [('press', 'Key.ctrl', 0.05), ('press', '=', 0.05), ('release', '=', 0.05), ('release', 'Key.ctrl', 0.05)]},
                7: {'name': 'Zoom Out', 'events': [('press', 'Key.ctrl', 0.05), ('press', '-', 0.05), ('release', '-', 0.05), ('release', 'Key.ctrl', 0.05)]},
                8: {'name': 'Fit Screen', 'events': [('press', 'Key.ctrl', 0.05), ('press', '0', 0.05), ('release', '0', 0.05), ('release', 'Key.ctrl', 0.05)]}
            },
            "Gaming": {
                0: {'name': 'Move Forward', 'events': [('press', 'w', 0.05), ('release', 'w', 0.05)]},
                1: {'name': 'Move Left', 'events': [('press', 'a', 0.05), ('release', 'a', 0.05)]},
                2: {'name': 'Move Back', 'events': [('press', 's', 0.05), ('release', 's', 0.05)]},
                3: {'name': 'Move Right', 'events': [('press', 'd', 0.05), ('release', 'd', 0.05)]},
                4: {'name': 'Jump', 'events': [('press', 'Key.space', 0.05), ('release', 'Key.space', 0.05)]},
                5: {'name': 'Crouch', 'events': [('press', 'Key.ctrl', 0.05), ('release', 'Key.ctrl', 0.05)]},
                6: {'name': 'Reload', 'events': [('press', 'r', 0.05), ('release', 'r', 0.05)]},
                7: {'name': 'Use/Interact', 'events': [('press', 'e', 0.05), ('release', 'e', 0.05)]},
                8: {'name': 'Inventory', 'events': [('press', 'i', 0.05), ('release', 'i', 0.05)]}
            },
            "Productivity": {
                0: {'name': 'New Tab', 'events': [('press', 'Key.ctrl', 0.05), ('press', 't', 0.05), ('release', 't', 0.05), ('release', 'Key.ctrl', 0.05)]},
                1: {'name': 'Close Tab', 'events': [('press', 'Key.ctrl', 0.05), ('press', 'w', 0.05), ('release', 'w', 0.05), ('release', 'Key.ctrl', 0.05)]},
                2: {'name': 'Next Tab', 'events': [('press', 'Key.ctrl', 0.05), ('press', 'Key.tab', 0.05), ('release', 'Key.tab', 0.05), ('release', 'Key.ctrl', 0.05)]},
                3: {'name': 'Prev Tab', 'events': [('press', 'Key.ctrl', 0.05), ('press', 'Key.shift', 0.05), ('press', 'Key.tab', 0.05), ('release', 'Key.tab', 0.05), ('release', 'Key.shift', 0.05), ('release', 'Key.ctrl', 0.05)]},
                4: {'name': 'Minimize', 'events': [('press', 'Key.alt', 0.05), ('press', 'Key.space', 0.05), ('release', 'Key.space', 0.05), ('press', 'n', 0.05), ('release', 'n', 0.05), ('release', 'Key.alt', 0.05)]},
                5: {'name': 'Maximize', 'events': [('press', 'Key.alt', 0.05), ('press', 'Key.space', 0.05), ('release', 'Key.space', 0.05), ('press', 'x', 0.05), ('release', 'x', 0.05), ('release', 'Key.alt', 0.05)]},
                6: {'name': 'Task View', 'events': [('press', 'Key.cmd', 0.05), ('press', 'Key.tab', 0.05), ('release', 'Key.tab', 0.05), ('release', 'Key.cmd', 0.05)]},
                7: {'name': 'Lock PC', 'events': [('press', 'Key.cmd', 0.05), ('press', 'l', 0.05), ('release', 'l', 0.05), ('release', 'Key.cmd', 0.05)]},
                8: {'name': 'Screenshot', 'events': [('press', 'Key.cmd', 0.05), ('press', 'Key.shift', 0.05), ('press', 's', 0.05), ('release', 's', 0.05), ('release', 'Key.shift', 0.05), ('release', 'Key.cmd', 0.05)]}
            }
        }
        return defaults.get(self.current_profile, {})
    
    def load_macros(self):
        file_path = self.get_file_path()
        if not os.path.exists(file_path):
            # Initialize with default macros for this profile
            self.macros = self.get_default_macros()
            self.save_macros()  # Save defaults so they persist
            for k in self.macros.keys():
                if k < len(self.buttons):
                    self.refresh_button(k)
            return
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
                self.macros = {int(k): v for k, v in data.items()}
                for k in list(self.macros.keys()):
                    if k < len(self.buttons):
                        self.refresh_button(k)
        except Exception as e:
            print(f"Load error: {e}")
    
    def closeEvent(self, event):
        self.save_macros()
        if not self.can_exit:
            event.ignore()
            self.hide()
            self.tray_icon.showMessage(
                "PyStreamDeck Pro",
                "App minimized to system tray. Right-click tray icon to quit.",
                QSystemTrayIcon.MessageIcon.Information,
                2000
            )
        else:
            event.accept()


if __name__ == "__main__":
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    window = StreamDeckWindow()
    window.show()
    sys.exit(app.exec())
