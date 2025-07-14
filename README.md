# PulseSeer

A PyQt6-based application for real-time visualization and analysis of multi-wavelength IR sensor data, designed for field engineering and laboratory use here at Hayden AI.

## 🚀 Features

### Core Functionality
- **Real-time Data Visualization**: Live plotting of sensor data with both bar and line graph modes
- **Multi-wavelength Support**: Simultaneous monitoring of 6 IR wavelengths (700nm, 800nm, 850nm, 900nm, 970nm, 1050nm)
- **Pattern Detection**: Advanced algorithm for detecting pulse patterns and synchronizing data streams
- **Automatic Gain Adjustment**: Intelligent ADC gain control for optimal signal quality
- **Dual Operation Modes**: Field Engineering and Engineering modes with different UI complexity

### Hardware Integration
- **ADC Support**: Compatible with 24-bits ADS131M02 (preferred) and 12-bits ADS7142 (fallback). Custom Pi HAT also supports MCP3565 24-bits ADC with Programmable gain from 0.33x to 64x
- **GPIO Control**: Automatic IR sensor power management via GPIO pins
- **LTC6903 Integration**: Frequency generation for precise timing
- **Raspberry Pi 5 Optimized**: Designed for Raspberry Pi 5 hardware

### Data Management
- **Automatic Logging**: CSV and text file logging with timestamps
- **Screenshot Capture**: One-click screenshot saving to log directory
- **Calibration System**: Built-in calibration for reference measurements
- **Data Export**: CSV file import/export capabilities

## 📋 Requirements

### Hardware
- Raspberry Pi 5 (recommended)
- Custom Pi Hat with ADS131M02 or ADS7142 ADC
- Multi-wavelength IR LED source

### Software Dependencies
```bash
pip install -r requirements.txt
```

**Key Dependencies:**
- PyQt6
- pyqtgraph
- numpy
- gpiod
- spidev
- RPi.GPIO

## 🛠️ Installation

1. **Clone the repository:**
```bash
git clone https://github.com/yourusername/pulseseer.git
cd pulseseer
```

2. **Install dependencies:**
```bash
pip install -r requirements.txt
```

3. **Configure hardware:**
   - Connect ADC to SPI bus
   - Configure GPIO pins for power control
   - Ensure IR LEDs are properly connected

4. **Run the application:**
```bash
python PulseSeer.py
```

## 🎯 Usage

### Startup
1. **Safety Warning**: The application starts with a safety splash screen
   - Verify IR LEDs are ON before proceeding
   - Click "YES - IR LEDs are ON" to continue
   - Click "NO - Exit Application" to close

### Operation Modes

#### Field Engineering Mode
- **Simplified Interface**: Large buttons and essential controls only
- **Large Text**: 16px fonts for better field visibility
- **Tall Buttons**: 80px height for easy touch operation
- **Hidden Advanced Features**: Console and advanced tabs hidden

#### Engineering Mode
- **Full Interface**: All controls and debugging features
- **Standard Sizing**: Normal button and text sizes
- **Advanced Features**: Console output and detailed statistics
- **CSV Import**: File import capabilities

### Main Controls

#### Buttons
- **MEASURE**: Start/stop data acquisition
- **CALIBRATE**: Set current values as calibration reference
- **CLEAR**: Clear all displayed data
- **SETTINGS** (⚙): Access additional options

#### Settings Menu
- **Open CSV File**: Import historical data (Engineering mode only)
- **Save Screenshot**: Capture current display
- **Show Desktop**: Minimize application
- **Engineering Mode**: Switch to full interface
- **Field Engineering Mode**: Switch to simplified interface
- **Restart**: Reboot Raspberry Pi
- **Shutdown**: Power down Raspberry Pi
- **Exit**: Close application

### Data Display

#### NORMAL MODE
- **Bar Graph**: Current values for all wavelengths
- **Real-time Updates**: Live data visualization
- **Calibration Comparison**: Current vs calibrated values
- **Ratio Display**: Current/Calibrated ratios with color coding

#### ADVANCED MODE
- **Time Series Plot**: Historical data trends
- **Multi-parameter Display**: All wavelengths on same graph
- **Statistical Information**: Min, max, current, calibrated values
- **Quality Metrics**: Pattern detection statistics

#### CONSOLE
- **Real-time Logging**: Live diagnostic information
- **Performance Metrics**: Samples per second, cycles per second
- **Pattern Detection**: Cycle statistics and quality scores
- **Error Reporting**: Hardware and software error messages

## 🔧 Configuration

### Sampling Settings
- **Batch Timer Frequency**: 1-50 Hz (default: 45 Hz)
- **Data Points**: 30-600 points (default: 300)
- **Continuous Mode**: Automatic data collection

### Display Options
- **Show in dB**: Toggle between voltage and dB display
- **Show All**: Display all historical data vs recent data
- **Verbose**: Enable detailed logging

### Hardware Configuration
```python
# GPIO Configuration
POWER_PIN = 19  # Power control pin
CS2_PIN = 20    # LTC6903 chip select

# ADC Configuration
SPI_BUS = 0
SPI_DEVICE = 0
CS_PIN = 21     # ADC chip select
DRDY_PIN = 16   # Data ready pin
RESET_PIN = 12  # Reset pin
```

## 📊 Data Format

### Log Files
Logs are automatically saved to date-stamped directories:
```
YYYY-MM-DD/
├── data_log_YYYYMMDD_HHMMSS.txt
├── data_log_YYYYMMDD_HHMMSS.csv
└── screenshot_YYYYMMDD_HHMMSS.png
```

### CSV Structure
```csv
Time,Current_Time,700nm,800nm,850nm,900nm,970nm,1050nm,Calibrated_700nm,Calibrated_800nm,Calibrated_850nm,Calibrated_900nm,Calibrated_970nm,Calibrated_1050nm,CH0_Gain,CH1_Gain
```

## 🔍 Pattern Detection

### Algorithm Features
- **6-Pulse Pattern Recognition**: Detects repeating 6-pulse cycles
- **Wavelength Assignment**: Automatically assigns pulses to correct wavelengths
- **Quality Scoring**: Correlation and timing quality metrics
- **Adaptive Thresholds**: Dynamic voltage threshold adjustment

### Cycle Statistics
- **Detection Rate**: Cycles per second
- **Pattern Quality**: 0-1 quality score
- **Timing Accuracy**: Pulse width and spacing analysis
- **Voltage Statistics**: Mean, std, min, max pulse voltages

## 🚨 Safety Features

### Startup Warning
- **IR LED Verification**: Ensures IR LEDs are powered before measurements
- **Safety Dialog**: Modal dialog requiring user confirmation
- **Clear Instructions**: Detailed safety guidelines

### Hardware Protection
- **Automatic Power Management**: GPIO-controlled power cycling
- **Gain Protection**: Prevents ADC saturation
- **Error Handling**: Graceful hardware failure recovery

## 🐛 Troubleshooting

### Common Issues

#### No Data Display
1. Check ADC connections
2. Verify GPIO permissions
3. Ensure IR LEDs are powered
4. Check console for error messages

#### Pattern Not Detected
1. Verify IR LED illumination
2. Check signal amplitude
3. Adjust sampling frequency in Engineering Mode
4. Enable verbose logging for diagnostics

#### Application Won't Start
1. Verify Python dependencies
2. Check hardware connections
3. Ensure proper permissions for GPIO access

### Debug Mode
Enable verbose logging for detailed diagnostics:
1. Switch to Engineering Mode
2. Check "Verbose" checkbox
3. Monitor console output

## 📈 Performance

### Typical Performance Metrics
- **Sampling Rate**: 45 Hz (configurable)
- **Pattern Detection**: 256 Hz expected frequency
- **Memory Usage**: ~50MB typical
- **CPU Usage**: <10% on Raspberry Pi 5

### Optimization Tips
- Use Field Engineering Mode for better performance
- Disable verbose logging in production
- Regular system reboots for optimal performance


## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

**PulseSeer** - Advanced IR sensor data visualization and analysis platform for field engineering applications. 
