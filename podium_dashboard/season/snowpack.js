(function () {
"use strict";
const COL = 3, MAXH = 16, REPOSE = 1.6, G = 1500, HOLD_MS = 320;

function settle(h) {
  const n = h.length;
  for (let pass = 0; pass < 2; pass++) for (let i = 0; i < n - 1; i++) {
    const d = h[i] - h[i + 1];
    if (Math.abs(d) > REPOSE) { const m = (Math.abs(d) - REPOSE) * 0.25 * Math.sign(d); h[i] -= m; h[i + 1] += m; }
  }
}

function blanket(n) {
  return Array.from({ length: n }, (_, i) => {
    const t = i / Math.max(1, n - 1), edge = Math.min(1, Math.min(t, 1 - t) * 9);
    return edge * (10 + 3 * Math.sin(i * 0.21) + 2 * Math.sin(i * 0.07 + 1));
  });
}

if (typeof module === "object" && module.exports) {
  module.exports = { settle, blanket, MAXH };
  return;
}

window.podiumSnowpack = ({ selector, key, dark, on, moving }) => {
  const cv = Object.assign(document.createElement("canvas"), { id: "season-snowpack" }), ctx = cv.getContext("2d");
  cv.style.cssText = "position: fixed; inset: 0; width: 100%; height: 100%; z-index: 29; pointer-events: none;";
  document.body.append(cv);
  document.head.append(Object.assign(document.createElement("style"), { textContent:
    ".snow-grab, .snow-grab * { cursor: grab !important; } .snow-holding, .snow-holding * { cursor: grabbing !important; user-select: none !important; }" }));

  const piles = new Map();
  let W = 0, H = 0, live = [], bits = [], thrown = [], ball = null, hold = null, swallow = false;
  const ptr = { x: 0, y: 0, hist: [] };
  const resize = () => { const r = devicePixelRatio || 1; W = innerWidth; H = innerHeight; cv.width = W * r; cv.height = H * r; ctx.setTransform(r, 0, 0, r, 0, 0); };
  addEventListener("resize", resize); resize();

  function measure() {
    live = [];
    for (const el of document.querySelectorAll(selector)) {
      const r = el.getBoundingClientRect();
      if (!r.width || r.top < 0 || r.top > H || !el.contains(document.elementFromPoint(r.left + r.width / 2, r.top + 3))) continue;
      const id = key(el), n = Math.max(2, Math.round((r.width - 16) / COL));
      let p = piles.get(id);
      if (!p) piles.set(id, (p = { h: blanket(n) }));
      if (p.h.length !== n) p.h = Array.from({ length: n }, (_, i) => p.h[Math.round((i * (p.h.length - 1)) / Math.max(1, n - 1))] ?? 0);
      Object.assign(p, { el, r });
      live.push(p);
    }
  }
  const colX = (p, i) => p.r.left + 8 + i * COL;
  const colAt = (p, x) => Math.round((x - p.r.left - 8) / COL);
  const heightAt = (p, x) => p.h[Math.max(0, Math.min(p.h.length - 1, colAt(p, x)))] || 0;
  const pileAt = (x, y) => live.find((p) => x > p.r.left && x < p.r.right && heightAt(p, x) > 2 && y >= p.r.top - heightAt(p, x) - 8 && y <= p.r.top + 4);

  function land(x, y, amount) {
    for (const p of live) {
      if (x < p.r.left + 8 || x > p.r.right - 8) continue;
      const i = colAt(p, x);
      if (i < 0 || i >= p.h.length) continue;
      if (y >= p.r.top - p.h[i] && y <= p.r.top + 6) { p.h[i] = Math.min(MAXH, p.h[i] + amount); return true; }
    }
    return false;
  }
  function shake(p, cx) {
    p.h.forEach((h, i) => {
      for (let k = 0; k < h / 2.2; k++) {
        const x = colX(p, i), dx = x - cx, side = Math.sign(dx) || (Math.random() < 0.5 ? -1 : 1);
        bits.push({ x, y: p.r.top - Math.random() * h, vx: side * (60 + Math.random() * 260) + dx * 0.6, vy: -(260 + Math.random() * 520), r: 1.2 + Math.random() * 2.2, age: 0 });
      }
    });
    p.h = p.h.map(() => 0);
    p.el.animate([{ transform: "translateY(0)" }, { transform: "translateY(3px)" }, { transform: "translateY(-2px)" }, { transform: "translateY(0)" }], { duration: 260 });
  }
  function splat(x, y, vx, vy, n) {
    for (let k = 0; k < n; k++) {
      const a = Math.random() * Math.PI * 2, s = 80 + Math.random() * 320;
      bits.push({ x, y, vx: Math.cos(a) * s - vx * 0.15, vy: Math.sin(a) * s - Math.abs(vy) * 0.2 - 120, r: 1.2 + Math.random() * 2.4, age: 0 });
    }
  }
  function scoop(p, x, want) {
    let got = 0; const c = colAt(p, x);
    for (let i = Math.max(0, c - 4); i <= Math.min(p.h.length - 1, c + 4); i++) {
      const take = Math.min(p.h[i], want * (1 - Math.abs(i - c) / 5));
      p.h[i] -= take; got += take;
    }
    return got;
  }

  addEventListener("pointermove", (e) => {
    ptr.x = e.clientX; ptr.y = e.clientY; ptr.hist.push({ x: e.clientX, y: e.clientY, t: performance.now() });
    if (ptr.hist.length > 8) ptr.hist.shift();
    if (hold && !ball && Math.hypot(e.clientX - hold.x, e.clientY - hold.y) > 8) { clearTimeout(hold.timer); hold = null; }
    document.documentElement.classList.toggle("snow-grab", on() && moving() && !ball && !!pileAt(e.clientX, e.clientY));
  }, { passive: true });
  addEventListener("pointerdown", (e) => {
    if (e.button !== 0 || !on() || !moving()) return;
    measure();
    const pile = pileAt(e.clientX, e.clientY), card = e.target.closest?.(selector);
    hold = { x: e.clientX, y: e.clientY, pile, card: card && live.find((p) => p.el === card) };
    ptr.x = e.clientX; ptr.y = e.clientY; ptr.hist = [{ x: e.clientX, y: e.clientY, t: performance.now() }];
    if (!pile) return;
    e.preventDefault();
    hold.timer = setTimeout(() => {
      if (!hold) return;
      ball = { x: ptr.x, y: ptr.y, r: 4, pile, spin: 0 };
      document.documentElement.classList.add("snow-holding");
    }, HOLD_MS);
  });
  addEventListener("pointerup", (e) => {
    if (ball) {
      const now = performance.now(), old = ptr.hist.find((h) => now - h.t < 90) || ptr.hist[0], dt = Math.max(16, now - old.t) / 1000;
      thrown.push({ x: ball.x, y: ball.y, r: ball.r, vx: (e.clientX - old.x) / dt, vy: (e.clientY - old.y) / dt, spin: 0, age: 0 });
      ball = null; swallow = true;
      document.documentElement.classList.remove("snow-holding");
    } else if (hold && Math.hypot(e.clientX - hold.x, e.clientY - hold.y) < 8) {
      clearTimeout(hold.timer);
      const p = hold.pile || hold.card;
      if (p) shake(p, e.clientX);
      swallow = !!hold.pile;
    }
    hold = null;
  });
  addEventListener("click", (e) => { if (swallow) { swallow = false; e.stopPropagation(); e.preventDefault(); } }, true);

  function step(dt) {
    measure();
    if (ball) {
      ball.x += (ptr.x - ball.x) * Math.min(1, dt * 25); ball.y += (ptr.y - ball.y) * Math.min(1, dt * 25);
      if (ball.r < 15 && ball.pile.r) ball.r = Math.min(15, ball.r + scoop(ball.pile, hold?.x ?? ball.x, dt * 30) * 0.12 + dt * 2);
    }
    for (const b of thrown) {
      b.vy += G * dt; b.x += b.vx * dt; b.y += b.vy * dt; b.spin += (b.vx * dt) / b.r; b.age += dt;
      const onCard = b.age > 0.08 && live.some((p) => b.x > p.r.left && b.x < p.r.right && b.y + b.r > p.r.top - heightAt(p, b.x) && b.y - b.r < p.r.bottom);
      if (onCard || b.x < b.r || b.x > W - b.r || b.y > H - b.r) { b.dead = true; splat(Math.max(0, Math.min(W, b.x)), Math.min(H, b.y), b.vx, b.vy, Math.round(b.r * 4)); }
    }
    thrown = thrown.filter((b) => !b.dead && b.y > -2000);
    for (const s of bits) {
      s.vy += G * 0.7 * dt; s.vx *= 1 - dt * 0.8; s.x += s.vx * dt; s.y += s.vy * dt; s.age += dt;
      if ((s.vy > 0 && s.age > 0.05 && land(s.x, s.y, s.r * 0.55)) || s.y > H + 20) s.dead = true;
    }
    bits = bits.filter((s) => !s.dead);
    live.forEach((p) => settle(p.h));
  }

  function drawPile(p, d) {
    const h = p.h, top = p.r.top + 1, last = h.length - 1;
    if (h.every((v) => v < 0.3)) return;
    ctx.beginPath(); ctx.moveTo(colX(p, 0), top);
    for (let i = 0; i <= last; i++) {
      const x = colX(p, i), nx = colX(p, Math.min(last, i + 1));
      ctx.quadraticCurveTo(x, top - h[i], (x + nx) / 2, top - (h[i] + h[Math.min(last, i + 1)]) / 2);
    }
    ctx.lineTo(colX(p, last), top);
    for (let i = last; i >= 0; i -= 9) if (h[i] > 6) { const x = colX(p, i); ctx.lineTo(x + 3, top); ctx.quadraticCurveTo(x, top + Math.min(7, h[i] * 0.45), x - 3, top); }
    ctx.closePath();
    const g = ctx.createLinearGradient(0, top - MAXH, 0, top + 4);
    g.addColorStop(0, "#ffffff"); g.addColorStop(0.7, "#f4f8fd"); g.addColorStop(1, d ? "#c9d7ea" : "#d9e5f3");
    ctx.fillStyle = g; ctx.shadowColor = "rgba(60,90,140,.28)"; ctx.shadowBlur = 3; ctx.shadowOffsetY = 1; ctx.fill();
    ctx.shadowColor = "transparent"; ctx.shadowOffsetY = 0;
    ctx.strokeStyle = d ? "rgba(255,255,255,.5)" : "rgba(150,175,205,.55)"; ctx.lineWidth = 0.8; ctx.stroke();
  }
  function drawBall(b) {
    const g = ctx.createRadialGradient(b.x - b.r * 0.35, b.y - b.r * 0.4, b.r * 0.15, b.x, b.y, b.r);
    g.addColorStop(0, "#fff"); g.addColorStop(0.7, "#eef3fa"); g.addColorStop(1, "#c4d3e6");
    ctx.shadowColor = "rgba(40,60,100,.3)"; ctx.shadowBlur = 8; ctx.shadowOffsetY = 3;
    ctx.beginPath(); ctx.arc(b.x, b.y, b.r, 0, 6.29); ctx.fillStyle = g; ctx.fill();
    ctx.shadowColor = "transparent"; ctx.shadowOffsetY = 0; ctx.fillStyle = "rgba(170,190,215,.6)";
    for (let k = 0; k < 4; k++) { const a = b.spin + k * 1.7; ctx.beginPath(); ctx.arc(b.x + Math.cos(a) * b.r * 0.55, b.y + Math.sin(a) * b.r * 0.5, b.r * 0.09, 0, 6.29); ctx.fill(); }
  }
  function draw() {
    ctx.clearRect(0, 0, W, H);
    if (!on()) return;
    const d = dark();
    live.forEach((p) => drawPile(p, d));
    ctx.fillStyle = "#fff"; ctx.shadowColor = "rgba(60,90,140,.45)"; ctx.shadowBlur = 2;
    for (const s of bits) { ctx.beginPath(); ctx.arc(s.x, s.y, s.r, 0, 6.29); ctx.fill(); }
    ctx.shadowColor = "transparent";
    if (ball) drawBall(ball);
    thrown.forEach(drawBall);
  }
  let last = performance.now();
  (function frame(now) {
    const dt = Math.min(0.033, (now - last) / 1000); last = now;
    if (on() && moving()) step(dt); else measure();
    draw();
    requestAnimationFrame(frame);
  })(last);

  return { land: (x, y, amount) => on() && moving() && land(x, y, amount) };
};
})();
