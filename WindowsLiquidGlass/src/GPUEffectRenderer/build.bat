@echo off
echo ============================================================
echo GPU Effect Renderer Build Script
echo ============================================================

:: 设置Visual Studio环境(根据你的VS版本调整)
if not defined VSCMD_VER (
    call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvarsall.bat" x64
)

:: 创建输出目录
if not exist bin mkdir bin

echo.
echo [1/3] 编译 HLSL Shader...
echo ============================================================

:: 编译边框特效Shader
fxc /T ps_5_0 /E PSMain /Fo bin\stroke_effect_ps.cso src\effects\stroke_effect.hlsl
if %ERRORLEVEL% NEQ 0 (
    echo ❌ Shader编译失败!
    pause
    exit /b 1
)

:: 编译光流特效Shader
fxc /T ps_5_0 /E PSMain /Fo bin\flow_effect_ps.cso src\effects\flow_effect.hlsl
if %ERRORLEVEL% NEQ 0 (
    echo ❌ 光流Shader编译失败!
    pause
    exit /b 1
)

:: 编译色散特效Shader
fxc /T ps_5_0 /E PSMain /Fo bin\chromatic_aberration_effect_ps.cso src\effects\chromatic_aberration_effect.hlsl
if %ERRORLEVEL% NEQ 0 (
    echo ❌ 色散Shader编译失败!
    pause
    exit /b 1
)

:: 编译高光特效Shader
fxc /T ps_5_0 /E PSMain /Fo bin\highlight_effect_ps.cso src\effects\highlight_effect.hlsl
if %ERRORLEVEL% NEQ 0 (
    echo ❌ 高光Shader编译失败!
    pause
    exit /b 1
)

:: 编译高斯模糊特效Shader（横向pass）
fxc /T ps_5_0 /E PSMain /Fo bin\blur_effect_horz_ps.cso src\effects\blur_effect_horz.hlsl
if %ERRORLEVEL% NEQ 0 (
    echo ❌ 模糊横向Shader编译失败!
    pause
    exit /b 1
)

:: 编译高斯模糊特效Shader（纵向pass）
fxc /T ps_5_0 /E PSMain /Fo bin\blur_effect_vert_ps.cso src\effects\blur_effect_vert.hlsl
if %ERRORLEVEL% NEQ 0 (
    echo ❌ 模糊纵向Shader编译失败!
    pause
    exit /b 1
)

:: 编译抗锯齿特效Shader（横向pass）
fxc /T ps_5_0 /E PSMain /Fo bin\anti_aliasing_effect_horz_ps.cso src\effects\anti_aliasing_effect_horz.hlsl
if %ERRORLEVEL% NEQ 0 (
    echo ❌ 抗锯齿横向Shader编译失败!
    pause
    exit /b 1
)

:: 编译抗锯齿特效Shader（纵向pass+SDF遮罩）
fxc /T ps_5_0 /E PSMain /Fo bin\anti_aliasing_effect_vert_ps.cso src\effects\anti_aliasing_effect_vert.hlsl
if %ERRORLEVEL% NEQ 0 (
    echo ❌ 抗锯齿纵向Shader编译失败!
    pause
    exit /b 1
)

:: 编译调色特效Shader
fxc /T ps_5_0 /E PSMain /Fo bin\color_grading_effect_ps.cso src\effects\color_grading_effect.hlsl
if %ERRORLEVEL% NEQ 0 (
    echo ❌ 调色Shader编译失败!
    pause
    exit /b 1
)

:: 编译颜色叠加滤镜特效Shader
fxc /T ps_5_0 /E PSMain /Fo bin\color_overlay_effect_ps.cso src\effects\color_overlay_effect.hlsl
if %ERRORLEVEL% NEQ 0 (
    echo ❌ 颜色叠加Shader编译失败!
    pause
    exit /b 1
)

echo ✅ Shader编译完成

echo.
echo [2/3] 编译 C++ 代码...
echo ============================================================

:: 编译DLL
cl /LD /EHsc /std:c++17 /O2 ^
    /D GPU_EFFECT_RENDERER_EXPORTS ^
    /I"." ^
    /I"src" ^
    /I"..\GPUDeviceManager\src" ^
    src\gpu_effect_renderer.cpp ^
    src\gpu_effect_api.cpp ^
    src\gpu_effect_registry.cpp ^
    src\effects\stroke_effect.cpp ^
    src\effects\flow_effect.cpp ^
    src\effects\chromatic_aberration_effect.cpp ^
    src\effects\highlight_effect.cpp ^
    src\effects\blur_effect.cpp ^
    src\effects\anti_aliasing_effect.cpp ^
    src\effects\color_grading_effect.cpp ^
    src\effects\color_overlay_effect.cpp ^
    /link ^
    /OUT:bin\gpu_effect_renderer.dll ^
    /LIBPATH:..\GPUDeviceManager\bin gpu_device_manager.lib ^
    d3d11.lib d3dcompiler.lib dxgi.lib

if %ERRORLEVEL% NEQ 0 (
    echo ❌ DLL编译失败!
    pause
    exit /b 1
)

echo ✅ DLL编译完成

echo.
echo [3/3] 清理临时文件...
echo ============================================================

:: 清理中间文件
del *.obj 2>nul
del *.exp 2>nul
del *.lib 2>nul

echo ✅ 清理完成

echo.
echo ============================================================
echo ✅ 构建完成!
echo ============================================================
echo.
echo 输出文件:
echo   bin\gpu_effect_renderer.dll
echo   bin\stroke_effect_ps.cso
echo   bin\flow_effect_ps.cso
echo   bin\chromatic_aberration_effect_ps.cso
echo   bin\highlight_effect_ps.cso
echo   bin\blur_effect_horz_ps.cso
echo   bin\blur_effect_vert_ps.cso
echo   bin\anti_aliasing_effect_horz_ps.cso
echo   bin\anti_aliasing_effect_vert_ps.cso
echo   bin\color_grading_effect_ps.cso
  bin\color_overlay_effect_ps.cso
echo.

pause