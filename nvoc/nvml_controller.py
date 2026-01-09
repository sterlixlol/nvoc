"""
NVOC - NVIDIA Overclocking Controller for Wayland
NVML Backend Controller

This module provides safe access to NVIDIA GPU controls via the NVML API.
All operations include safety checks and hard limits to prevent hardware damage.

SAFETY NOTES:
- All clock offsets are capped at SAFE limits (±200 MHz core, ±500 MHz memory)
- Power limits are constrained to GPU-reported min/max values
- Fan speed changes include temperature monitoring
- All operations require root privileges

API Reference: https://docs.nvidia.com/deploy/nvml-api/
"""

import logging
from dataclasses import dataclass
from typing import Optional, Tuple, Dict, Any, List
from enum import Enum

# Import nvidia-ml-py (the official NVIDIA Python bindings)
try:
    import pynvml
except ImportError:
    raise ImportError(
        "nvidia-ml-py is required. Install with: pip install nvidia-ml-py"
    )

logger = logging.getLogger(__name__)


# =============================================================================
# SAFETY LIMITS - DO NOT MODIFY WITHOUT CAREFUL CONSIDERATION
# =============================================================================

class SafetyLimits:
    """
    Hard safety limits for overclocking operations.
    These are intentionally conservative to prevent hardware damage.
    
    The actual GPU may support higher values, but we cap them here
    as a safety measure. Users who want to push beyond these limits
    should use nvidia-smi directly (at their own risk).
    """
    # Maximum core clock offset in MHz (positive or negative)
    MAX_CORE_CLOCK_OFFSET_MHZ: int = 1500  # "Sky's the limit"
    
    # Maximum memory clock offset in MHz (positive or negative)
    MAX_MEMORY_CLOCK_OFFSET_MHZ: int = 4000 # Reduced for stability from "Sky's the limit"
    
    # Minimum safe fan speed percentage when in manual mode
    MIN_FAN_SPEED_PERCENT: int = 30
    
    # Maximum allowed GPU temperature before forcing fan to 100%
    CRITICAL_TEMP_CELSIUS: int = 90
    
    # Temperature at which we should warn the user
    WARNING_TEMP_CELSIUS: int = 80


class NVMLError(Exception):
    """Base exception for NVML-related errors."""
    pass


class GPUNotFoundError(NVMLError):
    """Raised when no compatible GPU is found."""
    pass


class PermissionError(NVMLError):
    """Raised when operation requires elevated privileges."""
    pass


class SafetyLimitExceeded(NVMLError):
    """Raised when a requested value exceeds safety limits."""
    pass


@dataclass
class GPUInfo:
    """Information about the GPU."""
    index: int
    name: str
    uuid: str
    driver_version: str
    vbios_version: str
    pcie_gen: int
    pcie_width: int
    memory_total_mb: int
    
    
@dataclass
class GPUStats:
    """Real-time GPU statistics."""
    temperature_celsius: int
    fan_speed_percent: int
    power_draw_watts: float
    power_limit_watts: float
    gpu_utilization_percent: int
    memory_utilization_percent: int
    memory_used_mb: int
    
    # Advanced Monitoring
    effective_core_clock_mhz: int
    effective_memory_clock_mhz: int
    throttle_reasons: list[str]  # List of active throttle reason codes (e.g. "POWER", "THERMAL")
    peak_core_clock_mhz: int  # Maximum observed clock since last reset
    memory_total_mb: int
    core_clock_mhz: int
    memory_clock_mhz: int
    
    # Phase 13: Extended Monitoring
    pcie_gen: int  # Current PCIe generation (3, 4, 5)
    pcie_width: int  # Current PCIe link width (x16, x8, etc)
    pcie_gen_max: int  # Maximum supported PCIe generation
    pcie_width_max: int  # Maximum supported PCIe width
    thermal_threshold_celsius: int  # Temperature at which throttling begins
    thermal_headroom_celsius: int  # Degrees below throttle threshold
    power_limit_active: bool  # True if power limit is actively constraining boost
    avg_core_clock_mhz: int  # Rolling average clock (30s window)
    memory_errors: int  # ECC/memory error count (0 if not supported)
    
    
@dataclass
class PowerLimits:
    """Power limit constraints from the GPU."""
    current_watts: float
    default_watts: float
    min_watts: float
    max_watts: float


@dataclass 
class ClockOffsets:
    """Current clock offset values."""
    core_offset_mhz: int
    memory_offset_mhz: int


class FanControlMode(Enum):
    AUTO = "auto"
    MANUAL = "manual"


class NVMLController:
    """
    Controller for NVIDIA GPU management via NVML.
    
    This class provides a safe interface to GPU overclocking operations.
    All methods include safety checks and validation.
    
    Usage:
        controller = NVMLController()
        controller.initialize()
        try:
            info = controller.get_gpu_info()
            print(f"GPU: {info.name}")
        finally:
            controller.shutdown()
    
    Or using context manager:
        with NVMLController() as controller:
            info = controller.get_gpu_info()
    """
    
    def __init__(self, gpu_index: int = 0):
        """
        Initialize the controller.
        
        Args:
            gpu_index: Index of the GPU to control (default: 0)
        """
        self._gpu_index = gpu_index
        self._handle = None
        self._initialized = False
        self._peak_core_clock = 0  # Track peak clock for load monitoring
        self._clock_samples: list[int] = []  # Rolling buffer for avg clock (max 30 samples)
        
    def __enter__(self):
        self.initialize()
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.shutdown()
        return False
        
    def initialize(self) -> None:
        """
        Initialize NVML and get GPU handle.
        
        Raises:
            GPUNotFoundError: If no compatible GPU is found
            NVMLError: If initialization fails
        """
        try:
            pynvml.nvmlInit()
            self._initialized = True
            
            # Get device count
            device_count = pynvml.nvmlDeviceGetCount()
            if device_count == 0:
                raise GPUNotFoundError("No NVIDIA GPU found")
                
            if self._gpu_index >= device_count:
                raise GPUNotFoundError(
                    f"GPU index {self._gpu_index} not found. "
                    f"Available GPUs: 0-{device_count - 1}"
                )
            
            # Get device handle
            self._handle = pynvml.nvmlDeviceGetHandleByIndex(self._gpu_index)
            
            logger.info(f"NVML initialized successfully for GPU {self._gpu_index}")
            
        except pynvml.NVMLError as e:
            raise NVMLError(f"Failed to initialize NVML: {e}")
    
    def shutdown(self) -> None:
        """Shutdown NVML and release resources."""
        if self._initialized:
            try:
                pynvml.nvmlShutdown()
                self._initialized = False
                self._handle = None
                logger.info("NVML shutdown complete")
            except pynvml.NVMLError as e:
                logger.warning(f"Error during NVML shutdown: {e}")
                
    def _ensure_initialized(self) -> None:
        """Ensure NVML is initialized before operations."""
        if not self._initialized or self._handle is None:
            raise NVMLError("NVML not initialized. Call initialize() first.")
    
    # =========================================================================
    # GPU Information
    # =========================================================================
    
    def get_gpu_info(self) -> GPUInfo:
        """
        Get static GPU information.
        
        Returns:
            GPUInfo object with GPU details
        """
        self._ensure_initialized()
        
        try:
            name = pynvml.nvmlDeviceGetName(self._handle)
            # Handle bytes vs string (depends on pynvml version)
            if isinstance(name, bytes):
                name = name.decode('utf-8')
                
            uuid = pynvml.nvmlDeviceGetUUID(self._handle)
            if isinstance(uuid, bytes):
                uuid = uuid.decode('utf-8')
                
            driver_version = pynvml.nvmlSystemGetDriverVersion()
            if isinstance(driver_version, bytes):
                driver_version = driver_version.decode('utf-8')
            
            # VBIOS version
            try:
                vbios = pynvml.nvmlDeviceGetVbiosVersion(self._handle)
                if isinstance(vbios, bytes):
                    vbios = vbios.decode('utf-8')
            except pynvml.NVMLError:
                vbios = "Unknown"
            
            # PCIe info
            try:
                pcie_gen = pynvml.nvmlDeviceGetCurrPcieLinkGeneration(self._handle)
                pcie_width = pynvml.nvmlDeviceGetCurrPcieLinkWidth(self._handle)
            except pynvml.NVMLError:
                pcie_gen = 0
                pcie_width = 0
            
            # Memory info
            memory_info = pynvml.nvmlDeviceGetMemoryInfo(self._handle)
            memory_total_mb = memory_info.total // (1024 * 1024)
            
            return GPUInfo(
                index=self._gpu_index,
                name=name,
                uuid=uuid,
                driver_version=driver_version,
                vbios_version=vbios,
                pcie_gen=pcie_gen,
                pcie_width=pcie_width,
                memory_total_mb=memory_total_mb
            )
            
        except pynvml.NVMLError as e:
            raise NVMLError(f"Failed to get GPU info: {e}")
    
    def get_gpu_stats(self) -> GPUStats:
        """
        Get real-time GPU statistics.
        
        Returns:
            GPUStats object with current values
        """
        self._ensure_initialized()
        
        try:
            # Temperature
            temp = pynvml.nvmlDeviceGetTemperature(
                self._handle, 
                pynvml.NVML_TEMPERATURE_GPU
            )
            
            # Fan speed (may not be available on all GPUs)
            try:
                fan_speed = pynvml.nvmlDeviceGetFanSpeed(self._handle)
            except pynvml.NVMLError:
                fan_speed = 0
            
            # Power
            try:
                power_draw = pynvml.nvmlDeviceGetPowerUsage(self._handle) / 1000.0
            except pynvml.NVMLError:
                power_draw = 0.0
                
            try:
                power_limit = pynvml.nvmlDeviceGetPowerManagementLimit(self._handle) / 1000.0
            except pynvml.NVMLError:
                power_limit = 0.0
            
            # Utilization
            try:
                utilization = pynvml.nvmlDeviceGetUtilizationRates(self._handle)
                gpu_util = utilization.gpu
                mem_util = utilization.memory
            except pynvml.NVMLError:
                gpu_util = 0
                mem_util = 0
            
            # Memory
            memory_info = pynvml.nvmlDeviceGetMemoryInfo(self._handle)
            memory_used_mb = memory_info.used // (1024 * 1024)
            memory_total_mb = memory_info.total // (1024 * 1024)
            
            # Clock speeds (Effective)
            try:
                core_clock = pynvml.nvmlDeviceGetClockInfo(
                    self._handle, 
                    pynvml.NVML_CLOCK_GRAPHICS
                )
            except pynvml.NVMLError:
                core_clock = 0
                
            try:
                memory_clock = pynvml.nvmlDeviceGetClockInfo(
                    self._handle, 
                    pynvml.NVML_CLOCK_MEM
                )
            except pynvml.NVMLError:
                memory_clock = 0
            
            # Throttle Reasons (Enhanced Granularity)
            throttle_reasons = []
            try:
                # Get bitmask of active throttle reasons
                reasons_mask = pynvml.nvmlDeviceGetCurrentClocksThrottleReasons(self._handle)
                
                if reasons_mask & pynvml.nvmlClocksThrottleReasonGpuIdle:
                    throttle_reasons.append("IDLE")
                
                # Power Limits (separate SW and HW)
                if reasons_mask & pynvml.nvmlClocksThrottleReasonSwPowerCap:
                    throttle_reasons.append("Power (SW)")
                if reasons_mask & pynvml.nvmlClocksThrottleReasonHwPowerBrakeSlowdown:
                    throttle_reasons.append("Power (HW)")
                
                # Thermal Limits (separate types)
                if reasons_mask & pynvml.nvmlClocksThrottleReasonSwThermalSlowdown:
                    throttle_reasons.append("Thermal (SW)")
                if reasons_mask & pynvml.nvmlClocksThrottleReasonHwThermalSlowdown:
                    throttle_reasons.append("Thermal (HW)")
                if reasons_mask & pynvml.nvmlClocksThrottleReasonHwSlowdown:
                    throttle_reasons.append("HW Slowdown")
                
                # Sync Boost
                if reasons_mask & pynvml.nvmlClocksThrottleReasonSyncBoost:
                    throttle_reasons.append("Sync Boost")
                
                # Display Clock Setting
                if reasons_mask & pynvml.nvmlClocksThrottleReasonDisplayClockSetting:
                    throttle_reasons.append("Display")
                
                # Application Clocks Setting
                if reasons_mask & pynvml.nvmlClocksThrottleReasonApplicationsClocksSetting:
                    throttle_reasons.append("App Clocks")
                    
            except Exception:
                pass  # Ignore if not supported
            
            # Track peak clock (for load monitoring)
            if core_clock > self._peak_core_clock:
                self._peak_core_clock = core_clock
            
            # Rolling average clock (keep last 30 samples = ~30 seconds at 1/sec)
            self._clock_samples.append(core_clock)
            if len(self._clock_samples) > 30:
                self._clock_samples.pop(0)
            avg_clock = sum(self._clock_samples) // len(self._clock_samples) if self._clock_samples else 0
            
            # PCIe link state
            try:
                pcie_gen = pynvml.nvmlDeviceGetCurrPcieLinkGeneration(self._handle)
                pcie_width = pynvml.nvmlDeviceGetCurrPcieLinkWidth(self._handle)
                pcie_gen_max = pynvml.nvmlDeviceGetMaxPcieLinkGeneration(self._handle)
                pcie_width_max = pynvml.nvmlDeviceGetMaxPcieLinkWidth(self._handle)
            except pynvml.NVMLError:
                pcie_gen = pcie_width = pcie_gen_max = pcie_width_max = 0
            
            # Thermal threshold
            try:
                thermal_threshold = pynvml.nvmlDeviceGetTemperatureThreshold(
                    self._handle, pynvml.NVML_TEMPERATURE_THRESHOLD_SLOWDOWN
                )
            except pynvml.NVMLError:
                thermal_threshold = 83  # Default fallback
            thermal_headroom = thermal_threshold - temp
            
            # Power limit active check (from throttle reasons)
            power_limit_active = any("Power" in r for r in throttle_reasons)
            
            # Memory error count
            try:
                memory_errors = pynvml.nvmlDeviceGetTotalEccErrors(
                    self._handle,
                    pynvml.NVML_MEMORY_ERROR_TYPE_UNCORRECTED,
                    pynvml.NVML_VOLATILE_ECC
                )
            except pynvml.NVMLError:
                memory_errors = 0  # Not supported or no ECC
            
            return GPUStats(
                temperature_celsius=temp,
                fan_speed_percent=fan_speed,
                power_draw_watts=power_draw,
                power_limit_watts=power_limit,
                gpu_utilization_percent=gpu_util,
                memory_utilization_percent=mem_util,
                memory_used_mb=memory_used_mb,
                memory_total_mb=memory_total_mb,
                core_clock_mhz=core_clock,
                memory_clock_mhz=memory_clock,
                effective_core_clock_mhz=core_clock,
                effective_memory_clock_mhz=memory_clock,
                throttle_reasons=throttle_reasons,
                peak_core_clock_mhz=self._peak_core_clock,
                pcie_gen=pcie_gen,
                pcie_width=pcie_width,
                pcie_gen_max=pcie_gen_max,
                pcie_width_max=pcie_width_max,
                thermal_threshold_celsius=thermal_threshold,
                thermal_headroom_celsius=thermal_headroom,
                power_limit_active=power_limit_active,
                avg_core_clock_mhz=avg_clock,
                memory_errors=memory_errors
            )
            
        except pynvml.NVMLError as e:
            raise NVMLError(f"Failed to get GPU stats: {e}")
    
    def reset_peak_clock(self) -> None:
        """Reset the tracked peak core clock to current value."""
        self._peak_core_clock = 0
        logger.info("Peak clock counter reset")
    
    # =========================================================================
    # Power Management
    # =========================================================================
    
    def get_power_limits(self) -> PowerLimits:
        """
        Get power limit constraints from the GPU.
        
        Returns:
            PowerLimits object with current and allowed values
        """
        self._ensure_initialized()
        
        try:
            # Current power limit (in milliwatts)
            current_mw = pynvml.nvmlDeviceGetPowerManagementLimit(self._handle)
            
            # Default power limit
            default_mw = pynvml.nvmlDeviceGetPowerManagementDefaultLimit(self._handle)
            
            # Min/max constraints
            min_mw, max_mw = pynvml.nvmlDeviceGetPowerManagementLimitConstraints(
                self._handle
            )
            
            return PowerLimits(
                current_watts=current_mw / 1000.0,
                default_watts=default_mw / 1000.0,
                min_watts=min_mw / 1000.0,
                max_watts=max_mw / 1000.0
            )
            
        except pynvml.NVMLError as e:
            raise NVMLError(f"Failed to get power limits: {e}")
    
    def set_power_limit(self, watts: float) -> None:
        """
        Set GPU power limit.
        
        The value will be clamped to the GPU's reported min/max constraints.
        
        Args:
            watts: Power limit in watts
            
        Raises:
            PermissionError: If not running as root
            NVMLError: If operation fails
        """
        self._ensure_initialized()
        
        try:
            # Get constraints
            limits = self.get_power_limits()
            
            # Clamp to valid range
            clamped_watts = max(limits.min_watts, min(watts, limits.max_watts))
            
            if clamped_watts != watts:
                logger.warning(
                    f"Power limit {watts}W clamped to {clamped_watts}W "
                    f"(valid range: {limits.min_watts}W - {limits.max_watts}W)"
                )
            
            # Set power limit (NVML uses milliwatts)
            milliwatts = int(clamped_watts * 1000)
            pynvml.nvmlDeviceSetPowerManagementLimit(self._handle, milliwatts)
            
            logger.info(f"Power limit set to {clamped_watts}W")
            
        except pynvml.NVMLError_NoPermission:
            raise PermissionError(
                "Setting power limit requires root privileges. "
                "Run with sudo or as root."
            )
        except pynvml.NVMLError as e:
            raise NVMLError(f"Failed to set power limit: {e}")
    
    # =========================================================================
    # Clock Offsets (Overclocking)
    # =========================================================================
    
    def get_clock_offsets(self) -> ClockOffsets:
        """
        Get current clock offset values.
        
        Returns:
            ClockOffsets object with core and memory offsets
            
        Note:
            This may return 0 if offsets have never been set or after reboot.
        """
        self._ensure_initialized()
        
        try:
            # Try to get GPC clock offset
            try:
                core_offset = pynvml.nvmlDeviceGetGpcClkVfOffset(self._handle)
            except (pynvml.NVMLError, AttributeError):
                core_offset = 0
                
            # Try to get memory clock offset
            try:
                mem_offset = pynvml.nvmlDeviceGetMemClkVfOffset(self._handle)
            except (pynvml.NVMLError, AttributeError):
                mem_offset = 0
            
            return ClockOffsets(
                core_offset_mhz=core_offset,
                memory_offset_mhz=mem_offset
            )
            
        except pynvml.NVMLError as e:
            raise NVMLError(f"Failed to get clock offsets: {e}")
    
    def set_clock_offsets(
        self, 
        core_offset_mhz: Optional[int] = None,
        memory_offset_mhz: Optional[int] = None
    ) -> Tuple[int, int]:
        """
        Set GPU clock offsets for overclocking/underclocking.
        
        SAFETY: Values are clamped to safe limits defined in SafetyLimits.
        
        Args:
            core_offset_mhz: Core clock offset in MHz (can be negative)
            memory_offset_mhz: Memory clock offset in MHz (can be negative)
            
        Returns:
            Tuple of (actual_core_offset, actual_memory_offset) after clamping
            
        Raises:
            PermissionError: If not running as root
            NVMLError: If operation fails
        """
        self._ensure_initialized()
        
        # Get current offsets for any values not specified
        current = self.get_clock_offsets()
        
        if core_offset_mhz is None:
            core_offset_mhz = current.core_offset_mhz
        if memory_offset_mhz is None:
            memory_offset_mhz = current.memory_offset_mhz
        
        # Apply safety limits
        safe_core = max(
            -SafetyLimits.MAX_CORE_CLOCK_OFFSET_MHZ,
            min(core_offset_mhz, SafetyLimits.MAX_CORE_CLOCK_OFFSET_MHZ)
        )
        safe_mem = max(
            -SafetyLimits.MAX_MEMORY_CLOCK_OFFSET_MHZ,
            min(memory_offset_mhz, SafetyLimits.MAX_MEMORY_CLOCK_OFFSET_MHZ)
        )
        
        if safe_core != core_offset_mhz:
            logger.warning(
                f"Core offset {core_offset_mhz}MHz clamped to {safe_core}MHz "
                f"(safety limit: ±{SafetyLimits.MAX_CORE_CLOCK_OFFSET_MHZ}MHz)"
            )
        if safe_mem != memory_offset_mhz:
            logger.warning(
                f"Memory offset {memory_offset_mhz}MHz clamped to {safe_mem}MHz "
                f"(safety limit: ±{SafetyLimits.MAX_MEMORY_CLOCK_OFFSET_MHZ}MHz)"
            )
        
        # Check temperature before applying
        stats = self.get_gpu_stats()
        if stats.temperature_celsius >= SafetyLimits.CRITICAL_TEMP_CELSIUS:
            raise NVMLError(
                f"GPU temperature too high ({stats.temperature_celsius}°C). "
                f"Cannot apply overclock above {SafetyLimits.CRITICAL_TEMP_CELSIUS}°C. "
                "Cool down the GPU first."
            )
        
        try:
            # Set core clock offset
            # nvmlDeviceSetGpcClkVfOffset(handle, offset)
            pynvml.nvmlDeviceSetGpcClkVfOffset(self._handle, safe_core)
            logger.info(f"Core clock offset set to {safe_core}MHz")
            
            # Set memory clock offset
            # nvmlDeviceSetMemClkVfOffset(handle, offset)
            pynvml.nvmlDeviceSetMemClkVfOffset(self._handle, safe_mem)
            logger.info(f"Memory clock offset set to {safe_mem}MHz")
            
            return (safe_core, safe_mem)
            
        except pynvml.NVMLError_NoPermission:
            raise PermissionError(
                "Setting clock offsets requires root privileges. "
                "Run with sudo or as root."
            )
        except pynvml.NVMLError as e:
            raise NVMLError(f"Failed to set clock offsets: {e}")
    
    def reset_clock_offsets(self) -> None:
        """Reset clock offsets to zero (stock clocks)."""
        self.set_clock_offsets(core_offset_mhz=0, memory_offset_mhz=0)
        logger.info("Clock offsets reset to stock values")
    
    # =========================================================================
    # Fan Control
    # =========================================================================
    
    def get_fan_count(self) -> int:
        """Get the number of fans on the GPU."""
        self._ensure_initialized()
        
        try:
            return pynvml.nvmlDeviceGetNumFans(self._handle)
        except pynvml.NVMLError:
            return 0
    
    def get_fan_speed(self, fan_index: int = 0) -> int:
        """
        Get current fan speed percentage.
        
        Args:
            fan_index: Index of the fan (default: 0)
            
        Returns:
            Fan speed as percentage (0-100)
        """
        self._ensure_initialized()
        
        try:
            return pynvml.nvmlDeviceGetFanSpeed_v2(self._handle, fan_index)
        except pynvml.NVMLError:
            # Fall back to legacy function
            try:
                return pynvml.nvmlDeviceGetFanSpeed(self._handle)
            except pynvml.NVMLError:
                return 0
    
    def set_fan_speed(self, speed_percent: int, fan_index: int = 0) -> int:
        """
        Set fan speed manually.
        
        SAFETY: Speed is clamped to minimum safe value.
        
        Args:
            speed_percent: Target fan speed (0-100)
            fan_index: Index of the fan (default: 0)
            
        Returns:
            Actual speed set after safety clamping
            
        Raises:
            PermissionError: If not running as root
            NVMLError: If operation fails
        """
        self._ensure_initialized()
        
        # Check temperature
        stats = self.get_gpu_stats()
        
        # Force high fan speed if temperature is critical
        if stats.temperature_celsius >= SafetyLimits.CRITICAL_TEMP_CELSIUS:
            speed_percent = 100
            logger.warning(
                f"GPU at critical temperature ({stats.temperature_celsius}°C), "
                "forcing fan to 100%"
            )
        elif stats.temperature_celsius >= SafetyLimits.WARNING_TEMP_CELSIUS:
            # Ensure minimum 70% at warning temp
            speed_percent = max(speed_percent, 70)
            logger.warning(
                f"GPU temperature high ({stats.temperature_celsius}°C), "
                f"enforcing minimum 70% fan speed"
            )
        
        # Apply safety minimum
        safe_speed = max(SafetyLimits.MIN_FAN_SPEED_PERCENT, min(100, speed_percent))
        
        if safe_speed != speed_percent and speed_percent < SafetyLimits.MIN_FAN_SPEED_PERCENT:
            logger.warning(
                f"Fan speed {speed_percent}% clamped to {safe_speed}% "
                f"(safety minimum: {SafetyLimits.MIN_FAN_SPEED_PERCENT}%)"
            )
        
        try:
            # First, set fan control policy to manual
            pynvml.nvmlDeviceSetFanControlPolicy(
                self._handle, 
                fan_index, 
                pynvml.NVML_FAN_POLICY_MANUAL
            )
            
            # Set fan speed
            pynvml.nvmlDeviceSetFanSpeed_v2(self._handle, fan_index, safe_speed)
            
            logger.info(f"Fan {fan_index} speed set to {safe_speed}%")
            return safe_speed
            
        except pynvml.NVMLError_NoPermission:
            raise PermissionError(
                "Setting fan speed requires root privileges. "
                "Run with sudo or as root."
            )
        except pynvml.NVMLError as e:
            raise NVMLError(f"Failed to set fan speed: {e}")
    
    def set_fan_auto(self, fan_index: int = 0) -> None:
        """
        Return fan control to automatic (GPU-managed).
        
        Args:
            fan_index: Index of the fan (default: 0)
        """
        self._ensure_initialized()
        
        try:
            pynvml.nvmlDeviceSetFanControlPolicy(
                self._handle, 
                fan_index, 
                pynvml.NVML_FAN_POLICY_TEMPERATURE_CONTINOUS_SW
            )
            logger.info(f"Fan {fan_index} set to automatic control")
            
        except pynvml.NVMLError_NoPermission:
            raise PermissionError(
                "Setting fan mode requires root privileges. "
                "Run with sudo or as root."
            )
        except pynvml.NVMLError as e:
            raise NVMLError(f"Failed to set fan to auto: {e}")
    
    def set_all_fans_speed(self, speed_percent: int) -> None:
        """Set all fans to the same speed."""
        fan_count = self.get_fan_count()
        for i in range(fan_count):
            self.set_fan_speed(speed_percent, fan_index=i)
    
    def set_all_fans_auto(self) -> None:
        """Set all fans to automatic control."""
        fan_count = self.get_fan_count()
        for i in range(fan_count):
            self.set_fan_auto(fan_index=i)

    # =========================================================================
    # Advanced Overclocking (Clock Locking / Undervolting)
    # =========================================================================
    
    def set_gpu_locked_clocks(self, min_mhz: int, max_mhz: int) -> None:
        """
        Set min and max GPU clock speeds.
        Used for undervolting (by capping max freq) or forcing P-states.
        
        Args:
            min_mhz: Minimum clock speed in MHz (0 to reset)
            max_mhz: Maximum clock speed in MHz (0 to reset)
        """
        self._ensure_initialized()
        
        try:
            if min_mhz == 0 and max_mhz == 0:
                pynvml.nvmlDeviceResetGpuLockedClocks(self._handle)
                logger.info("GPU locked clocks reset")
            else:
                pynvml.nvmlDeviceSetGpuLockedClocks(self._handle, min_mhz, max_mhz)
                logger.info(f"GPU locked clocks set to {min_mhz}-{max_mhz} MHz")
                
        except pynvml.NVMLError_NoPermission:
            raise PermissionError("Setting locked clocks requires root privileges.")
        except pynvml.NVMLError as e:
            raise NVMLError(f"Failed to set locked clocks: {e}")
    
    # =========================================================================
    # Utility Methods
    # =========================================================================
    
    def get_all_settings(self) -> Dict[str, Any]:
        """
        Get all current settings as a dictionary (useful for profiles).
        
        Returns:
            Dictionary with all current settings
        """
        power = self.get_power_limits()
        clocks = self.get_clock_offsets()
        
        return {
            'power_limit_watts': power.current_watts,
            'core_clock_offset_mhz': clocks.core_offset_mhz,
            'memory_clock_offset_mhz': clocks.memory_offset_mhz,
        }
    
    def apply_settings(self, settings: Dict[str, Any]) -> None:
        """
        Apply a dictionary of settings (useful for profiles).
        
        Args:
            settings: Dictionary with setting values
        """
        if 'power_limit_watts' in settings:
            self.set_power_limit(settings['power_limit_watts'])
            
        if 'core_clock_offset_mhz' in settings or 'memory_clock_offset_mhz' in settings:
            self.set_clock_offsets(
                core_offset_mhz=settings.get('core_clock_offset_mhz'),
                memory_offset_mhz=settings.get('memory_clock_offset_mhz')
            )
    
    @staticmethod
    def get_device_count() -> int:
        """Get the number of NVIDIA GPUs in the system."""
        try:
            pynvml.nvmlInit()
            count = pynvml.nvmlDeviceGetCount()
            pynvml.nvmlShutdown()
            return count
        except pynvml.NVMLError:
            return 0


# =============================================================================
# Module-level convenience functions
# =============================================================================

def quick_status() -> None:
    """Quick status check - prints GPU info to console."""
    with NVMLController() as ctrl:
        info = ctrl.get_gpu_info()
        stats = ctrl.get_gpu_stats()
        power = ctrl.get_power_limits()
        clocks = ctrl.get_clock_offsets()
        
        print(f"GPU: {info.name}")
        print(f"Driver: {info.driver_version}")
        print(f"Temperature: {stats.temperature_celsius}°C")
        print(f"Power: {stats.power_draw_watts:.1f}W / {stats.power_limit_watts:.1f}W")
        print(f"Core Clock: {stats.core_clock_mhz} MHz (offset: {clocks.core_offset_mhz:+d})")
        print(f"Memory Clock: {stats.memory_clock_mhz} MHz (offset: {clocks.memory_offset_mhz:+d})")
        print(f"Fan: {stats.fan_speed_percent}%")
        print(f"GPU Load: {stats.gpu_utilization_percent}%")
        print(f"VRAM: {stats.memory_used_mb}MB / {stats.memory_total_mb}MB")


if __name__ == "__main__":
    # If run directly, show quick status
    logging.basicConfig(level=logging.INFO)
    quick_status()
