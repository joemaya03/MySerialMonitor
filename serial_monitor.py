#!/usr/bin/env python3
"""
Professional Serial Monitor
A comprehensive, feature-rich serial monitoring application
Author: Generated for professional embedded development
Version: 1.0.0
"""

import sys
import os
import json
import time
import threading
import queue
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import re

from PySide6.QtWidgets import *
from PySide6.QtCore import *
from PySide6.QtGui import *
import serial
import serial.tools.list_ports

# Configuration and Constants
class Config:
    APP_NAME = "Professional Serial Monitor"
    VERSION = "1.0.0"
    COMPANY = "DevTools Pro"
    
    # Log levels with colors and priorities
    LOG_LEVELS = {
        '0': {'name': 'ERROR', 'color': '#FF4444', 'priority': 0},
        '1': {'name': 'WARN', 'color': '#FFA500', 'priority': 1},
        '2': {'name': 'INFO', 'color': '#00AAFF', 'priority': 2},
        '3': {'name': 'DEBUG', 'color': '#00FF88', 'priority': 3},
        '4': {'name': 'VERBOSE', 'color': '#888888', 'priority': 4},
        'wm': {'name': 'WIFIMANAGER', 'color': '#FF00FF', 'priority': 5},  # Magenta
        'verbose': {'name': 'GENERIC', 'color': '#CCCCCC', 'priority': 6}  # Light gray
    }
    
    # Default settings
    DEFAULT_SETTINGS = {
        'baudrate': 115200,
        'line_ending': 'CRLF',
        'show_timestamps': True,
        'auto_scroll': True,
        'max_lines': 10000,
        'log_file_size_mb': 10,
        'auto_save': True,
        'auto_save_interval': 60,  # seconds
        'theme': 'dark',
        'font_family': 'Consolas',
        'font_size': 10,
        'log_level_filter': [True, True, True, True, True, True, True],  # All levels enabled (7 total)
        'window_geometry': None,
        'splitter_state': None
    }
    
    LINE_ENDINGS = {
        'CRLF': '\r\n',
        'LF': '\n',
        'CR': '\r',
        'None': ''
    }

class LogEntry:
    """Represents a single log entry with metadata"""
    def __init__(self, raw_data: str, timestamp: datetime, level: str = None, message: str = None):
        self.raw_data = raw_data.strip()
        self.timestamp = timestamp
        self.level = level
        self.message = message
        self.parsed = False
        
        # Parse log level and message
        self._parse_log()
    
    def _parse_log(self):
        """Parse log level and message from raw data"""
        # Pattern 1: [0/1/2/3/4] message
        level_pattern = r'^\[([0-4])\]\s*(.*)'
        level_match = re.match(level_pattern, self.raw_data)
        
        if level_match:
            self.level = level_match.group(1)
            self.message = level_match.group(2)
            self.parsed = True
            return
        
        # Pattern 2: *wm message (WiFi Manager logs)
        wm_pattern = r'^\*wm\s*(.*)'
        wm_match = re.match(wm_pattern, self.raw_data)
        
        if wm_match:
            self.level = 'wm'
            self.message = wm_match.group(1)
            self.parsed = True
            return
        
        # Pattern 3: No identifier - treat as generic
        self.level = 'verbose'
        self.message = self.raw_data
        self.parsed = False
    
    def get_level_name(self) -> str:
        """Get human-readable level name"""
        return Config.LOG_LEVELS.get(self.level, {}).get('name', 'UNKNOWN')
    
    def get_level_color(self) -> str:
        """Get color for this log level"""
        return Config.LOG_LEVELS.get(self.level, {}).get('color', '#FFFFFF')
    
    def to_display_string(self, show_timestamp: bool = True) -> str:
        """Convert to display string"""
        timestamp_str = ""
        if show_timestamp:
            timestamp_str = f"{self.timestamp.strftime('%H:%M:%S.%f')[:-3]} "
        
        # Always show formatted version
        return f"{timestamp_str}[{self.get_level_name()}] {self.message}"
    
    def to_export_string(self, show_timestamp: bool = True) -> str:
        """Convert to export string"""
        return self.to_display_string(show_timestamp)

class SerialWorker(QObject):
    """Worker thread for serial communication"""
    data_received = Signal(str)
    connection_lost = Signal(str)
    
    def __init__(self):
        super().__init__()
        self.serial_port = None
        self.running = False
        
    def connect_serial(self, port: str, baudrate: int) -> bool:
        """Connect to serial port"""
        try:
            self.serial_port = serial.Serial(
                port=port,
                baudrate=baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.1
            )
            self.running = True
            return True
        except Exception as e:
            self.connection_lost.emit(f"Failed to connect: {str(e)}")
            return False
    
    def disconnect_serial(self):
        """Disconnect from serial port"""
        self.running = False
        if self.serial_port and self.serial_port.is_open:
            self.serial_port.close()
            self.serial_port = None
    
    def read_data(self):
        """Main reading loop"""
        buffer = ""
        while self.running and self.serial_port and self.serial_port.is_open:
            try:
                if self.serial_port.in_waiting > 0:
                    data = self.serial_port.read(self.serial_port.in_waiting).decode('utf-8', errors='replace')
                    buffer += data
                    
                    # Process complete lines
                    while '\n' in buffer:
                        line, buffer = buffer.split('\n', 1)
                        line = line.rstrip('\r')
                        if line:
                            self.data_received.emit(line)
                else:
                    time.sleep(0.01)  # Small delay to prevent high CPU usage
                    
            except Exception as e:
                self.connection_lost.emit(f"Connection lost: {str(e)}")
                break
    
    def send_data(self, data: str, line_ending: str = '\r\n'):
        """Send data to serial port"""
        if self.serial_port and self.serial_port.is_open:
            try:
                self.serial_port.write((data + line_ending).encode('utf-8'))
                return True
            except Exception:
                return False
        return False

class LogDisplayWidget(QTextEdit):
    """Custom text widget for log display with advanced features"""
    
    def __init__(self):
        super().__init__()
        self.setReadOnly(True)
        self.setFont(QFont("Consolas", 10))
        self.log_entries: List[LogEntry] = []
        self.filtered_entries: List[LogEntry] = []
        self.show_timestamps = True
        self.level_filter = [True] * 7  # All 7 levels enabled
        self.auto_scroll_enabled = True
        self.max_lines = 10000
        
        # Setup context menu
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.show_context_menu)
    
    def add_log_entry(self, entry: LogEntry):
        """Add a new log entry"""
        self.log_entries.append(entry)
        
        # Trim to max lines
        if len(self.log_entries) > self.max_lines:
            self.log_entries = self.log_entries[-self.max_lines:]
        
        self.apply_filters()
    
    def apply_filters(self):
        """Apply current filters and refresh display"""
        self.filtered_entries = []
        
        level_map = {'0': 0, '1': 1, '2': 2, '3': 3, '4': 4, 'wm': 5, 'verbose': 6}

        for entry in self.log_entries:
            level_idx = level_map.get(entry.level, 2)  # Default to INFO if unknown
            if level_idx < len(self.level_filter) and self.level_filter[level_idx]:
                self.filtered_entries.append(entry)
        
        self.refresh_display()
    
    def refresh_display(self):
        """Refresh the display with current filtered entries"""
        # Save scroll position
        scrollbar = self.verticalScrollBar()
        was_at_bottom = scrollbar.value() == scrollbar.maximum()
        
        self.clear()
        
        for entry in self.filtered_entries:
            self.append_colored_text(entry)
        
        # Restore scroll position
        if self.auto_scroll_enabled and was_at_bottom:
            scrollbar.setValue(scrollbar.maximum())
    
    def append_colored_text(self, entry: LogEntry):
        """Append colored text to display"""
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.End)
        
        # Set color based on log level
        color = entry.get_level_color()
        char_format = QTextCharFormat()
        char_format.setForeground(QColor(color))
        
        cursor.setCharFormat(char_format)
        cursor.insertText(entry.to_display_string(self.show_timestamps) + '\n')
        
        self.setTextCursor(cursor)
    
    def set_level_filter(self, level_filter: List[bool]):
        """Set level filter"""
        self.level_filter = level_filter[:]
        self.apply_filters()
    
    def set_show_timestamps(self, show: bool):
        """Toggle timestamp display"""
        self.show_timestamps = show
        self.refresh_display()
    
    def set_auto_scroll(self, enabled: bool):
        """Toggle auto scroll"""
        self.auto_scroll_enabled = enabled
    
    def clear_logs(self):
        """Clear all logs"""
        self.log_entries.clear()
        self.filtered_entries.clear()
        self.clear()
    
    def get_all_entries(self) -> List[LogEntry]:
        """Get all log entries"""
        return self.log_entries[:]
    
    def get_filtered_entries(self) -> List[LogEntry]:
        """Get filtered log entries"""
        return self.filtered_entries[:]
    
    def show_context_menu(self, position):
        """Show context menu"""
        menu = QMenu(self)
        
        clear_action = menu.addAction("Clear All")
        copy_action = menu.addAction("Copy Selected")
        copy_all_action = menu.addAction("Copy All Visible")
        menu.addSeparator()
        export_action = menu.addAction("Export Logs...")
        
        action = menu.exec(self.mapToGlobal(position))
        
        if action == clear_action:
            self.clear_logs()
        elif action == copy_action:
            self.copy()
        elif action == copy_all_action:
            self.selectAll()
            self.copy()
        elif action == export_action:
            self.parent().export_logs()

class MainWindow(QMainWindow):
    """Main application window"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{Config.APP_NAME} v{Config.VERSION}")
        self.setMinimumSize(1000, 700)
        
        # Initialize components
        self.serial_worker = None
        self.worker_thread = None
        self.settings = Config.DEFAULT_SETTINGS.copy()
        self.connected = False
        self.auto_save_timer = QTimer()
        self.log_file_path = None
        
        # Load settings
        self.load_settings()
        
        # Setup UI
        self.setup_ui()
        self.setup_status_bar()
        self.setup_menu_bar()
        self.apply_theme()
        
        # Setup auto-save timer
        self.auto_save_timer.timeout.connect(self.auto_save_logs)
        if self.settings['auto_save']:
            self.auto_save_timer.start(self.settings['auto_save_interval'] * 1000)
        
        # Restore window state
        self.restore_window_state()
    
    def setup_ui(self):
        """Setup the user interface"""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Main layout
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)
        
        # Connection panel
        connection_panel = self.create_connection_panel()
        main_layout.addWidget(connection_panel)
        
        # Splitter for main content
        self.splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(self.splitter)
        
        # Left panel with controls
        left_panel = self.create_control_panel()
        self.splitter.addWidget(left_panel)
        
        # Right panel with log display
        right_panel = self.create_log_panel()
        self.splitter.addWidget(right_panel)
        
        # Set splitter proportions
        self.splitter.setSizes([300, 700])
    
    def create_connection_panel(self) -> QWidget:
        """Create connection control panel"""
        panel = QGroupBox("Connection")
        layout = QHBoxLayout(panel)
        
        # COM Port selection
        layout.addWidget(QLabel("Port:"))
        self.port_combo = QComboBox()
        self.refresh_ports()
        layout.addWidget(self.port_combo)
        
        # Refresh ports button
        refresh_btn = QPushButton("🔄")
        refresh_btn.setMaximumWidth(30)
        refresh_btn.clicked.connect(self.refresh_ports)
        layout.addWidget(refresh_btn)
        
        # Baudrate selection
        layout.addWidget(QLabel("Baud:"))
        self.baudrate_combo = QComboBox()
        self.baudrate_combo.addItems(['9600', '19200', '38400', '57600', '115200', '230400', '460800', '921600'])
        self.baudrate_combo.setCurrentText(str(self.settings['baudrate']))
        self.baudrate_combo.setEditable(True)
        layout.addWidget(self.baudrate_combo)
        
        # Line ending selection
        layout.addWidget(QLabel("Line Ending:"))
        self.line_ending_combo = QComboBox()
        self.line_ending_combo.addItems(list(Config.LINE_ENDINGS.keys()))
        self.line_ending_combo.setCurrentText(self.settings['line_ending'])
        layout.addWidget(self.line_ending_combo)
        
        layout.addStretch()
        
        # Connection button
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self.toggle_connection)
        layout.addWidget(self.connect_btn)
        
        return panel
    
    def create_control_panel(self) -> QWidget:
        """Create control panel"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Display options
        display_group = QGroupBox("Display Options")
        display_layout = QVBoxLayout(display_group)
        
        self.timestamp_cb = QCheckBox("Show Timestamps")
        self.timestamp_cb.setChecked(self.settings['show_timestamps'])
        self.timestamp_cb.toggled.connect(self.toggle_timestamps)
        display_layout.addWidget(self.timestamp_cb)
        
        self.autoscroll_cb = QCheckBox("Auto Scroll")
        self.autoscroll_cb.setChecked(self.settings['auto_scroll'])
        self.autoscroll_cb.toggled.connect(self.toggle_autoscroll)
        display_layout.addWidget(self.autoscroll_cb)
        
        layout.addWidget(display_group)
        
        # Log level filters
        filter_group = QGroupBox("Log Level Filters")
        filter_layout = QVBoxLayout(filter_group)
        
        self.level_checkboxes = []
        for i, (level, info) in enumerate(Config.LOG_LEVELS.items()):
            if level == 'wm':
                cb = QCheckBox(f"{info['name']} [*wm]")
            elif level == 'verbose':
                cb = QCheckBox(f"{info['name']} [no id]")
            else:
                cb = QCheckBox(f"{info['name']} [{level}]")
            
            cb.setChecked(self.settings['log_level_filter'][i] if i < len(self.settings['log_level_filter']) else True)
            cb.setStyleSheet(f"QCheckBox {{ color: {info['color']}; }}")
            cb.toggled.connect(self.update_level_filter)
            self.level_checkboxes.append(cb)
            filter_layout.addWidget(cb)
        
        # Filter buttons
        filter_btn_layout = QHBoxLayout()
        
        all_btn = QPushButton("All")
        all_btn.clicked.connect(self.select_all_levels)
        filter_btn_layout.addWidget(all_btn)
        
        none_btn = QPushButton("None")
        none_btn.clicked.connect(self.select_no_levels)
        filter_btn_layout.addWidget(none_btn)
        
        filter_layout.addLayout(filter_btn_layout)
        layout.addWidget(filter_group)
        
        # Send data panel
        send_group = QGroupBox("Send Data")
        send_layout = QVBoxLayout(send_group)
        
        self.send_text = QLineEdit()
        self.send_text.setPlaceholderText("Enter data to send...")
        self.send_text.returnPressed.connect(self.send_data)
        send_layout.addWidget(self.send_text)
        
        send_btn = QPushButton("Send")
        send_btn.clicked.connect(self.send_data)
        send_layout.addWidget(send_btn)
        
        layout.addWidget(send_group)
        
        # Control buttons
        btn_layout = QVBoxLayout()
        
        clear_btn = QPushButton("Clear Logs")
        clear_btn.clicked.connect(self.clear_logs)
        btn_layout.addWidget(clear_btn)
        
        export_btn = QPushButton("Export Logs...")
        export_btn.clicked.connect(self.export_logs)
        btn_layout.addWidget(export_btn)
        
        save_btn = QPushButton("Save Logs...")
        save_btn.clicked.connect(self.save_logs)
        btn_layout.addWidget(save_btn)
        
        layout.addLayout(btn_layout)
        layout.addStretch()
        
        return panel
    
    def create_log_panel(self) -> QWidget:
        """Create log display panel"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Log statistics
        stats_layout = QHBoxLayout()
        self.stats_label = QLabel("Ready")
        self.stats_label.setStyleSheet("color: #888888; font-size: 11px;")
        stats_layout.addWidget(self.stats_label)
        stats_layout.addStretch()
        
        self.connection_status = QLabel("Disconnected")
        self.connection_status.setStyleSheet("color: #FF4444; font-size: 11px; font-weight: bold;")
        stats_layout.addWidget(self.connection_status)
        
        layout.addLayout(stats_layout)
        
        # Log display
        self.log_display = LogDisplayWidget()
        layout.addWidget(self.log_display)
        
        return panel
    
    def setup_status_bar(self):
        """Setup status bar"""
        self.statusBar().showMessage("Ready")
        
        # Add permanent widgets
        self.log_count_label = QLabel("Logs: 0")
        self.statusBar().addPermanentWidget(self.log_count_label)
        
        self.file_size_label = QLabel("Size: 0 KB")
        self.statusBar().addPermanentWidget(self.file_size_label)
    
    def setup_menu_bar(self):
        """Setup menu bar"""
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu("File")
        
        new_action = file_menu.addAction("New Session")
        new_action.setShortcut("Ctrl+N")
        new_action.triggered.connect(self.new_session)
        
        file_menu.addSeparator()
        
        save_action = file_menu.addAction("Save Logs...")
        save_action.setShortcut("Ctrl+S")
        save_action.triggered.connect(self.save_logs)
        
        export_action = file_menu.addAction("Export Logs...")
        export_action.setShortcut("Ctrl+E")
        export_action.triggered.connect(self.export_logs)
        
        file_menu.addSeparator()
        
        exit_action = file_menu.addAction("Exit")
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        
        # Edit menu
        edit_menu = menubar.addMenu("Edit")
        
        clear_action = edit_menu.addAction("Clear Logs")
        clear_action.setShortcut("Ctrl+L")
        clear_action.triggered.connect(self.clear_logs)
        
        copy_action = edit_menu.addAction("Copy All Visible")
        copy_action.setShortcut("Ctrl+C")
        copy_action.triggered.connect(self.copy_all_logs)
        
        # View menu
        view_menu = menubar.addMenu("View")
        
        timestamp_action = view_menu.addAction("Show Timestamps")
        timestamp_action.setCheckable(True)
        timestamp_action.setChecked(self.settings['show_timestamps'])
        timestamp_action.triggered.connect(self.toggle_timestamps)
        
        autoscroll_action = view_menu.addAction("Auto Scroll")
        autoscroll_action.setCheckable(True)
        autoscroll_action.setChecked(self.settings['auto_scroll'])
        autoscroll_action.triggered.connect(self.toggle_autoscroll)
        
        # Tools menu
        tools_menu = menubar.addMenu("Tools")
        
        settings_action = tools_menu.addAction("Settings...")
        settings_action.triggered.connect(self.show_settings)
        
        # Help menu
        help_menu = menubar.addMenu("Help")
        
        about_action = help_menu.addAction("About")
        about_action.triggered.connect(self.show_about)
    
    def apply_theme(self):
        """Apply dark theme"""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #2b2b2b;
                color: #ffffff;
            }
            QWidget {
                background-color: #2b2b2b;
                color: #ffffff;
            }
            QGroupBox {
                font-weight: bold;
                border: 2px solid #555555;
                border-radius: 5px;
                margin: 5px 0px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
            QPushButton {
                background-color: #404040;
                border: 1px solid #606060;
                border-radius: 3px;
                padding: 5px 15px;
                min-height: 20px;
            }
            QPushButton:hover {
                background-color: #505050;
            }
            QPushButton:pressed {
                background-color: #353535;
            }
            QComboBox, QLineEdit {
                background-color: #404040;
                border: 1px solid #606060;
                border-radius: 3px;
                padding: 5px;
                min-height: 20px;
            }
            QComboBox::drop-down {
                border: 0px;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 5px solid #ffffff;
            }
            QTextEdit {
                background-color: #1e1e1e;
                border: 1px solid #606060;
                border-radius: 3px;
                font-family: 'Consolas';
                font-size: 10pt;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
            }
            QCheckBox::indicator:unchecked {
                background-color: #404040;
                border: 1px solid #606060;
                border-radius: 3px;
            }
            QCheckBox::indicator:checked {
                background-color: #0078d4;
                border: 1px solid #0078d4;
                border-radius: 3px;
                image: url(data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTQiIGhlaWdodD0iMTQiIHZpZXdCb3g9IjAgMCAxNCAxNCIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHBhdGggZD0iTTExLjUgNEw1LjUgMTBMMi41IDciIHN0cm9rZT0id2hpdGUiIHN0cm9rZS13aWR0aD0iMiIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIi8+Cjwvc3ZnPgo=);
            }
            QMenuBar {
                background-color: #2b2b2b;
                border-bottom: 1px solid #606060;
            }
            QMenuBar::item {
                padding: 4px 8px;
                background-color: transparent;
            }
            QMenuBar::item:selected {
                background-color: #404040;
                border-radius: 3px;
            }
            QMenu {
                background-color: #404040;
                border: 1px solid #606060;
                border-radius: 3px;
            }
            QMenu::item {
                padding: 5px 20px;
            }
            QMenu::item:selected {
                background-color: #505050;
            }
            QStatusBar {
                background-color: #2b2b2b;
                border-top: 1px solid #606060;
            }
            QSplitter::handle {
                background-color: #606060;
            }
            QSplitter::handle:horizontal {
                width: 2px;
            }
            QScrollBar:vertical {
                background-color: #404040;
                width: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background-color: #606060;
                border-radius: 6px;
                min-height: 20px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #707070;
            }
        """)
    
    def refresh_ports(self):
        """Refresh available COM ports"""
        self.port_combo.clear()
        ports = serial.tools.list_ports.comports()
        for port in sorted(ports):
            self.port_combo.addItem(f"{port.device} - {port.description}")
    
    def toggle_connection(self):
        """Toggle serial connection"""
        if not self.connected:
            self.connect_serial()
        else:
            self.disconnect_serial()
    
    def connect_serial(self):
        """Connect to serial port"""
        if self.port_combo.currentText():
            port = self.port_combo.currentText().split(' - ')[0]
            try:
                baudrate = int(self.baudrate_combo.currentText())
            except ValueError:
                QMessageBox.warning(self, "Error", "Invalid baudrate value")
                return
            
            # Create worker thread
            self.worker_thread = QThread()
            self.serial_worker = SerialWorker()
            self.serial_worker.moveToThread(self.worker_thread)
            
            # Connect signals
            self.serial_worker.data_received.connect(self.on_data_received)
            self.serial_worker.connection_lost.connect(self.on_connection_lost)
            self.worker_thread.started.connect(self.serial_worker.read_data)
            
            # Attempt connection
            if self.serial_worker.connect_serial(port, baudrate):
                self.worker_thread.start()
                self.connected = True
                self.connect_btn.setText("Disconnect")
                self.connection_status.setText("Connected")
                self.connection_status.setStyleSheet("color: #00FF88; font-size: 11px; font-weight: bold;")
                self.statusBar().showMessage(f"Connected to {port} at {baudrate} baud")
            else:
                self.worker_thread.quit()
                self.worker_thread.wait()
                self.worker_thread = None
                self.serial_worker = None
    
    def disconnect_serial(self):
        """Disconnect from serial port"""
        if self.serial_worker:
            self.serial_worker.disconnect_serial()
        
        if self.worker_thread:
            self.worker_thread.quit()
            self.worker_thread.wait()
        
        self.connected = False
        self.connect_btn.setText("Connect")
        self.connection_status.setText("Disconnected")
        self.connection_status.setStyleSheet("color: #FF4444; font-size: 11px; font-weight: bold;")
        self.statusBar().showMessage("Disconnected")
        
        self.worker_thread = None
        self.serial_worker = None
    
    @Slot(str)
    def on_data_received(self, data: str):
        """Handle received serial data"""
        entry = LogEntry(data, datetime.now())
        self.log_display.add_log_entry(entry)
        self.update_statistics()
    
    @Slot(str)
    def on_connection_lost(self, error: str):
        """Handle connection loss"""
        self.disconnect_serial()
        QMessageBox.warning(self, "Connection Lost", error)
    
    def send_data(self):
        """Send data through serial port"""
        if self.connected and self.serial_worker:
            data = self.send_text.text()
            if data:
                line_ending = Config.LINE_ENDINGS[self.line_ending_combo.currentText()]
                if self.serial_worker.send_data(data, line_ending):
                    self.send_text.clear()
                    # Add sent data to log display
                    entry = LogEntry(f">> {data}", datetime.now(), level='2')
                    self.log_display.add_log_entry(entry)
                else:
                    QMessageBox.warning(self, "Error", "Failed to send data")
    
    def toggle_timestamps(self, checked: bool = None):
        """Toggle timestamp display"""
        if checked is None:
            checked = self.timestamp_cb.isChecked()
        else:
            self.timestamp_cb.setChecked(checked)
        
        self.settings['show_timestamps'] = checked
        self.log_display.set_show_timestamps(checked)
    
    def toggle_autoscroll(self, checked: bool = None):
        """Toggle auto scroll"""
        if checked is None:
            checked = self.autoscroll_cb.isChecked()
        else:
            self.autoscroll_cb.setChecked(checked)
        
        self.settings['auto_scroll'] = checked
        self.log_display.set_auto_scroll(checked)
    
    def update_level_filter(self):
        """Update log level filter"""
        level_filter = [cb.isChecked() for cb in self.level_checkboxes]
        self.settings['log_level_filter'] = level_filter
        self.log_display.set_level_filter(level_filter)
        self.update_statistics()
    
    def select_all_levels(self):
        """Select all log levels"""
        for cb in self.level_checkboxes:
            cb.setChecked(True)
        self.update_level_filter()
    
    def select_no_levels(self):
        """Deselect all log levels"""
        for cb in self.level_checkboxes:
            cb.setChecked(False)
        self.update_level_filter()
    
    def clear_logs(self):
        """Clear all logs"""
        reply = QMessageBox.question(self, "Clear Logs", 
                                   "Are you sure you want to clear all logs?",
                                   QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.log_display.clear_logs()
            self.update_statistics()
    
    def update_statistics(self):
        """Update statistics display"""
        total_logs = len(self.log_display.get_all_entries())
        visible_logs = len(self.log_display.get_filtered_entries())
        
        # Calculate approximate file size
        total_size = sum(len(entry.raw_data) for entry in self.log_display.get_all_entries())
        size_kb = total_size / 1024
        
        self.stats_label.setText(f"Total: {total_logs} | Visible: {visible_logs}")
        self.log_count_label.setText(f"Logs: {total_logs}")
        self.file_size_label.setText(f"Size: {size_kb:.1f} KB")
        
        # Check file size limit
        if size_kb > self.settings['log_file_size_mb'] * 1024:
            self.trim_logs()
    
    def trim_logs(self):
        """Trim logs when size limit is reached"""
        entries = self.log_display.get_all_entries()
        if len(entries) > 1000:  # Keep at least 1000 recent entries
            self.log_display.log_entries = entries[-1000:]
            self.log_display.apply_filters()
            self.statusBar().showMessage("Logs trimmed due to size limit", 3000)
    
    def export_logs(self):
        """Export logs to file"""
        dialog = ExportDialog(self.log_display.get_all_entries(), self)
        dialog.exec()
    
    def save_logs(self):
        """Save logs to file"""
        filename, _ = QFileDialog.getSaveFileName(
            self, "Save Logs", "", 
            "Text Files (*.txt);;CSV Files (*.csv);;All Files (*)"
        )
        
        if filename:
            try:
                with open(filename, 'w', encoding='utf-8') as f:
                    for entry in self.log_display.get_all_entries():
                        f.write(entry.to_export_string(self.settings['show_timestamps']) + '\n')
                
                self.statusBar().showMessage(f"Logs saved to {filename}", 3000)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save logs: {str(e)}")
    
    def auto_save_logs(self):
        """Auto-save logs"""
        if not self.log_display.get_all_entries():
            return
        
        if not self.log_file_path:
            # Create auto-save directory
            auto_save_dir = Path("auto_save_logs")
            auto_save_dir.mkdir(exist_ok=True)
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.log_file_path = auto_save_dir / f"serial_log_{timestamp}.txt"
        
        try:
            with open(self.log_file_path, 'w', encoding='utf-8') as f:
                for entry in self.log_display.get_all_entries():
                    f.write(entry.to_export_string(True) + '\n')
        except Exception as e:
            print(f"Auto-save failed: {e}")
    
    def copy_all_logs(self):
        """Copy all visible logs to clipboard"""
        text = ""
        for entry in self.log_display.get_filtered_entries():
            text += entry.to_export_string(self.settings['show_timestamps']) + '\n'
        
        clipboard = QApplication.clipboard()
        clipboard.setText(text)
        self.statusBar().showMessage("Logs copied to clipboard", 2000)
    
    def new_session(self):
        """Start new session"""
        if self.log_display.get_all_entries():
            reply = QMessageBox.question(self, "New Session", 
                                       "This will clear all current logs. Continue?",
                                       QMessageBox.Yes | QMessageBox.No)
            if reply == QMessageBox.Yes:
                self.clear_logs()
                self.log_file_path = None
    
    def show_settings(self):
        """Show settings dialog"""
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec() == QDialog.Accepted:
            self.settings = dialog.get_settings()
            self.apply_settings()
            self.save_settings()
    
    def apply_settings(self):
        """Apply changed settings"""
        # Update auto-save timer
        if self.settings['auto_save']:
            self.auto_save_timer.start(self.settings['auto_save_interval'] * 1000)
        else:
            self.auto_save_timer.stop()
        
        # Update display settings
        self.log_display.max_lines = self.settings['max_lines']
        self.toggle_timestamps(self.settings['show_timestamps'])
        self.toggle_autoscroll(self.settings['auto_scroll'])
        
        # Update level filters
        for i, cb in enumerate(self.level_checkboxes):
            if i < len(self.settings['log_level_filter']):
                cb.setChecked(self.settings['log_level_filter'][i])
        self.update_level_filter()
    
    def show_about(self):
        """Show about dialog"""
        QMessageBox.about(self, "About", 
                         f"{Config.APP_NAME} v{Config.VERSION}\n\n"
                         "A professional serial monitoring application\n"
                         "for embedded development and debugging.\n\n"
                         "Features:\n"
                         "• Real-time log monitoring with color coding\n"
                         "• Advanced filtering and search capabilities\n"
                         "• Export and auto-save functionality\n"
                         "• Professional dark theme\n"
                         "• Comprehensive logging levels support")
    
    def save_settings(self):
        """Save settings to file"""
        settings_file = Path("settings.json")
        
        # Save window geometry
        self.settings['window_geometry'] = self.saveGeometry().data().hex()
        self.settings['splitter_state'] = self.splitter.saveState().data().hex()
        
        try:
            with open(settings_file, 'w') as f:
                json.dump(self.settings, f, indent=2)
        except Exception as e:
            print(f"Failed to save settings: {e}")
    
    def load_settings(self):
        """Load settings from file"""
        settings_file = Path("settings.json")
        
        if settings_file.exists():
            try:
                with open(settings_file, 'r') as f:
                    loaded_settings = json.load(f)
                    self.settings.update(loaded_settings)
            except Exception as e:
                print(f"Failed to load settings: {e}")
    
    def restore_window_state(self):
        """Restore window state"""
        if self.settings.get('window_geometry'):
            try:
                geometry = bytes.fromhex(self.settings['window_geometry'])
                self.restoreGeometry(QByteArray(geometry))
            except Exception:
                pass
        
        if self.settings.get('splitter_state'):
            try:
                state = bytes.fromhex(self.settings['splitter_state'])
                self.splitter.restoreState(QByteArray(state))
            except Exception:
                pass
    
    def closeEvent(self, event):
        """Handle close event"""
        # Disconnect serial if connected
        if self.connected:
            self.disconnect_serial()
        
        # Save settings
        self.save_settings()
        
        event.accept()

class ExportDialog(QDialog):
    """Dialog for exporting logs with various options"""
    
    def __init__(self, log_entries: List[LogEntry], parent=None):
        super().__init__(parent)
        self.log_entries = log_entries
        self.setWindowTitle("Export Logs")
        self.setModal(True)
        self.resize(400, 300)
        
        self.setup_ui()
    
    def setup_ui(self):
        """Setup UI for export dialog"""
        layout = QVBoxLayout(self)
        
        # Export options
        options_group = QGroupBox("Export Options")
        options_layout = QVBoxLayout(options_group)
        
        self.include_timestamps = QCheckBox("Include Timestamps")
        self.include_timestamps.setChecked(True)
        options_layout.addWidget(self.include_timestamps)
        
        # Level selection
        levels_group = QGroupBox("Log Levels to Export")
        levels_layout = QVBoxLayout(levels_group)
        
        self.level_checkboxes = []
        for level, info in Config.LOG_LEVELS.items():
            if level == 'wm':
                cb = QCheckBox(f"{info['name']} [*wm]")
            elif level == 'verbose':
                cb = QCheckBox(f"{info['name']} [no id]")
            else:
                cb = QCheckBox(f"{info['name']} [{level}]")
            
            cb.setChecked(True)
            cb.setStyleSheet(f"QCheckBox {{ color: {info['color']}; }}")
            self.level_checkboxes.append(cb)
            levels_layout.addWidget(cb)
        
        # Level selection buttons
        level_btn_layout = QHBoxLayout()
        
        all_btn = QPushButton("All")
        all_btn.clicked.connect(self.select_all_levels)
        level_btn_layout.addWidget(all_btn)
        
        none_btn = QPushButton("None")
        none_btn.clicked.connect(self.select_no_levels)
        level_btn_layout.addWidget(none_btn)
        
        levels_layout.addLayout(level_btn_layout)
        
        # Format selection
        format_group = QGroupBox("Export Format")
        format_layout = QVBoxLayout(format_group)
        
        self.format_combo = QComboBox()
        self.format_combo.addItems(["Plain Text (.txt)", "CSV (.csv)", "JSON (.json)"])
        format_layout.addWidget(self.format_combo)
        
        layout.addWidget(options_group)
        layout.addWidget(levels_group)
        layout.addWidget(format_group)
        
        # Preview
        preview_group = QGroupBox("Preview")
        preview_layout = QVBoxLayout(preview_group)
        
        self.preview_text = QTextEdit()
        self.preview_text.setMaximumHeight(100)
        self.preview_text.setReadOnly(True)
        preview_layout.addWidget(self.preview_text)
        
        update_preview_btn = QPushButton("Update Preview")
        update_preview_btn.clicked.connect(self.update_preview)
        preview_layout.addWidget(update_preview_btn)
        
        layout.addWidget(preview_group)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        export_btn = QPushButton("Export...")
        export_btn.clicked.connect(self.export_logs)
        button_layout.addWidget(export_btn)
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        layout.addLayout(button_layout)
        
        # Initial preview
        self.update_preview()
    
    def select_all_levels(self):
        """Select all log levels"""
        for cb in self.level_checkboxes:
            cb.setChecked(True)
    
    def select_no_levels(self):
        """Deselect all log levels"""
        for cb in self.level_checkboxes:
            cb.setChecked(False)
    
    def update_preview(self):
        """Update export preview"""
        filtered_entries = self.get_filtered_entries()
        preview_text = ""
        
        for i, entry in enumerate(filtered_entries[:5]):  # Show first 5 entries
            preview_text += self.format_entry(entry) + "\n"
        
        if len(filtered_entries) > 5:
            preview_text += f"... and {len(filtered_entries) - 5} more entries"
        
        self.preview_text.setPlainText(preview_text)
    
    def get_filtered_entries(self) -> List[LogEntry]:
        """Get filtered entries based on selected levels"""
        filtered = []
        level_keys = list(Config.LOG_LEVELS.keys())
        selected_levels = []

        for i, cb in enumerate(self.level_checkboxes):
            if cb.isChecked() and i < len(level_keys):
                selected_levels.append(level_keys[i])

        for entry in self.log_entries:
            if entry.level in selected_levels:
                filtered.append(entry)
        
        return filtered
    
    def format_entry(self, entry: LogEntry) -> str:
        """Format entry based on selected format"""
        format_type = self.format_combo.currentText()
        include_timestamps = self.include_timestamps.isChecked()
        
        if "Plain Text" in format_type:
            return entry.to_export_string(include_timestamps)
        elif "CSV" in format_type:
            timestamp = entry.timestamp.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3] if include_timestamps else ""
            level = entry.get_level_name()
            message = entry.message.replace('"', '""')  # Escape quotes
            if include_timestamps:
                return f'"{timestamp}","{level}","{message}"'
            else:
                return f'"{level}","{message}"'
        elif "JSON" in format_type:
            data = {
                "level": entry.get_level_name(),
                "message": entry.message
            }
            if include_timestamps:
                data["timestamp"] = entry.timestamp.isoformat()
            return json.dumps(data)
        
        return entry.to_export_string(include_timestamps)
    
    def export_logs(self):
        """Export logs to file"""
        format_type = self.format_combo.currentText()
        
        # Determine file extension
        if "Plain Text" in format_type:
            ext = "txt"
            filter_str = "Text Files (*.txt)"
        elif "CSV" in format_type:
            ext = "csv"
            filter_str = "CSV Files (*.csv)"
        elif "JSON" in format_type:
            ext = "json"
            filter_str = "JSON Files (*.json)"
        else:
            ext = "txt"
            filter_str = "All Files (*)"
        
        filename, _ = QFileDialog.getSaveFileName(
            self, "Export Logs", f"serial_logs.{ext}", filter_str
        )
        
        if filename:
            try:
                filtered_entries = self.get_filtered_entries()
                
                with open(filename, 'w', encoding='utf-8') as f:
                    if "CSV" in format_type:
                        # Write CSV header
                        include_timestamps = self.include_timestamps.isChecked()
                        if include_timestamps:
                            f.write("Timestamp,Level,Message\n")
                        else:
                            f.write("Level,Message\n")
                    
                    for entry in filtered_entries:
                        f.write(self.format_entry(entry) + "\n")
                
                QMessageBox.information(self, "Export Complete", 
                                      f"Exported {len(filtered_entries)} log entries to {filename}")
                self.accept()
                
            except Exception as e:
                QMessageBox.critical(self, "Export Error", f"Failed to export logs: {str(e)}")

class SettingsDialog(QDialog):
    """Settings dialog for configuring application preferences"""
    
    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self.settings = settings.copy()
        self.setWindowTitle("Settings")
        self.setModal(True)
        self.resize(400, 500)
        
        self.setup_ui()
        self.load_current_settings()
    
    def setup_ui(self):
        """Setup UI for settings dialog"""
        layout = QVBoxLayout(self)
        
        # Create tab widget
        tab_widget = QTabWidget()
        
        # General tab
        general_tab = QWidget()
        general_layout = QVBoxLayout(general_tab)
        
        # Display settings
        display_group = QGroupBox("Display")
        display_layout = QFormLayout(display_group)
        
        self.max_lines_spin = QSpinBox()
        self.max_lines_spin.setRange(1000, 100000)
        self.max_lines_spin.setSingleStep(1000)
        display_layout.addRow("Max Log Lines:", self.max_lines_spin)
        
        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(8, 20)
        display_layout.addRow("Font Size:", self.font_size_spin)
        
        general_layout.addWidget(display_group)
        
        # Auto-save settings
        autosave_group = QGroupBox("Auto-save")
        autosave_layout = QFormLayout(autosave_group)
        
        self.auto_save_cb = QCheckBox("Enable auto-save")
        autosave_layout.addRow(self.auto_save_cb)
        
        self.auto_save_interval_spin = QSpinBox()
        self.auto_save_interval_spin.setRange(10, 3600)
        self.auto_save_interval_spin.setSuffix(" seconds")
        autosave_layout.addRow("Auto-save Interval:", self.auto_save_interval_spin)
        
        self.log_file_size_spin = QSpinBox()
        self.log_file_size_spin.setRange(1, 100)
        self.log_file_size_spin.setSuffix(" MB")
        autosave_layout.addRow("Max Log File Size:", self.log_file_size_spin)
        
        general_layout.addWidget(autosave_group)
        general_layout.addStretch()
        
        tab_widget.addTab(general_tab, "General")
        
        # Serial tab
        serial_tab = QWidget()
        serial_layout = QVBoxLayout(serial_tab)
        
        serial_group = QGroupBox("Serial Communication")
        serial_form_layout = QFormLayout(serial_group)
        
        # Add more serial settings here if needed
        
        serial_layout.addWidget(serial_group)
        serial_layout.addStretch()
        
        tab_widget.addTab(serial_tab, "Serial")
        
        layout.addWidget(tab_widget)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        reset_btn = QPushButton("Reset to Defaults")
        reset_btn.clicked.connect(self.reset_to_defaults)
        button_layout.addWidget(reset_btn)
        
        button_layout.addStretch()
        
        ok_btn = QPushButton("OK")
        ok_btn.clicked.connect(self.accept)
        button_layout.addWidget(ok_btn)
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        layout.addLayout(button_layout)
    
    def load_current_settings(self):
        """Load current settings into UI"""
        self.max_lines_spin.setValue(self.settings.get('max_lines', 10000))
        self.font_size_spin.setValue(self.settings.get('font_size', 10))
        self.auto_save_cb.setChecked(self.settings.get('auto_save', True))
        self.auto_save_interval_spin.setValue(self.settings.get('auto_save_interval', 60))
        self.log_file_size_spin.setValue(self.settings.get('log_file_size_mb', 10))
    
    def reset_to_defaults(self):
        """Reset all settings to defaults"""
        reply = QMessageBox.question(self, "Reset Settings", 
                                   "Are you sure you want to reset all settings to defaults?",
                                   QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.settings = Config.DEFAULT_SETTINGS.copy()
            self.load_current_settings()
    
    def get_settings(self) -> dict:
        """Get current settings from UI"""
        self.settings['max_lines'] = self.max_lines_spin.value()
        self.settings['font_size'] = self.font_size_spin.value()
        self.settings['auto_save'] = self.auto_save_cb.isChecked()
        self.settings['auto_save_interval'] = self.auto_save_interval_spin.value()
        self.settings['log_file_size_mb'] = self.log_file_size_spin.value()
        
        return self.settings

def main():
    """Main application entry point"""
    app = QApplication(sys.argv)
    app.setApplicationName(Config.APP_NAME)
    app.setApplicationVersion(Config.VERSION)
    app.setOrganizationName(Config.COMPANY)
    
    # Set application icon (if available)
    # app.setWindowIcon(QIcon("icon.png"))
    
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()