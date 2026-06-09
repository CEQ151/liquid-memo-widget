from .src.gpu_device_manager_wrapper import GPUDeviceManager, GPUPreference, GPUResourceType
import os
GPU_MGR_DLL = os.path.join(os.path.dirname(__file__), "bin", "gpu_device_manager.dll").replace("\\", "/")

__all__ = ["GPUDeviceManager", "GPUPreference", "GPUResourceType", "GPU_MGR_DLL"]