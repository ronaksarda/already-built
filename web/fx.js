/* Already Built? — playful layer.
   1. Background: a WebGL take on the shadergradient.co "waterPlane" preset the project uses
      (#606080 / #8d7dca / #212121, speed 0.3, strength 1.5, density 1.5, rotationZ -60, no grain).
      Light mode uses pale versions of the same hues.
   2. A pixel dragon (original sprite) that flies around and says what the page reads aloud.
      Light mode: small, slow, cute. Dark mode: glowing eyes, fire, erratic dashes.
   Everything here is decoration. Without WebGL, canvas or motion the page works the same.
   Hook for app.js: window.buddy = { say(text, ms), listening(on), quip(kind) }. */
(() => {
  "use strict";
  const reduce = matchMedia("(prefers-reduced-motion: reduce)");
  const lightMq = matchMedia("(prefers-color-scheme: light)");
  const isLight = () => (document.documentElement.dataset.theme || (lightMq.matches ? "light" : "dark")) === "light";
  const store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* storage blocked */ } },
  };
  const onTheme = (fn) => {
    new MutationObserver(fn).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    lightMq.addEventListener("change", fn);
  };

  // ---------- shader gradient background ----------
  const PALETTES = {
    dark: ["#212121", "#606080", "#8D7DCA"],
    light: ["#F6F5FB", "#D9D8EA", "#CBC2F2"],
  };
  const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);

  function startGradient() {
    const canvas = document.createElement("canvas");
    canvas.className = "fx-bg";
    canvas.setAttribute("aria-hidden", "true");
    document.body.prepend(canvas);
    const fail = () => { canvas.remove(); document.body.classList.add("fx-fallback"); };
    const gl = canvas.getContext("webgl", { antialias: false, alpha: false, powerPreference: "low-power" });
    if (!gl) return fail();

    const vs = "attribute vec2 p;void main(){gl_Position=vec4(p,0.,1.);}";
    // A tilted plane of soft waves: bands along a rotated axis, bent by low-frequency noise.
    const fs = `precision mediump float;
uniform vec2 r;uniform float t;uniform vec3 c0,c1,c2;
vec3 m3(vec3 x){return x-floor(x*(1./289.))*289.;}vec2 m2(vec2 x){return x-floor(x*(1./289.))*289.;}vec3 pm(vec3 x){return m3(((x*34.)+1.)*x);}
float sn(vec2 v){const vec4 C=vec4(.211324865,.366025404,-.577350269,.024390244);vec2 i=floor(v+dot(v,C.yy));vec2 x0=v-i+dot(i,C.xx);
vec2 i1=(x0.x>x0.y)?vec2(1.,0.):vec2(0.,1.);vec4 x12=x0.xyxy+C.xxzz;x12.xy-=i1;i=m2(i);
vec3 p=pm(pm(i.y+vec3(0.,i1.y,1.))+i.x+vec3(0.,i1.x,1.));vec3 mm=max(.5-vec3(dot(x0,x0),dot(x12.xy,x12.xy),dot(x12.zw,x12.zw)),0.);
mm=mm*mm;mm=mm*mm;vec3 x=2.*fract(p*C.www)-1.;vec3 h=abs(x)-.5;vec3 ox=floor(x+.5);vec3 a0=x-ox;
mm*=1.79284291-.85373472*(a0*a0+h*h);vec3 g;g.x=a0.x*x0.x+h.x*x0.y;g.yz=a0.yz*x12.xz+h.yz*x12.yw;return 130.*dot(mm,g);}
void main(){vec2 uv=gl_FragCoord.xy/r;vec2 q=(uv-.5)*vec2(r.x/r.y,1.);
float a=-1.047;mat2 R=mat2(cos(a),-sin(a),sin(a),cos(a));vec2 w=R*q;
float n=sn(w*1.5+vec2(t*.5,-t*.3));float n2=sn(w*.75-vec2(t*.2,t*.4)+5.);
float band=sin(w.x*4.5+n*1.5*1.6+n2*1.2+t*1.2)*.5+.5;
float glow=smoothstep(.15,.95,n2*.5+.5);
vec3 col=mix(c0,c1,smoothstep(.1,.9,band));col=mix(col,c2,smoothstep(.55,1.,band)*glow);
col=mix(col,c0,smoothstep(.2,1.,length(q*vec2(.6,1.)))*.55);
gl_FragColor=vec4(col,1.);}`;
    const sh = (type, src) => { const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s); return gl.getShaderParameter(s, gl.COMPILE_STATUS) ? s : null; };
    const v = sh(gl.VERTEX_SHADER, vs), f = sh(gl.FRAGMENT_SHADER, fs);
    if (!v || !f) return fail();
    const prog = gl.createProgram();
    gl.attachShader(prog, v); gl.attachShader(prog, f); gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) return fail();
    gl.useProgram(prog);
    gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    const loc = gl.getAttribLocation(prog, "p");
    gl.enableVertexAttribArray(loc);
    gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    const U = Object.fromEntries(["r", "t", "c0", "c1", "c2"].map((n) => [n, gl.getUniformLocation(prog, n)]));

    const setColors = () => PALETTES[isLight() ? "light" : "dark"].forEach((h, i) => gl.uniform3fv(U["c" + i], hex(h)));
    const SCALE = 0.5; // half resolution: the image is soft anyway, and it keeps laptops cool
    function resize() {
      canvas.width = Math.max(1, Math.round(innerWidth * SCALE));
      canvas.height = Math.max(1, Math.round(innerHeight * SCALE));
      gl.viewport(0, 0, canvas.width, canvas.height);
      gl.uniform2f(U.r, canvas.width, canvas.height);
    }
    let last = 0, raf = 0;
    const t0 = performance.now();
    const SPEED = 0.3;
    function frame(now) {
      raf = 0;
      if (now - last >= 33) {
        last = now;
        gl.uniform1f(U.t, 8 + ((now - t0) / 1000) * SPEED); // uTime=8 start, as in the preset
        gl.drawArrays(gl.TRIANGLES, 0, 3);
      }
      if (!reduce.matches && !document.hidden) raf = requestAnimationFrame(frame);
    }
    const still = () => { gl.uniform1f(U.t, 8); gl.drawArrays(gl.TRIANGLES, 0, 3); };
    const go = () => (reduce.matches ? still() : raf || (raf = requestAnimationFrame(frame)));
    resize(); setColors(); go();
    addEventListener("resize", () => { resize(); still(); go(); });
    document.addEventListener("visibilitychange", go);
    onTheme(() => { setColors(); still(); go(); });
    reduce.addEventListener("change", go);
    canvas.addEventListener("webglcontextlost", (e) => { e.preventDefault(); fail(); });
  }

  // ---------- the dragon ----------
  // Original sprite. Faces left; mirrored when flying right. w/k = eye, p = blush, c = belly.
  const HEAD = [
    "....oo...oo....",
    "...oyyo.oyyo...",
    "..oggggogggo...",
    ".oggggggggggo..",
    "oggwwkgggggggo.",
    "oggwkkgggggggo.",
    "oggggggggppggo.",
    "occgggggggggo..",
    ".occccggggggo..",
    "..occcccgggo...",
    "...ooooooo.....",
  ];
  const SKIN = {
    light: { o: "#2B2F4A", g: "#7BD389", d: "#56B36B", y: "#FFD166", c: "#FFF1C9", w: "#FFFFFF", k: "#2B2F4A", p: "#FF9EB5", r: "#E2483C" },
    dark: { o: "#05050A", g: "#5B4FB0", d: "#3B3285", y: "#FF8A1F", c: "#2A2246", w: "#FF2D55", k: "#FFE45C", p: "#5B4FB0", r: "#FF2D55" },
  };
  const QUIPS = {
    light: {
      idle: ["Hi! Check before you build.", "I'm small but I've seen 10,000 to-do apps.", "Name your project in the idea and I'll remember it.", "Boop me again!", "Gaps are where the fun is."],
      taken: ["Someone got here first. Find the gap!", "Taken, but taken isn't finished."],
      crowded: ["Busy sky! Pick a narrow lane.", "Lots of neighbours. Be the weird one."],
      open: ["Nothing close in open source. Check closed apps too!", "Quiet sky. Doesn't mean empty."],
      unknown: ["Some sources didn't answer. Try again soon."],
      listening: ["I'm listening…", "All ears! Well, scales."],
    },
    dark: {
      idle: ["THE NIGHT BELONGS TO ME.", "I EAT CLONE APPS FOR BREAKFAST.", "FEED ME A REAL MOAT.", "WHO TURNED OFF THE LIGHTS?!", "BOOP ME AGAIN. I DARE YOU."],
      taken: ["IT'S TAKEN. BURN THE CLONE, FIND THE GAP.", "SOMEONE SHIPPED IT. OUT-WEIRD THEM."],
      crowded: ["CROWDED SKY. I WILL CIRCLE IT.", "TOO MANY NEIGHBOURS. GO NARROWER."],
      open: ["NOTHING IN OPEN SOURCE. CHECK THE APP STORES, MORTAL.", "QUIET SKY. SUSPICIOUSLY QUIET."],
      unknown: ["THE SOURCES FLED. TRY AGAIN."],
      listening: ["I HEAR EVERYTHING…", "SPEAK, MORTAL."],
    },
  };
  const pick = (a) => a[Math.floor(Math.random() * a.length)];

  function startDragon() {
    const KEY = "already-built:dragon";
    const canvas = document.createElement("canvas");
    canvas.className = "fx-dragon";
    canvas.setAttribute("aria-hidden", "true");
    const bubble = document.createElement("div");
    bubble.className = "buddy-bubble";
    bubble.setAttribute("aria-hidden", "true"); // what it says is already spoken or shown on the page
    bubble.hidden = true;
    const hit = document.createElement("button");
    hit.type = "button";
    hit.className = "buddy-hit";
    hit.setAttribute("aria-label", "Dragon: click for a tip");
    document.body.append(canvas, bubble, hit);
    const ctx = canvas.getContext("2d");
    if (!ctx) return null;

    const SEG = 14;
    let px = 3, gap = 8, W = 0, H = 0, dpr = 1;
    const pts = [];
    const sparks = [];
    function resize() {
      dpr = Math.min(2, devicePixelRatio || 1);
      W = innerWidth; H = innerHeight;
      canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr);
      canvas.style.width = W + "px"; canvas.style.height = H + "px";
    }
    resize();
    addEventListener("resize", resize);
    const home = () => ({ x: W - 80, y: H - 80 });
    for (let i = 0; i < SEG; i++) { const h = home(); pts.push({ x: h.x + i * gap, y: h.y }); }

    let speaking = false, listening = false, hideTimer = 0, facingRight = false, t = 0, raf = 0;
    let dash = null, nextDash = 0, mood = isLight() ? "light" : "dark";
    let visible = store.get(KEY, true) !== false;

    function sizes() {
      const small = W < 600;
      if (mood === "light") { px = small ? 2 : 3; gap = px * 2.6; }
      else { px = small ? 3 : 4; gap = px * 2.8; }
    }
    sizes();

    function target(time) {
      if (reduce.matches) return home();
      if (speaking || listening) return { x: W - 140 + Math.sin(time * 1.3) * 16, y: H - 160 + Math.cos(time * 1.7) * 10 };
      if (mood === "light") {
        // Lazy figure-eight in the lower half, with a gentle bob.
        return { x: W * 0.55 + Math.sin(time * 0.18) * W * 0.35, y: H * 0.68 + Math.sin(time * 0.36) * H * 0.18 + Math.sin(time * 3) * 6 };
      }
      // Dark: zips to random points across the whole screen, then jitters there.
      if (!dash || time > nextDash) {
        dash = { x: 40 + Math.random() * (W - 80), y: 40 + Math.random() * (H - 80) };
        nextDash = time + 0.6 + Math.random() * 1.2;
      }
      return { x: dash.x + (Math.random() - 0.5) * 14, y: dash.y + (Math.random() - 0.5) * 14 };
    }

    function drawHead(x, y) {
      const skin = SKIN[mood];
      const w = HEAD[0].length * px, h = HEAD.length * px;
      ctx.save();
      ctx.translate(Math.round(x), Math.round(y));
      if (mood === "dark" && !reduce.matches) ctx.rotate(Math.sin(t * 40) * 0.06); // headbang
      if (facingRight) ctx.scale(-1, 1);
      for (let r = 0; r < HEAD.length; r++) {
        for (let c = 0; c < HEAD[r].length; c++) {
          const ch = HEAD[r][c];
          if (ch === ".") continue;
          const glow = mood === "dark" && (ch === "w" || ch === "k");
          if (glow) { ctx.shadowColor = "#FF2D55"; ctx.shadowBlur = 12; }
          ctx.fillStyle = skin[ch];
          ctx.fillRect(Math.round(c * px - w / 2), Math.round(r * px - h / 2), px, px);
          if (glow) ctx.shadowBlur = 0;
        }
      }
      ctx.restore();
    }

    function emit(dt) {
      if (reduce.matches) return;
      const h = pts[0];
      const dir = facingRight ? 1 : -1;
      const mouth = { x: h.x + dir * HEAD[0].length * px * 0.5, y: h.y + px * 2 };
      if (mood === "dark") {
        for (let i = 0; i < 3; i++) {
          sparks.push({ x: mouth.x, y: mouth.y, vx: dir * (140 + Math.random() * 160), vy: (Math.random() - 0.5) * 90,
            life: 0.5 + Math.random() * 0.3, max: 0.8, col: pick(["#FF8A1F", "#FF2D55", "#FFE45C", "#8D7DCA"]), s: px * (1 + Math.round(Math.random())) });
        }
      } else if (Math.random() < dt * 0.8) {
        sparks.push({ x: h.x, y: h.y - px * 6, vx: (Math.random() - 0.5) * 20, vy: -30, life: 1.4, max: 1.4, col: "#FF9EB5", s: px, heart: true });
      }
      if (sparks.length > 160) sparks.splice(0, sparks.length - 160);
    }

    function draw() {
      const skin = SKIN[mood];
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, W, H);
      if (!visible) return;
      for (const s of sparks) {
        ctx.globalAlpha = Math.max(0, s.life / s.max);
        ctx.fillStyle = s.col;
        if (s.heart) {
          const q = s.s;
          ctx.fillRect(s.x - q, s.y, q, q); ctx.fillRect(s.x + q, s.y, q, q);
          ctx.fillRect(s.x - q * 2, s.y + q, q * 5, q); ctx.fillRect(s.x - q, s.y + q * 2, q * 3, q); ctx.fillRect(s.x, s.y + q * 3, q, q);
        } else ctx.fillRect(Math.round(s.x), Math.round(s.y), s.s, s.s);
      }
      ctx.globalAlpha = 1;
      for (let i = SEG - 1; i >= 1; i--) {
        const p = pts[i];
        const size = Math.max(px * 2, Math.round(px * (4.6 - (i / SEG) * 2.8)));
        const half = size / 2;
        ctx.fillStyle = skin.o;
        ctx.fillRect(Math.round(p.x - half - px / 2), Math.round(p.y - half - px / 2), size + px, size + px);
        ctx.fillStyle = i % 4 === 0 ? skin.y : i % 2 ? skin.g : skin.d;
        ctx.fillRect(Math.round(p.x - half), Math.round(p.y - half), size, size);
        if (mood === "dark" && i % 3 === 0) { // spikes
          ctx.fillStyle = skin.y;
          ctx.fillRect(Math.round(p.x - px / 2), Math.round(p.y - half - px * 2), px, px * 2);
        }
      }
      const n = pts[3];
      const flap = reduce.matches ? 0 : Math.sin(t * (mood === "dark" ? 24 : 7)) * px * 1.6;
      ctx.fillStyle = skin.y;
      ctx.fillRect(Math.round(n.x - px), Math.round(n.y - px * 5 - flap), px * 2, px * 3);
      ctx.fillRect(Math.round(n.x - px), Math.round(n.y + px * 2 + flap), px * 2, px * 3);
      drawHead(pts[0].x, pts[0].y);
    }

    function place() {
      const h = pts[0];
      const size = HEAD[0].length * px;
      hit.style.transform = `translate(${Math.round(h.x - size / 2)}px, ${Math.round(h.y - size / 2)}px)`;
      hit.style.width = hit.style.height = size + "px";
      if (!bubble.hidden) {
        const bw = bubble.offsetWidth, bh = bubble.offsetHeight;
        let bx = Math.min(Math.max(8, h.x - bw / 2), W - bw - 8);
        let by = h.y - size - bh;
        if (by < 8) by = h.y + size;
        bubble.style.transform = `translate(${Math.round(bx)}px, ${Math.round(by)}px)`;
      }
    }

    let lastT = performance.now();
    function step(now) {
      raf = 0;
      const dt = Math.min(0.05, (now - lastT) / 1000);
      lastT = now;
      t += dt;
      const tg = target(t);
      const head = pts[0];
      const ease = speaking || listening ? 2.2 : mood === "dark" ? 5.5 : 1.1;
      const nx = head.x + (tg.x - head.x) * Math.min(1, dt * ease);
      const ny = head.y + (tg.y - head.y) * Math.min(1, dt * ease);
      if (Math.abs(nx - head.x) > 0.4) facingRight = nx > head.x;
      head.x = nx; head.y = ny;
      for (let i = 1; i < SEG; i++) { // rope: each segment keeps its distance to the one ahead
        const a = pts[i - 1], b = pts[i];
        let dx = b.x - a.x, dy = b.y - a.y;
        if (mood === "dark" && !reduce.matches) dy += Math.sin(t * 18 + i) * 0.9; // wild wiggle
        const d = Math.hypot(dx, dy) || 1;
        b.x = a.x + (dx / d) * gap;
        b.y = a.y + (dy / d) * gap;
      }
      emit(dt);
      for (const s of sparks) { s.x += s.vx * dt; s.y += s.vy * dt; s.life -= dt; }
      for (let i = sparks.length - 1; i >= 0; i--) if (sparks[i].life <= 0) sparks.splice(i, 1);
      draw();
      place();
      if (visible && !document.hidden && !reduce.matches) raf = requestAnimationFrame(step);
    }
    const kick = () => {
      if (!visible) return;
      if (reduce.matches) { step(performance.now()); return; } // one still frame
      if (!raf) { lastT = performance.now(); raf = requestAnimationFrame(step); }
    };
    document.addEventListener("visibilitychange", kick);
    reduce.addEventListener("change", kick);
    onTheme(() => {
      const next = isLight() ? "light" : "dark";
      if (next === mood) return;
      mood = next;
      sizes();
      sparks.length = 0;
      say(pick(QUIPS[mood].idle), 2600); // announce the transformation
    });

    function say(text, ms) {
      const msg = String(text || "").trim();
      if (!msg || !visible) return;
      bubble.textContent = msg.length > 160 ? msg.slice(0, 157) + "…" : msg;
      bubble.classList.toggle("wild", mood === "dark");
      bubble.hidden = false;
      clearTimeout(hideTimer);
      speaking = true;
      hideTimer = setTimeout(() => { bubble.hidden = true; speaking = false; }, ms || Math.min(9000, 1800 + msg.length * 55));
      kick();
    }
    function setListening(on) {
      listening = !!on;
      if (on) say(pick(QUIPS[mood].listening), 60000);
      else if (speaking && [...QUIPS.light.listening, ...QUIPS.dark.listening].includes(bubble.textContent)) {
        clearTimeout(hideTimer); bubble.hidden = true; speaking = false;
      }
      kick();
    }
    function setVisible(on) {
      visible = !!on;
      store.set(KEY, visible);
      canvas.hidden = hit.hidden = !visible;
      if (!visible) { bubble.hidden = true; speaking = false; ctx.clearRect(0, 0, canvas.width, canvas.height); }
      document.dispatchEvent(new CustomEvent("buddy:visibility", { detail: visible }));
      kick();
    }
    hit.addEventListener("click", () => say(pick(QUIPS[mood].idle)));
    setVisible(visible);
    return {
      say, listening: setListening,
      quip: (kind) => say(pick(QUIPS[mood][kind] || QUIPS[mood].idle)),
      get visible() { return visible; }, setVisible,
    };
  }

  try { startGradient(); } catch { document.body.classList.add("fx-fallback"); }
  let buddy = null;
  try { buddy = startDragon(); } catch { buddy = null; }
  const noop = () => {};
  window.buddy = buddy || { say: noop, listening: noop, quip: noop, visible: false, setVisible: noop, off: true };
})();
