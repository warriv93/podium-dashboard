"use strict";
(() => {
const ASSETS = "/podium-season/";
const mmdd = (d) => `${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const within = (d, from, to) => (from <= to ? mmdd(d) >= from && mmdd(d) <= to : mmdd(d) >= from || mmdd(d) <= to);
const noon = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate(), 12);
const daysUntil = (d, month, day) => Math.round((new Date(d.getFullYear(), month - 1, day, 12) - noon(d)) / 864e5);

const SVG = {
  bauble: ([deep, light], id) => `<svg viewBox="0 0 34 40" width="34" height="40"><defs><radialGradient id="${id}" cx=".35" cy=".35" r=".75"><stop offset="0" stop-color="${light}"/><stop offset="1" stop-color="${deep}"/></radialGradient></defs><path d="M17 1 v6" stroke="#8e8e93" stroke-width="1.2"/><rect x="12.5" y="6" width="9" height="5" rx="1.2" fill="#c7a33a"/><circle cx="17" cy="24" r="14" fill="url(#${id})"/><path d="M5 22 Q17 28 29 22" stroke="rgba(255,255,255,.55)" stroke-width="1.6" fill="none"/><ellipse cx="12" cy="18" rx="3.2" ry="2" fill="rgba(255,255,255,.7)" transform="rotate(-30 12 18)"/></svg>`,
  star: `<svg viewBox="0 0 40 40" width="34" height="34"><path d="M20 2 L25 15 L39 15 L28 24 L32 38 L20 30 L8 38 L12 24 L1 15 L15 15 Z" fill="#ffcc00" stroke="#e0a800" stroke-width="1.2"/></svg>`,
  santaHat: `<svg viewBox="0 0 40 32"><path d="M4 26 C8 12 18 2 30 4 C34 5 36 10 35 14 C30 10 24 12 20 26 Z" fill="#d70015"/><rect x="1" y="23" width="24" height="7" rx="3.5" fill="#fff"/><circle cx="35.5" cy="15" r="4" fill="#fff"/></svg>`,
  luciaCrown: `<svg viewBox="0 0 40 32"><ellipse cx="20" cy="27" rx="18" ry="4" fill="#1f8a3b"/><circle cx="8" cy="27" r="1.6" fill="#d70015"/><circle cx="20" cy="29" r="1.6" fill="#d70015"/><circle cx="32" cy="27" r="1.6" fill="#d70015"/>${[7, 15, 25, 33].map((x) => `<rect x="${x - 1.5}" y="13" width="3" height="12" rx="1" fill="#fffaf0" stroke="#b8a98a" stroke-width=".7"/><path class="flame" d="M${x} 6 q3 4 0 7 q-3 -3 0 -7" fill="#ffb340"/>`).join("")}</svg>`,
  partyHat: `<svg viewBox="0 0 40 32"><path d="M8 28 L20 2 L32 28 Z" fill="#8250df"/><path d="M12 20 L28 20 M10 25 L30 25 M15 13 L25 13" stroke="#ffcc00" stroke-width="2.5"/><circle cx="20" cy="3" r="3" fill="#ff3b30"/></svg>`,
};
const BAUBLES = [["#d70015", "#ff6b6b"], ["#c99700", "#ffe28a"], ["#1f5fbf", "#8ec5ff"], ["#1f8a3b", "#7be29a"]];
const SNOW = { count: 70, fall: [0.25, 1.15], sway: 0.4 };
const ornament = (n) => (n % 4 === 3 ? SVG.star : SVG.bauble(BAUBLES[n % 4], `podium-bauble-${n}`));
const xmas = {
  name: "Christmas", active: (d) => within(d, "12-01", "01-06"),
  chip: (d) => { const n = daysUntil(d, 12, 24); return mmdd(d) <= "01-06" ? "✨ God fortsättning" : n > 1 ? `🎄 ${n} days to Christmas Eve` : n === 1 ? "🎄 Christmas Eve tomorrow" : n === 0 ? "🎅 God jul!" : "🎄 God jul!"; },
  tint: ["rgba(215,0,21,.10)", "#b0101e"], snow: SNOW, caps: true, hat: SVG.santaHat,
  flyer: { every: 60, make: ornament },
  walker: { every: 180, lottie: "reindeer.json", size: 96, seconds: 26, title: "Rudolf" },
  burst: ["❄️", "✨", "⭐", "🎁"],
};
const SEASONS = {
  __proto__: null,
  lucia: { ...xmas, name: "Lucia", active: (d) => mmdd(d) === "12-13", chip: () => "🕯️ Glad Lucia", tint: ["rgba(255,179,64,.2)", "#8a5300"], hat: SVG.luciaCrown, hatAt: "left: 1px; top: -17px; transform: none", burst: ["🕯️", "✨", "⭐", "❄️"] },
  newyear: { ...xmas, name: "New Year", active: (d) => within(d, "12-31", "01-01"), chip: () => "🎆 Gott nytt år!", tint: ["rgba(130,80,223,.14)", "#6f42c1"], hat: SVG.partyHat, flyer: { every: 40, firework: true }, walker: null, burst: ["🎆", "✨", "🥂", "🎉"] },
  xmas,
};

const seasonOn = (d) => Object.keys(SEASONS).find((k) => SEASONS[k].active(d)) || null;
const chipFor = (key, d) => SEASONS[key].chip(d);
const snoozeKey = (key, d) => `${key}-${d.getMonth() === 0 ? d.getFullYear() - 1 : d.getFullYear()}`;
const pick = (d, force) => (force === "off" ? null : Object.hasOwn(SEASONS, force ?? "") ? force : seasonOn(d));

if (typeof module === "object" && module.exports) {
  module.exports = { seasonOn, chipFor, snoozeKey, pick };
  return;
}

const forced = new URLSearchParams(location.search).get("season");
const key = pick(new Date(), forced);
if (!key) return;
const season = SEASONS[key], root = document.documentElement, snoozed = () => localStorage.getItem("podium-season-off") === snoozeKey(key, new Date());
const still = () => matchMedia("(prefers-reduced-motion: reduce)").matches || document.hidden;
const dark = () => root.dataset.theme === "dark" || (root.dataset.theme !== "light" && matchMedia("(prefers-color-scheme: dark)").matches);

document.head.append(Object.assign(document.createElement("style"), { textContent: `
#season-fx { position: fixed; inset: 0; z-index: 30; pointer-events: none; }
#season-back { position: fixed; inset: 0; z-index: -1; pointer-events: none; overflow: hidden; }
#season-back > * { position: absolute; left: 0; top: 0; filter: drop-shadow(0 4px 6px rgba(0,0,0,.18)); }
#season-back .spark { width: 5px; height: 5px; border-radius: 50%; filter: none; }
.season-on .fepic::before { content: ""; position: absolute; left: 10px; right: 18px; top: -7px; height: 12px; z-index: 2; pointer-events: none; filter: drop-shadow(0 1px 1.5px rgba(70,100,145,.6));
  background: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 120 12' preserveAspectRatio='none'%3E%3Cpath d='M0 12 C2 4 8 3 12 6 C16 1 26 0 30 5 C35 2 42 3 46 7 C52 1 62 1 66 6 C71 3 78 2 82 6 C88 0 98 1 102 6 C107 3 116 4 120 12 Z' fill='white'/%3E%3C/svg%3E") 0 0 / 100% 100% no-repeat; }
.season-hatwrap { position: relative; display: inline-flex; flex: none; }
.season-hat { position: absolute; left: 9px; top: -15px; width: 32px; height: 26px; transform: rotate(18deg); pointer-events: none; display: none; }
.season-on .season-hat { display: block; }
.season-hat .flame { animation: season-flicker .9s ease-in-out infinite alternate; transform-box: fill-box; transform-origin: bottom center; }
.season-chip { display: none; margin-left: 8px; padding: 1px 8px; border-radius: 999px; background: ${season.tint[0]}; color: ${season.tint[1]}; font-size: 11px; font-weight: 650; letter-spacing: 0; text-transform: none; white-space: nowrap; }
.season-on .season-chip { display: inline-block; }
.season-toggle { margin-left: 6px; border: 0; background: none; cursor: pointer; font-size: 13px; opacity: .7; padding: 0 2px; }
.season-toggle[aria-pressed="false"] { opacity: .35; filter: grayscale(1); }
#season-walker { position: fixed; bottom: 4px; left: 0; z-index: 31; display: none; cursor: pointer; }
#season-walker.hop > * { animation: season-hop .5s ease-out; }
.season-burst { position: fixed; left: 0; top: 0; z-index: 32; pointer-events: none; font-size: 14px; }
@keyframes season-flicker { from { transform: scaleY(1); opacity: 1; } to { transform: scaleY(.8); opacity: .8; } }
@keyframes season-hop { 0%,100% { transform: translateY(0); } 40% { transform: translateY(-22px) rotate(-6deg); } }
@media (prefers-reduced-motion: reduce) { .season-hat .flame { animation: none; } }
` }));

const logo = document.getElementById("logo"), wrap = Object.assign(document.createElement("span"), { className: "season-hatwrap" });
logo.replaceWith(wrap);
wrap.append(logo, Object.assign(document.createElement("span"), { className: "season-hat", innerHTML: season.hat }));
if (season.hatAt) wrap.lastElementChild.style.cssText = season.hatAt;
const chip = Object.assign(document.createElement("span"), { className: "season-chip", textContent: chipFor(key, new Date()) });
const toggle = Object.assign(document.createElement("button"), { className: "season-toggle", textContent: "❄" });
document.querySelector(".topbar .brand .eyebrow").append(chip, toggle);
toggle.onclick = () => { localStorage.setItem("podium-season-off", snoozed() ? "" : snoozeKey(key, new Date())); show(); };

const fx = Object.assign(document.createElement("canvas"), { id: "season-fx" }), back = Object.assign(document.createElement("div"), { id: "season-back" });
const walker = Object.assign(document.createElement("div"), { id: "season-walker" });
document.body.append(fx, back, walker);
const ctx = fx.getContext("2d");
let W = 0, H = 0, flakes = [];
const flake = (scattered) => { const z = Math.random(); return { x: Math.random() * W, y: scattered ? Math.random() * H : -8, z, r: 1 + z * 2.6, v: SNOW.fall[0] + z * (SNOW.fall[1] - SNOW.fall[0]), a: Math.random() * 6.28, s: 0.004 + Math.random() * 0.01 }; };
const resize = () => { const r = devicePixelRatio || 1; W = innerWidth; H = innerHeight; fx.width = W * r; fx.height = H * r; ctx.setTransform(r, 0, 0, r, 0, 0); flakes = Array.from({ length: Math.round(SNOW.count * Math.min(1.6, W / 1200)) }, () => flake(true)); };
function frame() {
  ctx.clearRect(0, 0, W, H);
  if (!snoozed() && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
    const d = dark();
    for (const f of flakes) {
      f.y += f.v; f.a += f.s; f.x += Math.sin(f.a) * SNOW.sway + 0.15;
      if (f.y > H + 6) Object.assign(f, flake(false));
      if (f.x > W + 6) f.x = -6;
      ctx.beginPath(); ctx.arc(f.x, f.y, f.r, 0, 6.29);
      ctx.fillStyle = d ? `rgba(255,255,255,${0.35 + f.z * 0.5})` : `rgba(255,255,255,${0.8 + f.z * 0.2})`; ctx.fill();
      if (!d) { ctx.lineWidth = 0.8; ctx.strokeStyle = "rgba(100,130,175,.5)"; ctx.stroke(); }
    }
  }
  requestAnimationFrame(frame);
}
addEventListener("resize", resize);
resize();
requestAnimationFrame(frame);

let flown = 0;
function fly() {
  if (season.flyer.firework) return firework(W * (0.1 + Math.random() * 0.8), H * (0.1 + Math.random() * 0.35));
  back.insertAdjacentHTML("beforeend", season.flyer.make(flown++));
  const el = back.lastElementChild, ltr = Math.random() < 0.5, y0 = H * (0.2 + Math.random() * 0.5), lift = 100 + Math.random() * 180;
  const x0 = ltr ? -60 : W + 60, x1 = ltr ? W + 60 : -60, scale = 0.8 + Math.random() * 0.6, spin = (ltr ? 1 : -1) * (360 + Math.random() * 540);
  const frames = Array.from({ length: 21 }, (_, k) => { const t = k / 20; return { transform: `translate(${x0 + (x1 - x0) * t}px, ${y0 - lift * 4 * t * (1 - t)}px) rotate(${spin * t}deg) scale(${scale})` }; });
  el.animate(frames, { duration: 9000 + Math.random() * 5000, easing: "linear" }).onfinish = () => el.remove();
}
function firework(x, y) {
  const hue = Math.floor(Math.random() * 360);
  for (let k = 0; k < 28; k++) {
    const el = Object.assign(document.createElement("i"), { className: "spark" });
    el.style.background = `hsl(${hue + (k % 3) * 25} 95% 60%)`;
    back.append(el);
    const a = (k / 28) * 6.283, d = 60 + Math.random() * 50;
    el.animate([{ transform: `translate(${x}px, ${y}px)`, opacity: 1 }, { transform: `translate(${x + Math.cos(a) * d}px, ${y + Math.sin(a) * d}px)`, opacity: 1, offset: 0.55 },
      { transform: `translate(${x + Math.cos(a) * d * 1.1}px, ${y + Math.sin(a) * d + 40}px) scale(.4)`, opacity: 0 }], { duration: 1600 + Math.random() * 400, easing: "cubic-bezier(.15,.8,.3,1)" }).onfinish = () => el.remove();
  }
}

let lottieReady, walking, playing;
const loadLottie = () => (lottieReady ??= Promise.all([
  new Promise((ok, fail) => document.head.append(Object.assign(document.createElement("script"), { src: `${ASSETS}lottie_light.min.js`, onload: ok, onerror: fail }))),
  fetch(`${ASSETS}${season.walker.lottie}`).then((r) => r.json()),
]).then(([, data]) => data));
async function walk() {
  const w = season.walker;
  if (!w || walking?.playState === "running") return;
  let data;
  try { data = await loadLottie(); } catch { return; }
  playing?.destroy();
  Object.assign(walker.style, { display: "block", width: `${w.size}px`, height: `${w.size}px` });
  walker.title = w.title;
  playing = window.lottie.loadAnimation({ container: walker, renderer: "svg", loop: true, autoplay: true, animationData: data });
  walking = walker.animate([{ transform: `translateX(-${w.size + 20}px)` }, { transform: `translateX(${W + 10}px)` }], { duration: w.seconds * 1000, easing: "linear" });
  walking.onfinish = () => { walker.style.display = "none"; playing?.destroy(); playing = null; };
}
walker.onclick = () => { walker.classList.remove("hop"); void walker.offsetWidth; walker.classList.add("hop"); const r = walker.getBoundingClientRect(); burst(r.right - 20, r.top + 10); };

function burst(x, y) {
  for (let k = 0; k < 18; k++) {
    const el = Object.assign(document.createElement("span"), { className: "season-burst", textContent: season.burst[k % season.burst.length] });
    document.body.append(el);
    const a = Math.random() * 6.28, d = 40 + Math.random() * 70;
    el.animate([{ transform: `translate(${x}px, ${y}px) scale(.6)`, opacity: 1 }, { transform: `translate(${x + Math.cos(a) * d}px, ${y + Math.sin(a) * d - 30}px) scale(1)`, opacity: 1, offset: 0.6 },
      { transform: `translate(${x + Math.cos(a) * d * 1.2}px, ${y + Math.sin(a) * d + 30}px) scale(.8)`, opacity: 0 }], { duration: 1300 + Math.random() * 500, easing: "cubic-bezier(.2,.7,.3,1)" }).onfinish = () => el.remove();
  }
}
const landed = new Map();
function watchLandings() {
  for (const card of document.querySelectorAll("#map .fms[data-id]")) {
    const id = card.dataset.id, done = card.classList.contains("done");
    if (landed.get(id) === false && done && !snoozed() && !still()) { const r = card.getBoundingClientRect(); burst(r.left + 24, r.top + r.height / 2); }
    landed.set(id, done);
  }
}
let queued = false;
new MutationObserver(() => { if (!queued) { queued = true; requestAnimationFrame(() => { queued = false; watchLandings(); }); } }).observe(document.getElementById("map"), { childList: true, subtree: true });
watchLandings();

const soon = (every, spread) => Date.now() + every * 1000 * (1 - spread + Math.random() * spread * 2);
let nextFly = soon(15, 0.5), nextWalk = soon(40, 0.5);
setInterval(() => {
  if (snoozed() || still()) return;
  const now = Date.now();
  if (now > nextFly) { fly(); nextFly = soon(season.flyer.every, 0.4); }
  if (season.walker && now > nextWalk) { walk(); nextWalk = soon(season.walker.every, 0.3); }
}, 1000);
if (key === "newyear" && mmdd(new Date()) === "12-31") {
  const midnight = new Date(); midnight.setHours(24, 0, 0, 0);
  setTimeout(() => { for (let k = 0; k < 10; k++) setTimeout(() => !still() && firework(W * (0.1 + Math.random() * 0.8), H * (0.1 + Math.random() * 0.4)), k * 600); }, midnight - Date.now());
}

function show() {
  const off = snoozed();
  root.classList.toggle("season-on", !off);
  toggle.setAttribute("aria-pressed", String(!off));
  toggle.title = off ? `Bring back ${season.name}` : `Turn ${season.name} off until next year`;
  if (off) { back.replaceChildren(); walking?.cancel(); walker.style.display = "none"; }
}
show();
})();
