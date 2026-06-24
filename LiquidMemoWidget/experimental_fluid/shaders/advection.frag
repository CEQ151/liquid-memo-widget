#version 330 core

// Semi-Lagrangian advection: walk backwards along the velocity field and
// sample the source, then divide by a per-step decay.
//
//   coord  = uv - dt * v * texelSize
//   result = sample(source, coord) / decay
//
// `decay` is precomputed on the CPU so velocity (1 + damping*dt) and dye
// (1 / persistence) can use the same shader with different fade behaviour.

out vec4 fragColor;

in vec2 vUv;
uniform sampler2D uVelocity;
uniform sampler2D uSource;
uniform vec2 texelSize;     // velocity texel size
uniform float dt;
uniform float decay;

void main() {
    vec2 coord = vUv - dt * texture(uVelocity, vUv).xy * texelSize;
    vec4 result = texture(uSource, coord);
    fragColor = result / decay;
}
