#include "gpu_effect_registry.h"

std::map<GPUEffectType, EffectRegistryEntry>& GPUEffectRegistry::Entries() {
    static std::map<GPUEffectType, EffectRegistryEntry> s_entries;
    return s_entries;
}

bool GPUEffectRegistry::Register(GPUEffectType type,
                                  std::function<GPUEffectBase*()> factory,
                                  int priority) {
    Entries()[type] = {factory, priority};
    return true;
}
