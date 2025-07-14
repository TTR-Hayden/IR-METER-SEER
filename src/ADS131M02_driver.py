#!/usr/bin/env python3
"""
ADS131M02 Raspberry Pi Interface
Minimal implementation for register read/write, sampling rate, continuous sampling, and gain control
"""

import spidev
import time
import RPi.GPIO as GPIO
import argparse
from typing import List, Optional

class ADS131M02:
    # Command definitions
    CMD_NULL = 0x0000
    CMD_RESET = 0x0011
    CMD_STANDBY = 0x0022
    CMD_WAKEUP = 0x0033
    CMD_LOCK = 0x0555
    CMD_UNLOCK = 0x0655
    CMD_RREG = 0xA000  # Read register command base
    CMD_WREG = 0x6000  # Write register command base
    
    # Register addresses (ADS131M02 specific)
    REG_ID = 0x00
    REG_STATUS = 0x01
    REG_MODE = 0x02
    REG_CLOCK = 0x03
    REG_GAIN = 0x04
    REG_CFG = 0x06
    REG_THRSH_MSB = 0x07
    REG_THRSH_LSB = 0x08
    REG_CH0_CFG = 0x09
    REG_CH0_OCAL_MSB = 0x0A
    REG_CH0_OCAL_LSB = 0x0B
    REG_CH0_GCAL_MSB = 0x0C
    REG_CH0_GCAL_LSB = 0x0D
    REG_CH1_CFG = 0x0E
    REG_CH1_OCAL_MSB = 0x0F
    REG_CH1_OCAL_LSB = 0x10
    REG_CH1_GCAL_MSB = 0x11
    REG_CH1_GCAL_LSB = 0x12
    REG_REGMAP_CRC = 0x3E
    
    # Gain values
    GAIN_1 = 0b000
    GAIN_2 = 0b001
    GAIN_4 = 0b010
    GAIN_8 = 0b011
    GAIN_16 = 0b100
    GAIN_32 = 0b101
    GAIN_64 = 0b110
    GAIN_128 = 0b111
    
    # Sampling rates (OSR - Over Sampling Ratio) - corrected values
    OSR_128 = 0b000   # Highest data rate (64 kSPS)
    OSR_256 = 0b001   # 32 kSPS
    OSR_512 = 0b010   # 16 kSPS
    OSR_1024 = 0b011  # 8 kSPS
    OSR_2048 = 0b100  # 4 kSPS
    OSR_4096 = 0b101  # 2 kSPS
    OSR_8192 = 0b110  # 1 kSPS
    OSR_16384 = 0b111 # 0.5 kSPS (highest resolution)
    
    def __init__(self, spi_bus=0, spi_device=0, cs_pin=None, drdy_pin=None, reset_pin=None, vref=1.2):
        """
        Initialize ADS131M02
        
        Args:
            spi_bus: SPI bus number (0 or 1)
            spi_device: SPI device number (0 or 1)
            cs_pin: Chip select pin (if using manual CS control)
            drdy_pin: Data ready pin (optional)
            reset_pin: Reset pin (optional)
            vref: Reference voltage in volts (default 2.5V)
        """
        self.spi = spidev.SpiDev()
        self.spi.open(spi_bus, spi_device)
        
        # SPI configuration for ADS131M02
        self.spi.max_speed_hz = 8000000  # 1 MHz
        self.spi.mode = 0b01  # CPOL=0, CPHA=1
        self.spi.bits_per_word = 8
        
        self.cs_pin = cs_pin
        self.drdy_pin = drdy_pin
        self.reset_pin = reset_pin
        self.vref = vref
        self.channel_gains = [1, 1]  # Track gain for each channel for voltage conversion
        self.dc_block_enabled = [False, False]  # Track DC blocking filter state for each channel
        
        # Setup GPIO pins if provided
        if any([cs_pin, drdy_pin, reset_pin]):
            GPIO.setmode(GPIO.BCM)
            
        if cs_pin:
            GPIO.setup(cs_pin, GPIO.OUT)
            GPIO.output(cs_pin, GPIO.HIGH)
            
        if drdy_pin:
            GPIO.setup(drdy_pin, GPIO.IN)
            
        if reset_pin:
            GPIO.setup(reset_pin, GPIO.OUT)
            GPIO.output(reset_pin, GPIO.HIGH)
            
        self.continuous_mode = False
        
    def _spi_transfer(self, data: List[int]) -> List[int]:
        """
        Perform SPI transfer with optional manual CS control
        """
        if self.cs_pin:
            GPIO.output(self.cs_pin, GPIO.LOW)
            
        result = self.spi.xfer2(data)
        
        if self.cs_pin:
            GPIO.output(self.cs_pin, GPIO.HIGH)
            
        return result
        
    def _create_command_frame(self, command: int, data: List[int] = None) -> List[int]:
        """
        Create a command frame for SPI transmission
        Frame format: [CMD_MSB, CMD_LSB, DATA0, DATA1, ...]
        """
        frame = [
            (command >> 8) & 0xFF,  # Command MSB
            command & 0xFF          # Command LSB
        ]
        
        if data:
            frame.extend(data)
            
        # Pad frame to minimum length (6 bytes for ADS131M02)
        while len(frame) < 6:
            frame.append(0x00)
            
        return frame
        
    def reset(self):
        """Reset the device"""
        if self.reset_pin:
            GPIO.output(self.reset_pin, GPIO.LOW)
            time.sleep(0.001)  # 1ms pulse
            GPIO.output(self.reset_pin, GPIO.HIGH)
            time.sleep(0.01)   # Wait for reset
        else:
            # Software reset
            frame = self._create_command_frame(self.CMD_RESET)
            self._spi_transfer(frame)
            time.sleep(0.01)
            
    def read_register(self, reg_addr: int) -> int:
        """
        Read a single register
        
        Args:
            reg_addr: Register address to read
            
        Returns:
            Register value (16-bit)
        """
        # Create read register command
        cmd = self.CMD_RREG | ((reg_addr & 0x1F) << 7) | 0x01  # Read 1 register
        frame = self._create_command_frame(cmd)
        
        # Send command
        self._spi_transfer(frame)
        
        # Read response in next frame
        response_frame = self._create_command_frame(self.CMD_NULL)
        response = self._spi_transfer(response_frame)
        
        # Extract register data from response (bytes 3-4 for ADS131M02)
        # Response format: [Status_MSB, Status_LSB, Register_MSB, Register_LSB, CRC]
        # ADS131M02 returns data in little-endian format (LSB first)
        if len(response) >= 5:
            return (response[3] << 8) | response[2]  # Swap byte order: LSB first, then MSB
        else:
            return 0
            
    def write_register(self, reg_addr: int, value: int):
        """
        Write a single register
        
        Args:
            reg_addr: Register address to write
            value: 16-bit value to write
        """
        # Create write register command
        cmd = self.CMD_WREG | ((reg_addr & 0x1F) << 7) | 0x01  # Write 1 register
        data = [(value >> 8) & 0xFF, value & 0xFF]
        frame = self._create_command_frame(cmd, data)
        
        self._spi_transfer(frame)
        time.sleep(0.001)  # Small delay after write
        
    def set_sampling_rate(self, osr: int):
        """
        Set the over-sampling ratio (sampling rate)
        
        Args:
            osr: Over-sampling ratio (use OSR_* constants)
        """
        # Read current CLOCK register
        clock_reg = self.read_register(self.REG_CLOCK)
        
        # Clear OSR bits (bits 2:0) and set new value
        clock_reg = (clock_reg & 0xFFF8) | (osr & 0x07)
        
        # Write back to register
        self.write_register(self.REG_CLOCK, clock_reg)
        
    def set_gain(self, channel: int, gain: int):
        """
        Set gain for a specific channel
        
        Args:
            channel: Channel number (0 or 1)
            gain: Gain value (use GAIN_* constants)
        """
        if channel not in [0, 1]:
            raise ValueError("Channel must be 0 or 1")
            
        # Read current GAIN register
        gain_reg = self.read_register(self.REG_GAIN)
        
        # Set gain for the channel
        # Channel 0: bits 2:0, Channel 1: bits 6:4
        if channel == 0:
            gain_reg = (gain_reg & 0xFFF8) | (gain & 0x07)
        else:
            gain_reg = (gain_reg & 0xFF8F) | ((gain & 0x07) << 4)
            
        self.write_register(self.REG_GAIN, gain_reg)
        
        # Update stored gain value for voltage conversion
        gain_values = [1, 2, 4, 8, 16, 32, 64, 128]
        self.channel_gains[channel] = gain_values[gain]
        
    def set_dc_blocking_filter(self, channel: int, enable: bool):
        """
        Enable or disable DC blocking filter for a specific channel
        
        Args:
            channel: Channel number (0 or 1)
            enable: True to enable DC blocking filter, False to disable
        """
        if channel not in [0, 1]:
            raise ValueError("Channel must be 0 or 1")
            
        # Determine which channel config register to use
        if channel == 0:
            reg_addr = self.REG_CH0_CFG
        else:
            reg_addr = self.REG_CH1_CFG
            
        # Read current channel configuration register
        ch_cfg = self.read_register(reg_addr)
        
        # DC blocking filter is typically controlled by bit 8 (DCBLOCK)
        if enable:
            ch_cfg |= 0x0100  # Set bit 8
        else:
            ch_cfg &= 0xFEFF  # Clear bit 8
            
        # Write back to register
        self.write_register(reg_addr, ch_cfg)
        
        # Update stored state
        self.dc_block_enabled[channel] = enable
        
    def get_dc_blocking_filter_status(self, channel: int) -> bool:
        """
        Get DC blocking filter status for a specific channel
        
        Args:
            channel: Channel number (0 or 1)
            
        Returns:
            True if DC blocking filter is enabled, False if disabled
        """
        if channel not in [0, 1]:
            raise ValueError("Channel must be 0 or 1")
            
        return self.dc_block_enabled[channel]
        
    def enable_continuous_sampling(self, enable: bool = True):
        """
        Enable or disable continuous conversion mode
        
        Args:
            enable: True to enable continuous mode, False for single-shot
        """
        # Read current MODE register
        mode_reg = self.read_register(self.REG_MODE)
        
        if enable:
            # Set continuous conversion mode (clear CONVST bit)
            mode_reg &= 0xFFFE
        else:
            # Set single-shot mode (set CONVST bit)
            mode_reg |= 0x0001
            
        self.write_register(self.REG_MODE, mode_reg)
        self.continuous_mode = enable
        
    def read_data_raw(self) -> Optional[List[int]]:
        """
        Read raw conversion data from both channels
        
        Returns:
            List of [channel0_data, channel1_data] or None if no data ready
        """
        # Check if data is ready (DRDY is active HIGH)
        if self.drdy_pin and GPIO.input(self.drdy_pin) == GPIO.HIGH:
            return None  # Data not ready
            
        # Send NULL command to read data
        frame = self._create_command_frame(self.CMD_NULL)
        # Try reading more bytes to see if data is elsewhere
        while len(frame) < 12:
            frame.append(0x00)
            
        response = self._spi_transfer(frame)
        
        if len(response) >= 12:
            # Try reading from the middle of the response (bytes 4-6 and 7-9)
            ch0_data = (response[4] << 16) | (response[5] << 8) | response[6]
            ch1_data = (response[7] << 16) | (response[8] << 8) | response[9]
            
            # Convert from unsigned to signed 24-bit
            if ch0_data & 0x800000:
                ch0_data -= 0x1000000
            if ch1_data & 0x800000:
                ch1_data -= 0x1000000
                
            return [ch0_data, ch1_data]
        else:
            return None
            
    def read_data(self) -> Optional[List[float]]:
        """
        Read conversion data from both channels and convert to voltage
        
        Returns:
            List of [channel0_voltage, channel1_voltage] in volts, or None if no data ready
        """
        raw_data = self.read_data_raw()
        if raw_data is None:
            return None
            
        voltages = []
        for i, raw_value in enumerate(raw_data):
            # Convert 24-bit ADC code to voltage
            # ADS131M02: 24-bit ADC with ±VREF/Gain full-scale range
            # ADC range: -8388608 to +8388607 (24-bit signed)
            # Voltage = (ADC_Code / 8388608) * (VREF / Gain)
            full_scale_voltage = self.vref / self.channel_gains[i]
            voltage = (raw_value / 8388608.0) * self.vref * self.channel_gains[i]
            #voltage = (raw_value / 8388608.0) * full_scale_voltage
            voltages.append(voltage)
            
        return voltages
            
    def get_device_id(self) -> int:
        """Get device ID"""
        return self.read_register(self.REG_ID)
        
    def cleanup(self):
        """Cleanup resources"""
        self.spi.close()
        if any([self.cs_pin, self.drdy_pin, self.reset_pin]):
            GPIO.cleanup()

    def check_drdy_status(self) -> bool:
        """
        Check the current status of the DRDY pin
        
        Returns:
            True if data is ready (DRDY pin is LOW), False otherwise
        """
        if self.drdy_pin:
            return GPIO.input(self.drdy_pin) == GPIO.LOW
        else:
            return True  # If no DRDY pin, assume data is always ready
            
    def read_data_debug(self) -> Optional[dict]:
        """
        Read conversion data with debug information
        
        Returns:
            Dictionary with raw ADC values, voltages, and conversion details
        """
        # Check if data is ready (DRDY is active HIGH)
        if self.drdy_pin and GPIO.input(self.drdy_pin) == GPIO.HIGH:
            return None  # Data not ready
            
        # Send NULL command to read data
        frame = self._create_command_frame(self.CMD_NULL)
        # Try reading more bytes to see if data is elsewhere
        while len(frame) < 12:
            frame.append(0x00)
            
        response = self._spi_transfer(frame)
        
        if len(response) >= 12:
            # Show raw response bytes for debugging
            raw_bytes = ' '.join([f'{b:02X}' for b in response[:12]])
            
            # Try reading from the middle of the response (bytes 4-6 and 7-9)
            ch0_data = (response[4] << 16) | (response[5] << 8) | response[6]
            ch1_data = (response[7] << 16) | (response[8] << 8) | response[9]
            
            # Convert from unsigned to signed 24-bit
            if ch0_data & 0x800000:
                ch0_data -= 0x1000000
            if ch1_data & 0x800000:
                ch1_data -= 0x1000000
                
            debug_info = {
                'raw_bytes': raw_bytes,
                'raw_adc': [ch0_data, ch1_data],
                'voltages': [],
                'conversion_details': []
            }
            
            for i, raw_value in enumerate([ch0_data, ch1_data]):
                # Convert 24-bit ADC code to voltage
                full_scale_voltage = self.vref / self.channel_gains[i]
                voltage = (raw_value / 8388608.0) * full_scale_voltage
                
                debug_info['voltages'].append(voltage)
                debug_info['conversion_details'].append({
                    'channel': i,
                    'raw_adc': raw_value,
                    'vref': self.vref,
                    'gain': self.channel_gains[i],
                    'full_scale_voltage': full_scale_voltage,
                    'voltage': voltage
                })
                
            return debug_info
        else:
            return None


# Example usage
if __name__ == "__main__":
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='ADS131M02 ADC Test Script')
    parser.add_argument('--osr', type=int, choices=[128, 256, 512, 1024, 2048, 4096, 8192, 16384], 
                       default=8192, help='Over Sampling Ratio (default: 8192)')
    parser.add_argument('--samples', type=int, default=10000, 
                       help='Number of samples to read for performance test (default: 10000)')
    args = parser.parse_args()
    
    # Map OSR values to constants
    osr_map = {
        128: ADS131M02.OSR_128,
        256: ADS131M02.OSR_256,
        512: ADS131M02.OSR_512,
        1024: ADS131M02.OSR_1024,
        2048: ADS131M02.OSR_2048,
        4096: ADS131M02.OSR_4096,
        8192: ADS131M02.OSR_8192,
        16384: ADS131M02.OSR_16384
    }
    
    selected_osr = osr_map[args.osr]
    
    print(f"Starting ADS131M02 test with OSR={args.osr}")
    print(f"Expected sampling rate: {8000000/args.osr:.1f} SPS")
    
    # Initialize ADS131M02 with specified GPIO pins
    adc = ADS131M02(
        spi_bus=0, 
        spi_device=0,
        cs_pin=21,    # GPIO21 for chip select
        drdy_pin=16,  # GPIO16 for data ready
        reset_pin=12, # GPIO12 for reset
        vref=1.2      # 2.5V reference voltage
    )
    
    try:
        # Reset device
        print("Resetting ADS131M02...")
        adc.reset()
        
        # Read device ID
        device_id = adc.get_device_id()
        print(f"Device ID: 0x{device_id:04X}")
        
        # Print initial register values
        print("\n=== INITIAL REGISTER VALUES ===")
        print(f"ID Register: 0x{adc.read_register(adc.REG_ID):04X}")
        print(f"Status Register: 0x{adc.read_register(adc.REG_STATUS):04X}")
        print(f"Mode Register: 0x{adc.read_register(adc.REG_MODE):04X}")
        print(f"Clock Register: 0x{adc.read_register(adc.REG_CLOCK):04X}")
        print(f"Gain Register: 0x{adc.read_register(adc.REG_GAIN):04X}")
        print(f"Config Register: 0x{adc.read_register(adc.REG_CFG):04X}")
        print(f"Channel 0 Config: 0x{adc.read_register(adc.REG_CH0_CFG):04X}")
        print(f"Channel 1 Config: 0x{adc.read_register(adc.REG_CH1_CFG):04X}")
        
        # Configure sampling rate (use user-specified OSR)
        print(f"\nSetting sampling rate to OSR={args.osr}...")
        adc.set_sampling_rate(selected_osr)
        
        # Set gain for both channels (gain of 4)
        print("Setting gain...")
        adc.set_gain(0, adc.GAIN_2)  # Channel 0
        adc.set_gain(1, adc.GAIN_2)  # Channel 1
        
        # Configure DC blocking filter
        print("Configuring DC blocking filter...")
        adc.set_dc_blocking_filter(0, False)   # Enable DC blocking on Channel 0
        adc.set_dc_blocking_filter(1, False)  # Disable DC blocking on Channel 1
        
        print(f"DC blocking CH0: {'Enabled' if adc.get_dc_blocking_filter_status(0) else 'Disabled'}")
        print(f"DC blocking CH1: {'Enabled' if adc.get_dc_blocking_filter_status(1) else 'Disabled'}")
        
        # Enable continuous sampling
        print("Enabling continuous sampling...")
        adc.enable_continuous_sampling(True)
        
        # Print register values after configuration
        print("\n=== REGISTER VALUES AFTER CONFIGURATION ===")
        print(f"ID Register: 0x{adc.read_register(adc.REG_ID):04X}")
        print(f"Status Register: 0x{adc.read_register(adc.REG_STATUS):04X}")
        print(f"Mode Register: 0x{adc.read_register(adc.REG_MODE):04X}")
        print(f"Clock Register: 0x{adc.read_register(adc.REG_CLOCK):04X}")
        print(f"Gain Register: 0x{adc.read_register(adc.REG_GAIN):04X}")
        print(f"Config Register: 0x{adc.read_register(adc.REG_CFG):04X}")
        print(f"Channel 0 Config: 0x{adc.read_register(adc.REG_CH0_CFG):04X}")
        print(f"Channel 1 Config: 0x{adc.read_register(adc.REG_CH1_CFG):04X}")
        
        # Read initial 5 samples
        print("\nReading initial 5 samples...")
        for i in range(5):
            # Check DRDY status first
            drdy_status = adc.check_drdy_status()
            print(f"Sample {i+1}: DRDY status = {'Ready' if drdy_status else 'Not Ready'}")
            
            debug_info = adc.read_data_debug()
            if debug_info:
                print(f"  Raw bytes: {debug_info['raw_bytes']}")
                for ch in range(2):
                    details = debug_info['conversion_details'][ch]

                    print(f"  CH{ch}: Raw={details['raw_adc']:8d}, "
                          f"Vref={details['vref']:.2f}V, Gain={details['gain']}, "
                          f"FS={details['full_scale_voltage']:.2f}V, "
                          f"Voltage={details['voltage']:8.6f}V")
            else:
                print(f"  No data available")
            time.sleep(1)
        
        # Read samples and measure elapsed time
        print(f"\nReading {args.samples} samples to measure performance...")
        start_time = time.time()
        
        samples_read = 0
        ch0_data = []
        ch1_data = []
        for i in range(args.samples):
            voltages = adc.read_data()
            if voltages:
                samples_read += 1
                ch0_data.append(voltages[0])
                ch1_data.append(voltages[1])
            # No printing to avoid slowing down the measurement
        
        end_time = time.time()
        elapsed_time = end_time - start_time
        
        print(f"Read {samples_read} samples in {elapsed_time:.3f} seconds")
        print(f"Average time per sample: {(elapsed_time/samples_read)*1000:.3f} ms")
        print(f"Effective sampling rate: {samples_read/elapsed_time:.1f} samples/second")
        
        # Calculate statistics for the collected data
        if ch0_data and ch1_data:
            import statistics
            
            print("\n=== STATISTICAL ANALYSIS ===")
            print("Channel 0 Statistics:")
            print(f"  Mean: {statistics.mean(ch0_data):.6f} V")
            print(f"  Median: {statistics.median(ch0_data):.6f} V")
            print(f"  Mode: {statistics.mode(ch0_data):.6f} V")
            print(f"  Min: {min(ch0_data):.6f} V")
            print(f"  Max: {max(ch0_data):.6f} V")
            print(f"  Standard Deviation: {statistics.stdev(ch0_data):.6f} V")
            
            print("\nChannel 1 Statistics:")
            print(f"  Mean: {statistics.mean(ch1_data):.6f} V")
            print(f"  Median: {statistics.median(ch1_data):.6f} V")
            print(f"  Mode: {statistics.mode(ch1_data):.6f} V")
            print(f"  Min: {min(ch1_data):.6f} V")
            print(f"  Max: {max(ch1_data):.6f} V")
            print(f"  Standard Deviation: {statistics.stdev(ch1_data):.6f} V")
            
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        adc.cleanup()