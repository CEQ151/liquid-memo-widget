#version 330 core

// Full-screen quad. aPosition in [-1,1]. Outputs uv in [0,1] plus one-texel
// offsets so fragment shaders can sample neighbours without recomputing.

layout(location = 0) in vec2 aPosition;

uniform vec2 texelSize; // 1.0 / texture dimensions

out vec2 vUv;
out vec2 vL;
out vec2 vR;
out vec2 vT;
out vec2 vB;

void main() {
    vUv = aPosition * 0.5 + 0.5;
    vL = vUv - vec2(texelSize.x, 0.0);
    vR = vUv + vec2(texelSize.x, 0.0);
    vT = vUv + vec2(0.0, texelSize.y);
    vB = vUv - vec2(0.0, texelSize.y);
    gl_Position = vec4(aPosition, 0.0, 1.0);
}
