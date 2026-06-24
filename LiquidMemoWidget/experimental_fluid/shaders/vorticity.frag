#version 330 core

// Vorticity confinement: inject a small rotational force back into the
// velocity field so the fluid keeps curling instead of dying flat.

out vec4 fragColor;

in vec2 vUv;
in vec2 vL;
in vec2 vR;
in vec2 vT;
in vec2 vB;
uniform sampler2D uVelocity;
uniform sampler2D uCurl;
uniform float curl;     // confinement strength
uniform float dt;

void main() {
    float L = texture(uCurl, vL).x;
    float R = texture(uCurl, vR).x;
    float T = texture(uCurl, vT).x;
    float B = texture(uCurl, vB).x;
    float C = texture(uCurl, vUv).x;

    vec2 force = 0.5 * vec2(abs(T) - abs(B), abs(R) - abs(L));
    force /= length(force) + 0.0001;
    force *= curl * C;
    force.y *= -1.0;

    vec2 velocity = texture(uVelocity, vUv).xy;
    velocity += force * dt;
    velocity = clamp(velocity, vec2(-1000.0), vec2(1000.0));
    fragColor = vec4(velocity, 0.0, 1.0);
}
