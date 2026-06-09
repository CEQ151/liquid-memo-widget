#pragma once

/*
 * gpu_effect_registry.h
 *
 * 特效自注册机制。在每个 xxx_effect.cpp 末尾添加一行：
 *   REGISTER_EFFECT(GPUEffectType::Flow, FlowEffect, 10)
 * 渲染器 Initialize() 会自动发现并实例化所有注册的特效，无需手动修改渲染器代码。
 *
 * renderPriority：数越小越先渲染（Flow=10、Chromatic=20、… AntiAliasing=80）
 */

#include "gpu_effect_types.h"
#include <functional>
#include <map>

class GPUEffectBase;

struct EffectRegistryEntry {
    std::function<GPUEffectBase*()> factory;
    int                             renderPriority;
};

class GPUEffectRegistry {
public:
    // 全局注册表（进程级单例）
    static std::map<GPUEffectType, EffectRegistryEntry>& Entries();

    // 由 REGISTER_EFFECT 宏在全局静态初始化期间调用
    static bool Register(GPUEffectType type,
                         std::function<GPUEffectBase*()> factory,
                         int priority);
};

// ─────────────────────────────────────────────────────────────────────────────
//  使用方式：放在 xxx_effect.cpp 文件末尾
//  REGISTER_EFFECT(GPUEffectType::Flow, FlowEffect, 10)
// ─────────────────────────────────────────────────────────────────────────────
#define REGISTER_EFFECT(type, cls, priority)                                    \
    namespace {                                                                  \
        static bool _registered_##cls =                                          \
            GPUEffectRegistry::Register(                                         \
                type,                                                             \
                []() -> GPUEffectBase* { return new cls(); },                   \
                priority);                                                        \
    }
