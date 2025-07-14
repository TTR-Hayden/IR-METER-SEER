"""
ADS7142 Python Driver
Based on MikroElektronika click board implementation
Compatible with Raspberry Pi and other Linux systems with I2C support

The ADS7142 is a 12-bit, 1MSPS, 8-channel ADC with I2C interface.
This driver provides full functionality for configuration and data acquisition.
"""

import time
import struct
from typing import Optional, List, Tuple, Dict, Any
import logging

try:
    import smbus2 as smbus
    SMBUS_AVAILABLE = True
except ImportError:
    try:
        import smbus
        SMBUS_AVAILABLE = True
    except ImportError:
        SMBUS_AVAILABLE = False
        print("Warning: smbus not available. Install smbus2 or smbus for I2C support.")

# ADS7142 Register Addresses
class ADS7142Registers:
    # Configuration registers
    GENERAL_CFG = 0x00
    DATA_CFG = 0x01
    OSR_CFG = 0x02
    OPMODE_CFG = 0x03
    PIN_CFG = 0x04
    GPIO_CFG = 0x05
    
    # Status registers
    STATUS = 0x06
    STATUS_MASK = 0x07
    
    # Data registers
    DATA_CH0 = 0x08
    DATA_CH1 = 0x09
    DATA_CH2 = 0x0A
    DATA_CH3 = 0x0B
    DATA_CH4 = 0x0C
    DATA_CH5 = 0x0D
    DATA_CH6 = 0x0E
    DATA_CH7 = 0x0F
    
    # FIFO registers
    FIFO_CFG = 0x10
    FIFO_COUNT = 0x11
    FIFO_DATA = 0x12
    
    # Threshold registers
    THRESHOLD_CH0 = 0x20
    THRESHOLD_CH1 = 0x21
    THRESHOLD_CH2 = 0x22
    THRESHOLD_CH3 = 0x23
    THRESHOLD_CH4 = 0x24
    THRESHOLD_CH5 = 0x25
    THRESHOLD_CH6 = 0x26
    THRESHOLD_CH7 = 0x27
    
    # Interrupt registers
    INT_CFG = 0x30
    INT_MASK = 0x31
    
    # Device identification
    DEVICE_ID = 0x40
    REVISION_ID = 0x41

# ADS7142 Configuration Values
class ADS7142Config:
    # Operating modes
    MODE_STANDBY = 0x00
    MODE_SINGLE_SHOT = 0x01
    MODE_CONTINUOUS = 0x02
    MODE_BURST = 0x03
    
    # Input ranges
    RANGE_0_TO_2_5V = 0x00
    RANGE_0_TO_5V = 0x01
    RANGE_0_TO_10V = 0x02
    RANGE_PM_2_5V = 0x03
    RANGE_PM_5V = 0x04
    RANGE_PM_10V = 0x05
    
    # Oversampling ratios
    OSR_1 = 0x00
    OSR_2 = 0x01
    OSR_4 = 0x02
    OSR_8 = 0x03
    OSR_16 = 0x04
    OSR_32 = 0x05
    OSR_64 = 0x06
    OSR_128 = 0x07
    
    # Channel configurations
    CHANNEL_DISABLED = 0x00
    CHANNEL_ENABLED = 0x01
    CHANNEL_DIFFERENTIAL = 0x02

class ADS7142Error(Exception):
    """Custom exception for ADS7142 driver errors"""
    pass

class ADS7142:
    """
    Python driver for the ADS7142 12-bit, 1MSPS, 8-channel ADC
    
    Features:
    - 12-bit resolution
    - Up to 1 MSPS sampling rate
    - 8 single-ended or 4 differential channels
    - I2C interface
    - Configurable input ranges
    - Oversampling support
    - FIFO buffer
    - Interrupt support
    """
    
    def __init__(self, 
                 i2c_bus: int = 1, 
                 i2c_address: int = 0x12,
                 voltage_reference: float = 2.5,
                 debug: bool = False):
        """
        Initialize the ADS7142 driver
        
        Args:
            i2c_bus: I2C bus number (default: 1 for Raspberry Pi)
            i2c_address: I2C address of the ADS7142 (default: 0x12)
            voltage_reference: Reference voltage in volts (default: 2.5V)
            debug: Enable debug logging
        """
        self.i2c_bus = i2c_bus
        self.i2c_address = i2c_address
        self.voltage_reference = voltage_reference
        self.debug = debug
        
        # Setup logging
        if debug:
            logging.basicConfig(level=logging.DEBUG)
        self.logger = logging.getLogger(__name__)
        
        # Initialize I2C bus
        if not SMBUS_AVAILABLE:
            raise ADS7142Error("SMBus not available. Install smbus2 or smbus.")
        
        try:
            self.bus = smbus.SMBus(i2c_bus)
            self.logger.info(f"Initialized I2C bus {i2c_bus}")
        except Exception as e:
            raise ADS7142Error(f"Failed to initialize I2C bus {i2c_bus}: {e}")
        
        # Device configuration
        self.sampling_rate = 1000000  # 1 MSPS default
        self.active_channels = []
        self.input_range = ADS7142Config.RANGE_0_TO_2_5V
        self.oversampling_ratio = ADS7142Config.OSR_1
        self.operating_mode = ADS7142Config.MODE_STANDBY
        
        # Initialize device
        self._init_device()
    
    def _init_device(self):
        """Initialize the ADS7142 device"""
        try:
            # Check device ID
            device_id = self.read_register(ADS7142Registers.DEVICE_ID)
            revision_id = self.read_register(ADS7142Registers.REVISION_ID)
            
            self.logger.info(f"Device ID: 0x{device_id:02X}, Revision: 0x{revision_id:02X}")
            
            if device_id != 0x42:  # Expected device ID for ADS7142
                self.logger.warning(f"Unexpected device ID: 0x{device_id:02X}")
            
            # Reset device to known state
            self.reset()
            
            # Configure default settings
            self._configure_defaults()
            
            self.logger.info("ADS7142 initialized successfully")
            
        except Exception as e:
            raise ADS7142Error(f"Failed to initialize ADS7142: {e}")
    
    def _configure_defaults(self):
        """Configure default device settings"""
        # General configuration
        general_cfg = 0x00  # Default settings
        self.write_register(ADS7142Registers.GENERAL_CFG, general_cfg)
        
        # Data configuration
        data_cfg = (self.input_range << 4) | 0x00  # Input range + default settings
        self.write_register(ADS7142Registers.DATA_CFG, data_cfg)
        
        # Oversampling configuration
        osr_cfg = self.oversampling_ratio
        self.write_register(ADS7142Registers.OSR_CFG, osr_cfg)
        
        # Operating mode
        self.write_register(ADS7142Registers.OPMODE_CFG, self.operating_mode)
        
        # Pin configuration (all pins as analog inputs)
        pin_cfg = 0x00
        self.write_register(ADS7142Registers.PIN_CFG, pin_cfg)
        
        # GPIO configuration
        gpio_cfg = 0x00
        self.write_register(ADS7142Registers.GPIO_CFG, gpio_cfg)
        
        # FIFO configuration
        fifo_cfg = 0x00  # Disable FIFO by default
        self.write_register(ADS7142Registers.FIFO_CFG, fifo_cfg)
        
        # Interrupt configuration
        int_cfg = 0x00  # Disable interrupts by default
        self.write_register(ADS7142Registers.INT_CFG, int_cfg)
        self.write_register(ADS7142Registers.INT_MASK, 0xFF)  # Mask all interrupts
    
    def reset(self):
        """Reset the ADS7142 device"""
        try:
            # Write to a reserved register to trigger reset
            self.write_register(0x7F, 0x00)
            time.sleep(0.01)  # Wait for reset to complete
            self.logger.debug("Device reset completed")
        except Exception as e:
            self.logger.warning(f"Reset failed: {e}")
    
    def write_register(self, register: int, value: int):
        """
        Write a value to a register
        
        Args:
            register: Register address
            value: Value to write
        """
        try:
            self.bus.write_byte_data(self.i2c_address, register, value)
            if self.debug:
                self.logger.debug(f"Write register 0x{register:02X} = 0x{value:02X}")
        except Exception as e:
            raise ADS7142Error(f"Failed to write register 0x{register:02X}: {e}")
    
    def read_register(self, register: int) -> int:
        """
        Read a value from a register
        
        Args:
            register: Register address
            
        Returns:
            Register value
        """
        try:
            value = self.bus.read_byte_data(self.i2c_address, register)
            if self.debug:
                self.logger.debug(f"Read register 0x{register:02X} = 0x{value:02X}")
            return value
        except Exception as e:
            raise ADS7142Error(f"Failed to read register 0x{register:02X}: {e}")
    
    def read_registers(self, start_register: int, count: int) -> List[int]:
        """
        Read multiple consecutive registers
        
        Args:
            start_register: Starting register address
            count: Number of registers to read
            
        Returns:
            List of register values
        """
        try:
            values = self.bus.read_i2c_block_data(self.i2c_address, start_register, count)
            if self.debug:
                self.logger.debug(f"Read registers 0x{start_register:02X}-0x{start_register+count-1:02X}: {[f'0x{v:02X}' for v in values]}")
            return values
        except Exception as e:
            raise ADS7142Error(f"Failed to read registers starting at 0x{start_register:02X}: {e}")
    
    def configure_channel(self, channel: int, enabled: bool = True, differential: bool = False):
        """
        Configure a channel
        
        Args:
            channel: Channel number (0-7)
            enabled: Enable the channel
            differential: Use differential mode (only for channels 0-3)
        """
        if not 0 <= channel <= 7:
            raise ADS7142Error(f"Invalid channel number: {channel}")
        
        if differential and channel > 3:
            raise ADS7142Error("Differential mode only available for channels 0-3")
        
        # Update pin configuration
        pin_cfg = self.read_register(ADS7142Registers.PIN_CFG)
        
        if enabled:
            if differential:
                pin_cfg |= (1 << channel)
            else:
                pin_cfg &= ~(1 << channel)
        else:
            pin_cfg |= (1 << channel)  # Disable by setting to differential mode
            
        self.write_register(ADS7142Registers.PIN_CFG, pin_cfg)
        
        # Update active channels list
        if enabled and channel not in self.active_channels:
            self.active_channels.append(channel)
        elif not enabled and channel in self.active_channels:
            self.active_channels.remove(channel)
        
        self.logger.info(f"Channel {channel} configured: enabled={enabled}, differential={differential}")
    
    def set_input_range(self, input_range: int):
        """
        Set the input voltage range
        
        Args:
            input_range: Input range from ADS7142Config.RANGE_*
        """
        self.input_range = input_range
        data_cfg = self.read_register(ADS7142Registers.DATA_CFG)
        data_cfg = (data_cfg & 0x0F) | (input_range << 4)
        self.write_register(ADS7142Registers.DATA_CFG, data_cfg)
        self.logger.info(f"Input range set to: {input_range}")
    
    def set_oversampling_ratio(self, osr: int):
        """
        Set the oversampling ratio
        
        Args:
            osr: Oversampling ratio from ADS7142Config.OSR_*
        """
        self.oversampling_ratio = osr
        self.write_register(ADS7142Registers.OSR_CFG, osr)
        self.logger.info(f"Oversampling ratio set to: {osr}")
    
    def set_operating_mode(self, mode: int):
        """
        Set the operating mode
        
        Args:
            mode: Operating mode from ADS7142Config.MODE_*
        """
        self.operating_mode = mode
        self.write_register(ADS7142Registers.OPMODE_CFG, mode)
        self.logger.info(f"Operating mode set to: {mode}")
    
    def read_channel(self, channel: int) -> float:
        """
        Read a single channel and convert to voltage
        
        Args:
            channel: Channel number (0-7)
            
        Returns:
            Voltage in volts
        """
        if not 0 <= channel <= 7:
            raise ADS7142Error(f"Invalid channel number: {channel}")
        
        # Read the data register for the channel
        data_register = ADS7142Registers.DATA_CH0 + channel
        raw_data = self.read_registers(data_register, 2)
        
        # Convert to 12-bit value
        raw_value = (raw_data[0] << 4) | (raw_data[1] >> 4)
        
        # Convert to voltage based on input range
        voltage = self._raw_to_voltage(raw_value)
        
        if self.debug:
            self.logger.debug(f"Channel {channel}: raw=0x{raw_value:03X}, voltage={voltage:.6f}V")
        
        return voltage
    
    def read_all_channels(self) -> Dict[int, float]:
        """
        Read all active channels
        
        Returns:
            Dictionary mapping channel numbers to voltages
        """
        results = {}
        
        for channel in self.active_channels:
            try:
                voltage = self.read_channel(channel)
                results[channel] = voltage
            except Exception as e:
                self.logger.error(f"Failed to read channel {channel}: {e}")
                results[channel] = float('nan')
        
        return results
    
    def read_single_shot(self, channels: Optional[List[int]] = None) -> Dict[int, float]:
        """
        Perform a single-shot conversion on specified channels
        
        Args:
            channels: List of channels to read (None for all active channels)
            
        Returns:
            Dictionary mapping channel numbers to voltages
        """
        if channels is None:
            channels = self.active_channels.copy()
        
        # Configure channels
        for ch in range(8):
            self.configure_channel(ch, ch in channels)
        
        # Set to single-shot mode
        self.set_operating_mode(ADS7142Config.MODE_SINGLE_SHOT)
        
        # Wait for conversion to complete
        time.sleep(0.001)  # 1ms should be sufficient
        
        # Read results
        results = {}
        for channel in channels:
            try:
                voltage = self.read_channel(channel)
                results[channel] = voltage
            except Exception as e:
                self.logger.error(f"Failed to read channel {channel}: {e}")
                results[channel] = float('nan')
        
        return results
    
    def start_continuous_conversion(self, channels: Optional[List[int]] = None):
        """
        Start continuous conversion mode
        
        Args:
            channels: List of channels to convert (None for all active channels)
        """
        if channels is None:
            channels = self.active_channels.copy()
        
        # Configure channels
        for ch in range(8):
            self.configure_channel(ch, ch in channels)
        
        # Set to continuous mode
        self.set_operating_mode(ADS7142Config.MODE_CONTINUOUS)
        
        self.logger.info(f"Started continuous conversion on channels: {channels}")
    
    def stop_conversion(self):
        """Stop conversion and return to standby mode"""
        self.set_operating_mode(ADS7142Config.MODE_STANDBY)
        self.logger.info("Stopped conversion")
    
    def _raw_to_voltage(self, raw_value: int) -> float:
        """
        Convert raw ADC value to voltage
        
        Args:
            raw_value: Raw 12-bit ADC value
            
        Returns:
            Voltage in volts
        """
        # Convert 12-bit value to voltage based on input range
        if self.input_range == ADS7142Config.RANGE_0_TO_2_5V:
            return (raw_value / 4095.0) * 2.5
        elif self.input_range == ADS7142Config.RANGE_0_TO_5V:
            return (raw_value / 4095.0) * 5.0
        elif self.input_range == ADS7142Config.RANGE_0_TO_10V:
            return (raw_value / 4095.0) * 10.0
        elif self.input_range == ADS7142Config.RANGE_PM_2_5V:
            return ((raw_value / 4095.0) - 0.5) * 5.0
        elif self.input_range == ADS7142Config.RANGE_PM_5V:
            return ((raw_value / 4095.0) - 0.5) * 10.0
        elif self.input_range == ADS7142Config.RANGE_PM_10V:
            return ((raw_value / 4095.0) - 0.5) * 20.0
        else:
            return (raw_value / 4095.0) * self.voltage_reference
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get device status
        
        Returns:
            Dictionary containing status information
        """
        status = self.read_register(ADS7142Registers.STATUS)
        
        return {
            'conversion_ready': bool(status & 0x01),
            'fifo_full': bool(status & 0x02),
            'fifo_empty': bool(status & 0x04),
            'interrupt_active': bool(status & 0x08),
            'power_good': bool(status & 0x10),
            'overrange': bool(status & 0x20),
            'underrange': bool(status & 0x40),
            'data_ready': bool(status & 0x80)
        }
    
    def set_threshold(self, channel: int, threshold: float):
        """
        Set threshold for a channel
        
        Args:
            channel: Channel number (0-7)
            threshold: Threshold voltage in volts
        """
        if not 0 <= channel <= 7:
            raise ADS7142Error(f"Invalid channel number: {channel}")
        
        # Convert voltage to raw value
        raw_threshold = int((threshold / self.voltage_reference) * 4095.0)
        raw_threshold = max(0, min(4095, raw_threshold))
        
        # Write threshold register
        threshold_register = ADS7142Registers.THRESHOLD_CH0 + channel
        self.write_register(threshold_register, raw_threshold >> 4)
        self.write_register(threshold_register + 1, (raw_threshold & 0x0F) << 4)
        
        self.logger.info(f"Channel {channel} threshold set to {threshold:.6f}V (raw: 0x{raw_threshold:03X})")
    
    def enable_interrupt(self, channel: int, enable: bool = True):
        """
        Enable/disable interrupt for a channel
        
        Args:
            channel: Channel number (0-7)
            enable: Enable interrupt
        """
        if not 0 <= channel <= 7:
            raise ADS7142Error(f"Invalid channel number: {channel}")
        
        int_mask = self.read_register(ADS7142Registers.INT_MASK)
        
        if enable:
            int_mask &= ~(1 << channel)
        else:
            int_mask |= (1 << channel)
        
        self.write_register(ADS7142Registers.INT_MASK, int_mask)
        
        # Enable/disable interrupt generation
        int_cfg = self.read_register(ADS7142Registers.INT_CFG)
        if enable:
            int_cfg |= 0x01
        else:
            int_cfg &= ~0x01
        
        self.write_register(ADS7142Registers.INT_CFG, int_cfg)
        
        self.logger.info(f"Channel {channel} interrupt {'enabled' if enable else 'disabled'}")
    
    def read_fifo(self, count: Optional[int] = None) -> List[Tuple[int, float]]:
        """
        Read data from FIFO buffer
        
        Args:
            count: Number of samples to read (None for all available)
            
        Returns:
            List of (channel, voltage) tuples
        """
        if count is None:
            fifo_count = self.read_register(ADS7142Registers.FIFO_COUNT)
            count = fifo_count
        
        results = []
        for _ in range(count):
            try:
                # Read FIFO data (2 bytes per sample)
                data = self.read_registers(ADS7142Registers.FIFO_DATA, 2)
                
                # Extract channel and value
                channel = data[0] & 0x07
                raw_value = ((data[0] & 0xF0) >> 4) | (data[1] << 4)
                
                # Convert to voltage
                voltage = self._raw_to_voltage(raw_value)
                
                results.append((channel, voltage))
                
            except Exception as e:
                self.logger.error(f"Failed to read FIFO data: {e}")
                break
        
        return results
    
    def get_device_info(self) -> Dict[str, Any]:
        """
        Get device information
        
        Returns:
            Dictionary containing device information
        """
        device_id = self.read_register(ADS7142Registers.DEVICE_ID)
        revision_id = self.read_register(ADS7142Registers.REVISION_ID)
        
        return {
            'device_id': f"0x{device_id:02X}",
            'revision_id': f"0x{revision_id:02X}",
            'device_name': 'ADS7142',
            'resolution': '12-bit',
            'max_sampling_rate': '1 MSPS',
            'channels': 8,
            'interface': 'I2C',
            'voltage_reference': f"{self.voltage_reference}V",
            'active_channels': self.active_channels,
            'input_range': self.input_range,
            'oversampling_ratio': self.oversampling_ratio,
            'operating_mode': self.operating_mode
        }
    
    def close(self):
        """Close the I2C bus connection"""
        try:
            self.bus.close()
            self.logger.info("I2C bus closed")
        except Exception as e:
            self.logger.error(f"Error closing I2C bus: {e}")
    
    def __enter__(self):
        """Context manager entry"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.close()


# Example usage and testing
if __name__ == "__main__":
    try:
        # Initialize the ADC
        adc = ADS7142(debug=True)
        
        # Print device information
        info = adc.get_device_info()
        print("Device Information:")
        for key, value in info.items():
            print(f"  {key}: {value}")
        
        # Configure channels
        adc.configure_channel(0, enabled=True)
        adc.configure_channel(1, enabled=True)
        
        # Set input range
        adc.set_input_range(ADS7142Config.RANGE_0_TO_2_5V)
        
        # Read single channel
        voltage = adc.read_channel(0)
        print(f"Channel 0 voltage: {voltage:.6f}V")
        
        # Read all active channels
        voltages = adc.read_all_channels()
        print("All channel voltages:")
        for channel, voltage in voltages.items():
            print(f"  Channel {channel}: {voltage:.6f}V")
        
        # Single-shot conversion
        results = adc.read_single_shot([0, 1])
        print("Single-shot results:")
        for channel, voltage in results.items():
            print(f"  Channel {channel}: {voltage:.6f}V")
        
        # Get status
        status = adc.get_status()
        print("Device status:")
        for key, value in status.items():
            print(f"  {key}: {value}")
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if 'adc' in locals():
            adc.close() 