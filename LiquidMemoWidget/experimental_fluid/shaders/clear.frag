#version 330 core

// Multiply texture by a scalar (used to decay the pressure field each frame).

out vec4 fragColor;

in vec2 vUv;
uniform sampler2D uTexture;
uniform float value;

void main() {
    fragColor = value * texture(uTexture, vUv);
}
