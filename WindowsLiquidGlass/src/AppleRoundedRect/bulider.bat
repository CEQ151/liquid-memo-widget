@echo off
REM ============================================================
REM 使用 Visual Studio 2022 直接编译 Apple Rounded Rect GPU DLL
REM 不需要 CMake
REM ============================================================

setlocal enabledelayedexpansion

echo ============================================================
echo 苹果圆角矩形 GPU DLL 编译脚本
echo 使用 Visual Studio 2022
echo ============================================================
echo.

REM 设置 Visual Studio 2022 环境变量
REM 尝试常见的安装路径
set "VS_PATH=C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat"
if not exist "%VS_PATH%" (
    set "VS_PATH=C:\Program Files\Microsoft Visual Studio\2022\Professional\VC\Auxiliary\Build\vcvars64.bat"
)
if not exist "%VS_PATH%" (
    set "VS_PATH=C:\Program Files\Microsoft Visual Studio\2022\Enterprise\VC\Auxiliary\Build\vcvars64.bat"
)

if not exist "%VS_PATH%" (
    echo 错误: 未找到 Visual Studio 2022 安装
    echo 请确保已安装 Visual Studio 2022
    pause
    exit /b 1
)

echo 正在加载 Visual Studio 2022 环境...
call "%VS_PATH%"
echo.

REM 创建输出目录
if not exist "bin" mkdir bin
if not exist "obj" mkdir obj

echo 正在编译 apple_rounded_rect_gpu.dll ...
echo.

REM 编译参数说明:
REM /LD            - 创建 DLL
REM /EHsc          - 启用 C++ 异常处理
REM /O2            - 优化代码
REM /MD            - 使用多线程 DLL 运行时库
REM /W3            - 警告级别 3
REM /DAPPLE_ROUNDED_RECT_GPU_EXPORTS - 定义导出宏
REM /std:c++17     - 使用 C++17 标准
REM /Fo            - 指定对象文件输出目录
REM /Fe            - 指定可执行文件输出目录

cl /LD /EHsc /O2 /MD /W3 ^
   /DAPPLE_ROUNDED_RECT_GPU_EXPORTS ^
   /std:c++17 ^
   /Fo"obj\\" ^
   /Fe"bin\\" ^
   src\apple_rounded_rect_gpu.cpp ^
   d3d11.lib d3dcompiler.lib

if errorlevel 1 (
    echo.
    echo 编译失败！
    pause
    exit /b 1
)

echo.
echo 正在复制 HLSL shader 文件...
copy /Y src\apple_rounded_rect_perfect.hlsl bin\apple_rounded_rect_perfect.hlsl >nul

if errorlevel 1 (
    echo 警告: HLSL 文件复制失败
) else (
    echo HLSL 文件复制成功
)

rd /s /q obj >nul

echo.
echo ============================================================
echo 编译成功！
echo 输出文件:
echo   - bin\apple_rounded_rect_gpu.dll
echo   - bin\apple_rounded_rect_gpu.lib
echo   - bin\apple_rounded_rect_perfect.hlsl
echo ============================================================
echo.

pause