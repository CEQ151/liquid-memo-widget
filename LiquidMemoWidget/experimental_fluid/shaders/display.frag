#version 330 core

// Ink-wash display: ink concentration -> paper / mid-ink / deep-ink tone ramp,
// with a soft watermark edge, 宣纸 paper texture, dry-brush 飞白 and dithering.
// Desktop GL 3.3 core guarantees linear filtering of RGBA16F, so the dye is
// already smoothly upsampled — no manual bilinear is needed here.

out vec4 fragColor;

in vec2 vUv;
in vec2 vL;
in vec2 vR;
in vec2 vT;
in vec2 vB;
uniform sampler2D uDye;        // ink concentration (stored in .r)
uniform vec3 uPaper;           // 宣纸底色
uniform vec3 uMid;             // 中墨
uniform vec3 uDeep;            // 浓墨
uniform float uDensity;        // 浓度倍率
uniform float uGamma;          // 浓淡对比
uniform float uEdge;           // 边缘晕染
uniform float uDry;            // 飞白
uniform float uPaperTex;       // 宣纸纹理

float hash(vec2 p) {
    p = fract(p * vec2(123.34, 456.21));
    p += dot(p, p + 45.32);
    return fract(p.x * p.y);
}
float vnoise(vec2 p) {
    vec2 i = floor(p), f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    float a = hash(i), b = hash(i + vec2(1, 0)), c = hash(i + vec2(0, 1)), d = hash(i + vec2(1, 1));
    return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
}
float fbm(vec2 p) {
    float s = 0.0, a = 0.5;
    for (int i = 0; i < 5; i++) { s += a * vnoise(p); p *= 2.02; a *= 0.5; }
    return s;
}

float conc(vec2 uv) { return texture(uDye, uv).r; }

vec3 ramp(float t) {
    t = clamp(t, 0.0, 1.0);
    if (t < 0.55) return mix(uPaper, uMid, smoothstep(0.0, 0.55, t));
    return mix(uMid, uDeep, smoothstep(0.55, 1.0, t));
}

void main() {
    float c = conc(vUv);
    float t = pow(clamp(c * uDensity, 0.0, 1.0), uGamma);

    // 宣纸纹理（静态纤维 + 细颗粒）
    float fiber = fbm(vUv * vec2(180.0, 34.0));
    float grain = fbm(vUv * 760.0);
    float paperShade = mix(1.0, 0.55 * fiber + 0.45 * grain, uPaperTex);

    vec3 col = ramp(t);

    // 柔和水痕：只在有墨处轻轻加深，不画硬轮廓（否则边像贪吃蛇）
    float em = length(vec2(conc(vR) - conc(vL), conc(vT) - conc(vB)));
    float edgeDark = uEdge * smoothstep(0.0, 0.35, em * 3.0) * smoothstep(0.04, 0.22, c);
    col *= 1.0 - 0.3 * edgeDark;

    col *= mix(1.0, paperShade, 0.7);

    // 飞白：墨稀薄处用高频噪声打断，露出纸
    float dry = fbm(vUv * 520.0);
    float thinness = (1.0 - smoothstep(0.02, 0.4, t)) * step(0.015, t);
    col = mix(col, uPaper * paperShade, uDry * thinness * (1.0 - dry));

    // 完全空白处即带纹理的纸
    col = mix(uPaper * paperShade, col, smoothstep(0.0, 0.02, c));

    // 抖动：打散 8bit 色带（线条感）
    col += (hash(gl_FragCoord.xy) - 0.5) / 255.0;
    fragColor = vec4(col, 1.0);
}
