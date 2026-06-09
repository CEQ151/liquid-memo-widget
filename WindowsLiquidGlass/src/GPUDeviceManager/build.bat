@echo off
REM 文件名: build.bat
REM 功能: 编译GPU设备管理器DLL (支持 D3D11/OpenGL 互操作)

echo ====================================
echo Building GPU Device Manager DLL
echo ====================================

set VS_PATH=C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build
if not exist "%VS_PATH%\vcvars64.bat" (
    echo Error: Visual Studio 2022 not found!
    pause
    exit /b 1
)

call "%VS_PATH%\vcvars64.bat"

set SRC_DIR=src
set BIN_DIR=bin

if not exist %BIN_DIR% mkdir %BIN_DIR%

echo.
echo Compiling source files...

cl /c ^
    /EHsc /O2 /std:c++17 ^
    /DGPU_DEVICE_MANAGER_EXPORTS ^
    /I"%DXSDK_DIR%\Include" ^
    %SRC_DIR%\gpu_device_manager.cpp ^
    %SRC_DIR%\gpu_resource_pool.cpp ^
    %SRC_DIR%\gpu_display_capture.cpp ^
    %SRC_DIR%\gpu_manager_api.cpp ^
    %SRC_DIR%\gpu_gl_interop.cpp ^
    %SRC_DIR%\gpu_swapchain_presenter.cpp

if %errorlevel% neq 0 (
    echo Error: Compilation failed!
    pause
    exit /b 1
)

echo.
echo Linking DLL...

link /DLL /OUT:%BIN_DIR%\gpu_device_manager.dll ^
    gpu_device_manager.obj ^
    gpu_resource_pool.obj ^
    gpu_display_capture.obj ^
    gpu_manager_api.obj ^
    gpu_gl_interop.obj ^
    gpu_swapchain_presenter.obj ^
    d3d11.lib dxgi.lib dcomp.lib user32.lib opengl32.lib

if %errorlevel% neq 0 (
    echo Error: Linking failed!
    pause
    exit /b 1
)

echo.
echo Cleaning up temporary files...
del *.obj

echo.
echo ====================================
echo Build completed successfully!
echo Output: %BIN_DIR%\gpu_device_manager.dll
echo ====================================
echo.
echo Features:
echo - D3D11 Device Management
echo - GPU Resource Pool
echo - Desktop Duplication Capture
echo - D3D11/OpenGL Zero-Copy Interop
echo ====================================

pause