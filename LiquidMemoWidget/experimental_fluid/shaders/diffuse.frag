#version 330 core

// Light box blur on the dye so ink bleeds (晕开) a touch each frame.
// Kept gentle (small `amount`) to avoid the cross/diamond artefacts a strong
// 4-tap kernel would leave.

out vec4 fragColor;

in vec2 vUv;
in vec2 vL;
in vec2 vR;
in vec2 vT;
in vec2 vB;
uniform sampler2D uSource;
uniform float amount;

void main() {
    vec4 avg = 0.25 * (texture(uSource, vL) + texture(uSource, vR)
                     + texture(uSource, vT) + texture(uSource, vB));
    fragColor = mix(texture(uSource, vUv), avg, amount);
}
