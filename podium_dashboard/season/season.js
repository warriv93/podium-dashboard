"use strict";
(() => {
const ASSETS = "/podium-season/";
const mmdd = (d) => `${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const within = (d, from, to) => (from <= to ? mmdd(d) >= from && mmdd(d) <= to : mmdd(d) >= from || mmdd(d) <= to);
const noon = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate(), 12);
const daysUntil = (d, month, day) => Math.round((new Date(d.getFullYear(), month - 1, day, 12) - noon(d)) / 864e5);
const easter = (y) => {
  const a = y % 19, b = Math.floor(y / 100), c = y % 100, h = (19 * a + b - Math.floor(b / 4) - Math.floor((b - Math.floor((b + 8) / 25) + 1) / 3) + 15) % 30;
  const l = (32 + 2 * (b % 4) + 2 * Math.floor(c / 4) - h - (c % 4)) % 7, m = Math.floor((a + 11 * h + 22 * l) / 451);
  return new Date(y, Math.floor((h + l - 7 * m + 114) / 31) - 1, ((h + l - 7 * m + 114) % 31) + 1, 12);
};
const fromEaster = (d) => Math.round((noon(d) - easter(d.getFullYear())) / 864e5);
const count = (n, what) => `${n} ${n === 1 ? "day" : "days"} to ${what}`;

const SVG = {
  bauble: ([deep, light], id) => `<svg viewBox="0 0 34 40" width="34" height="40"><defs><radialGradient id="${id}" cx=".35" cy=".35" r=".75"><stop offset="0" stop-color="${light}"/><stop offset="1" stop-color="${deep}"/></radialGradient></defs><path d="M17 1 v6" stroke="#8e8e93" stroke-width="1.2"/><rect x="12.5" y="6" width="9" height="5" rx="1.2" fill="#c7a33a"/><circle cx="17" cy="24" r="14" fill="url(#${id})"/><path d="M5 22 Q17 28 29 22" stroke="rgba(255,255,255,.55)" stroke-width="1.6" fill="none"/><ellipse cx="12" cy="18" rx="3.2" ry="2" fill="rgba(255,255,255,.7)" transform="rotate(-30 12 18)"/></svg>`,
  star: `<svg viewBox="0 0 40 40" width="34" height="34"><path d="M20 2 L25 15 L39 15 L28 24 L32 38 L20 30 L8 38 L12 24 L1 15 L15 15 Z" fill="#ffcc00" stroke="#e0a800" stroke-width="1.2"/></svg>`,
  santaHat: `<svg viewBox="0 0 40 32"><path d="M4 26 C8 12 18 2 30 4 C34 5 36 10 35 14 C30 10 24 12 20 26 Z" fill="#d70015"/><rect x="1" y="23" width="24" height="7" rx="3.5" fill="#fff"/><circle cx="35.5" cy="15" r="4" fill="#fff"/></svg>`,
  luciaCrown: `<svg viewBox="0 0 40 32"><ellipse cx="20" cy="27" rx="18" ry="4" fill="#1f8a3b"/><circle cx="8" cy="27" r="1.6" fill="#d70015"/><circle cx="20" cy="29" r="1.6" fill="#d70015"/><circle cx="32" cy="27" r="1.6" fill="#d70015"/>${[7, 15, 25, 33].map((x) => `<rect x="${x - 1.5}" y="13" width="3" height="12" rx="1" fill="#fffaf0" stroke="#b8a98a" stroke-width=".7"/><path class="flame" d="M${x} 6 q3 4 0 7 q-3 -3 0 -7" fill="#ffb340"/>`).join("")}</svg>`,
  witchHat: `<svg viewBox="0 0 40 32"><path d="M8 26 L22 2 L28 24 Z" fill="#3a2a5c"/><rect x="2" y="23" width="34" height="5" rx="2.5" fill="#2c1f45"/><rect x="11" y="20" width="16" height="4" fill="#f08c00"/></svg>`,
  bunnyEars: `<svg viewBox="0 0 40 32"><ellipse cx="13" cy="14" rx="5" ry="13" fill="#fff" stroke="#d1d1d6" transform="rotate(-12 13 14)"/><ellipse cx="13" cy="15" rx="2.4" ry="9" fill="#ffc0d0" transform="rotate(-12 13 15)"/><ellipse cx="27" cy="14" rx="5" ry="13" fill="#fff" stroke="#d1d1d6" transform="rotate(12 27 14)"/><ellipse cx="27" cy="15" rx="2.4" ry="9" fill="#ffc0d0" transform="rotate(12 27 15)"/></svg>`,
  semlaHat: `<svg viewBox="0 0 40 32"><path d="M5 26 q15 6 30 0 l-2 -6 h-26 z" fill="#c98a4b"/><path d="M6 21 q3 -9 14 -9 q11 0 14 9 q-14 4 -28 0 z" fill="#fffaf0" stroke="#e6dccb" stroke-width=".8"/><path d="M9 14 q11 -12 22 0 q-11 -4 -22 0 z" fill="#d9a066"/><circle cx="14" cy="11" r=".9" fill="#fff"/><circle cx="22" cy="9" r=".9" fill="#fff"/><circle cx="27" cy="12" r=".9" fill="#fff"/></svg>`,
  studentCap: `<svg viewBox="0 0 40 32"><path d="M6 20 q14 -18 28 0 z" fill="#fff" stroke="#c7c7cc" stroke-width=".8"/><rect x="5" y="19" width="30" height="5" rx="1.5" fill="#1d1d1f"/><path d="M8 24 q12 5 24 0 l-2 3 q-10 3 -20 0 z" fill="#1d1d1f"/><circle cx="20" cy="15" r="2" fill="#d4a017"/></svg>`,
  egg: ([deep, light]) => `<svg viewBox="0 0 30 38" width="28" height="36"><ellipse cx="15" cy="20" rx="13" ry="17" fill="${deep}"/><path d="M3 18 q6 -5 12 0 t12 0" stroke="${light}" stroke-width="3" fill="none"/><path d="M3 25 q6 4 12 0 t12 0" stroke="#fff" stroke-width="2" fill="none" opacity=".8"/><ellipse cx="10" cy="11" rx="3" ry="4" fill="#fff" opacity=".45"/></svg>`,
  witch: `<svg viewBox="0 0 90 50" width="90" height="50"><path d="M4 34 L70 26" stroke="#8e5a2b" stroke-width="3" stroke-linecap="round"/><path d="M70 26 l16 -8 l-2 10 l4 6 z" fill="#d9a441"/><path d="M30 31 q2 -14 12 -16 q8 6 6 15 z" fill="#3b5ba5"/><circle cx="44" cy="12" r="6" fill="#f6c9a4"/><path d="M36 10 q8 -3 16 0 l-6 -2 l-3 -9 l-3 9 z" fill="#d70015"/><path d="M38 14 q-6 4 -4 10" stroke="#e8a33d" stroke-width="3" fill="none"/></svg>`,
  bat: `<svg viewBox="0 0 60 30" width="54" height="27"><path class="wing l" d="M30 14 C22 2 10 4 2 10 C8 12 10 18 14 20 C18 16 24 18 30 16 Z" fill="#2c2c2e"/><path class="wing r" d="M30 14 C38 2 50 4 58 10 C52 12 50 18 46 20 C42 16 36 18 30 16 Z" fill="#2c2c2e"/><ellipse cx="30" cy="16" rx="5" ry="7" fill="#1d1d1f"/><path d="M26 10 l1 -5 l2 4 M34 10 l-1 -5 l-2 4" fill="#1d1d1f" stroke="#1d1d1f"/><circle cx="28" cy="14" r="1" fill="#ffcc00"/><circle cx="32" cy="14" r="1" fill="#ffcc00"/></svg>`,
  semla: `<svg viewBox="0 0 60 52" width="60" height="52"><g class="roller"><circle cx="30" cy="26" r="24" fill="#c98a4b"/><circle cx="30" cy="26" r="17" fill="#fffaf0" stroke="#e6dccb"/><path d="M17 20 q13 -14 26 0 q-13 -5 -26 0 z" fill="#d9a066"/><circle cx="24" cy="15" r="1.4" fill="#fff"/><circle cx="33" cy="13" r="1.4" fill="#fff"/><circle cx="38" cy="18" r="1.4" fill="#fff"/><circle cx="30" cy="34" r="3" fill="#b07a3e" opacity=".5"/></g></svg>`,
  partyHat: `<svg viewBox="0 0 40 32"><path d="M8 28 L20 2 L32 28 Z" fill="#8250df"/><path d="M12 20 L28 20 M10 25 L30 25 M15 13 L25 13" stroke="#ffcc00" stroke-width="2.5"/><circle cx="20" cy="3" r="3" fill="#ff3b30"/></svg>`,
};
const BAUBLES = [["#d70015", "#ff6b6b"], ["#c99700", "#ffe28a"], ["#1f5fbf", "#8ec5ff"], ["#1f8a3b", "#7be29a"]];
const SNOW = { kind: "flake", count: 70, fall: [0.25, 1.15], sway: 0.4 };
const CAPS = {
  __proto__: null,
  snow: { view: "0 0 240 16", at: "left: 6px; right: 6px; top: -14px; height: 23px; background-size: 280px 100%; background-repeat: round; border-radius: 10px 10px 0 0",
    svg: "<defs><linearGradient id='g' x2='0' y2='1'><stop offset='.35' stop-color='white'/><stop offset='1' stop-color='%23d5e2f1'/></linearGradient></defs>"
      + "<path d='M0 6 C8 3 16 3 24 5 C34 0 52 0 62 4 C70 2 80 2 88 5 C100 -1 122 0 134 4 C142 2 152 2 160 5 C172 0 192 0 204 4 C214 2 230 3 240 6 L240 10 L222 10 C221 14 217 14 216 10 L170 10 C169 13 166 13 165 10 L110 10 C109 15 105 15 104 10 L52 10 C51 13 48 13 47 10 L0 10 Z' fill='url(%23g)'/><path d='M0 6 C8 3 16 3 24 5 C34 0 52 0 62 4 C70 2 80 2 88 5 C100 -1 122 0 134 4 C142 2 152 2 160 5 C172 0 192 0 204 4 C214 2 230 3 240 6' fill='none' stroke='%23c6d4e5' stroke-width='.7'/>" },
  grass: { view: "0 0 120 12", svg: "<path d='M0 12 L3 4 L5 12 L8 2 L10 12 L13 5 L15 12 L18 1 L20 12 L23 4 L26 12 L29 3 L31 12 L34 5 L37 12 L40 2 L42 12 L45 4 L48 12 L51 1 L53 12 L56 5 L59 12 L62 3 L64 12 L67 4 L70 12 L73 2 L75 12 L78 5 L81 12 L84 1 L86 12 L89 4 L92 12 L95 3 L97 12 L100 5 L103 12 L106 2 L108 12 L111 4 L114 12 L117 3 L120 12 Z' fill='%2334c759'/>",
    at: "left: 10px; right: 18px; top: -7px; height: 12px; background-size: 100% 100%; background-repeat: no-repeat" },
};
const EGGS = [["#ff9fb7", "#ffd6e0"], ["#7fd6a8", "#e6fff1"], ["#8ab4ff", "#e3edff"], ["#ffd60a", "#fff3b0"]];
const ornament = (n) => (n % 4 === 3 ? SVG.star : SVG.bauble(BAUBLES[n % 4], `podium-bauble-${n}`));
const xmas = {
  name: "Christmas", active: (d) => within(d, "12-01", "01-06"),
  chip: (d) => { const n = daysUntil(d, 12, 24); return mmdd(d) <= "01-06" ? "✨ God fortsättning" : n > 1 ? `🎄 ${n} days to Christmas Eve` : n === 1 ? "🎄 Christmas Eve tomorrow" : n === 0 ? "🎅 God jul!" : "🎄 God jul!"; },
  tint: ["rgba(215,0,21,.10)", "#b0101e"], particles: SNOW, cap: "snow", hat: SVG.santaHat,
  flyer: { every: 60, make: ornament },
  walker: { every: 180, lottie: "reindeer.json", size: 96, seconds: 26, title: "Rudolf" },
  burst: ["❄️", "✨", "⭐", "🎁"],
};
const SEASONS = {
  __proto__: null,
  lucia: { ...xmas, name: "Lucia", active: (d) => mmdd(d) === "12-13", chip: () => "🕯️ Glad Lucia", tint: ["rgba(255,179,64,.2)", "#8a5300"], hat: SVG.luciaCrown, hatAt: "left: 1px; top: -17px; transform: none", burst: ["🕯️", "✨", "⭐", "❄️"] },
  newyear: { ...xmas, name: "New Year", active: (d) => within(d, "12-31", "01-01"), chip: () => "🎆 Gott nytt år!", tint: ["rgba(130,80,223,.14)", "#6f42c1"], hat: SVG.partyHat, flyer: { every: 40, firework: true }, walker: null, burst: ["🎆", "✨", "🥂", "🎉"] },
  xmas,
  halloween: {
    name: "Halloween", active: (d) => within(d, "10-24", "11-01"),
    chip: (d) => { const n = daysUntil(d, 10, 31); return n > 1 ? `🎃 ${count(n, "Halloween")}` : n === 1 ? "🎃 Halloween tomorrow" : "🎃 Happy Halloween"; },
    tint: ["rgba(240,140,0,.16)", "#8a4b00"], particles: { kind: "leaf", count: 28, fall: [0.4, 1], sway: 1.2, colors: ["#f08c00", "#c2410c", "#a16207", "#d97706"] },
    cap: null, hat: SVG.witchHat, flyer: { every: 45, make: () => SVG.bat },
    walker: { every: 200, lottie: "pumpkin.json", size: 72, seconds: 30, title: "Pumpkin" }, burst: ["🎃", "🦇", "🍬", "👻"],
  },
  easter: {
    name: "Easter", active: (d) => fromEaster(d) >= -7 && fromEaster(d) <= 1,
    chip: (d) => (fromEaster(d) < -1 ? `🐣 ${count(-fromEaster(d), "Easter")}` : "🐣 Glad påsk!"),
    tint: ["rgba(255,214,10,.22)", "#7a5c00"], particles: { kind: "feather", count: 30, fall: [0.3, 0.8], sway: 1, colors: ["#ffb3c6", "#ffd84d", "#8fe0ad", "#a9c4ff", "#d6b3ff"] },
    cap: "grass", hat: SVG.bunnyEars, hatAt: "left: 6px; top: -13px; width: 28px; height: 22px; transform: none",
    flyer: { every: 70, make: (n) => (n % 4 === 3 ? SVG.witch : SVG.egg(EGGS[n % 4])) },
    walker: { every: 180, lottie: "bunny-chicks.json", size: 110, seconds: 32, title: "Påskharen" }, burst: ["🐣", "🥚", "🌷", "🪶"],
  },
  fettisdagen: {
    name: "Fettisdagen", active: (d) => fromEaster(d) >= -49 && fromEaster(d) <= -47,
    chip: (d) => (fromEaster(d) < -47 ? `🧁 ${count(-47 - fromEaster(d), "Fettisdagen")}` : "🧁 Glad fettisdag!"),
    tint: ["rgba(201,138,75,.18)", "#7a4a1c"], particles: null,
    cap: null, hat: SVG.semlaHat, hatAt: "left: 6px; top: -12px; transform: rotate(8deg)", flyer: { every: 25, make: () => SVG.semla },
    walker: { every: 90, svg: SVG.semla, size: 60, seconds: 24, title: "Semla" }, burst: ["🧁", "✨", "🤍", "🥄"],
  },
  valborg: {
    name: "Valborg", active: (d) => within(d, "04-28", "04-30"),
    chip: (d) => { const n = daysUntil(d, 4, 30); return n > 0 ? `🔥 ${count(n, "Valborg")}` : "🔥 Glad Valborg!"; },
    tint: ["rgba(255,95,31,.14)", "#9a3412"], particles: { kind: "spark", count: 50, fall: [-1.3, -0.4], sway: 0.6 },
    cap: null, hat: SVG.studentCap, hatAt: "left: 7px; top: -10px; transform: rotate(-8deg)", flyer: null, walker: null, burst: ["🔥", "✨", "🎓", "🌸"],
  },
};

const seasonOn = (d) => Object.keys(SEASONS).find((k) => SEASONS[k].active(d)) || null;
const chipFor = (key, d) => SEASONS[key].chip(d);
const snoozeKey = (key, d) => `${key}-${d.getMonth() === 0 ? d.getFullYear() - 1 : d.getFullYear()}`;
const pick = (d, force) => (force === "off" ? null : Object.hasOwn(SEASONS, force ?? "") ? force : seasonOn(d));

if (typeof module === "object" && module.exports) {
  module.exports = { SEASONS, seasonOn, chipFor, snoozeKey, pick };
  return;
}

const forced = new URLSearchParams(location.search).get("season");
const key = pick(new Date(), forced);
if (!key) return;
const season = SEASONS[key], cap = CAPS[season.cap], root = document.documentElement, snoozed = () => localStorage.getItem("podium-season-off") === snoozeKey(key, new Date());
const still = () => matchMedia("(prefers-reduced-motion: reduce)").matches || document.hidden;
const dark = () => root.dataset.theme === "dark" || (root.dataset.theme !== "light" && matchMedia("(prefers-color-scheme: dark)").matches);

document.head.append(Object.assign(document.createElement("style"), { textContent: `
#season-fx { position: fixed; inset: 0; z-index: 30; pointer-events: none; }
#season-back { position: fixed; inset: 0; z-index: -1; pointer-events: none; overflow: hidden; }
#season-back > * { position: absolute; left: 0; top: 0; filter: drop-shadow(0 4px 6px rgba(0,0,0,.18)); }
#season-back .spark { width: 5px; height: 5px; border-radius: 50%; filter: none; }
${cap ? `.season-on .fepic::before { content: ""; position: absolute; ${cap.at}; z-index: 2; pointer-events: none; filter: drop-shadow(0 1px 1px rgba(70,100,145,.25));
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='${cap.view}' preserveAspectRatio='none'%3E${cap.svg.replace(/</g, "%3C").replace(/>/g, "%3E")}%3C/svg%3E"); }` : ""}
#season-back .wing { transform-box: fill-box; animation: season-flap .22s ease-in-out infinite alternate; }
#season-back .wing.l { transform-origin: right center; } #season-back .wing.r { transform-origin: left center; }
#season-walker .roller { transform-box: fill-box; transform-origin: center; animation: season-roll 1.6s linear infinite; }
@keyframes season-flap { from { transform: scaleY(1); } to { transform: scaleY(.35); } }
@keyframes season-roll { to { transform: rotate(360deg); } }
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
const P = season.particles;
let W = 0, H = 0, flakes = [];
const flake = (scattered) => {
  const z = Math.random(), rises = P.fall[1] < 0;
  return { x: Math.random() * W, y: scattered ? Math.random() * H : rises ? H + 8 : -8, z, r: 1 + z * 2.6, v: P.fall[0] + z * (P.fall[1] - P.fall[0]), a: Math.random() * 6.28,
    s: 0.004 + Math.random() * 0.01, turn: Math.random() * 6.28, spin: (Math.random() - 0.5) * 0.06, color: P.colors?.[Math.floor(Math.random() * P.colors.length)] };
};
const resize = () => { const r = devicePixelRatio || 1; W = innerWidth; H = innerHeight; fx.width = W * r; fx.height = H * r; ctx.setTransform(r, 0, 0, r, 0, 0); flakes = P ? Array.from({ length: Math.round(P.count * Math.min(1.6, W / 1200)) }, () => flake(true)) : []; };
function draw(f, d) {
  ctx.beginPath();
  if (P.kind === "leaf" || P.kind === "feather") {
    ctx.save(); ctx.translate(f.x, f.y); ctx.rotate(f.turn);
    ctx.ellipse(0, 0, f.r * (P.kind === "leaf" ? 2.4 : 3), f.r * (P.kind === "leaf" ? 1.3 : 0.8), 0, 0, 6.29);
    ctx.globalAlpha = 0.65 + f.z * 0.35; ctx.fillStyle = f.color; ctx.fill(); ctx.restore(); ctx.globalAlpha = 1;
  } else if (P.kind === "spark") {
    ctx.arc(f.x, f.y, 0.8 + f.z * 1.6, 0, 6.29);
    ctx.fillStyle = `hsla(${20 + f.z * 25} 100% ${55 + Math.sin(f.a * 5) * 10}% / ${0.55 + f.z * 0.45})`;
    ctx.shadowColor = "rgba(255,120,30,.8)"; ctx.shadowBlur = 6; ctx.fill(); ctx.shadowBlur = 0;
  } else {
    ctx.arc(f.x, f.y, f.r, 0, 6.29);
    ctx.fillStyle = d ? `rgba(255,255,255,${0.35 + f.z * 0.5})` : `rgba(255,255,255,${0.8 + f.z * 0.2})`; ctx.fill();
    if (!d) { ctx.lineWidth = 0.8; ctx.strokeStyle = "rgba(100,130,175,.5)"; ctx.stroke(); }
  }
}
function frame() {
  ctx.clearRect(0, 0, W, H);
  if (P && !snoozed() && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
    const d = dark();
    for (const f of flakes) {
      f.y += f.v; f.a += f.s; f.turn += f.spin; f.x += Math.sin(f.a) * P.sway + 0.15;
      if (f.y > H + 8 || f.y < -10) Object.assign(f, flake(false));
      if (f.x > W + 6) f.x = -6;
      draw(f, d);
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
const loadLottie = () => (lottieReady ??= season.walker.svg ? Promise.resolve(null) : Promise.all([
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
  if (w.svg) walker.innerHTML = w.svg;
  else playing = window.lottie.loadAnimation({ container: walker, renderer: "svg", loop: true, autoplay: true, animationData: data });
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
window.podiumSeason = { burst: () => (snoozed() ? null : season.burst) };

const soon = (every, spread) => Date.now() + every * 1000 * (1 - spread + Math.random() * spread * 2);
let nextFly = soon(15, 0.5), nextWalk = soon(40, 0.5);
setInterval(() => {
  if (snoozed() || still()) return;
  const now = Date.now();
  if (season.flyer && now > nextFly) { fly(); nextFly = soon(season.flyer.every, 0.4); }
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
