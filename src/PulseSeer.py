#!/usr/bin/env python3
"""
PulseSeer - A PyQt application for visualizing sensor data.

Changelog:
- Initial GUI Creation:
  - Features: Bar and line graphs using pyqtgraph, with tabs for "NORMAL" and "ADVANCED" modes.
  - Controls: Buttons for MEASURE, CALIBRATE, and CLEAR, with sliders for sampling frequency and data points.
  - File Menu: Includes Open, Clear, Save Screenshot, Restart, and Shutdown functionalities.

- Hardware Integration (Raspberry Pi 5):
  - ADC: Reads live voltage data from an ADS7142 ADC.
  - GPIO: Uses GPIO20 as a power pin, controlled via the 'gpiod' library. The pin is HIGH only during measurements.

- Advanced Data Processing:
  - Pulse Pattern Detection: Implements an algorithm to detect a repeating pattern of 6 pulses followed by 2 empty spaces, synchronizing the data stream.
  - Data Filtering: Averages only valid data points from detected cycles that are above a minimum voltage threshold, ensuring noise is excluded from results.
  - Timeout Logic: If the pattern is not detected for more than 3 seconds, the GUI displays a "NO PATTERN DETECTED" warning and enters a fallback mode to continue displaying data.

- UI and Logging Enhancements:
  - Dynamic Y-Axis: The graph's Y-axis label automatically switches between "Voltage" and "Voltage [dB]".
  - CONSOLE Tab: An in-app console displays real-time diagnostic information.
  - Verbose Logging: A "Verbose" checkbox allows toggling of detailed log messages.
  - Real-time Stats: The console shows live Samples Per Second (SPS) and Cycles Per Second (CPS).
  - Measurement Summary: After each measurement, a summary of the total elapsed time, average SPS, and average CPS is printed to the console.
  - Screenshot Fix: The "Save Screenshot" feature was fixed to reliably capture the GUI without producing black images.
"""


import sys
from PyQt6.QtWidgets import (
    QApplication, QWidget, QPushButton, QLabel, QLineEdit, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox, QSlider, QCheckBox, QFrame, QTabWidget, QMenuBar, QMenu, QFileDialog, QStackedWidget, QMessageBox, QTextEdit, QInputDialog, QDialog
)
from PyQt6.QtCore import Qt, QTimer, QObject, pyqtSignal
from PyQt6.QtGui import QPixmap, QIcon, QScreen, QTextCursor
import pyqtgraph as pg
import numpy as np
import csv
import os
from datetime import datetime
try:
    from ADS131M02_driver import ADS131M02
    ADS131M02_AVAILABLE = True
except ImportError:
    ADS131M02_AVAILABLE = False
    print("ADS131M02 driver not available - will try ADS7142")
from ADS7142_driver_new import ADS7142  # Import the ADS7142 driver
import time
try:
    import gpiod
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False
    print("gpiod not available - running without GPIO control")
import spidev
import RPi.GPIO as GPIO

PARAMETERS = ["700nm", "800nm", "850nm", "900nm", "970nm", "1050nm"]

# Custom stream object to redirect stdout
class ConsoleStream(QObject):
    new_text = pyqtSignal(str)

    def write(self, text):
        # Filter out pyqtgraph's benign "ignored exception" message
        if "ignored exception" in text:
            return
        self.new_text.emit(str(text))
    
    def flush(self):
        pass # Required for stream interface

class SplashScreenDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PulseSeer - Safety Warning")
        self.setModal(True)
        self.setFixedSize(1000, 570)  # Same size as main GUI
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowStaysOnTopHint)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(40)
        layout.setContentsMargins(80, 80, 80, 80)
        
        # Add some top spacing
        layout.addStretch(1)
        
        # Warning icon and title
        title_label = QLabel("âš ï¸  SAFETY WARNING  âš ï¸")
        title_label.setStyleSheet("font-size: 36px; font-weight: bold; color: #d32f2f;")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)
        
        # Warning message
        warning_text = """
        IMPORTANT: Before starting any measurements, 
        please ensure that the IR LEDs (700nm LED should be visible) are TURNED ON.
        
        Failure to do so will result in:
        â€¢ Inaccurate measurements
        â€¢ Invalid data collection
        â€¢ Potential damage to equipment
        
        
        Please verify that all IR LEDs are illuminated 
        before proceeding with measurements.
        """
        
        warning_label = QLabel(warning_text)
        warning_label.setStyleSheet("font-size: 20px; line-height: 1.6; color: #333;")
        warning_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        warning_label.setWordWrap(True)
        layout.addWidget(warning_label)
        
        # Confirmation buttons
        button_layout = QHBoxLayout()
        
        yes_btn = QPushButton("YES - IR LEDs are ON")
        yes_btn.setStyleSheet("""
            QPushButton {
                font-size: 24px;
                font-weight: bold;
                padding: 20px 40px;
                background-color: #4caf50;
                color: white;
                border: none;
                border-radius: 10px;
                min-height: 60px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        yes_btn.clicked.connect(self.accept)
        
        no_btn = QPushButton("NO - Exit Application")
        no_btn.setStyleSheet("""
            QPushButton {
                font-size: 24px;
                font-weight: bold;
                padding: 20px 40px;
                background-color: #f44336;
                color: white;
                border: none;
                border-radius: 10px;
                min-height: 60px;
            }
            QPushButton:hover {
                background-color: #da190b;
            }
        """)
        no_btn.clicked.connect(self.reject)
        
        button_layout.addWidget(yes_btn)
        button_layout.addWidget(no_btn)
        layout.addLayout(button_layout)
        
        # Add some bottom spacing
        layout.addStretch(1)

class NumberKeypadDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Enter Engineering Password")
        self.setModal(True)
        self.setFixedSize(340, 420)
        layout = QVBoxLayout(self)
        self.label = QLabel("Enter Password:")
        self.label.setStyleSheet("font-size: 18px; font-weight: bold;")
        layout.addWidget(self.label)
        self.line_edit = QLineEdit()
        self.line_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.line_edit.setReadOnly(True)
        self.line_edit.setFixedHeight(48)
        self.line_edit.setStyleSheet("font-size: 28px; padding: 8px;")
        layout.addWidget(self.line_edit)
        # Keypad grid
        btn_layout = QVBoxLayout()
        for row in [["1","2","3"],["4","5","6"],["7","8","9"],["Clear","0","OK"]]:
            h = QHBoxLayout()
            for key in row:
                btn = QPushButton(key)
                btn.setFixedSize(80, 60)
                btn.setStyleSheet("font-size: 22px;")
                if key == "OK":
                    btn.clicked.connect(self.accept)
                elif key == "Clear":
                    btn.clicked.connect(self.clear)
                else:
                    btn.clicked.connect(lambda _, k=key: self.append_digit(k))
                h.addWidget(btn)
            btn_layout.addLayout(h)
        layout.addLayout(btn_layout)
    def append_digit(self, digit):
        self.line_edit.setText(self.line_edit.text() + digit)
    def clear(self):
        self.line_edit.clear()
    def get_password(self):
        return self.line_edit.text()

class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PulseSeer")
        self.setWindowIcon(QIcon("logo.png"))
        self.setGeometry(100, 100, 1000, 570)
        self.calibrated_values = {param: None for param in PARAMETERS}
        
        # Show splash screen on startup
        splash = SplashScreenDialog(self)
        if splash.exec() != QDialog.DialogCode.Accepted:
            # User clicked "NO - Exit Application"
            sys.exit(0)
        
        # --- LTC6903 setup: set output to 8192kHz before ADC config ---
        CS2_PIN = 20
        SPI_BUS = 0
        SPI_DEVICE = 0
        def ltc6903_config_bytes(frequency_hz):
            oct_table = [
                (34050000, 68030000, 15), (17020000, 34010000, 14), (8511000, 17010000, 13), (4256000, 8503000, 12),
                (2128000, 4252000, 11), (1064000, 2126000, 10), (532000, 1063000, 9), (266000, 531400, 8),
                (133000, 265700, 7), (66500, 132900, 6), (33200, 66200, 5), (16600, 33220, 4), (8310, 16610, 3),
                (4150, 8300, 2), (2070, 4140, 1), (1039, 2076, 0),
            ]
            oct_val = None
            for f_min, f_max, oct_candidate in oct_table:
                if frequency_hz >= f_min and frequency_hz < f_max:
                    oct_val = oct_candidate
                    break
            if oct_val is None:
                if frequency_hz < oct_table[-1][0]:
                    oct_val = oct_table[-1][2]
                else:
                    oct_val = oct_table[0][2]
            dac_float = 2048 - (2078 * (2 ** (10 + oct_val))) / frequency_hz
            dac = int(round(dac_float))
            dac = max(0, min(1023, dac))
            command = ((oct_val & 0xF) << 12) | ((dac & 0x3FF) << 2)
            cmd_bytes = [(command >> 8) & 0xFF, command & 0xFF]
            return oct_val, dac, cmd_bytes
        try:
            self.ltc6903_spi = spidev.SpiDev()
            self.ltc6903_spi.open(SPI_BUS, SPI_DEVICE)
            self.ltc6903_spi.max_speed_hz = 4096000
            self.ltc6903_spi.mode = 0
            self.ltc6903_spi.lsbfirst = False
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(CS2_PIN, GPIO.OUT, initial=GPIO.HIGH)
            freq_hz = 8192000
            oct_val, dac_val, cmd_bytes = ltc6903_config_bytes(freq_hz)
            GPIO.output(CS2_PIN, GPIO.LOW)
            self.ltc6903_spi.xfer2(cmd_bytes)
            GPIO.output(CS2_PIN, GPIO.HIGH)
            print(f"LTC6903 set to {freq_hz/1000:.1f} kHz (OCT={oct_val}, DAC={dac_val})")
        except Exception as e:
            print(f"Error initializing LTC6903: {e}")

        # --- End LTC6903 setup ---

        # Initialize the ADC (prefer ADS131M02, fallback to ADS7142)
        self.adc = None
        self.adc_type = None
        if ADS131M02_AVAILABLE:
            try:
                self.adc = ADS131M02(spi_bus=0, spi_device=0,cs_pin=21, drdy_pin=16, reset_pin=12, vref=1.2)
                self.adc_type = 'ADS131M02'
                self.adc.reset()
                print("ADS131M02 initialized successfully (preferred)")
                device_id = self.adc.get_device_id()
                print(f"Device ID: 0x{device_id:04X}")
                self.adc.set_sampling_rate(ADS131M02.OSR_8192)
                self.adc.set_gain(0, self.adc.GAIN_1)  # Channel 0
                self.adc.set_gain(1, self.adc.GAIN_1)  # Channel 1
                self.adc.set_dc_blocking_filter(0, False)   # Enable DC blocking on Channel 0
                self.adc.set_dc_blocking_filter(1, False)  # Disable DC blocking on Channel 1
                self.adc.enable_continuous_sampling(True)
                # Automatically adjust gain for CH0 only
                self.auto_adjust_gain(channel=0, threshold_low=0.1, threshold_high=1.0)
                
            except Exception as e:
                print(f"Error initializing ADS131M02: {e}")
                self.adc = None
                self.adc_type = None
        if self.adc is None:
            try:
                self.adc = ADS7142()  # Use default I2C settings
                self.adc_type = 'ADS7142'
                print("ADS7142 initialized successfully (fallback)")
            except Exception as e:
                print(f"Error initializing ADS7142: {e}")
                self.adc = None
                self.adc_type = None
                QMessageBox.warning(self, "Warning", "Failed to initialize any ADC. The application will run without live data.")
        
        # Initialize GPIO control
        self.gpio_available = False
        self.chip = None
        self.power_line = None
        try:
            # Get the GPIO chip (usually gpiochip4 for Pi 5)
            self.chip = gpiod.Chip('gpiochip4')
            # Get line handle for GPIO19 (changed from 20)
            self.POWER_PIN = 19
            # Request the line as output with initial value LOW
            self.power_line = self.chip.get_line(self.POWER_PIN)
            self.power_line.request(
                consumer="PulseSeer",
                type=gpiod.LINE_REQ_DIR_OUT,
                flags=0
            )
            # Set initial value to LOW
            self.power_line.set_value(0)
            self.gpio_available = True
            print(f"GPIO{self.POWER_PIN} initialized successfully")
        except Exception as e:
            print(f"Error initializing GPIO: {e}")
            print("Running without GPIO control")
            self.chip = None
            self.power_line = None
        
        self.init_ui()
        self.setStyleSheet("")

        # Redirect console output to the QTextEdit
        self.console_stream = ConsoleStream()
        self.console_stream.new_text.connect(self.on_new_console_text)
        sys.stdout = self.console_stream
        sys.stderr = self.console_stream # Also redirect errors
        
        # Add new attributes for cycle detection
        self.PULSE_WIDTH_MS = 0.24  # milliseconds
        self.CYCLE_PERIOD_MS = 3.9  # milliseconds
        self.MIN_VOLTAGE_THRESHOLD = 0.1  # Minimum voltage to consider as a pulse (100mV threshold)
        self.raw_buffer = []  # Store raw voltage readings
        self.last_pulse_time = 0
        self.pulse_count = 0
        self.empty_count = 0
        self.cycle_detected = False
        self.current_wavelength_idx = 0
        
        # Add timeout parameters for cycle detection
        self.CYCLE_TIMEOUT_SEC = 3.0  # Timeout in seconds
        self.last_cycle_time = time.time()
        self.in_timeout = False
        self.consecutive_cycles = 0
        self.is_locked = False
        self.LOCK_THRESHOLD = 2
        self.is_timing_adjusted = False
        self.BATCH_TIMER_INTERVAL_MS = 22  # 50 Hz timer
        self.last_sample_batch_time = 0
        
        # Add timer for 3-second delay before showing "NO PATTERN DETECTED"
        self.no_pattern_timer = QTimer(self)
        self.no_pattern_timer.setSingleShot(True)
        self.no_pattern_timer.timeout.connect(self.show_no_pattern_detected)
        self.last_pattern_detection_time = time.time()
        self.pattern_detection_active = False
        
        # Add continuous averaging mechanism
        self.continuous_wavelength_cycle = 0  # Continuous wavelength cycling counter
        self.continuous_sample_buffer = {param: [] for param in PARAMETERS}  # Continuous averaging buffer
        
        # Graph averaging configuration
        self.graph_averaging_window = 10  # Default number of recent pulses to average for graph display
        self.last_cycle_count_time = time.time()  # Track when we last counted cycles
        self.cycles_in_last_second = 0  # Count of cycles in the last second
        
        # Enhanced cycle statistics
        self.cycle_timestamps = []  # Store timestamps of detected cycles
        self.cycle_intervals = []   # Store time intervals between cycles
        self.cycle_scores = []      # Store correlation scores for each cycle
        self.cycle_qualities = []   # Store quality metrics for each cycle
        self.cycle_pulse_counts = [] # Store number of pulses detected in each cycle
        self.cycle_voltage_stats = [] # Store voltage statistics for each cycle
        self.last_cycle_detection_time = 0
        self.cycle_detection_count = 0
        self.total_cycles_detected = 0
        self.cycle_rate_history = [] # Store cycle rates over time
        self.pattern_quality_history = [] # Store pattern quality over time
        
        # Wavelength cycling and data assignment
        self.wavelength_cycle_count = 0  # Count of cycles to determine wavelength
        self.wavelength_data = {param: [] for param in PARAMETERS}  # Store data for each wavelength
        self.current_wavelength = PARAMETERS[0]  # Current wavelength being measured
        
        # Calculate samples per pulse and cycle based on sampling rate
        self.update_timing_parameters()

        self.measure_start_time = None
        self.adc_read_count = 0
        self.cycle_detected_count = 0
        self.sample_timestamps = []  # Store timestamps of ADC samples

        self.set_operation_mode('field') # Start in Field Operation Mode by default

    def init_ui(self):
        main_layout = QHBoxLayout()
        self.setLayout(main_layout)

        # Left: Graph (StackedWidget for switching between bar and line graph)
        left_layout = QVBoxLayout()
        
        # Add status label at the top
        self.status_label = QLabel("NO PATTERN DETECTED")
        self.status_label.setStyleSheet("""
            QLabel {
                color: red;
                font-weight: bold;
                font-size: 18px;
            }
        """)
        self.status_label.hide()  # Initially hidden
        left_layout.addWidget(self.status_label)
        
        # Remove lock status label - we don't want to show "PATTERN LOCKED"
        # self.lock_label = QLabel("PATTERN LOCKED")
        # self.lock_label.setStyleSheet("""
        #     QLabel {
        #         color: green;
        #         font-weight: bold;
        #         font-size: 18px;
        #     }
        # """)
        # self.lock_label.hide() # Initially hidden
        # left_layout.addWidget(self.lock_label)
        
        self.graph_stack = QStackedWidget()
        # Time series graph (for ADVANCED MODE)
        self.graph_widget = pg.PlotWidget()
        self.graph_widget.setBackground('w')
        legend = self.graph_widget.addLegend()
        self.graph_widget.showGrid(x=True, y=True)
        self.graph_widget.setLabel('left', 'Value')
        self.graph_widget.setLabel('bottom', 'Time (s)')
        self.curves = {}
        for i, param in enumerate(PARAMETERS):
            color = pg.intColor(i, hues=len(PARAMETERS))
            self.curves[param] = self.graph_widget.plot(pen=pg.mkPen(color, width=2), name=param, symbol='o', symbolSize=5, symbolBrush=color)
        self.graph_stack.addWidget(self.graph_widget)
        # Bar graph (for NORMAL MODE)
        self.bar_widget = pg.PlotWidget()
        self.bar_widget.setBackground('w')
        self.bar_widget.setLabel('left', 'Value')
        self.bar_widget.setLabel('bottom', 'Wavelength')
        self.bar_item = None
        self.graph_stack.addWidget(self.bar_widget)
        left_layout.addWidget(self.graph_stack)
        main_layout.addLayout(left_layout, stretch=3)

        # Right: Controls
        right_layout = QVBoxLayout()
        # Buttons
        button_layout = QHBoxLayout()
        self.scan_btn = QPushButton("MEASURE")
        self.scan_btn.setFixedHeight(44)
        self.scan_btn.setFixedWidth(140)
        self.calibrate_btn = QPushButton("CALIBRATE")
        self.calibrate_btn.setFixedHeight(44)
        self.calibrate_btn.setFixedWidth(140)
        self.clear_btn = QPushButton("CLEAR")
        self.clear_btn.setFixedHeight(44)
        self.clear_btn.setFixedWidth(140)
        self.clear_btn.clicked.connect(self.clear_data)

        # Settings Button with Gear Icon
        self.settings_btn = QPushButton("âš™")
        self.settings_btn.setFixedHeight(44)
        self.settings_btn.setFixedWidth(60) # Make the button wider
        self.settings_btn.setStyleSheet("font-size: 24px;") # Increase font size for a larger icon
        
        # Overlay panel for settings actions
        self.settings_overlay = QWidget(self)
        self.settings_overlay.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.settings_overlay.setStyleSheet("background: rgba(255,255,255,0.97); border: 2px solid #888; border-radius: 16px;")
        self.settings_overlay.setFixedWidth(340)
        self.settings_overlay.hide()

        overlay_layout = QVBoxLayout(self.settings_overlay)
        overlay_layout.setContentsMargins(24, 24, 24, 24)
        overlay_layout.setSpacing(20)

        def make_big_button(text):
            btn = QPushButton(text)
            btn.setMinimumHeight(48)
            btn.setStyleSheet("font-size: 20px; padding: 12px 0; border-radius: 10px;")
            return btn

        self.open_btn = make_big_button("Open CSV File")
        self.open_btn.clicked.connect(lambda: [self.settings_overlay.hide(), self.open_csv_file()])
        overlay_layout.addWidget(self.open_btn)

        screenshot_btn = make_big_button("Save Screenshot")
        screenshot_btn.clicked.connect(lambda: [self.settings_overlay.hide(), self.save_screenshot()])
        overlay_layout.addWidget(screenshot_btn)

        show_desktop_btn = make_big_button("Show Desktop")
        show_desktop_btn.clicked.connect(lambda: [self.settings_overlay.hide(), self.showMinimized()])
        overlay_layout.addWidget(show_desktop_btn)

        self.engineering_mode_btn = make_big_button("Engineering Mode")
        self.engineering_mode_btn.clicked.connect(lambda: [self.settings_overlay.hide(), self.switch_to_engineering_mode()])
        overlay_layout.addWidget(self.engineering_mode_btn)

        self.field_mode_btn = make_big_button("Field Engineering Mode")
        self.field_mode_btn.clicked.connect(lambda: [self.settings_overlay.hide(), self.set_operation_mode('field')])
        overlay_layout.addWidget(self.field_mode_btn)

        restart_btn = make_big_button("Restart")
        restart_btn.clicked.connect(lambda: [self.settings_overlay.hide(), self.restart_pi()])
        overlay_layout.addWidget(restart_btn)

        shutdown_btn = make_big_button("Shutdown")
        shutdown_btn.clicked.connect(lambda: [self.settings_overlay.hide(), self.shutdown_pi()])
        overlay_layout.addWidget(shutdown_btn)

        exit_btn = make_big_button("Exit")
        exit_btn.clicked.connect(lambda: [self.settings_overlay.hide(), self.close()])
        overlay_layout.addWidget(exit_btn)

        # Show/hide overlay when settings button is clicked
        self.settings_btn.clicked.connect(self.toggle_settings_overlay)

        button_layout.addWidget(self.scan_btn)
        button_layout.addWidget(self.calibrate_btn)
        button_layout.addWidget(self.clear_btn)
        button_layout.addWidget(self.settings_btn)
        right_layout.addLayout(button_layout)
        # Checkboxes for graph options
        checkbox_layout = QHBoxLayout()
        checkbox_layout.setSpacing(8)
        self.show_db_checkbox = QCheckBox("Show in dB")
        self.show_db_checkbox.setChecked(True)
        self.show_db_checkbox.stateChanged.connect(self.update_graph)
        self.show_all_checkbox = QCheckBox("Show all")
        self.show_all_checkbox.setChecked(False)
        self.show_all_checkbox.stateChanged.connect(self.update_graph)
        self.continuous_checkbox = QCheckBox("Continuous mode")
        self.continuous_checkbox.setChecked(False)
        self.continuous_checkbox.stateChanged.connect(self.on_continuous_mode_changed)
        self.verbose_checkbox = QCheckBox("Verbose")
        self.verbose_checkbox.setChecked(False)
        checkbox_layout.addWidget(self.show_db_checkbox)
        checkbox_layout.addWidget(self.continuous_checkbox)
        checkbox_layout.addWidget(self.show_all_checkbox)
        checkbox_layout.addWidget(self.verbose_checkbox)
        right_layout.addLayout(checkbox_layout)
        right_layout.setSpacing(4)
        
        # Container for sampling controls
        self.sampling_widget = QWidget()
        self.sampling_layout = QHBoxLayout(self.sampling_widget)
        self.sampling_label = QLabel("Batch Timer Frequency: 45 Hz")
        self.sampling_slider = QSlider(Qt.Orientation.Horizontal)
        self.sampling_slider.setMinimum(1)  # 1 Hz
        self.sampling_slider.setMaximum(50)  # 50 Hz
        self.sampling_slider.setValue(45)  # Default 45 Hz
        self.sampling_slider.setTickInterval(1)
        self.sampling_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.sampling_slider.setFixedWidth(200)
        self.sampling_slider.valueChanged.connect(self.update_sampling_label)
        self.sampling_layout.addWidget(self.sampling_label)
        self.sampling_layout.addWidget(self.sampling_slider)
        self.sampling_layout.setContentsMargins(0, 2, 0, 0)
        right_layout.addWidget(self.sampling_widget)

        # Container for Data Points Slider
        self.datapoints_widget = QWidget()
        self.datapoints_layout = QHBoxLayout(self.datapoints_widget)
        self.datapoints_label = QLabel("Data Points: 600")
        self.datapoints_slider = QSlider(Qt.Orientation.Horizontal)
        self.datapoints_slider.setMinimum(30)
        self.datapoints_slider.setMaximum(600)
        self.datapoints_slider.setValue(300)
        self.datapoints_slider.setTickInterval(10)
        self.datapoints_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.datapoints_slider.setFixedWidth(200)
        self.datapoints_slider.valueChanged.connect(self.update_datapoints_label)
        self.datapoints_layout.addWidget(self.datapoints_label)
        self.datapoints_layout.addWidget(self.datapoints_slider)
        self.datapoints_layout.setContentsMargins(0, 2, 0, 0)
        right_layout.addWidget(self.datapoints_widget)

        # Tabs for NORMAL, ADVANCED, and CONSOLE
        self.tabs = QTabWidget()
        # NORMAL tab (current readings only)
        normal_tab = QWidget()
        normal_layout = QVBoxLayout(normal_tab)
        normal_grid = QGridLayout()
        
        # Create header labels with larger font
        wavelength_header = QLabel("Wavelength")
        wavelength_header.setStyleSheet("font-size: 16px;")
        normal_grid.addWidget(wavelength_header, 0, 0)
        
        self.normal_current_header = QLabel("Current [dB]")
        self.normal_current_header.setStyleSheet("font-size: 16px;")
        self.normal_calibrated_header = QLabel("Calibrated [dB]")
        self.normal_calibrated_header.setStyleSheet("font-size: 16px;")
        self.normal_diff_header = QLabel("Ratio[dB] Cur/Calib")
        self.normal_diff_header.setStyleSheet("font-size: 16px;")
        normal_grid.addWidget(self.normal_current_header, 0, 1)
        normal_grid.addWidget(self.normal_calibrated_header, 0, 2)
        normal_grid.addWidget(self.normal_diff_header, 0, 3)
        
        self.normal_db_labels = {}
        self.normal_calib_db_labels = {}
        self.normal_diff_db_labels = {}
        
        for i, param in enumerate(PARAMETERS):
            # Create wavelength labels with larger font
            param_label = QLabel(param)
            param_label.setStyleSheet("font-size: 16px;")
            normal_grid.addWidget(param_label, i+1, 0)
            
            # Create value labels with larger font
            db_label = QLabel("-")
            db_label.setStyleSheet("font-size: 16px;")
            calib_db_label = QLabel("-")
            calib_db_label.setStyleSheet("font-size: 16px;")
            diff_db_label = QLabel("-")
            diff_db_label.setStyleSheet("font-size: 16px;")
            
            self.normal_db_labels[param] = db_label
            self.normal_calib_db_labels[param] = calib_db_label
            self.normal_diff_db_labels[param] = diff_db_label
            normal_grid.addWidget(db_label, i+1, 1)
            normal_grid.addWidget(calib_db_label, i+1, 2)
            normal_grid.addWidget(diff_db_label, i+1, 3)
        normal_layout.addLayout(normal_grid)
        self.tabs.addTab(normal_tab, "NORMAL MODE")
        # ADVANCE tab (existing parameter grid)
        advance_tab = QWidget()
        advance_layout = QVBoxLayout(advance_tab)
        minmax_group = QGroupBox("")
        minmax_layout = QGridLayout()
        # Add parameter headers as the top row
        minmax_layout.addWidget(QLabel(""), 0, 0)
        for j, param in enumerate(PARAMETERS):
            header = QLabel(param)
            header.setFixedWidth(50)
            minmax_layout.addWidget(header, 0, j+1)
        # Add 'Show' row with checkboxes
        minmax_layout.addWidget(QLabel("Show"), 1, 0)
        self.param_checkboxes = {}
        for j, param in enumerate(PARAMETERS):
            checkbox = QCheckBox()
            checkbox.setChecked(True)
            checkbox.stateChanged.connect(lambda state, p=param: self.toggle_curve(p, state))
            self.param_checkboxes[param] = checkbox
            minmax_layout.addWidget(checkbox, 1, j+1)
        # Add value rows starting from row 2
        minmax_layout.addWidget(QLabel("Calibrated"), 2, 0)
        minmax_layout.addWidget(QLabel("Current"), 3, 0)
        minmax_layout.addWidget(QLabel("Min"), 4, 0)
        minmax_layout.addWidget(QLabel("Max"), 5, 0)
        diff_pct_label = QLabel("Ratio Cur[dB]/Calib[dB]")
        diff_pct_label.setWordWrap(True)
        diff_pct_label.setFixedHeight(32)
        minmax_layout.addWidget(diff_pct_label, 6, 0)
        # Add horizontal line between normal and dB groups
        hline = QFrame()
        hline.setFrameShape(QFrame.Shape.HLine)
        hline.setFrameShadow(QFrame.Shadow.Sunken)
        hline.setLineWidth(3)
        hline.setMinimumHeight(8)
        minmax_layout.addWidget(hline, 7, 0, 1, len(PARAMETERS) + 1)
        # Move dB labels and fields down by one row
        minmax_layout.addWidget(QLabel("Calibrated [dB]"), 8, 0)
        minmax_layout.addWidget(QLabel("Current [dB]"), 9, 0)
        minmax_layout.addWidget(QLabel("Min [dB]"), 10, 0)
        minmax_layout.addWidget(QLabel("Max [dB]"), 11, 0)
        diff_db_label = QLabel("Ratio Cur[dB]/Calib[dB]")
        diff_db_label.setWordWrap(True)
        diff_db_label.setFixedHeight(32)
        minmax_layout.addWidget(diff_db_label, 12, 0)
        self.min_db_fields = {}
        self.max_db_fields = {}
        self.diff_pct_fields = {}
        self.diff_db_fields = {}
        self.min_fields = {}
        self.max_fields = {}
        self.cur_fields = {}
        self.calib_fields = {}
        self.calib_db_fields = {}
        self.db_fields = {}
        for j, param in enumerate(PARAMETERS):
            calib_field = QLineEdit()
            calib_field.setPlaceholderText("Calibrated")
            calib_field.setFixedWidth(45)
            cur_field = QLineEdit()
            cur_field.setPlaceholderText("CUR")
            cur_field.setFixedWidth(45)
            min_field = QLineEdit()
            min_field.setPlaceholderText("MIN")
            min_field.setFixedWidth(45)
            max_field = QLineEdit()
            max_field.setPlaceholderText("MAX")
            max_field.setFixedWidth(45)
            diff_pct_field = QLineEdit()
            diff_pct_field.setPlaceholderText("%")
            diff_pct_field.setFixedWidth(45)
            calib_db_field = QLineEdit()
            calib_db_field.setPlaceholderText("dB")
            calib_db_field.setFixedWidth(45)
            cur_db_field = QLineEdit()
            cur_db_field.setPlaceholderText("dB")
            cur_db_field.setFixedWidth(45)
            min_db_field = QLineEdit()
            min_db_field.setPlaceholderText("dB")
            min_db_field.setFixedWidth(45)
            max_db_field = QLineEdit()
            max_db_field.setPlaceholderText("dB")
            max_db_field.setFixedWidth(45)
            diff_db_field = QLineEdit()
            diff_db_field.setPlaceholderText("dB")
            diff_db_field.setFixedWidth(45)
            self.calib_fields[param] = calib_field
            self.cur_fields[param] = cur_field
            self.min_fields[param] = min_field
            self.max_fields[param] = max_field
            self.diff_pct_fields[param] = diff_pct_field
            self.calib_db_fields[param] = calib_db_field
            self.db_fields[param] = cur_db_field
            self.min_db_fields[param] = min_db_field
            self.max_db_fields[param] = max_db_field
            self.diff_db_fields[param] = diff_db_field
            minmax_layout.addWidget(calib_field, 2, j+1)
            minmax_layout.addWidget(cur_field, 3, j+1)
            minmax_layout.addWidget(min_field, 4, j+1)
            minmax_layout.addWidget(max_field, 5, j+1)
            minmax_layout.addWidget(diff_pct_field, 6, j+1)
            minmax_layout.addWidget(calib_db_field, 8, j+1)
            minmax_layout.addWidget(cur_db_field, 9, j+1)
            minmax_layout.addWidget(min_db_field, 10, j+1)
            minmax_layout.addWidget(max_db_field, 11, j+1)
            minmax_layout.addWidget(diff_db_field, 12, j+1)
        minmax_group.setLayout(minmax_layout)
        advance_layout.addWidget(minmax_group)
        self.tabs.addTab(advance_tab, "ADVANCED MODE")
        
        # CONSOLE tab
        console_tab = QWidget()
        console_layout = QVBoxLayout(console_tab)
        self.console_output = QTextEdit()
        self.console_output.setReadOnly(True)
        console_layout.addWidget(self.console_output)
        self.tabs.addTab(console_tab, "CONSOLE")
        
        self.tabs.setCurrentIndex(0)  # Start in NORMAL MODE
        self.tabs.tabBar().setMinimumHeight(28)
        self.tabs.setStyleSheet("QTabBar::tab { height: 28px; font-size: 13px; min-width: 90px; }")
        # Move all text in NORMAL MODE and ADVANCED MODE tabs up by 5px
        normal_layout.setContentsMargins(0, 5, 0, 0)
        advance_layout.setContentsMargins(0, 5, 0, 0)

        right_layout.addWidget(self.tabs)
        right_layout.addStretch(1)
        main_layout.addLayout(right_layout, stretch=1)

        # Example: Simulate data update
        self.buffer_size = 600
        self.t = []
        self.data = {param: [] for param in PARAMETERS}
        self.all_data = {param: [] for param in PARAMETERS}  # Not needed, just use self.data
        self.update_graph()

        # Timers for sampling and graph update
        self.sampling_timer = QTimer(self)
        self.sampling_timer.timeout.connect(self.sample_data)
        self.graph_timer = QTimer(self)
        self.graph_timer.timeout.connect(self.update_graph_from_buffer)
        # Add timer for cycle statistics display
        self.stats_timer = QTimer(self)
        self.stats_timer.timeout.connect(self.print_cycle_statistics)
        # self.sampling_timer.start(...)  # Will be started by SCAN
        # self.graph_timer.start(1000)    # Will be started by SCAN
        # self.stats_timer.start(5000)    # Will be started by SCAN - every 5 seconds

        # Buffer for samples within each second
        self.sample_buffer = {param: [] for param in PARAMETERS}
        self.samples_per_second = (self.sampling_slider.value() / 10) * 1000
        self.sampling_slider.valueChanged.connect(self.update_sampling_rate)

        # Connect SCAN button to start/stop scanning
        self.scanning = False
        self.scan_btn.clicked.connect(self.toggle_scan)

        # Logging setup
        self.init_log_files()

        # New attribute for calibrated values
        self.calibrated_values = {param: None for param in PARAMETERS}
        self.calibrate_btn.clicked.connect(self.calibrate_current_values)

        self.sampling_slider.setValue(45)  # Default 45 Hz
        self.update_sampling_label(self.sampling_slider.value())
        self.datapoints_slider.setValue(300)
        self.update_datapoints_label(self.datapoints_slider.value())

        self.tabs.currentChanged.connect(self.on_tab_changed)

        # Ensure main_layout and graph_stack use stretch factors
        main_layout.setStretch(0, 3)
        main_layout.setStretch(1, 1)

    def init_log_files(self):
        # Create a directory for today's logs
        today_str = datetime.now().strftime("%Y-%m-%d")
        log_dir = os.path.join(os.getcwd(), today_str)
        os.makedirs(log_dir, exist_ok=True)
        
        # Update file paths to include the new directory
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.text_log_file = os.path.join(log_dir, f"data_log_{timestamp}.txt")
        self.csv_log_file = os.path.join(log_dir, f"data_log_{timestamp}.csv")
        
        # Initialize text log file with header if not exists
        header = ["Time", "Current_Time"] + PARAMETERS + [f"Calibrated_{param}" for param in PARAMETERS] + ["CH0_Gain", "CH1_Gain"]
        if not os.path.exists(self.text_log_file):
            with open(self.text_log_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(header)
        # Initialize CSV log file with header if not exists
        if not os.path.exists(self.csv_log_file):
            with open(self.csv_log_file, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(header)

    def db_value(self, v):
        return 20 * np.log10(abs(v)) if v != 0 else 0

    def update_graph(self):
        tab_idx = self.tabs.currentIndex()
        show_db = self.show_db_checkbox.isChecked()
        
        # Get current gain for CH0 (if available)
        gain_info = ""
        if hasattr(self, 'adc') and self.adc is not None and hasattr(self.adc, 'channel_gains'):
            gain_val = self.adc.channel_gains[0]
            gain_info = f" (CH0 Gain: {gain_val}x)"
        
        # Ensure correct graph is shown and update Y-axis label
        self.graph_stack.setCurrentIndex(1 if tab_idx == 0 else 0)
        if show_db:
            y_label = "Voltage [dB]" + gain_info
            self.normal_current_header.setText("Current [dB]")
            self.normal_calibrated_header.setText("Calibrated [dB]")
            self.normal_diff_header.setText("Ratio[dB] Cur/Calib")
        else:
            y_label = "Voltage [V]" + gain_info
            self.normal_current_header.setText("Current [V]")
            self.normal_calibrated_header.setText("Calibrated [V]")
            self.normal_diff_header.setText("Ratio Cur/Calib")
        self.graph_widget.setLabel('left', y_label)
        self.bar_widget.setLabel('left', y_label)

        if tab_idx == 0:
            # NORMAL MODE: Bar graph of current values
            x = list(range(len(PARAMETERS)))
            if self.t:
                y = []
                for param in PARAMETERS:
                    cur_val = self.data[param][-1] if self.data[param] else 0
                    y.append(self.db_value(cur_val) if show_db else cur_val)
            else:
                y = [0] * len(PARAMETERS)
            # Remove previous bar item
            self.bar_widget.clear()
            # Bar for current values (blue)
            self.bar_item = pg.BarGraphItem(x=[i-0.15 for i in x], height=y, width=0.3, brush='b')
            self.bar_widget.addItem(self.bar_item)
            # Bar for calibrated values (red)
            y_calib = []
            for param in PARAMETERS:
                calib_val = self.calibrated_values.get(param)
                y_calib.append(self.db_value(calib_val) if (show_db and calib_val is not None) else (calib_val if calib_val is not None else 0))
            self.bar_item_calib = pg.BarGraphItem(x=[i+0.15 for i in x], height=y_calib, width=0.3, brush='r')
            self.bar_widget.addItem(self.bar_item_calib)
            # Set x-axis ticks to wavelength labels
            ax = self.bar_widget.getAxis('bottom')
            ax.setTicks([[ (i, PARAMETERS[i]) for i in range(len(PARAMETERS)) ]])
            
            # This logic needs to run for both tabs to keep NORMAL mode display consistent
            for param in PARAMETERS:
                if self.data[param]:
                    cur_val = self.data[param][-1]
                    calib_val = self.calibrated_values.get(param)

                    # Calculate ratio based on show_db mode
                    ratio = None
                    if cur_val > 0 and calib_val is not None and calib_val > 0:
                        try:
                            if show_db:
                                # dB mode: 20*log10(current/calibrated)
                                ratio = 20 * np.log10(cur_val / calib_val)
                            else:
                                # Non-dB mode: current/calibrated
                                ratio = cur_val / calib_val
                        except Exception:
                            ratio = None
                    # Display values
                    if show_db:
                        self.normal_db_labels[param].setText(f"{self.db_value(cur_val):.2f}")
                        if calib_val is not None:
                            self.normal_calib_db_labels[param].setText(f"{self.db_value(calib_val):.2f}")
                            if ratio is not None:
                                self.normal_diff_db_labels[param].setText(f"{ratio:.2f}")
                                # For dB ratio: flag red if less than -6dB
                                if ratio < -6:
                                    self.normal_diff_db_labels[param].setStyleSheet("font-size: 16px; background-color: red; color: white;")
                                else:
                                    self.normal_diff_db_labels[param].setStyleSheet("font-size: 16px; background-color: green; color: white;")
                            else:
                                self.normal_diff_db_labels[param].setText("-")
                                self.normal_diff_db_labels[param].setStyleSheet("font-size: 16px;")
                        else:
                            self.normal_calib_db_labels[param].setText("-")
                            self.normal_diff_db_labels[param].setText("-")
                            self.normal_diff_db_labels[param].setStyleSheet("font-size: 16px;")
                    else: # Not in dB mode
                        self.normal_db_labels[param].setText(f"{cur_val:.4f}")
                        if calib_val is not None:
                            self.normal_calib_db_labels[param].setText(f"{calib_val:.4f}")
                            if ratio is not None:
                                self.normal_diff_db_labels[param].setText(f"{ratio:.2f}")
                                # For ratio: flag red if less than 0.5
                                if ratio < 0.5:
                                    self.normal_diff_db_labels[param].setStyleSheet("font-size: 16px; background-color: red; color: white;")
                                else:
                                    self.normal_diff_db_labels[param].setStyleSheet("font-size: 16px; background-color: green; color: white;")
                            else:
                                self.normal_diff_db_labels[param].setText("-")
                                self.normal_diff_db_labels[param].setStyleSheet("font-size: 16px;")
                        else:
                            self.normal_calib_db_labels[param].setText("-")
                            self.normal_diff_db_labels[param].setText("-")
                            self.normal_diff_db_labels[param].setStyleSheet("font-size: 16px;")
                else:
                    self.normal_db_labels[param].setText("-")
                    self.normal_calib_db_labels[param].setText("-")
                    self.normal_diff_db_labels[param].setText("-")
                    self.normal_diff_db_labels[param].setStyleSheet("font-size: 16px;")
        else:
            # ADVANCED MODE: Time series plot
            if hasattr(self, 'show_all_checkbox') and self.show_all_checkbox.isChecked():
                t_show = self.t
                buffer_size = len(self.t)
            else:
                t_show = self.t[-self.buffer_size:]
                buffer_size = self.buffer_size
            for param in PARAMETERS:
                data_show = self.data[param][-buffer_size:]
                if show_db:
                    data_plot = [self.db_value(v) for v in data_show]
                else:
                    data_plot = data_show
                
                # Safeguard against mismatched data lengths to prevent crashes
                if len(t_show) == len(data_plot):
                    self.curves[param].setData(t_show, data_plot)
                else:
                    self.curves[param].setData([], []) # Clear plot on mismatch

                self.curves[param].setVisible(self.param_checkboxes[param].isChecked())
                # Update all value and dB fields
                if data_show:
                    min_val = min(data_show)
                    max_val = max(data_show)
                    cur_val = data_show[-1]
                    calib_val = self.calibrated_values.get(param)
                    # Calibrated
                    if calib_val is not None:
                        self.calib_fields[param].setText(f"{calib_val:.2f}")
                        self.calib_db_fields[param].setText(f"{self.db_value(calib_val):.2f}")
                    else:
                        self.calib_fields[param].setText("")
                        self.calib_db_fields[param].setText("")
                    # Current
                    self.cur_fields[param].setText(f"{cur_val:.2f}")
                    self.db_fields[param].setText(f"{self.db_value(cur_val):.2f}")
                    # Min
                    self.min_fields[param].setText(f"{min_val:.2f}")
                    self.min_db_fields[param].setText(f"{self.db_value(min_val):.2f}")
                    # Max
                    self.max_fields[param].setText(f"{max_val:.2f}")
                    self.max_db_fields[param].setText(f"{self.db_value(max_val):.2f}")
                    # Diff Ratio (based on show_db mode)
                    ratio = None
                    if cur_val > 0 and calib_val is not None and calib_val > 0:
                        try:
                            if show_db:
                                # dB mode: 20*log10(current/calibrated)
                                ratio = 20 * np.log10(cur_val / calib_val)
                            else:
                                # Non-dB mode: current/calibrated
                                ratio = cur_val / calib_val
                        except Exception:
                            ratio = None
                    if ratio is not None:
                        self.diff_pct_fields[param].setText(f"{ratio:.2f}")
                        # Flag based on mode
                        if show_db:
                            # For dB ratio: flag red if less than -6dB
                            if ratio < -6:
                                self.diff_pct_fields[param].setStyleSheet("background-color: red; color: white;")
                            else:
                                self.diff_pct_fields[param].setStyleSheet("background-color: green; color: white;")
                        else:
                            # For ratio: flag red if less than 0.5
                            if ratio < 0.5:
                                self.diff_pct_fields[param].setStyleSheet("background-color: red; color: white;")
                            else:
                                self.diff_pct_fields[param].setStyleSheet("background-color: green; color: white;")
                    else:
                        self.diff_pct_fields[param].setText("")
                        self.diff_pct_fields[param].setStyleSheet("")
                    # Ratio Cur/Calib (same logic as above)
                    if ratio is not None:
                        self.diff_db_fields[param].setText(f"{ratio:.2f}")
                        # Flag based on mode
                        if show_db:
                            # For dB ratio: flag red if less than -6dB
                            if ratio < -6:
                                self.diff_db_fields[param].setStyleSheet("background-color: red; color: white;")
                            else:
                                self.diff_db_fields[param].setStyleSheet("background-color: green; color: white;")
                        else:
                            # For ratio: flag red if less than 0.5
                            if ratio < 0.5:
                                self.diff_db_fields[param].setStyleSheet("background-color: red; color: white;")
                            else:
                                self.diff_db_fields[param].setStyleSheet("background-color: green; color: white;")
                    else:
                        self.diff_db_fields[param].setText("")
                        self.diff_db_fields[param].setStyleSheet("")
                else:
                    self.calib_fields[param].setText("")
                    self.cur_fields[param].setText("")
                    self.min_fields[param].setText("")
                    self.max_fields[param].setText("")
                    self.diff_pct_fields[param].setText("")
                    self.calib_db_fields[param].setText("")
                    self.db_fields[param].setText("")
                    self.min_db_fields[param].setText("")
                    self.max_db_fields[param].setText("")
                    self.diff_db_fields[param].setText("")

    def update_sampling_label(self, value):
        self.sampling_label.setText(f"Batch Timer Frequency: {value} Hz")

    def update_datapoints_label(self, value):
        self.datapoints_label.setText(f"Data Points: {value}")
        self.buffer_size = value
        self.update_graph()

    def log_data(self, t, data_row):
        # Log to text file (CSV)
        calib_row = [self.calibrated_values[param] if self.calibrated_values[param] is not None else "" for param in PARAMETERS]
        
        # Get current gain values for both channels
        ch0_gain = 0
        ch1_gain = 0
        if hasattr(self, 'adc') and self.adc is not None and hasattr(self.adc, 'channel_gains'):
            ch0_gain = self.adc.channel_gains[0] if len(self.adc.channel_gains) > 0 else 0
            ch1_gain = self.adc.channel_gains[1] if len(self.adc.channel_gains) > 1 else 0
        
        # Get current timestamp
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Add gain information and current time to the row
        gain_row = [ch0_gain, ch1_gain]
        row_to_write = [t, current_time] + data_row + calib_row + gain_row
        
        with open(self.text_log_file, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(row_to_write)
        # Log to CSV file
        with open(self.csv_log_file, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(row_to_write)

    def update_sampling_rate(self, value):
        """Update batch timer interval based on slider value (calls per second)"""
        # Clamp value to avoid division by zero
        freq_hz = max(1, int(value))
        interval_ms = max(1, int(round(1000 / freq_hz)))
        self.BATCH_TIMER_INTERVAL_MS = interval_ms
        print(f"Batch timer interval set to {self.BATCH_TIMER_INTERVAL_MS} ms ({freq_hz} Hz)")
        # If scanning, restart the timer with new interval
        if self.scanning:
            self.sampling_timer.stop()
            self.sampling_timer.start(self.BATCH_TIMER_INTERVAL_MS)

    def toggle_scan(self):
        if not self.scanning:
            # Store the start time of the measurement
            self.measure_start_time = time.time()
            self.adc_read_count = 0  # Reset ADC read counter
            self.cycle_detected_count = 0  # Reset cycle counter
            self.sample_timestamps = []  # Reset sample timestamps
            self.consecutive_cycles = 0
            self.is_locked = False
            self.is_timing_adjusted = False
            # Removed lock_label.hide() since we don't have the lock label anymore
            self.last_sample_batch_time = time.time() # Initialize batch time
            
            # Reset cycle statistics
            self.cycle_timestamps = []
            self.cycle_intervals = []
            self.cycle_scores = []
            self.cycle_qualities = []
            self.cycle_pulse_counts = []
            self.cycle_voltage_stats = []
            self.cycle_rate_history = []
            self.pattern_quality_history = []
            self.total_cycles_detected = 0
            
            # Reset wavelength cycling
            self.wavelength_cycle_count = 0
            self.current_wavelength = PARAMETERS[0]
            self.wavelength_data = {param: [] for param in PARAMETERS}
            
            # Reset continuous averaging
            self.continuous_wavelength_cycle = 0
            self.continuous_sample_buffer = {param: [] for param in PARAMETERS}
            
            # Stop any existing no-pattern timer
            self.no_pattern_timer.stop()
            self.pattern_detection_active = False
            
            # Turn on power before starting measurement
            if self.gpio_available and self.power_line:
                try:
                    self.power_line.set_value(1)  # Set HIGH
                    print(f"GPIO{self.POWER_PIN} set to HIGH")
                except Exception as e:
                    print(f"Error setting GPIO HIGH: {e}")
            
            self.update_sampling_rate(self.sampling_slider.value())  # Ensure timer interval matches slider
            self.sampling_timer.start(self.BATCH_TIMER_INTERVAL_MS)
            self.graph_timer.start(1000)
            self.stats_timer.start(5000)  # Display stats every 5 seconds
            self.scan_btn.setText("STOP")
            self.scanning = True
            if not self.continuous_checkbox.isChecked():
                # Single measurement: stop after one update
                QTimer.singleShot(1100, self.stop_scan)
        else:
            self.stop_scan()

    def print_cycle_statistics(self):
        """Print current cycle statistics to console"""
        if not self.scanning or len(self.cycle_timestamps) == 0:
            return
            
        print("\n" + "-"*50)
        print("           CURRENT CYCLE STATISTICS")
        print("-"*50)
        print(f"  Total Cycles Detected:  {self.total_cycles_detected}")
        print(f"  Consecutive Cycles:     {self.consecutive_cycles}")
        print(f"  Pattern Lock Status:    {'LOCKED' if self.is_locked else 'UNLOCKED'}")
        
        # Detection timing
        if len(self.cycle_timestamps) > 0:
            time_since_last = time.time() - self.cycle_timestamps[-1]
            print(f"  Time Since Last Cycle:  {time_since_last:.2f} seconds")
        
        # Recent cycle rate
        if len(self.cycle_rate_history) > 0:
            recent_rate = np.mean(self.cycle_rate_history[-5:])  # Last 5 cycles
            print(f"  Recent Cycle Rate:      {recent_rate:.2f} Hz")
        
        # Recent pattern quality
        if len(self.cycle_qualities) > 0:
            recent_quality = np.mean(self.cycle_qualities[-5:])  # Last 5 cycles
            print(f"  Recent Pattern Quality: {recent_quality:.3f}")
        
        # Recent correlation scores
        if len(self.cycle_scores) > 0:
            recent_score = np.mean(self.cycle_scores[-5:])  # Last 5 cycles
            print(f"  Recent Correlation:     {recent_score:.3f}")
        
        # Recent pulse counts
        if len(self.cycle_pulse_counts) > 0:
            recent_pulses = np.mean(self.cycle_pulse_counts[-5:])  # Last 5 cycles
            print(f"  Recent Pulses/Cycle:    {recent_pulses:.1f}")
        
        # Recent voltage statistics
        if len(self.cycle_voltage_stats) > 0:
            recent_stats = self.cycle_voltage_stats[-5:]  # Last 5 cycles
            avg_mean = np.mean([stats['mean'] for stats in recent_stats])
            avg_std = np.mean([stats['std'] for stats in recent_stats])
            print(f"  Recent Pulse Voltage Mean: {avg_mean:.4f} V")
            print(f"  Recent Pulse Voltage Std:  {avg_std:.4f} V")
            
            # Show the most recent pulse voltages
            if recent_stats and 'pulse_voltages' in recent_stats[-1]:
                latest_pulses = recent_stats[-1]['pulse_voltages']
                wavelengths = ["700nm", "800nm", "850nm", "900nm", "970nm", "1050nm"]
                print(f"  Latest Pulse Voltages:")
                for wavelength, voltage in zip(wavelengths, latest_pulses):
                    print(f"    {wavelength}: {voltage:.4f}V")
        
        # Data availability
        total_samples = sum(len(buffer) for buffer in self.sample_buffer.values())
        print(f"  Samples in Buffer:      {total_samples}")
        
        # Wavelength cycling information
        print(f"  Current Wavelength:    {self.current_wavelength}")
        print(f"  Wavelength Cycle:      {self.wavelength_cycle_count}")
        
        # Show samples per wavelength
        print("  Samples per Wavelength:")
        for param in PARAMETERS:
            # Count from pattern-based sample buffers (detected cycles)
            pattern_count = len(self.sample_buffer[param])
            # Count from continuous sample buffers (all readings)
            continuous_count = len([v for v in self.data[param] if v > 0])
            print(f"    {param}: {continuous_count} continuous, {pattern_count} pattern-based")
        
        print("-"*50)

    def stop_scan(self):
        self.sampling_timer.stop()
        self.graph_timer.stop()
        self.stats_timer.stop()  # Stop stats timer
        self.no_pattern_timer.stop()  # Stop the no-pattern timer
        self.scan_btn.setText("MEASURE")
        self.scanning = False
        
        # Print measurement summary with detailed cycle statistics
        if self.measure_start_time and self.adc_read_count > 0:
            duration = time.time() - self.measure_start_time
            if duration > 0:
                avg_sps = self.adc_read_count / duration
                avg_cps = self.cycle_detected_count / duration
                
                print("\n" + "="*60)
                print("           MEASUREMENT SUMMARY")
                print("="*60)
                print(f"  Elapsed Time:           {duration:.2f} s")
                print(f"  Total ADC Reads:        {self.adc_read_count:,}")
                print(f"  Avg. Samples / Sec:     {avg_sps:.1f}")
                print(f"  Total Cycles Detected:  {self.total_cycles_detected}")
                print(f"  Avg. Cycles / Sec:      {avg_cps:.2f}")
                
                # Cycle statistics
                if len(self.cycle_intervals) > 0:
                    avg_interval = np.mean(self.cycle_intervals)
                    std_interval = np.std(self.cycle_intervals)
                    min_interval = np.min(self.cycle_intervals)
                    max_interval = np.max(self.cycle_intervals)
                    print(f"  Avg. Cycle Interval:    {avg_interval*1000:.1f} ms")
                    print(f"  Cycle Interval Std:     {std_interval*1000:.1f} ms")
                    print(f"  Min Cycle Interval:     {min_interval*1000:.1f} ms")
                    print(f"  Max Cycle Interval:     {max_interval*1000:.1f} ms")
                
                # Pattern quality statistics
                if len(self.cycle_qualities) > 0:
                    avg_quality = np.mean(self.cycle_qualities)
                    std_quality = np.std(self.cycle_qualities)
                    min_quality = np.min(self.cycle_qualities)
                    max_quality = np.max(self.cycle_qualities)
                    print(f"  Avg. Pattern Quality:   {avg_quality:.3f}")
                    print(f"  Quality Std Dev:        {std_quality:.3f}")
                    print(f"  Min Quality:            {min_quality:.3f}")
                    print(f"  Max Quality:            {max_quality:.3f}")
                
                # Correlation score statistics
                if len(self.cycle_scores) > 0:
                    avg_score = np.mean(self.cycle_scores)
                    std_score = np.std(self.cycle_scores)
                    min_score = np.min(self.cycle_scores)
                    max_score = np.max(self.cycle_scores)
                    print(f"  Avg. Correlation Score: {avg_score:.3f}")
                    print(f"  Score Std Dev:          {std_score:.3f}")
                    print(f"  Min Score:              {min_score:.3f}")
                    print(f"  Max Score:              {max_score:.3f}")
                
                # Pulse count statistics
                if len(self.cycle_pulse_counts) > 0:
                    avg_pulses = np.mean(self.cycle_pulse_counts)
                    std_pulses = np.std(self.cycle_pulse_counts)
                    min_pulses = np.min(self.cycle_pulse_counts)
                    max_pulses = np.max(self.cycle_pulse_counts)
                    print(f"  Avg. Pulses per Cycle:  {avg_pulses:.1f}")
                    print(f"  Pulse Count Std Dev:    {std_pulses:.1f}")
                    print(f"  Min Pulses:             {min_pulses}")
                    print(f"  Max Pulses:             {max_pulses}")
                
                # Voltage statistics
                if len(self.cycle_voltage_stats) > 0:
                    avg_voltage_mean = np.mean([stats['mean'] for stats in self.cycle_voltage_stats])
                    avg_voltage_std = np.mean([stats['std'] for stats in self.cycle_voltage_stats])
                    avg_voltage_min = np.mean([stats['min'] for stats in self.cycle_voltage_stats])
                    avg_voltage_max = np.mean([stats['max'] for stats in self.cycle_voltage_stats])
                    print(f"  Avg. Pulse Voltage Mean: {avg_voltage_mean:.4f} V")
                    print(f"  Avg. Pulse Voltage Std:  {avg_voltage_std:.4f} V")
                    print(f"  Avg. Pulse Voltage Min:  {avg_voltage_min:.4f} V")
                    print(f"  Avg. Pulse Voltage Max:  {avg_voltage_max:.4f} V")
                    
                    # Show recent pulse voltage range
                    if len(self.cycle_voltage_stats) >= 5:
                        recent_stats = self.cycle_voltage_stats[-5:]
                        recent_means = [stats['mean'] for stats in recent_stats]
                        print(f"  Recent Pulse Voltages:  {[f'{v:.3f}V' for v in recent_means]}")
                
                # Lock status
                print(f"  Pattern Lock Status:    {'LOCKED' if self.is_locked else 'UNLOCKED'}")
                print(f"  Consecutive Cycles:     {self.consecutive_cycles}")
                
                # Wavelength cycling statistics
                print(f"  Total Wavelength Cycles: {self.wavelength_cycle_count}")
                print(f"  Complete Wavelength Sets: {self.wavelength_cycle_count // len(PARAMETERS)}")
                print(f"  Current Wavelength:      {self.current_wavelength}")
                
                # Samples per wavelength
                print("  Samples per Wavelength:")
                for param in PARAMETERS:
                    # Count from pattern-based sample buffers (detected cycles)
                    pattern_count = len(self.sample_buffer[param])
                    # Count from continuous sample buffers (all readings)
                    continuous_count = len([v for v in self.data[param] if v > 0])
                    print(f"    {param}: {continuous_count} continuous, {pattern_count} pattern-based")
                
                # Recent performance (last 10 cycles)
                if len(self.cycle_rate_history) > 0:
                    recent_rate = np.mean(self.cycle_rate_history[-10:])
                    print(f"  Recent Cycle Rate:      {recent_rate:.2f} Hz")
                
                if len(self.pattern_quality_history) > 0:
                    recent_quality = np.mean(self.pattern_quality_history[-10:])
                    print(f"  Recent Pattern Quality: {recent_quality:.3f}")
                
                print("="*60)

        # Turn off power when stopping measurement
        if self.gpio_available and self.power_line:
            try:
                self.power_line.set_value(0)  # Set LOW
                print(f"GPIO{self.POWER_PIN} set to LOW")
            except Exception as e:
                print(f"Error setting GPIO LOW: {e}")

    def toggle_curve(self, param, state):
        if state == 0:
            self.curves[param].setVisible(False)
        else:
            self.curves[param].setVisible(True)

    def read_adc_batch(self, duration_ms=20):
        """
        Read as many ADC samples as possible in duration_ms milliseconds.
        Returns a list of (timestamp, voltage) tuples.
        """
        start = time.perf_counter()
        readings = []
        while (time.perf_counter() - start) * 1000 < duration_ms:
            try:
                if self.adc_type == 'ADS131M02':
                    voltages = self.adc.read_data()
                    voltage = voltages[0] if voltages and len(voltages) > 0 else 0.0
                else:
                    voltage = self.adc.read_voltage(0)
                
                # Apply voltage scaling correction
                voltage = self.apply_voltage_scaling(voltage)
                
                readings.append((time.perf_counter(), voltage))
            except Exception as e:
                print(f"Error reading from ADC: {e}")
        return readings

    def sample_data(self):
        # If ADC is not available, do nothing.
        if self.adc is None:
            return
        # Ensure sample_buffer is initialized
        if not hasattr(self, 'sample_buffer'):
            self.sample_buffer = {param: [] for param in PARAMETERS}
        # Read a batch of samples for 20ms
        batch = self.read_adc_batch(duration_ms=20)
        voltages = [v for t, v in batch]
        if not voltages:
            return
        
        # Debug voltage readings (only in verbose mode)
        if self.verbose_checkbox.isChecked() and len(voltages) > 0:
            min_v = min(voltages)
            max_v = max(voltages)
            mean_v = np.mean(voltages)
            print(f"Voltage batch: min={min_v:.4f}V, max={max_v:.4f}V, mean={mean_v:.4f}V")
        
        # Pattern detection on the batch using new algorithm
        pattern_result = self.detect_cycle_in_batch(voltages)
        
        # Update ADC read count and timestamps
        self.adc_read_count += len(voltages)
        now = time.time()
        self.sample_timestamps.extend([now] * len(voltages))
        
        # Always average the voltage readings and cycle through wavelengths continuously
        avg_val = float(np.mean(voltages))
        self.continuous_wavelength_cycle += 1
        continuous_wavelength_idx = (self.continuous_wavelength_cycle - 1) % len(PARAMETERS)
        continuous_wavelength = PARAMETERS[continuous_wavelength_idx]
        self.continuous_sample_buffer[continuous_wavelength].append(avg_val)
        
        # --- Only auto-adjust gain if any value from last detected cycle is < 0.1V ---
        if pattern_result['detected']:
            # Pattern detected - update cycle statistics
            self.cycle_detected_count += 1
            self.total_cycles_detected += 1
            
            # Stop the no-pattern timer since we detected a pattern
            self.no_pattern_timer.stop()
            self.pattern_detection_active = False
            
            # Get information about all valid cycles found
            all_valid_cycles = pattern_result.get('all_valid_cycles', [])
            total_valid_cycles = pattern_result.get('total_valid_cycles', 0)
            
            if self.verbose_checkbox.isChecked():
                print(f"Processing {total_valid_cycles} valid cycles from this batch")
            
            # Process all valid cycles (but limit to avoid overwhelming the system)
            max_cycles_to_process = min(3, total_valid_cycles)  # Process up to 3 cycles per batch
            
            for cycle_idx in range(max_cycles_to_process):
                cycle_data = all_valid_cycles[cycle_idx]
                
                # Use the sorted pulse data from the new algorithm
                sorted_pulse_times = cycle_data.get('sorted_pulse_times', [])
                sorted_pulse_clusters = cycle_data.get('sorted_pulse_clusters', [])
                sorted_pulse_voltages = cycle_data.get('sorted_pulse_voltages', [])
                
                if len(sorted_pulse_times) == 6 and len(sorted_pulse_clusters) == 6:
                    # Assign each pulse to the correct wavelength in order
                    wavelengths = ["700nm", "800nm", "850nm", "900nm", "970nm", "1050nm"]
                    
                    for i, (pulse_time, pulse_cluster, pulse_voltage) in enumerate(zip(sorted_pulse_times, sorted_pulse_clusters, sorted_pulse_voltages)):
                        if i < len(wavelengths):
                            wavelength = wavelengths[i]
                            # Use the pre-calculated average voltage for this pulse
                            gain = self.adc.channel_gains[0] if hasattr(self.adc, 'channel_gains') and len(self.adc.channel_gains) > 0 else 1
                            self.sample_buffer[wavelength].append(pulse_voltage / gain)
                            if self.verbose_checkbox.isChecked() and cycle_idx == 0:  # Only show for first cycle
                                print(f"  Assigned pulse {i+1} ({pulse_time:.2f}ms) to {wavelength}: {pulse_voltage:.4f}V (raw), {pulse_voltage / gain:.4f}V (normalized)")
                    # Update wavelength cycling counter for each cycle processed
                    self.wavelength_cycle_count += 1
                    if self.verbose_checkbox.isChecked() and cycle_idx == 0:  # Only show for first cycle
                        print(f"  Wavelength assignment: {[f'{wavelengths[i]}:{sorted_pulse_times[i]:.2f}ms' for i in range(6)]}")
                    # --- Check if any value is < 0.1V and trigger gain adjustment ---
                    if any(abs(v) < 0.1 for v in sorted_pulse_voltages):
                        self.auto_adjust_gain(channel=0, voltage_batch=voltages, threshold_low=0.1, threshold_high=1.0)
            # Update current wavelength based on total cycles processed
            wavelengths = ["700nm", "800nm", "850nm", "900nm", "970nm", "1050nm"]
            self.current_wavelength = wavelengths[self.wavelength_cycle_count % len(wavelengths)]
            # Store cycle timestamp
            self.cycle_timestamps.append(now)
            # Calculate cycle interval
            if len(self.cycle_timestamps) > 1:
                interval = self.cycle_timestamps[-1] - self.cycle_timestamps[-2]
                self.cycle_intervals.append(interval)
                # Keep only last 100 intervals for statistics
                if len(self.cycle_intervals) > 100:
                    self.cycle_intervals.pop(0)
            # Store cycle statistics
            self.cycle_scores.append(pattern_result.get('score', 0))
            self.cycle_qualities.append(pattern_result.get('quality', 0))
            self.cycle_pulse_counts.append(pattern_result.get('pulse_count', 0))
            # Calculate voltage statistics from the actual detected pulses, not the entire batch
            if pattern_result.get('sorted_pulse_voltages'):
                pulse_voltages = pattern_result['sorted_pulse_voltages']
                self.cycle_voltage_stats.append({
                    'mean': np.mean(pulse_voltages),
                    'std': np.std(pulse_voltages),
                    'min': np.min(pulse_voltages),
                    'max': np.max(pulse_voltages),
                    'high_samples': pattern_result.get('high_samples', 0),
                    'pulse_voltages': pulse_voltages  # Store actual pulse voltages
                })
            else:
                # Fallback to batch statistics if no pulse voltages available
                self.cycle_voltage_stats.append({
                    'mean': np.mean(voltages),
                    'std': np.std(voltages),
                    'min': np.min(voltages),
                    'max': np.max(voltages),
                    'high_samples': pattern_result.get('high_samples', 0)
                })
            # Keep only last 100 entries for each statistic
            for stat_list in [self.cycle_scores, self.cycle_qualities, self.cycle_pulse_counts, self.cycle_voltage_stats]:
                if len(stat_list) > 100:
                    stat_list.pop(0)
            # Calculate current cycle rate
            if len(self.cycle_intervals) > 0:
                avg_interval = np.mean(self.cycle_intervals)
                current_cycle_rate = 1.0 / avg_interval if avg_interval > 0 else 0
                self.cycle_rate_history.append(current_cycle_rate)
                if len(self.cycle_rate_history) > 50:
                    self.cycle_rate_history.pop(0)
            # Calculate pattern quality trend
            if len(self.cycle_qualities) > 0:
                avg_quality = np.mean(self.cycle_qualities[-10:])  # Last 10 cycles
                self.pattern_quality_history.append(avg_quality)
                if len(self.pattern_quality_history) > 50:
                    self.pattern_quality_history.pop(0)
            # Update consecutive cycles and lock status
            self.consecutive_cycles += 1
            if self.consecutive_cycles >= self.LOCK_THRESHOLD:
                self.is_locked = True
                # Don't show lock label anymore
            # Hide the status label if it was shown
            self.status_label.hide()
            if self.verbose_checkbox.isChecked():
                print(f"âœ“ Cycle #{self.total_cycles_detected} detected: score={pattern_result.get('score', 0):.3f}, "
                      f"quality={pattern_result.get('quality', 0):.3f}, pulses={pattern_result.get('pulse_count', 0)}")
                print(f"  Processed {max_cycles_to_process} cycles from this batch")
                # Show the actual pulse voltages being used for this cycle
                if pattern_result.get('sorted_pulse_voltages'):
                    pulse_voltages = pattern_result['sorted_pulse_voltages']
                    wavelengths = ["700nm", "800nm", "850nm", "900nm", "970nm", "1050nm"]
                    print(f"  Pulse voltages for this cycle:")
                    for i, (wavelength, voltage) in enumerate(zip(wavelengths, pulse_voltages)):
                        print(f"    {wavelength}: {voltage:.4f}V")
                    print(f"  Average pulse voltage: {np.mean(pulse_voltages):.4f}V")
        else:
            # No pattern detected - reset consecutive cycles
            self.consecutive_cycles = 0
            self.is_locked = False
            # Start the 3-second timer to show "NO PATTERN DETECTED" if no patterns are detected
            if not self.pattern_detection_active:
                self.no_pattern_timer.start(3000)  # 3 seconds
                self.pattern_detection_active = True
            if self.verbose_checkbox.isChecked():
                print(f"âœ— No pattern detected in batch of {len(voltages)} samples")
                print(f"  Continuous averaging: {avg_val:.4f}V")
            # DO NOT add to pattern-based sample buffer when no pattern is detected
            # But continuous averaging continues regardless
            # --- Auto-adjust gain if all voltages are below threshold and no pattern detected ---
            self.auto_adjust_gain(channel=0, voltage_batch=voltages, threshold_low=0.1, threshold_high=1.0)

    def detect_cycle_in_batch(self, voltages):
        """
        New algorithm to detect pulse patterns in a 20ms batch.
        Assumes voltage threshold > 100mV for pulses, < 100mV for no pulse.
        Groups multiple samples of the same pulse together.
        Sorts pulses to correct placement for wavelength assignment.
        """
        import numpy as np
        
        # Expected pattern: 6 pulses representing 6 wavelengths (700nm, 800nm, 850nm, 900nm, 970nm, 1050nm)
        # Repeating at 256Hz = 1 cycle every ~3.9ms
        EXPECTED_PULSE_COUNT = 6
        EXPECTED_CYCLE_FREQUENCY_HZ = 256.0
        EXPECTED_CYCLE_DURATION_MS = 1000.0 / EXPECTED_CYCLE_FREQUENCY_HZ  # ~3.9ms
        VOLTAGE_THRESHOLD = 0.1  # 100mV threshold
        
        # Calculate actual samples per second from the current 20ms batch
        batch_duration_ms = 20.0  # 20ms batch window
        actual_samples_in_batch = len(voltages)
        avg_sps = (actual_samples_in_batch / batch_duration_ms) * 1000  # Convert to samples per second
            
        # Use the calculated actual samples per second for timing
        sps = avg_sps
        samples_per_cycle = int(round(EXPECTED_CYCLE_DURATION_MS * (sps / 1000)))

        # Initialize result dictionary
        result = {
            'detected': False,
            'score': 0.0,
            'quality': 0.0,
            'pulse_count': 0,
            'high_samples': 0,
            'pulse_width_ms': 0.0,
            'actual_sps': sps,
            'voltage_stats': {
                'mean': np.mean(voltages),
                'std': np.std(voltages),
                'min': np.min(voltages),
                'max': np.max(voltages)
            }
        }

        # Debug information
        if self.verbose_checkbox.isChecked():
            print(f"\n--- New Pattern Detection Algorithm ---")
            print(f"Batch size: {len(voltages)} samples")
            print(f"Batch duration: {batch_duration_ms}ms")
            print(f"Calculated SPS from batch: {avg_sps:.1f}")
            print(f"Voltage range: {min(voltages):.4f}V to {max(voltages):.4f}V")
            print(f"Voltage mean: {np.mean(voltages):.4f}V, std: {np.std(voltages):.4f}V")
            print(f"Voltage threshold: {VOLTAGE_THRESHOLD}V")
            print(f"Samples above threshold: {sum(1 for v in voltages if v > VOLTAGE_THRESHOLD)}")
            print(f"Expected cycle frequency: {EXPECTED_CYCLE_FREQUENCY_HZ}Hz")
            print(f"Expected cycle duration: {EXPECTED_CYCLE_DURATION_MS:.3f}ms")
            print(f"Samples per cycle: {samples_per_cycle}")

        # Check if we have enough samples for at least one cycle
        if len(voltages) < samples_per_cycle:
            if self.verbose_checkbox.isChecked():
                print(f"Buffer too small: {len(voltages)} < {samples_per_cycle}")
            return result

        # --- New pulse detection algorithm ---
        buf = np.array(voltages)
        
        # Step 1: Identify pulse and no-pulse regions
        pulse_mask = buf > VOLTAGE_THRESHOLD
        no_pulse_mask = buf <= VOLTAGE_THRESHOLD
        
        if self.verbose_checkbox.isChecked():
            print(f"Pulse mask: {sum(pulse_mask)} samples above threshold")
            print(f"No-pulse mask: {sum(no_pulse_mask)} samples below threshold")
        
        # Step 2: Find transitions between pulse and no-pulse regions
        transitions = []
        for i in range(1, len(pulse_mask)):
            if pulse_mask[i] != pulse_mask[i-1]:
                transitions.append(i)
        
        if self.verbose_checkbox.isChecked():
            print(f"Found {len(transitions)} transitions")
        
        # Step 3: Group consecutive pulse samples into pulse clusters
        pulse_clusters = []
        current_cluster = []
        in_pulse = False
        
        for i in range(len(buf)):
            if pulse_mask[i]:  # Above threshold
                if not in_pulse:
                    # Start of new pulse
                    current_cluster = [i]
                    in_pulse = True
                else:
                    # Continue current pulse
                    current_cluster.append(i)
            else:  # Below threshold
                if in_pulse:
                    # End of pulse
                    if len(current_cluster) > 0:
                        pulse_clusters.append(current_cluster)
                    current_cluster = []
                    in_pulse = False
        
        # Handle case where batch ends with a pulse
        if in_pulse and len(current_cluster) > 0:
            pulse_clusters.append(current_cluster)
        
        if self.verbose_checkbox.isChecked():
            print(f"Found {len(pulse_clusters)} pulse clusters")
            for i, cluster in enumerate(pulse_clusters):
                cluster_start = cluster[0] / sps * 1000
                cluster_end = cluster[-1] / sps * 1000
                cluster_width = (cluster[-1] - cluster[0]) / sps * 1000
                cluster_voltage = np.mean([buf[idx] for idx in cluster])
                print(f"  Pulse {i+1}: {len(cluster)} samples, {cluster_start:.2f}ms-{cluster_end:.2f}ms, "
                      f"width={cluster_width:.2f}ms, avg_voltage={cluster_voltage:.4f}V")
        
        # Step 4: Calculate pulse characteristics
        pulse_center_times = []
        pulse_widths = []
        pulse_voltages = []
        
        for cluster in pulse_clusters:
            center_idx = np.mean(cluster)
            center_time = center_idx / sps * 1000  # Convert to ms
            pulse_center_times.append(center_time)
            
            width = (cluster[-1] - cluster[0]) / sps * 1000  # Convert to ms
            pulse_widths.append(width)
            
            voltage = np.mean([buf[idx] for idx in cluster])
            pulse_voltages.append(voltage)
        
        if self.verbose_checkbox.isChecked():
            print(f"Pulse times: {[f'{t:.2f}ms' for t in pulse_center_times]}")
            print(f"Pulse widths: {[f'{w:.2f}ms' for w in pulse_widths]}")
            print(f"Pulse voltages: {[f'{v:.4f}V' for v in pulse_voltages]}")
        
        # Step 5: Look for valid 6-pulse cycles
        valid_cycles = []
        
        # Try different starting points for 6-pulse sequences
        for start_idx in range(len(pulse_center_times) - EXPECTED_PULSE_COUNT + 1):
            # Get 6 consecutive pulses
            cycle_pulses = pulse_center_times[start_idx:start_idx + EXPECTED_PULSE_COUNT]
            cycle_widths = pulse_widths[start_idx:start_idx + EXPECTED_PULSE_COUNT]
            cycle_clusters = pulse_clusters[start_idx:start_idx + EXPECTED_PULSE_COUNT]
            
            if len(cycle_pulses) != EXPECTED_PULSE_COUNT:
                continue
            
            # Calculate cycle characteristics
            cycle_duration = cycle_pulses[-1] - cycle_pulses[0] + np.mean(cycle_widths)
            avg_pulse_width = np.mean(cycle_widths)
            
            # Calculate spacings between pulses
            spacings = []
            for i in range(1, len(cycle_pulses)):
                spacing = cycle_pulses[i] - cycle_pulses[i-1]
                spacings.append(spacing)
            
            avg_spacing = np.mean(spacings)
            spacing_std = np.std(spacings)
            
            # Validation criteria
            # 1. Cycle duration should be reasonable (2-6ms for 256Hz)
            cycle_duration_ok = 2.0 <= cycle_duration <= 6.0
            
            # 2. Pulse widths should be reasonable (0.1-0.5ms)
            pulse_width_ok = 0.1 <= avg_pulse_width <= 0.5
            
            # 3. Spacing should be reasonable (not too large gaps, not too small)
            min_spacing = min(spacings) if spacings else 0
            max_spacing = max(spacings) if spacings else 0
            spacing_ok = 0.1 <= min_spacing <= 2.0 and 0.1 <= max_spacing <= 2.0
            
            # 4. Should have exactly 6 pulses
            pulse_count_ok = len(cycle_pulses) == EXPECTED_PULSE_COUNT
            
            if self.verbose_checkbox.isChecked():
                print(f"  Cycle {start_idx}: duration={cycle_duration:.2f}ms, width={avg_pulse_width:.2f}ms, "
                      f"avg_spacing={avg_spacing:.2f}ms, spacing_range=[{min_spacing:.2f}-{max_spacing:.2f}]ms")
                print(f"    Duration OK: {cycle_duration_ok}, Width OK: {pulse_width_ok}, "
                      f"Spacing OK: {spacing_ok}, Count OK: {pulse_count_ok}")
            
            # Check if this cycle meets our criteria
            if cycle_duration_ok and pulse_width_ok and spacing_ok and pulse_count_ok:
                # Calculate quality score
                duration_error = abs(cycle_duration - EXPECTED_CYCLE_DURATION_MS) / EXPECTED_CYCLE_DURATION_MS
                width_error = abs(avg_pulse_width - 0.24) / 0.24  # Expected 0.24ms
                
                # Spacing consistency
                spacing_consistency = 1.0 - (spacing_std / avg_spacing) if avg_spacing > 0 else 0.0
                spacing_consistency = max(0, spacing_consistency)  # Clamp to 0-1
                
                # Overall quality (0-1, higher is better)
                quality_score = max(0, 1 - (duration_error + width_error + (1 - spacing_consistency)) / 3)
                
                if self.verbose_checkbox.isChecked():
                    print(f"    VALID - Quality: {quality_score:.3f} (duration_err={duration_error:.3f}, "
                          f"width_err={width_error:.3f}, spacing_consistency={spacing_consistency:.3f})")
                
                # Sort the pulses by time to ensure proper wavelength assignment
                pulse_data = list(zip(cycle_pulses, cycle_widths, cycle_clusters, pulse_voltages[start_idx:start_idx + EXPECTED_PULSE_COUNT]))
                pulse_data.sort(key=lambda x: x[0])  # Sort by time
                
                # Extract sorted data
                sorted_pulses = [p[0] for p in pulse_data]
                sorted_widths = [p[1] for p in pulse_data]
                sorted_clusters = [p[2] for p in pulse_data]
                sorted_voltages = [p[3] for p in pulse_data]
                
                # Store this valid cycle with sorted data
                valid_cycles.append({
                    'start_idx': start_idx,
                    'quality': quality_score,
                    'pulses': cycle_pulses,
                    'widths': cycle_widths,
                    'clusters': cycle_clusters,
                    'voltages': pulse_voltages[start_idx:start_idx + EXPECTED_PULSE_COUNT],
                    'sorted_pulse_times': sorted_pulses,
                    'sorted_pulse_widths': sorted_widths,
                    'sorted_pulse_clusters': sorted_clusters,
                    'sorted_pulse_voltages': sorted_voltages
                })
            else:
                if self.verbose_checkbox.isChecked():
                    print(f"    REJECTED")
        
        # Sort valid cycles by quality (best first)
        valid_cycles.sort(key=lambda x: x['quality'], reverse=True)
        
        # Check if we found any valid cycles
        if valid_cycles:
            # Use the best cycle
            best_cycle = valid_cycles[0]
            best_cycle_start = best_cycle['start_idx']
            best_cycle_quality = best_cycle['quality']
            cycle_pulses = best_cycle['pulses']
            cycle_widths = best_cycle['widths']
            cycle_clusters = best_cycle['clusters']
            cycle_voltages = best_cycle['voltages']
            
            # Use the pre-sorted data from the best cycle
            sorted_pulses = best_cycle['sorted_pulse_times']
            sorted_widths = best_cycle['sorted_pulse_widths']
            sorted_clusters = best_cycle['sorted_pulse_clusters']
            sorted_voltages = best_cycle['sorted_pulse_voltages']
            
            result['detected'] = True
            result['pulse_count'] = EXPECTED_PULSE_COUNT
            result['quality'] = best_cycle_quality
            result['score'] = best_cycle_quality
            result['pulse_width_ms'] = np.mean(sorted_widths)
            result['high_samples'] = sum(1 for v in voltages if v > VOLTAGE_THRESHOLD)
            
            # Add sorted pulse information for wavelength assignment
            result['sorted_pulse_times'] = sorted_pulses
            result['sorted_pulse_widths'] = sorted_widths
            result['sorted_pulse_clusters'] = sorted_clusters
            result['sorted_pulse_voltages'] = sorted_voltages
            
            # Add information about all valid cycles found
            result['total_valid_cycles'] = len(valid_cycles)
            result['all_valid_cycles'] = valid_cycles
            
            if self.verbose_checkbox.isChecked():
                print(f"âœ“ Found {len(valid_cycles)} valid cycles, using best one (start_idx={best_cycle_start})")
                print(f"  Original cycle pulses: {[f'{t:.2f}ms' for t in cycle_pulses]}")
                print(f"  Sorted cycle pulses: {[f'{t:.2f}ms' for t in sorted_pulses]}")
                print(f"  Sorted cycle voltages: {[f'{v:.4f}V' for v in sorted_voltages]}")
                print(f"  Sorted cycle widths: {[f'{w:.2f}ms' for w in sorted_widths]}")
                print(f"  Cycle duration: {sorted_pulses[-1] - sorted_pulses[0] + np.mean(sorted_widths):.2f}ms")
                print(f"  Quality score: {best_cycle_quality:.3f}")
                print(f"  Pulse samples per cluster: {[len(cluster) for cluster in sorted_clusters]}")
            else:
                if self.verbose_checkbox.isChecked():
                    print("âœ— No valid 6-pulse cycle found in batch")
                    print(f"  Total pulses found: {len(pulse_clusters)}")
                    print(f"  Expected: exactly {EXPECTED_PULSE_COUNT} pulses per cycle")
                    
                    # Show timing analysis for debugging
                    if len(pulse_center_times) >= 6:
                        print(f"  First 6 pulses: {[f'{t:.2f}ms' for t in pulse_center_times[:6]]}")
                        print(f"  First 6 spacings: {[f'{pulse_center_times[i] - pulse_center_times[i-1]:.2f}ms' for i in range(1, 6)]}")
            
        if self.verbose_checkbox.isChecked():
            print("--- End New Algorithm ---\n")
        
        return result

    def update_graph_from_buffer(self):
        # Compute average for each parameter and append to data arrays
        row = []
        
        # Check if we have recent pattern detections (within last 2 seconds)
        current_time = time.time()
        recent_pattern_detection = False
        if hasattr(self, 'cycle_timestamps') and self.cycle_timestamps:
            time_since_last_pattern = current_time - self.cycle_timestamps[-1]
            recent_pattern_detection = time_since_last_pattern < 2.0  # 2 second threshold
        
        # Clear old pattern data if no recent patterns detected (after 5 seconds)
        if not recent_pattern_detection and hasattr(self, 'cycle_timestamps') and self.cycle_timestamps:
            time_since_last_pattern = current_time - self.cycle_timestamps[-1]
            if time_since_last_pattern > 5.0:  # 5 second threshold to clear old data
                for param in PARAMETERS:
                    if self.sample_buffer[param]:
                        old_count = len(self.sample_buffer[param])
                        self.sample_buffer[param] = []  # Clear old pattern data
                        if self.verbose_checkbox.isChecked() and old_count > 0:
                            print(f"  Cleared {old_count} old pattern samples for {param} (no recent patterns)")
        
        for param in PARAMETERS:
            # Prioritize continuous data when no recent patterns detected
            if not recent_pattern_detection and self.continuous_sample_buffer[param]:
                # Use continuous averaging data when no recent patterns
                avg_val = float(np.mean(self.continuous_sample_buffer[param]))
                self.data[param].append(avg_val)
                row.append(avg_val)
                if self.verbose_checkbox.isChecked():
                    print(f"  Using continuous data for {param}: {avg_val:.4f}V (no recent patterns)")
                # Don't clear the continuous buffer immediately - let it accumulate more data
                # Only clear if it gets too large (more than 100 samples)
                if len(self.continuous_sample_buffer[param]) > 100:
                    self.continuous_sample_buffer[param] = self.continuous_sample_buffer[param][-50:]  # Keep last 50 samples
            elif self.sample_buffer[param]:
                # Use pattern-based data only when we have recent pattern detections
                dynamic_window = self.get_dynamic_averaging_window()
                # Average the recent pulse voltages for this wavelength
                recent_pulses = self.sample_buffer[param][-dynamic_window:]  # Last N pulse values
                avg_val = float(np.mean(recent_pulses))
                self.data[param].append(avg_val)
                row.append(avg_val)
                if self.verbose_checkbox.isChecked():
                    print(f"  Using averaged pulse data for {param}: {avg_val:.4f}V (from {len(recent_pulses)} pulses, window={dynamic_window})")
            elif self.continuous_sample_buffer[param]:
                # Fallback to continuous averaging data
                avg_val = float(np.mean(self.continuous_sample_buffer[param]))
                self.data[param].append(avg_val)
                row.append(avg_val)
                if self.verbose_checkbox.isChecked():
                    print(f"  Processing {len(self.continuous_sample_buffer[param])} continuous samples for {param}: avg={avg_val:.4f}V")
                # Don't clear the continuous buffer immediately - let it accumulate more data
                # Only clear if it gets too large (more than 100 samples)
                if len(self.continuous_sample_buffer[param]) > 100:
                    self.continuous_sample_buffer[param] = self.continuous_sample_buffer[param][-50:]  # Keep last 50 samples
            else:
                # No data available - try to get latest continuous data or use last known value
                latest_continuous_val = None
                if hasattr(self, 'continuous_sample_buffer') and self.continuous_sample_buffer[param]:
                    latest_continuous_val = float(np.mean(self.continuous_sample_buffer[param]))
                
                if latest_continuous_val is not None:
                    # Use latest continuous data
                    self.data[param].append(latest_continuous_val)
                    row.append(latest_continuous_val)
                    if self.verbose_checkbox.isChecked():
                        print(f"  Using latest continuous data for {param}: {latest_continuous_val:.4f}V")
                elif self.data[param]:
                    # Use the last known value
                    last_val = self.data[param][-1]
                    self.data[param].append(last_val)
                    row.append(last_val)
                    if self.verbose_checkbox.isChecked():
                        print(f"  Using last known value for {param}: {last_val:.4f}V")
                else:
                    # No previous data available, use latest avg_val from last batch if available
                    if hasattr(self, 'avg_val'):
                        self.data[param].append(self.avg_val)
                        row.append(self.avg_val)
                    else:
                        self.data[param].append(0.0)
                        row.append(0.0)
        # Append new time point
        if not self.t:
            self.t.append(0)
        else:
            self.t.append(self.t[-1] + 1)
        # Log the new data point
        self.log_data(self.t[-1], row)
        # Display real-time cycle information
        if self.scanning and self.verbose_checkbox.isChecked():
            elapsed = time.time() - self.measure_start_time if self.measure_start_time else 0
            current_sps = self.adc_read_count / elapsed if elapsed > 0 else 0
            current_cps = self.cycle_detected_count / elapsed if elapsed > 0 else 0
            # Check if any cycles were detected in the last interval
            cycles_in_interval = any(len(buffer) > 0 for buffer in self.sample_buffer.values())
            cycle_status = "âœ“" if cycles_in_interval else "âœ—"
            print(f"Time: {elapsed:.1f}s | SPS: {current_sps:.1f} | CPS: {current_cps:.2f} | "
                  f"Cycles: {self.total_cycles_detected} | Lock: {'âœ“' if self.is_locked else 'âœ—'} | "
                  f"Data: {cycle_status} | Continuous: {self.continuous_wavelength_cycle}")
        
        # Ensure we always have some data to display, even after gain changes
        if self.scanning and all(len(self.data[param]) == 0 for param in PARAMETERS):
            # If no data at all, try to get a fresh reading from ADC
            try:
                if self.adc and hasattr(self.adc, 'read_data'):
                    fresh_data = self.adc.read_data()
                    if fresh_data and len(fresh_data) > 0:
                        # Use the first channel data for all parameters temporarily
                        fresh_voltage = fresh_data[0]
                        for param in PARAMETERS:
                            self.data[param].append(fresh_voltage)
                        if self.verbose_checkbox.isChecked():
                            print(f"  Using fresh ADC reading for all parameters: {fresh_voltage:.4f}V")
            except Exception as e:
                if self.verbose_checkbox.isChecked():
                    print(f"  Error getting fresh ADC reading: {e}")
        
        self.update_graph()

    def calibrate_current_values(self):
        # Capture the current value for each parameter
        for param in PARAMETERS:
            data_show = self.data[param][-self.buffer_size:]
            if data_show:
                self.calibrated_values[param] = data_show[-1]
            else:
                self.calibrated_values[param] = None
        self.update_graph()

    def open_csv_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Open CSV File", "", "CSV Files (*.csv)")
        if not file_path:
            return
        import csv
        with open(file_path, 'r', newline='') as f:
            reader = csv.reader(f)
            header = next(reader)
            # Expect header: Time, 700nm, 800nm, ...
            time_idx = header.index("Time") if "Time" in header else 0
            param_indices = {param: header.index(param) for param in PARAMETERS if param in header}
            t = []
            data = {param: [] for param in PARAMETERS}
            for row in reader:
                try:
                    t.append(float(row[time_idx]))
                    for param in PARAMETERS:
                        if param in param_indices:
                            data[param].append(float(row[param_indices[param]]))
                except Exception:
                    continue
        self.t = t
        self.data = data
        # Do not stop timers; allow new data to be appended and graph to scroll
        self.update_graph()

    def clear_data(self):
        self.t = []
        self.data = {param: [] for param in PARAMETERS}
        self.calibrated_values = {param: None for param in PARAMETERS}
        # Do not stop timers; allow new data to be appended and graph to scroll
        self.update_graph()

    def on_tab_changed(self, idx):
        # 0: NORMAL MODE, 1: ADVANCED MODE
        self.graph_stack.setCurrentIndex(1 if idx == 0 else 0)
        self.update_graph()

    def on_continuous_mode_changed(self, state):
        if not self.continuous_checkbox.isChecked() and self.scanning:
            # If running, schedule a stop after the next update
            QTimer.singleShot(1100, self.stop_scan)

    def restart_pi(self):
        reply = QMessageBox.question(self, 'Restart Raspberry Pi',
                                     'Are you sure you want to restart the Raspberry Pi?',
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            os.system('sudo reboot')

    def shutdown_pi(self):
        reply = QMessageBox.question(self, 'Shutdown Raspberry Pi',
                                     'Are you sure you want to shutdown the Raspberry Pi?',
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            os.system('sudo shutdown now')

    def save_screenshot(self):
        # Get the current timestamp for the default filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"screenshot_{timestamp}.png"

        # Use the log directory as the save location
        log_dir = os.path.dirname(self.text_log_file) if hasattr(self, 'text_log_file') else os.getcwd()
        file_path = os.path.join(log_dir, filename)
        
        # Use QWidget.grab() for a reliable screenshot
        screenshot = self.grab()
        if screenshot.save(file_path):
            QMessageBox.information(self, "Success", f"Screenshot saved successfully!\nLocation: {file_path}")
        else:
            QMessageBox.warning(self, "Error", "Failed to save screenshot!")

    def closeEvent(self, event):
        # Restore original stdout/stderr
        sys.stdout = sys.__stdout__
        sys.stderr = sys.__stderr__

        # Clean up GPIO on exit
        if self.gpio_available and self.power_line:
            try:
                self.power_line.set_value(0)  # Ensure power is off
                self.power_line.release()
                if self.chip:
                    self.chip.close()
                print("GPIO cleanup completed")
            except Exception as e:
                print(f"Error during GPIO cleanup: {e}")

        # Clean up RPi.GPIO (used by ADS131M02 driver)
        try:
            import RPi.GPIO as GPIO
            GPIO.cleanup()
            print("RPi.GPIO cleanup completed")
        except Exception as e:
            print(f"Error during RPi.GPIO cleanup: {e}")

        # Clean up ADC
        if self.adc is not None:
            try:
                if hasattr(self.adc, 'close') and callable(getattr(self.adc, 'close')):
                    self.adc.close()
                elif hasattr(self.adc, 'cleanup') and callable(getattr(self.adc, 'cleanup')):
                    self.adc.cleanup()
            except Exception as e:
                print(f"Error closing ADC: {e}")
        
        event.accept()
        super().closeEvent(event)

    def update_timing_parameters(self):
        """Update timing parameters when sampling rate changes"""
        sampling_period_ms = 1000 / self.samples_per_second  # Convert Hz to ms
        self.samples_per_pulse = int(round(self.PULSE_WIDTH_MS / sampling_period_ms))
        self.samples_per_cycle = int(round(self.CYCLE_PERIOD_MS / sampling_period_ms))
        self.slots_per_cycle = 8  # 6 pulses, 2 empty
        self.samples_per_slot = self.samples_per_cycle // self.slots_per_cycle
        print(f"Samples per pulse: {self.samples_per_pulse}")
        print(f"Samples per cycle: {self.samples_per_cycle}")
        print(f"Samples per slot: {self.samples_per_slot}")

    def update_status_display(self, in_timeout):
        """Update the status label visibility based on timeout state"""
        if in_timeout:
            self.status_label.show()
            if self.is_timing_adjusted:
                print("Timeout occurred. Reverting to user-defined frequency.")
                self.is_timing_adjusted = False
                self.update_sampling_rate(self.sampling_slider.value()) # Revert timer
            self.is_locked = False # Lose lock on timeout
            self.consecutive_cycles = 0
            # Removed lock_label.hide() since we don't have the lock label anymore
        else:
            # Check if we have recent cycle detections
            if len(self.cycle_timestamps) > 0:
                time_since_last_cycle = time.time() - self.cycle_timestamps[-1]
                if time_since_last_cycle > 1.0:  # No cycles detected in last second
                    #self.status_label.setText(f"NO RECENT CYCLES ({time_since_last_cycle:.1f}s)")
                    #self.status_label.setStyleSheet("QLabel { color: orange; font-weight: bold; font-size: 18px; }")
                    #self.status_label.show()
                    pass
                else:
                    self.status_label.hide()
            else:
                self.status_label.setText("NO CYCLES DETECTED")
                self.status_label.setStyleSheet("QLabel { color: red; font-weight: bold; font-size: 18px; }")
                self.status_label.show()

    def print_cycle_detection_stats(self):
        """Print cycle detection statistics"""
        if not self.scanning:
            return
            
        print("\n" + "="*50)
        print("        CYCLE DETECTION STATISTICS")
        print("="*50)
        
        # Overall detection rate
        if self.measure_start_time:
            elapsed = time.time() - self.measure_start_time
            if elapsed > 0:
                detection_rate = self.total_cycles_detected / elapsed
                print(f"  Detection Rate:         {detection_rate:.2f} cycles/sec")
        
        # Recent detection status
        if len(self.cycle_timestamps) > 0:
            time_since_last = time.time() - self.cycle_timestamps[-1]
            print(f"  Time Since Last Cycle:  {time_since_last:.2f} seconds")
            
            # Last 10 cycles timing
            if len(self.cycle_timestamps) >= 10:
                recent_times = self.cycle_timestamps[-10:]
                recent_intervals = [recent_times[i] - recent_times[i-1] for i in range(1, len(recent_times))]
                avg_recent_interval = np.mean(recent_intervals)
                print(f"  Avg Recent Interval:    {avg_recent_interval:.3f} seconds")
        
        # Detection quality
        if len(self.cycle_qualities) > 0:
            recent_quality = np.mean(self.cycle_qualities[-10:]) if len(self.cycle_qualities) >= 10 else np.mean(self.cycle_qualities)
            print(f"  Recent Quality:         {recent_quality:.3f}")
        
        # Lock status
        print(f"  Pattern Lock:           {'LOCKED' if self.is_locked else 'UNLOCKED'}")
        print(f"  Consecutive Cycles:     {self.consecutive_cycles}")
        
        print("="*50)

    def on_new_console_text(self, text):
        cursor = self.console_output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text)
        self.console_output.setTextCursor(cursor)
        self.console_output.ensureCursorVisible()

    def switch_to_engineering_mode(self):
        """
        Prompts for a password before switching to Engineering Mode.
        Uses a custom number keypad dialog. Password is '1234'.
        """
        dlg = NumberKeypadDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            password = dlg.get_password()
            if password == "1234":
                self.set_operation_mode('engineering')
            else:
                QMessageBox.warning(self, "Access Denied", "Incorrect password.")
    
    def set_operation_mode(self, mode):
        """
        Switches the UI between 'field' and 'engineering' modes.
        """
        if mode == 'field':
            # Field Operation Mode: Show limited controls
            self.sampling_widget.setVisible(False)
            self.datapoints_widget.setVisible(False)
            self.show_all_checkbox.setVisible(False)
            self.verbose_checkbox.setVisible(False)
            self.tabs.setTabVisible(1, False)  # Hide ADVANCED tab
            self.tabs.setTabVisible(2, False)  # Hide CONSOLE tab
            
            # Make checkboxes larger for field use
            field_mode_stylesheet = "QCheckBox::indicator { width: 25px; height: 25px; } QCheckBox { font-size: 16px; }"
            self.show_db_checkbox.setStyleSheet(field_mode_stylesheet)
            self.continuous_checkbox.setStyleSheet(field_mode_stylesheet)
            
            # Make buttons taller for field use
            self.scan_btn.setFixedHeight(80)
            self.calibrate_btn.setFixedHeight(80)
            self.clear_btn.setFixedHeight(80)
            self.settings_btn.setFixedHeight(80)
            
            # Hide Open CSV File option in field mode
            self.open_btn.setVisible(False)

            # Update menu item visibility
            self.engineering_mode_btn.setVisible(True)
            self.field_mode_btn.setVisible(False)
            
        elif mode == 'engineering':
            # Engineering Mode: Show all controls
            self.sampling_widget.setVisible(True)
            self.datapoints_widget.setVisible(True)
            self.show_all_checkbox.setVisible(True)
            self.verbose_checkbox.setVisible(True)
            self.tabs.setTabVisible(1, True)   # Show ADVANCED tab
            self.tabs.setTabVisible(2, True)   # Show CONSOLE tab

            # Reset checkbox size to default
            self.show_db_checkbox.setStyleSheet("")
            self.continuous_checkbox.setStyleSheet("")
            
            # Reset button height to default
            self.scan_btn.setFixedHeight(44)
            self.calibrate_btn.setFixedHeight(44)
            self.clear_btn.setFixedHeight(44)
            self.settings_btn.setFixedHeight(44)
            
            # Show Open CSV File option in engineering mode
            self.open_btn.setVisible(True)

            # Update menu item visibility
            self.engineering_mode_btn.setVisible(False)
            self.field_mode_btn.setVisible(True)
        # Always update/repaint the overlay to ensure menu items are refreshed
        self.settings_overlay.update()
        self.settings_overlay.repaint()

    def toggle_settings_overlay(self):
        if self.settings_overlay.isVisible():
            self.settings_overlay.hide()
        else:
            # Position overlay at the top right of the main window, just below the top edge
            parent_geom = self.geometry()
            overlay_width = self.settings_overlay.width()
            x = parent_geom.x() + parent_geom.width() - overlay_width - 100  # Move 30px further left
            y = parent_geom.y() + 20  # 20px from the top
            self.settings_overlay.move(x, y)
            self.settings_overlay.show()

    def calibrate_adc_voltage(self):
        """Calibrate ADC voltage readings to correct scaling"""
        if self.adc is None or self.adc_type != 'ADS131M02':
            return
            
        print("Starting ADC voltage calibration...")
        
        # Read a few samples to understand the current voltage range
        calibration_samples = []
        for i in range(100):
            try:
                if self.adc_type == 'ADS131M02':
                    voltages = self.adc.read_data()
                    voltage = voltages[0] if voltages and len(voltages) > 0 else 0.0
                else:
                    voltage = self.adc.read_voltage(0)
                calibration_samples.append(voltage)
                time.sleep(0.001)  # 1ms delay
            except Exception as e:
                print(f"Error during calibration sample {i}: {e}")
                break
        
        if calibration_samples:
            min_voltage = min(calibration_samples)
            max_voltage = max(calibration_samples)
            mean_voltage = np.mean(calibration_samples)
            std_voltage = np.std(calibration_samples)
            
            print(f"Calibration results:")
            print(f"  Min voltage: {min_voltage:.6f} V")
            print(f"  Max voltage: {max_voltage:.6f} V")
            print(f"  Mean voltage: {mean_voltage:.6f} V")
            print(f"  Std voltage: {std_voltage:.6f} V")
            print(f"  Voltage range: {max_voltage - min_voltage:.6f} V")
            
            # If the voltage range is much smaller than expected (should be around Â±1.2V)
            # we might need to adjust the scaling
            expected_range = 2.4  # Â±1.2V = 2.4V total range
            actual_range = max_voltage - min_voltage
            
            if actual_range > 0 and actual_range < expected_range * 0.5:
                # Voltage range is too small, might need scaling adjustment
                print(f"  Warning: Voltage range ({actual_range:.3f}V) is much smaller than expected ({expected_range:.1f}V)")
                print(f"  This suggests the input signal amplitude is lower than expected")
                
                # Calculate a scaling factor if needed
                if hasattr(self.adc, 'voltage_scaling_factor'):
                    # If the ADC driver supports voltage scaling, we could adjust it here
                    pass
                else:
                    print(f"  Consider checking the input signal amplitude and ADC gain settings")
            
            # Store calibration info for reference
            self.voltage_calibration = {
                'min': min_voltage,
                'max': max_voltage,
                'mean': mean_voltage,
                'std': std_voltage,
                'range': actual_range,
                'expected_range': expected_range
            }
        else:
            print("No calibration samples collected")
            self.voltage_calibration = None

    def apply_voltage_scaling(self, voltage):
        """Apply voltage scaling correction if calibration data is available"""
        if hasattr(self, 'voltage_calibration') and self.voltage_calibration:
            # If the voltage range is much smaller than expected, we might need scaling
            expected_range = self.voltage_calibration['expected_range']
            actual_range = self.voltage_calibration['range']
            
            if actual_range > 0 and actual_range < expected_range * 0.5:
                # Apply scaling factor to bring readings closer to expected range
                # This is a simple linear scaling - in practice, you might need more sophisticated calibration
                scaling_factor = expected_range / actual_range
                return voltage * scaling_factor
        
        return voltage

    def get_dynamic_averaging_window(self):
        """Calculate dynamic averaging window based on recent cycle detection rate"""
        current_time = time.time()
        
        # Count cycles in the last second
        if len(self.cycle_timestamps) > 0:
            recent_cycles = [ts for ts in self.cycle_timestamps if current_time - ts <= 1.0]
            cycles_in_last_second = len(recent_cycles)
        else:
            cycles_in_last_second = 0
        
        # Update the tracking variables
        self.cycles_in_last_second = cycles_in_last_second
        self.last_cycle_count_time = current_time
        
        # Calculate dynamic window: use cycles from last second, but with reasonable bounds
        if cycles_in_last_second > 0:
            # Each cycle has 6 pulses, so multiply by 6 to get total pulses
            dynamic_window = cycles_in_last_second * 6
            # Apply reasonable bounds: minimum 3 pulses, maximum 30 pulses
            dynamic_window = max(3, min(30, dynamic_window))
        else:
            # Fallback to default if no recent cycles
            dynamic_window = 10
        
        return dynamic_window

    def show_no_pattern_detected(self):
        # This method is called when the no_pattern_timer times out
        self.status_label.setText("NO PATTERN DETECTED")
        self.status_label.setStyleSheet("QLabel { color: red; font-weight: bold; font-size: 18px; }")
        self.status_label.show()
        self.pattern_detection_active = False

    def auto_adjust_gain(self, channel=0, voltage_batch=None, threshold_low=0.1, threshold_high=1.0):
        """
        Automatically adjust gain for the specified channel (CH0 only).
        - Increase gain if any voltage in batch is below threshold_low (default 0.1V) and max voltage <= threshold_high.
        - Decrease gain if any voltage is above threshold_high.
        - Gain steps: 1x, 2x, 4x, 8x.
        """
        if self.adc_type != 'ADS131M02' or channel != 0:
            return
        
        current_gain = self.adc.channel_gains[channel]
        verbose = getattr(self, 'verbose_checkbox', None)
        is_verbose = verbose.isChecked() if verbose else False
        if is_verbose:
            print(f"Auto-gain: Starting adjustment for CH{channel}, current gain: {current_gain}x")
        gain_steps = [self.adc.GAIN_1, self.adc.GAIN_2, self.adc.GAIN_4, self.adc.GAIN_8]
        gain_values = [1, 2, 4, 8]
        current_gain_idx = 0
        for i, gain_val in enumerate(gain_values):
            if current_gain == gain_val:
                current_gain_idx = i
                break
        if voltage_batch:
            min_voltage = min(abs(v) for v in voltage_batch)
            max_voltage = max(abs(v) for v in voltage_batch)
            if is_verbose:
                print(f"Auto-gain: Min voltage in batch: {min_voltage:.4f}V, Max voltage in batch: {max_voltage:.4f}V")
            # If any voltage is above threshold_high, decrease gain (down to 1x)
            if any(abs(v) > threshold_high for v in voltage_batch):
                if is_verbose:
                    print(f"Auto-gain: At least one voltage above {threshold_high}V, decreasing gain...")
                if current_gain_idx > 0:
                    prev_gain = gain_steps[current_gain_idx - 1]
                    try:
                        self.adc.set_gain(channel, prev_gain)
                        time.sleep(0.01)
                        if is_verbose:
                            print(f"Auto-gain: Decreased gain from {gain_values[current_gain_idx]}x to {gain_values[current_gain_idx-1]}x")
                            print("Auto-gain: Cleared continuous sample buffer for fresh data")
                        else:
                            print(f"Auto-gain: Gain changed to {gain_values[current_gain_idx-1]}x (decreased)")
                        self.continuous_sample_buffer = {param: [] for param in PARAMETERS}
                    except Exception as e:
                        if is_verbose:
                            print(f"Auto-gain: Error setting gain: {e}")
                else:
                    if is_verbose:
                        print(f"Auto-gain: Already at minimum gain {gain_values[current_gain_idx]}x")
            # If any voltage is below threshold_low and max voltage <= threshold_high, increase gain (up to 8x)
            elif any(abs(v) < threshold_low for v in voltage_batch) and max_voltage <= threshold_high:
                if is_verbose:
                    print(f"Auto-gain: At least one voltage below {threshold_low}V and max <= {threshold_high}V, increasing gain...")
                if current_gain_idx < len(gain_steps) - 1:
                    next_gain = gain_steps[current_gain_idx + 1]
                    try:
                        self.adc.set_gain(channel, next_gain)
                        time.sleep(0.01)
                        if is_verbose:
                            print(f"Auto-gain: Increased gain from {gain_values[current_gain_idx]}x to {gain_values[current_gain_idx+1]}x")
                            print("Auto-gain: Cleared continuous sample buffer for fresh data")
                        else:
                            print(f"Auto-gain: Gain changed to {gain_values[current_gain_idx+1]}x (increased)")
                        self.continuous_sample_buffer = {param: [] for param in PARAMETERS}
                    except Exception as e:
                        if is_verbose:
                            print(f"Auto-gain: Error setting gain: {e}")
                else:
                    if is_verbose:
                        print(f"Auto-gain: Already at maximum gain {gain_values[current_gain_idx]}x")
            else:
                if is_verbose:
                    print(f"Auto-gain: Voltages in acceptable range, no adjustment needed")
        final_gain = self.adc.channel_gains[channel]
        if is_verbose:
            print(f"Auto-gain: Final gain setting for CH{channel}: {final_gain}x")
        if final_gain != current_gain:
            if not is_verbose:
                print(f"Auto-gain: Gain changed from {current_gain}x to {final_gain}x")
        else:
            if is_verbose:
                print(f"Auto-gain: No gain change needed, keeping {current_gain}x")

def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.showMaximized()
    sys.exit(app.exec())

if __name__ == "__main__":
    main() 
