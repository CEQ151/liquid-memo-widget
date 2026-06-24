#version 330 core

// Gaussian "splat" added onto a target field (velocity or dye).
//   splat = exp(-dot(p,p)/radius) * color
//   out = base + splat

out vec4 fragColor;

in vec2 vUv;
uniform sampler2D uTarget;
uniform float aspectRatio;
uniform vec3 color;     // (dx,dy,0) for velocity, (r,g,b) for dye
uniform vec2 point;     // splat center in uv space
uniform float radius;

void main() {
    vec2 p = vUv - point;
    p.x *= aspectRatio;
    vec3 splat = exp(-dot(p, p) / radius) * color;
    vec3 base = texture(uTarget, vUv).xyz;
    fragColor = vec4(base + splat, 1.0);
}
