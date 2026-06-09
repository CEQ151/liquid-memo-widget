/*
 * 文件名: apple_rounded_rect_gpu.cpp
 * 功能: 苹果圆角矩形GPU生成器 - 完全GPU化 + 资源池集成
 *
 * 缓存策略：每个实例持有唯一 fixedResourceID（SDF 段 1000~1999）
 *   - tag 相同且尺寸相同 → 直接返回，不重新生成
 *   - tag 不同但尺寸相同  → 重新 Dispatch，就地更新纹理内容，ID 不变
 *   - 尺寸变化            → 重建纹理，UpdateResourceInPool 更新指针，ID 不变
 */

#include <d3d11.h>
#include <d3dcompiler.h>
#include <vector>
#include <string>
#include <sstream>
#include <windows.h>
#include <algorithm>

#pragma comment(lib, "d3d11.lib")
#pragma comment(lib, "d3dcompiler.lib")

#ifdef APPLE_ROUNDED_RECT_GPU_EXPORTS
#define ARRGPU_API __declspec(dllexport)
#else
#define ARRGPU_API __declspec(dllimport)
#endif

#ifdef min
#undef min
#endif
#ifdef max
#undef max
#endif

// ============================================================
//  SDF 资源 ID 段（与 gpu_types.h 保持一致）
// ============================================================

static const UINT64 ARRGPU_SDF_SLOT_BEGIN = 1000;
static const UINT64 ARRGPU_SDF_SLOT_END   = 1999;

// ============================================================
//  前置声明 - GPU设备管理器接口
// ============================================================

extern "C" {
    typedef int    (__stdcall *GPUMgr_UpdateResourceInPoolFunc)(
        void* handle, UINT64 resourceId, void* newResource, void* newSRV, const char* newTag);

    typedef UINT64 (__stdcall *GPUMgr_AddResourceToPoolInSlotFunc)(
        void* handle, void* resource, int type, void* srv, int ownerGPU,
        const char* tag, UINT64 slotBegin, UINT64 slotEnd);

    typedef int    (__stdcall *GPUMgr_GetResourceFromPoolFunc)(
        void* handle, UINT64 resourceId, void** outResource, void** outSRV,
        int* type, int* width, int* height, int* ownerGPU);

    typedef void   (__stdcall *GPUMgr_RemoveResourceFromPoolFunc)(void* handle, UINT64 resourceId);
}

// ============================================================
//  错误日志
// ============================================================

static std::string g_lastError;

void SetLastErrorMsg(const std::string& error) {
    g_lastError = error;
    OutputDebugStringA("[ARRGPU] ");
    OutputDebugStringA(error.c_str());
    OutputDebugStringA("\n");
}

std::wstring GetDLLDirectory() {
    wchar_t path[MAX_PATH];
    HMODULE hModule = NULL;
    GetModuleHandleExW(
        GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
        (LPCWSTR)&GetDLLDirectory, &hModule);
    GetModuleFileNameW(hModule, path, MAX_PATH);
    std::wstring fullPath(path);
    size_t pos = fullPath.rfind(L'\\');
    return (pos != std::wstring::npos) ? fullPath.substr(0, pos + 1) : L"";
}

// ============================================================
//  常量缓冲区结构体
// ============================================================

struct AppleRoundedRectParams {
    float rectWidth;
    float rectHeight;
    float cornerRadius;
    float radiusRatio;
    float centerOffsetX;
    float centerOffsetY;
    float scale;
    float _padding;
};

// ============================================================
//  主类
// ============================================================

class AppleRoundedRectGPU {
public:
    AppleRoundedRectGPU() = default;
    ~AppleRoundedRectGPU() { Cleanup(); }

    bool Initialize(ID3D11Device* device, ID3D11DeviceContext* context);
    bool InitializeWithOwnDevice();
    void EnableResourcePool(void* gpuManagerDLLPath, void* gpuMgrHandle);
    bool GenerateSDF(float width, float height, float radiusRatio, float scale = 1.0f);
    bool ReadbackSDF(float* output, int width, int height);

    ID3D11Texture2D*            GetSDFTexture() { return sdfTexture; }
    ID3D11ShaderResourceView*   GetSDFSRV()     { return sdfSRV; }
    UINT64 GetCurrentSDFResourceID()            { return fixedResourceID; }

private:
    // D3D11
    ID3D11Device*               device       = nullptr;
    ID3D11DeviceContext*        context      = nullptr;
    bool                        ownsDevice   = false;

    // Shaders / buffers
    ID3D11ComputeShader*        generateShader  = nullptr;
    ID3D11Buffer*               paramsBuffer    = nullptr;

    // SDF 纹理
    ID3D11Texture2D*            sdfTexture      = nullptr;
    ID3D11UnorderedAccessView*  sdfUAV          = nullptr;
    ID3D11ShaderResourceView*   sdfSRV          = nullptr;
    ID3D11Texture2D*            sdfStagingTexture = nullptr;

    int currentWidth  = 0;
    int currentHeight = 0;

    // 资源池集成
    HMODULE                             gpuManagerDLL     = nullptr;
    void*                               gpuManagerHandle  = nullptr;  // GPUContext handle
    GPUMgr_UpdateResourceInPoolFunc     updateResourceFunc  = nullptr;
    GPUMgr_AddResourceToPoolInSlotFunc  addInSlotFunc       = nullptr;
    GPUMgr_GetResourceFromPoolFunc      getResourceFunc     = nullptr;
    GPUMgr_RemoveResourceFromPoolFunc   removeResourceFunc  = nullptr;

    // 单一固定 ID + tag 缓存
    UINT64      fixedResourceID = 0;   // 整个实例生命周期内保持不变
    std::string lastTag;               // 上次生成所用的 tag

    // 辅助
    bool CompileShaderFromFile(const wchar_t* filename, const char* entryPoint,
                               const char* target, ID3D11ComputeShader** outShader);
    bool CreateTextures(int width, int height);
    bool CreateConstantBuffers();
    std::string MakeSDFTag(int w, int h, float r, float s);
    bool DispatchCompute(float width, float height, float radiusRatio, float scale);
    void Cleanup();

    template<typename T>
    void SafeRelease(T*& ptr) { if (ptr) { ptr->Release(); ptr = nullptr; } }
};

// ============================================================
//  实现
// ============================================================

bool AppleRoundedRectGPU::InitializeWithOwnDevice() {
    D3D_FEATURE_LEVEL featureLevels[] = { D3D_FEATURE_LEVEL_11_0 };
    D3D_FEATURE_LEVEL featureLevel;
    HRESULT hr = D3D11CreateDevice(
        nullptr, D3D_DRIVER_TYPE_HARDWARE, nullptr, 0,
        featureLevels, 1, D3D11_SDK_VERSION,
        &device, &featureLevel, &context);
    if (FAILED(hr)) { SetLastErrorMsg("D3D11CreateDevice failed"); return false; }
    ownsDevice = true;
    return Initialize(device, context);
}

bool AppleRoundedRectGPU::Initialize(ID3D11Device* dev, ID3D11DeviceContext* ctx) {
    device  = dev;
    context = ctx;

    std::wstring shaderPath = GetDLLDirectory() + L"apple_rounded_rect_perfect.hlsl";
    if (!CompileShaderFromFile(shaderPath.c_str(),
                               "CSGenerateAppleRoundedRect", "cs_5_0", &generateShader)) {
        SetLastErrorMsg("Failed to compile shader");
        return false;
    }
    if (!CreateConstantBuffers()) {
        SetLastErrorMsg("Failed to create constant buffers");
        return false;
    }
    return true;
}

void AppleRoundedRectGPU::EnableResourcePool(void* gpuManagerDLLPath, void* gpuMgrHandle) {
    if (!gpuManagerDLLPath || !gpuMgrHandle) return;

    gpuManagerHandle = gpuMgrHandle;

    gpuManagerDLL = LoadLibraryW((const wchar_t*)gpuManagerDLLPath);
    if (!gpuManagerDLL) { SetLastErrorMsg("Failed to load GPU Manager DLL"); return; }

    updateResourceFunc = (GPUMgr_UpdateResourceInPoolFunc)
        GetProcAddress(gpuManagerDLL, "GPUMgr_UpdateResourceInPool");
    addInSlotFunc = (GPUMgr_AddResourceToPoolInSlotFunc)
        GetProcAddress(gpuManagerDLL, "GPUMgr_AddResourceToPoolInSlot");
    getResourceFunc = (GPUMgr_GetResourceFromPoolFunc)
        GetProcAddress(gpuManagerDLL, "GPUMgr_GetResourceFromPool");
    removeResourceFunc = (GPUMgr_RemoveResourceFromPoolFunc)
        GetProcAddress(gpuManagerDLL, "GPUMgr_RemoveResourceFromPool");

    if (addInSlotFunc && updateResourceFunc)
        SetLastErrorMsg("Resource Pool enabled");
    else
        SetLastErrorMsg("Resource Pool partially available");
}

std::string AppleRoundedRectGPU::MakeSDFTag(int w, int h, float r, float s) {
    char buf[128];
    snprintf(buf, sizeof(buf), "sdf_%d_%d_%.4f_%.4f", w, h, r, s);
    return std::string(buf);
}

bool AppleRoundedRectGPU::DispatchCompute(float width, float height,
                                           float radiusRatio, float scale) {
    float minDim = (width < height) ? width : height;

    AppleRoundedRectParams params;
    params.rectWidth     = width;
    params.rectHeight    = height;
    params.cornerRadius  = radiusRatio * minDim * 0.5f;
    params.radiusRatio   = radiusRatio;
    params.scale         = scale;
    params.centerOffsetX = (width  - width  * scale) * 0.5f;
    params.centerOffsetY = (height - height * scale) * 0.5f;

    D3D11_MAPPED_SUBRESOURCE mapped;
    context->Map(paramsBuffer, 0, D3D11_MAP_WRITE_DISCARD, 0, &mapped);
    memcpy(mapped.pData, &params, sizeof(AppleRoundedRectParams));
    context->Unmap(paramsBuffer, 0);

    context->CSSetShader(generateShader, nullptr, 0);
    context->CSSetConstantBuffers(0, 1, &paramsBuffer);
    context->CSSetUnorderedAccessViews(0, 1, &sdfUAV, nullptr);

    int threadGroupsX = ((int)width  + 7) / 8;
    int threadGroupsY = ((int)height + 7) / 8;
    context->Dispatch(threadGroupsX, threadGroupsY, 1);

    ID3D11UnorderedAccessView* nullUAV = nullptr;
    context->CSSetUnorderedAccessViews(0, 1, &nullUAV, nullptr);
    return true;
}

bool AppleRoundedRectGPU::GenerateSDF(float width, float height,
                                       float radiusRatio, float scale) {
    int w = (int)width;
    int h = (int)height;
    std::string tag = MakeSDFTag(w, h, radiusRatio, scale);

    // ── 情况 1：tag 完全相同，直接返回（内容未变）────────────────────────
    if (tag == lastTag && fixedResourceID != 0) {
        SetLastErrorMsg("SDF cache hit (same tag)");
        return true;
    }

    bool sizeChanged = (w != currentWidth || h != currentHeight);

    // ── 情况 2/3：需要重新生成 ─────────────────────────────────────────────
    if (sizeChanged) {
        // 尺寸变化 → 重建纹理（旧 D3D11 对象被 Release，新对象被创建）
        if (!CreateTextures(w, h)) return false;
    }

    // 执行 Compute Shader（更新 sdfTexture 的内容）
    if (!DispatchCompute(width, height, radiusRatio, scale)) return false;

    // ── 资源池注册 / 更新 ─────────────────────────────────────────────────
    if (addInSlotFunc) {
        if (fixedResourceID == 0) {
            // 首次：注册到 SDF 段，拿到固定 ID
            fixedResourceID = addInSlotFunc(
                gpuManagerHandle,
                sdfTexture, 0 /*Texture2D*/, sdfSRV, 0,
                tag.c_str(),
                ARRGPU_SDF_SLOT_BEGIN, ARRGPU_SDF_SLOT_END);
        } else {
            // 后续：ID 不变，只更新纹理指针（尺寸变化时指针变了）和 tag
            if (updateResourceFunc) {
                updateResourceFunc(gpuManagerHandle, fixedResourceID, sdfTexture, sdfSRV, tag.c_str());
            }
        }
    }

    lastTag = tag;
    return true;
}

bool AppleRoundedRectGPU::ReadbackSDF(float* output, int width, int height) {
    if (width != currentWidth || height != currentHeight) {
        SetLastErrorMsg("Readback size mismatch");
        return false;
    }
    context->CopyResource(sdfStagingTexture, sdfTexture);

    D3D11_MAPPED_SUBRESOURCE mapped;
    if (FAILED(context->Map(sdfStagingTexture, 0, D3D11_MAP_READ, 0, &mapped))) {
        SetLastErrorMsg("Failed to map staging texture");
        return false;
    }
    for (int y = 0; y < height; y++) {
        float* srcRow = (float*)((BYTE*)mapped.pData + y * mapped.RowPitch);
        memcpy(output + y * width, srcRow, width * sizeof(float));
    }
    context->Unmap(sdfStagingTexture, 0);
    return true;
}

bool AppleRoundedRectGPU::CreateTextures(int width, int height) {
    SafeRelease(sdfTexture);
    SafeRelease(sdfUAV);
    SafeRelease(sdfSRV);
    SafeRelease(sdfStagingTexture);

    D3D11_TEXTURE2D_DESC texDesc = {};
    texDesc.Width            = width;
    texDesc.Height           = height;
    texDesc.MipLevels        = 1;
    texDesc.ArraySize        = 1;
    texDesc.Format           = DXGI_FORMAT_R32_FLOAT;
    texDesc.SampleDesc.Count = 1;
    texDesc.Usage            = D3D11_USAGE_DEFAULT;
    texDesc.BindFlags        = D3D11_BIND_UNORDERED_ACCESS | D3D11_BIND_SHADER_RESOURCE;

    if (FAILED(device->CreateTexture2D(&texDesc, nullptr, &sdfTexture))) return false;

    D3D11_UNORDERED_ACCESS_VIEW_DESC uavDesc = {};
    uavDesc.Format        = DXGI_FORMAT_R32_FLOAT;
    uavDesc.ViewDimension = D3D11_UAV_DIMENSION_TEXTURE2D;
    if (FAILED(device->CreateUnorderedAccessView(sdfTexture, &uavDesc, &sdfUAV))) return false;

    D3D11_SHADER_RESOURCE_VIEW_DESC srvDesc = {};
    srvDesc.Format                  = DXGI_FORMAT_R32_FLOAT;
    srvDesc.ViewDimension           = D3D11_SRV_DIMENSION_TEXTURE2D;
    srvDesc.Texture2D.MipLevels     = 1;
    if (FAILED(device->CreateShaderResourceView(sdfTexture, &srvDesc, &sdfSRV))) return false;

    texDesc.Usage          = D3D11_USAGE_STAGING;
    texDesc.BindFlags      = 0;
    texDesc.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
    if (FAILED(device->CreateTexture2D(&texDesc, nullptr, &sdfStagingTexture))) return false;

    currentWidth  = width;
    currentHeight = height;
    return true;
}

bool AppleRoundedRectGPU::CreateConstantBuffers() {
    D3D11_BUFFER_DESC cbDesc = {};
    cbDesc.ByteWidth      = sizeof(AppleRoundedRectParams);
    cbDesc.Usage          = D3D11_USAGE_DYNAMIC;
    cbDesc.BindFlags      = D3D11_BIND_CONSTANT_BUFFER;
    cbDesc.CPUAccessFlags = D3D11_CPU_ACCESS_WRITE;
    return SUCCEEDED(device->CreateBuffer(&cbDesc, nullptr, &paramsBuffer));
}

bool AppleRoundedRectGPU::CompileShaderFromFile(const wchar_t* filename,
                                                const char* entryPoint,
                                                const char* target,
                                                ID3D11ComputeShader** outShader) {
    ID3DBlob* shaderBlob = nullptr;
    ID3DBlob* errorBlob  = nullptr;
    HRESULT hr = D3DCompileFromFile(
        filename, nullptr, D3D_COMPILE_STANDARD_FILE_INCLUDE,
        entryPoint, target, D3DCOMPILE_ENABLE_STRICTNESS, 0,
        &shaderBlob, &errorBlob);
    if (FAILED(hr)) {
        if (errorBlob) { SetLastErrorMsg((char*)errorBlob->GetBufferPointer()); errorBlob->Release(); }
        return false;
    }
    hr = device->CreateComputeShader(
        shaderBlob->GetBufferPointer(), shaderBlob->GetBufferSize(), nullptr, outShader);
    shaderBlob->Release();
    return SUCCEEDED(hr);
}

void AppleRoundedRectGPU::Cleanup() {
    // 从资源池移除（还 ID 回空闲池）
    if (fixedResourceID != 0 && removeResourceFunc && gpuManagerHandle) {
        removeResourceFunc(gpuManagerHandle, fixedResourceID);
        fixedResourceID = 0;
    }

    SafeRelease(generateShader);
    SafeRelease(sdfTexture);
    SafeRelease(sdfUAV);
    SafeRelease(sdfSRV);
    SafeRelease(sdfStagingTexture);
    SafeRelease(paramsBuffer);

    if (ownsDevice) {
        SafeRelease(context);
        SafeRelease(device);
    }
    if (gpuManagerDLL) {
        FreeLibrary(gpuManagerDLL);
        gpuManagerDLL = nullptr;
    }
}

// ============================================================
//  C API
// ============================================================

extern "C" {

ARRGPU_API void* __stdcall ARRGPU_Create() {
    return new AppleRoundedRectGPU();
}

ARRGPU_API void* __stdcall ARRGPU_CreateAndInit() {
    auto* gen = new AppleRoundedRectGPU();
    if (!gen->InitializeWithOwnDevice()) { delete gen; return nullptr; }
    return gen;
}

ARRGPU_API void __stdcall ARRGPU_Destroy(void* handle) {
    delete (AppleRoundedRectGPU*)handle;
}

ARRGPU_API int __stdcall ARRGPU_Initialize(void* handle, void* device, void* context) {
    return ((AppleRoundedRectGPU*)handle)->Initialize(
        (ID3D11Device*)device, (ID3D11DeviceContext*)context) ? 1 : 0;
}

ARRGPU_API void __stdcall ARRGPU_EnableResourcePool(void* handle, const wchar_t* dllPath, void* gpuMgrHandle) {
    ((AppleRoundedRectGPU*)handle)->EnableResourcePool((void*)dllPath, gpuMgrHandle);
}

ARRGPU_API int __stdcall ARRGPU_GenerateSDF(void* handle, float width, float height,
                                             float radiusRatio, float scale) {
    return ((AppleRoundedRectGPU*)handle)->GenerateSDF(width, height, radiusRatio, scale) ? 1 : 0;
}

ARRGPU_API int __stdcall ARRGPU_ReadbackSDF(void* handle, float* output,
                                             int width, int height) {
    return ((AppleRoundedRectGPU*)handle)->ReadbackSDF(output, width, height) ? 1 : 0;
}

ARRGPU_API UINT64 __stdcall ARRGPU_GetCurrentResourceID(void* handle) {
    return ((AppleRoundedRectGPU*)handle)->GetCurrentSDFResourceID();
}

ARRGPU_API const char* __stdcall ARRGPU_GetLastError() {
    return g_lastError.c_str();
}

} // extern "C"