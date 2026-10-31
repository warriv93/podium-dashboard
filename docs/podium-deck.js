const pptxgen = require("pptxgenjs");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");
const fa = require("react-icons/fa6");
const { applyTheme } = require(process.env.PPTX_SKILL + "/scripts/apply_theme.js");

const OUT = process.argv[2] || "podium-deck.pptx";
const PODIUM_SHOT = process.argv[3];

const THEME = {
  name: "Podium",
  headFontFace: "Helvetica Neue",
  bodyFontFace: "Helvetica Neue",
  colors: {
    dk1: "1D1D1F", lt1: "FFFFFF", dk2: "000000", lt2: "F5F5F7",
    accent1: "0071E3", accent2: "AF52DE", accent3: "28A745",
    accent4: "FF9500", accent5: "FF2D55", accent6: "30B0C7",
    hlink: "0071E3", folHlink: "AF52DE",
  },
};
const HEX = THEME.colors;
const FONT = process.env.QA_FONT || THEME.headFontFace;
const GRAY = "6E6E73";
const DARK_GRAY = "86868B";
const BRIGHT = { blue: "2997FF", purple: "BF5AF2", green: "30D158", orange: "FF9F0A", red: "FF375F", teal: "64D2FF" };

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE";
pres.title = "Agents that finish the job";
pres.author = "Simon Irengard-Gullstrand";
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
const C = pres.SchemeColor;

const W = 13.333;
const M = 0.7;
const CW = W - 2 * M;

const titleOpts = (color) => ({ name: "title", type: "title", x: M, y: 0.55, w: CW, h: 0.9, fontSize: 36, bold: true, fontFace: FONT, color, valign: "middle", align: "left", margin: 0 });
const slideNumber = (color) => ({ x: W - M - 0.6, y: 6.95, w: 0.6, h: 0.3, fontSize: 10, color, align: "right" });

pres.defineSlideMaster({
  title: "HERO",
  background: { color: HEX.dk2 },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: M, y: 3.55, w: CW, h: 1.2, fontSize: 60, bold: true, fontFace: FONT, color: C.background1, valign: "middle", align: "center", margin: 0 }, text: "" } },
    { placeholder: { options: { name: "body", type: "body", x: M, y: 4.8, w: CW, h: 0.6, fontSize: 24, fontFace: FONT, color: DARK_GRAY, valign: "top", align: "center", margin: 0 }, text: "" } },
  ],
});
pres.defineSlideMaster({
  title: "DARK",
  background: { color: HEX.dk2 },
  objects: [{ placeholder: { options: titleOpts(C.background1), text: "" } }],
  slideNumber: slideNumber("48484A"),
});
pres.defineSlideMaster({
  title: "LIGHT",
  background: { color: HEX.lt1 },
  objects: [{ placeholder: { options: titleOpts(C.text1), text: "" } }],
  slideNumber: slideNumber("AEAEB2"),
});
pres.defineSlideMaster({
  title: "LIGHT_GRAY",
  background: { color: HEX.lt2 },
  objects: [{ placeholder: { options: titleOpts(C.text1), text: "" } }],
  slideNumber: slideNumber("AEAEB2"),
});

async function icon(Comp, hex, size = 256) {
  const svg = ReactDOMServer.renderToStaticMarkup(React.createElement(Comp, { color: "#" + hex, size: String(size) }));
  const png = await sharp(Buffer.from(svg)).png().toBuffer();
  return "image/png;base64," + png.toString("base64");
}

async function glyph(slide, Comp, hex, { x, y, d, name }) {
  slide.addImage({ data: await icon(Comp, hex), x, y, w: d, h: d, altText: name, objectName: name + " icon" });
}

function rounded(slide, { x, y, w, h, fill, transparency = 0, line, r = 0.2, name, shadow }) {
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x, y, w, h, rectRadius: r,
    fill: { color: fill, transparency },
    line: line ? { color: line, width: 1 } : { type: "none" },
    objectName: name,
    ...(shadow ? { shadow: { type: "outer", color: "000000", opacity: 0.12, blur: 12, offset: 3, angle: 90 } } : {}),
  });
}

function dot(slide, { x, y, d, fill, line, name }) {
  slide.addShape(pres.shapes.OVAL, { x, y, w: d, h: d, fill: { color: fill }, line: line ? { color: line, width: 3 } : { type: "none" }, objectName: name });
}

function text(slide, t, opts) {
  slide.addText(t, { isTextBox: true, margin: 0, valign: "top", color: C.text1, fontFace: FONT, ...opts });
}

function slide(masterName, title, section) {
  const s = pres.addSlide({ masterName, sectionTitle: section });
  if (title) s.addText(title, { placeholder: "title" });
  return s;
}

const LAYER_HEX = [HEX.dk1, HEX.accent1, HEX.accent2, HEX.accent3, HEX.accent4, HEX.accent6];

async function build() {
  // 1 — hero
  pres.addSection({ title: "Why" });
  let s = slide("HERO", null, "Why");
  s.addText("Agents that finish the job.", { placeholder: "title" });
  s.addText("Many agents in parallel. One screen to steer them.", { placeholder: "body" });
  const heroLayers = [BRIGHT.blue, BRIGHT.purple, BRIGHT.green, BRIGHT.orange, BRIGHT.teal];
  heroLayers.forEach((hex, i) => {
    const w = 3.6 - i * 0.35;
    rounded(s, { x: (W - w) / 2, y: 2.75 - i * 0.36, w, h: 0.26, r: 0.13, fill: hex, name: "hero layer " + (i + 1) });
  });
  text(s, "Simon Irengard-Gullstrand · October 2026", { x: M, y: 6.6, w: CW, h: 0.35, fontSize: 13, color: DARK_GRAY, align: "center" });
  s.addNotes("Today: how I run AI coding at scale without it running away from me. The pitfalls, the layered setup that answers them, and what it buys us as a team.");

  // 2 — pitfalls
  s = slide("DARK", "Left alone, agents go wrong in six ways.", "Why");
  const pitfalls = [
    [fa.FaArrowsRotate, "Endless fix loops", "The same failing idea, retried for an hour."],
    [fa.FaLayerGroup, "Snowballing context", "Every early token is paid for again on each turn."],
    [fa.FaMicrochip, "One model for everything", "Opus skimming logs. Haiku reviewing money code."],
    [fa.FaCircleCheck, "Confidently wrong", "Green tests that test nothing."],
    [fa.FaEyeSlash, "Agents in the dark", "Five terminals. Which one is stuck?"],
    [fa.FaUpload, "Unseen pushes", "Code leaves before anyone looks."],
  ];
  for (let i = 0; i < pitfalls.length; i++) {
    const [Ic, head, body] = pitfalls[i];
    const x = M + (i % 3) * 4.05, y = 1.95 + Math.floor(i / 3) * 2.5;
    await glyph(s, Ic, BRIGHT.red, { x, y, d: 0.6, name: "pitfall " + (i + 1) });
    text(s, head, { x, y: y + 0.85, w: 3.7, h: 0.45, fontSize: 22, bold: true, color: C.background1 });
    text(s, body, { x, y: y + 1.35, w: 3.7, h: 0.7, fontSize: 16, color: DARK_GRAY });
  }
  s.addNotes("Everyone who has used Claude Code or Copilot agents for real work has hit these. Everything that follows answers one of these six.");

  // 3 — layers
  pres.addSection({ title: "How" });
  s = slide("LIGHT", "Six layers. Each with one job.", "How");
  const layers = [
    ["Podium", "The control room", "A live dashboard and CLI over the whole run."],
    ["Shell", "orchestrate-deep-plans", "Epics to stories, built in parallel."],
    ["Planner", "deep-plan", "One feature from recon to a merged PR."],
    ["Leaf skills", "Swappable one by one", "grilling, tdd, deep-qa, create-deep-pr."],
    ["Runtime", "Under every spawn", "Paseo or Agent, model tiers, a contract."],
    ["RTK", "Under every command", "Trims output before the model reads it."],
  ];
  layers.forEach(([name, role, desc], i) => {
    const y = 1.75 + i * 0.85;
    rounded(s, { x: M, y, w: 4.2, h: 0.68, r: 0.34, fill: LAYER_HEX[i], name: "layer " + name, shadow: true });
    text(s, name, { x: M, y, w: 4.2, h: 0.68, fontSize: 18, bold: true, color: C.background1, align: "center", valign: "middle" });
    text(s, [
      { text: role + "  ", options: { bold: true, color: C.text1 } },
      { text: desc, options: { color: GRAY } },
    ], { x: M + 4.7, y, w: CW - 4.7, h: 0.68, fontSize: 17, valign: "middle" });
  });
  s.addNotes("Top to bottom: Podium is where I watch and steer. orchestrate-deep-plans plans a feature and fans out stories. deep-plan runs one feature end to end, and deep-app-plan sits above it for a whole new app. Leaf skills are small and swappable. The runtime decides how each agent is spawned and on which model: the subagent protocol, Paseo or Claude Code agents, Haiku/Sonnet/Opus, and a contract of commands that must pass. RTK sits under every shell command.");

  // parallel
  s = slide("LIGHT", "Many agents in parallel. One plan.", "How");
  const cy = 3.35;
  const wavesX = [3.5, 6.2, 8.9], pillW = 2.1, pillH = 0.5, gap = 0.15;
  rounded(s, { x: M, y: cy - 0.55, w: 2.2, h: 1.1, fill: HEX.dk1, name: "orchestrator", shadow: true });
  text(s, [
    { text: "Orchestrator", options: { bold: true, fontSize: 17, breakLine: true } },
    { text: "plans, dispatches, lands", options: { fontSize: 12, color: "AEAEB2" } },
  ], { x: M, y: cy - 0.55, w: 2.2, h: 1.1, align: "center", valign: "middle", color: C.background1 });
  const waves = [
    [["S1", "Invite API", 0], ["S2", "Email sender", 0], ["S3", "Billing math", 1], ["S4", "Settings UI", 0]],
    [["S5", "Audit log", 0], ["S6", "Invite page", 0], ["S7", "Migration", 1]],
    [["S8", "Onboarding", 0], ["S9", "End-to-end", 0]],
  ];
  waves.forEach((wave, wi) => {
    const x = wavesX[wi], top = cy - (wave.length * pillH + (wave.length - 1) * gap) / 2;
    text(s, "Wave " + (wi + 1), { x, y: 1.65, w: pillW, h: 0.3, fontSize: 13, bold: true, color: GRAY, align: "center" });
    wave.forEach(([id, label, opus], i) => {
      const hex = opus ? HEX.accent2 : HEX.accent1, y = top + i * (pillH + gap);
      rounded(s, { x, y, w: pillW, h: pillH, r: 0.25, fill: hex, transparency: 85, name: "story " + id });
      text(s, [
        { text: id + "  ", options: { bold: true, color: hex } },
        { text: label, options: { color: C.text1 } },
      ], { x: x + 0.2, y, w: pillW - 0.3, h: pillH, fontSize: 14, valign: "middle" });
    });
  });
  [[M + 2.25, 3.45], [5.65, 6.15], [8.35, 8.85], [11.05, 11.55]].forEach(([x0, x1], i) => {
    s.addShape(pres.shapes.RIGHT_ARROW, { x: x0 + 0.05, y: cy - 0.12, w: x1 - x0 - 0.1, h: 0.24, fill: { color: "D2D2D7" }, line: { type: "none" }, objectName: "flow arrow " + (i + 1) });
  });
  rounded(s, { x: 11.6, y: cy - 0.55, w: W - M - 11.6, h: 1.1, fill: HEX.accent3, name: "merged" });
  text(s, "Merged", { x: 11.6, y: cy - 0.55, w: W - M - 11.6, h: 1.1, fontSize: 15, bold: true, align: "center", valign: "middle", color: C.background1 });
  [[HEX.accent1, "Sonnet builds"], [HEX.accent2, "Opus where it matters"]].forEach(([hex, label], i) => {
    const y = cy + 0.85 + i * 0.32;
    dot(s, { x: M, y: y + 0.07, d: 0.16, fill: hex, name: "legend " + label });
    text(s, label, { x: M + 0.28, y, w: 2.3, h: 0.3, fontSize: 12, color: GRAY });
  });
  const speed = [
    ["10", HEX.accent1, "stories building at once", "Stories that share no files run side by side."],
    ["7 min", HEX.accent3, "median story, dispatch to merge", "Each agent works in its own worktree and branch."],
    ["4.2 days", HEX.accent2, "for a 14-milestone app", "Skåne Spa, planned and steered from Podium."],
  ];
  speed.forEach(([num, hex, head, body], i) => {
    const x = M + i * (CW / 3);
    text(s, num, { x, y: 5.15, w: CW / 3 - 0.3, h: 0.65, fontSize: 36, bold: true, color: hex, valign: "middle" });
    text(s, [
      { text: head, options: { bold: true, fontSize: 15, breakLine: true } },
      { text: body, options: { fontSize: 13, color: GRAY } },
    ], { x, y: 5.85, w: CW / 3 - 0.3, h: 0.8 });
  });
  s.addNotes("This is the core idea. The orchestrator breaks a milestone into stories, works out which ones depend on each other or touch the same files, and dispatches every story that is ready at once, each to its own agent in its own git worktree. Most build on Sonnet; stories touching money, dates, auth or migrations get Opus. When a wave lands, the next one starts. Podium shows all of it live, so speed doesn't cost you control. Numbers are from my Skåne Spa run: up to 10 stories building at once, a median of about 7 minutes from dispatch to merge per story.");

  // 4 — phases
  s = slide("LIGHT", "A run, from plan to retro.", "How");
  const phases = [
    ["P0", "Adopt", "Picks up earlier plans"],
    ["P1", "Plan", "Epics and decisions first"],
    ["P2", "Breakdown", "Stories and their models"],
    ["P3", "Build", "One agent per story"],
    ["P4", "Handback", "Gate, verify and land"],
    ["P5", "Retro", "Only after friction"],
  ];
  const pw = CW / phases.length;
  s.addShape(pres.shapes.LINE, { x: M + pw / 2, y: 2.38, w: CW - pw, h: 0, line: { color: "D2D2D7", width: 2 }, objectName: "phase line" });
  phases.forEach(([code, name, desc], i) => {
    const cx = M + i * pw + pw / 2;
    text(s, code, { x: cx - pw / 2, y: 1.7, w: pw, h: 0.3, fontSize: 13, bold: true, color: GRAY, align: "center" });
    dot(s, { x: cx - 0.2, y: 2.18, d: 0.4, fill: i === 5 ? HEX.accent5 : HEX.accent1, line: HEX.lt1, name: "phase " + code });
    text(s, name, { x: cx - pw / 2, y: 2.75, w: pw, h: 0.4, fontSize: 20, bold: true, align: "center" });
    text(s, desc, { x: cx - pw / 2 + 0.1, y: 3.2, w: pw - 0.2, h: 0.4, fontSize: 14, color: GRAY, align: "center" });
  });
  text(s, "Inside every milestone", { x: M, y: 4.2, w: CW, h: 0.35, fontSize: 15, bold: true, color: GRAY });
  const steps = [["R", "recon"], ["0", "grill"], ["0.5", "UI mock"], ["1", "architecture"], ["2", "spec"], ["3", "TDD + gate"], ["4", "verify"], ["5–6", "land"]];
  const sw = (CW - 7 * 0.2) / 8;
  steps.forEach(([n, label], i) => {
    const x = M + i * (sw + 0.2);
    rounded(s, { x, y: 4.7, w: sw, h: 1.25, fill: HEX.lt2, name: "step " + n });
    text(s, [
      { text: n, options: { fontSize: 28, bold: true, color: C.accent2, breakLine: true } },
      { text: label, options: { fontSize: 13, color: GRAY } },
    ], { x, y: 4.7, w: sw, h: 1.25, align: "center", valign: "middle" });
  });
  text(s, "Each step ends on a checkpoint, so a fresh context can pick up where the last one stopped.", { x: M, y: 6.2, w: CW, h: 0.4, fontSize: 15, color: GRAY });
  s.addNotes("The orchestrator owns P0 to P5; P3 is where the parallelism happens, and P4 runs in a fresh Opus subagent. Inside each milestone, deep-plan walks the same steps every time. The ledger stays under 60 lines, so a phase can restart in a clean context instead of dragging a huge one along.");

  // cake
  s = slide("LIGHT", "The suite as a layer cake.", "How");
  const gx = M + 1.9, gw6 = (W - M - gx - 5 * 0.12) / 6, col = (i) => gx + i * (gw6 + 0.12);
  [["P0", "Adopt"], ["P1", "Plan"], ["P2", "Breakdown"], ["P3", "Build"], ["P4", "Handback"], ["P5", "Retro"]].forEach(([code, name], i) => {
    text(s, [
      { text: code + "  ", options: { bold: true, color: GRAY } },
      { text: name, options: { bold: true } },
    ], { x: col(i), y: 1.5, w: gw6, h: 0.35, fontSize: 14 });
  });
  const rows = [
    ["Shell", "orchestrate-deep-plans", HEX.accent1, 1.95, 0.7],
    ["Planner", "deep-plan", HEX.accent2, 2.8, 1.2],
    ["Leaf skills", "swappable one by one", HEX.accent3, 4.15, 1.55],
    ["Runtime", "under every spawn", HEX.accent4, 5.85, 0.65],
  ];
  rows.forEach(([name, sub, hex, y, h]) => {
    dot(s, { x: M, y: y + 0.08, d: 0.16, fill: hex, name: "cake dot " + name });
    text(s, [
      { text: name, options: { bold: true, fontSize: 15, breakLine: true } },
      { text: sub, options: { fontSize: 11, color: GRAY } },
    ], { x: M + 0.28, y, w: 1.55, h });
  });
  const band = (y, h, hex, body, name) => {
    rounded(s, { x: gx, y, w: W - M - gx, h, r: 0.12, fill: hex, transparency: 88, name });
    text(s, body, { x: gx + 0.2, y, w: W - M - gx - 0.4, h, fontSize: 13, valign: "middle" });
  };
  band(1.95, 0.7, HEX.accent1, "Podium CLI and extension · human modes · two milestones at once · epic decisions before the milestone cut", "cake shell");
  const planner = ["Reads earlier plan history", "deep-plan: recon, grill, mock, architecture, spec", "Splits tasks into stories", "Parallel story agents replace the serial build", "deep-plan: gate, verify, land", "A fresh subagent reads the milestone's friction"];
  const leaf = [["Explore"], ["grilling", "research", "prototype", "domain-modeling", "codebase-design"], ["—"], ["tdd in every story prompt"], ["deep-qa", "code-review", "security-review", "diagnosing-bugs", "create-deep-pr"], ["retro rules", "podium tokens", "podium finding"]];
  planner.forEach((t, i) => {
    rounded(s, { x: col(i), y: 2.8, w: gw6, h: 1.2, r: 0.12, fill: HEX.accent2, transparency: i === 3 ? 94 : 88, name: "cake planner " + i });
    text(s, t, { x: col(i) + 0.12, y: 2.9, w: gw6 - 0.24, h: 1.0, fontSize: 12 });
  });
  leaf.forEach((items, i) => {
    rounded(s, { x: col(i), y: 4.15, w: gw6, h: 1.55, r: 0.12, fill: HEX.accent3, transparency: 88, name: "cake leaf " + i });
    text(s, items.map((t, k) => ({ text: t, options: { breakLine: k < items.length - 1 } })), { x: col(i) + 0.12, y: 4.25, w: gw6 - 0.24, h: 1.35, fontSize: 12 });
  });
  band(5.85, 0.65, HEX.accent4, "subagent protocol · Paseo or Agent · Opus for critical work, Sonnet for the rest · a contract of commands per repo", "cake runtime");
  s.addNotes("The same suite drawn as a layer cake: phases left to right, layers top to bottom. The shell owns the run and Podium. The planner/lander is the per-feature skill; only its plan and land halves are used, because P3 swaps its serial build for parallel story agents. Leaf skills are swappable one by one. The runtime sits under every spawn. A layer only calls the one beneath it, which is what makes each part replaceable.");

  // ideas
  s = slide("LIGHT", "Built on ideas that work.", "How");
  const ideas = [
    ["Grill before you build", "grilling · Matt Pocock", "A spec brief with numbered assumptions you confirm before any code.", HEX.accent1],
    ["Map decisions, then build", "wayfinder · Matt Pocock", "Questions spanning milestones are settled first; work too big gets re-cut.", HEX.accent1],
    ["Thin vertical slices", "epic-breakdown-advisor · Dean Peters", "Milestones cut with Humanizing Work's splitting patterns and a Valuable check.", HEX.accent1],
    ["Prototype to decide", "prototype · Matt Pocock", "A clickable mock is signed off before a single story is built.", HEX.accent1],
    ["Red, green, refactor", "tdd · Matt Pocock", "One commit per green slice, and a contract that must pass.", HEX.accent1],
    ["Review on two axes", "code-review · Matt Pocock", "Standards and spec reviewed by parallel subagents at every gate.", HEX.accent1],
    ["Deep modules", "codebase-design · after John Ousterhout", "Interfaces are pinned before stories split, so agents don't collide.", HEX.accent1],
    ["Learn from every run", "retro · Matt Pocock", "Friction becomes findings, and findings become next week's fixes.", HEX.accent1],
    ["Checkable instructions", "writing-for-agents · Matt Pocock", "Every step ends on a completion criterion an agent can verify.", HEX.accent1],
  ];
  const iw = (CW - 2 * 0.25) / 3, ih = 1.6;
  ideas.forEach(([idea, source, became, hex], i) => {
    const x = M + (i % 3) * (iw + 0.25), y = 1.55 + Math.floor(i / 3) * (ih + 0.2);
    rounded(s, { x, y, w: iw, h: ih, fill: HEX.lt2, name: "idea " + (i + 1) });
    text(s, [
      { text: source, options: { fontSize: 11, bold: true, color: hex, breakLine: true } },
      { text: idea, options: { fontSize: 17, bold: true, breakLine: true } },
      { text: became, options: { fontSize: 13, color: GRAY } },
    ], { x: x + 0.25, y: y + 0.18, w: iw - 0.5, h: ih - 0.3, paraSpaceAfter: 3 });
  });
  s.addNotes("The suite is mostly good ideas from other people, wired together and enforced. Matt Pocock's skills (github.com/mattpocock/skills): grilling, wayfinder, prototype, tdd, code-review, codebase-design, retro and writing-for-agents. Dean Peters' epic-breakdown-advisor (github.com/deanpeters/Product-Manager-Skills), built on Richard Lawrence and Peter Green's Humanizing Work guide to splitting user stories, shaped how epics are cut into milestones, including its rule that a slice that isn't valuable shouldn't be split off. Deep modules come from John Ousterhout's A Philosophy of Software Design. What the suite adds is the orchestration: these run in a fixed order, in parallel where they can, with Podium showing all of it.");

  // 5 — Podium
  s = slide("LIGHT_GRAY", "See every agent. Steer from one screen.", "How");
  const shotW = 8.5, shotH = shotW * 900 / 1440;
  s.addImage({ path: PODIUM_SHOT, x: M, y: 1.6, w: shotW, h: shotH, altText: "Podium dashboard: pipeline stepper, a Needs you panel, decisions made while away, stories in progress and the activity feed", objectName: "Podium screenshot", shadow: { type: "outer", color: "000000", opacity: 0.18, blur: 18, offset: 6, angle: 90 } });
  const podiumPoints = [
    [HEX.accent4, "Needs you", "A draft PR or a story waiting for your approval."],
    [HEX.accent1, "Decided while away", "Assumptions the run made. Confirm or reverse."],
    [HEX.accent3, "Working now", "Every story agent and what it is doing."],
    [GRAY, "Two Macs, one run", "State syncs through a git ref. Each claims milestones."],
  ];
  podiumPoints.forEach(([hex, head, body], i) => {
    const x = M + shotW + 0.45, y = 1.75 + i * 1.3;
    dot(s, { x, y: y + 0.08, d: 0.2, fill: hex, name: "podium dot " + (i + 1) });
    text(s, [
      { text: head, options: { bold: true, fontSize: 17, breakLine: true } },
      { text: body, options: { fontSize: 14, color: GRAY } },
    ], { x: x + 0.38, y, w: CW - shotW - 0.85, h: 1.15 });
  });
  s.addNotes("The Podium on a sample run. Orange: things that need me. Blue: decisions the run made while I was away. Green: stories being built right now. On the right the activity feed shows each dispatch with its model, retries and failures. It's plain JSON and a CLI, Python standard library only, with 438 tests.");

  // 6 — caps
  pres.addSection({ title: "Cost" });
  s = slide("DARK", "Nothing loops forever.", "Cost");
  const caps = [
    ["3", BRIGHT.blue, "tries per failure", "Then it stops and reports."],
    ["2", BRIGHT.purple, "attempts per story", "Then it blocks dependants and asks."],
    ["2", BRIGHT.green, "rounds of gate churn", "Then the verify loop stops and reports."],
    ["8", BRIGHT.orange, "lines per subagent reply", "Or one: COMMITTED or FAILED."],
    ["6", BRIGHT.red, "open decisions per epic", "Settled before the build starts."],
    ["1h", BRIGHT.teal, "idle and Podium stops", "No one around, nothing running."],
  ];
  caps.forEach(([num, hex, head, body], i) => {
    const x = M + (i % 3) * 4.05, y = 1.75 + Math.floor(i / 3) * 2.6;
    text(s, num, { x, y, w: 3.7, h: 1.2, fontSize: 80, bold: true, color: hex, valign: "middle" });
    text(s, head, { x, y: y + 1.3, w: 3.7, h: 0.4, fontSize: 19, bold: true, color: C.background1 });
    text(s, body, { x, y: y + 1.72, w: 3.7, h: 0.4, fontSize: 15, color: DARK_GRAY });
  });
  s.addNotes("The direct answer to the infinite loop. Verify retries start from the last green commit each time. A failed story blocks the stories that depend on it. When a cap is hit, a human decides, which is cheaper than an agent burning an afternoon.");

  // 7 — model routing
  s = slide("LIGHT", "The right model for every job.", "Cost");
  const tiers = [
    ["Haiku", 1.7, HEX.accent3, "Recon, security pass,", "screenshot checks"],
    ["Sonnet", 2.3, HEX.accent1, "Story builders,", "background drafts"],
    ["Opus", 2.9, HEX.accent2, "Review gates, bug diagnosis,", "money, dates, auth"],
  ];
  const base = 4.55;
  tiers.forEach(([name, d, hex, l1, l2], i) => {
    const cx = M + CW / 6 + i * (CW / 3);
    s.addShape(pres.shapes.OVAL, { x: cx - d / 2, y: base - d, w: d, h: d, fill: { color: hex, transparency: 82 }, line: { type: "none" }, objectName: "tier " + name });
    text(s, name, { x: cx - d / 2, y: base - d, w: d, h: d, fontSize: 18 + i * 4, bold: true, color: hex, align: "center", valign: "middle" });
    text(s, [{ text: l1, options: { breakLine: true } }, { text: l2 }], { x: cx - 2, y: base + 0.25, w: 4, h: 0.7, fontSize: 15, color: GRAY, align: "center" });
  });
  rounded(s, { x: M, y: 5.75, w: CW, h: 0.85, fill: HEX.lt2, name: "context rules" });
  text(s, [
    { text: "And a small context.  ", options: { bold: true } },
    { text: "Every spawn names its model, late phases start fresh, briefs share a cache prefix.", options: { color: GRAY } },
  ], { x: M + 0.35, y: 5.75, w: CW - 0.7, h: 0.85, fontSize: 16, valign: "middle" });
  s.addNotes("An unnamed spawn inherits the session model, usually Opus, so the subagent protocol makes every spawn pick deliberately. Context matters because the orchestrator re-reads its whole context every turn; files over 300 lines get targeted reads only.");

  // 8 — RTK
  s = slide("DARK", "RTK shrinks what the model reads.", "Cost");
  text(s, "−71%", { x: M, y: 1.75, w: 5.2, h: 1.6, fontSize: 110, bold: true, color: BRIGHT.teal, valign: "middle" });
  text(s, "output on ls -la. −48% on git log.", { x: M, y: 3.45, w: 5.2, h: 0.45, fontSize: 19, bold: true, color: C.background1 });
  text(s, "Tests show only failures. Truncated output tells the model how to get the rest. Already-tight output, like a single diff, barely shrinks.", { x: M, y: 4.15, w: 4.8, h: 1.4, fontSize: 15, color: DARK_GRAY });
  s.addChart(pres.charts.BAR, [
    { name: "Raw", labels: ["git log -20", "ls -la", "find *.py", "git status"], values: [7993, 1339, 923, 100] },
    { name: "Through RTK", labels: ["git log -20", "ls -la", "find *.py", "git status"], values: [4125, 384, 485, 49] },
  ], {
    x: 6.4, y: 1.7, w: W - M - 6.4, h: 4.9, barDir: "bar", barGrouping: "clustered", barGapWidthPct: 60,
    chartColors: ["3A3A3C", BRIGHT.teal],
    showTitle: true, title: "Characters of output, measured in this repo", titleFontSize: 13, titleColor: DARK_GRAY, titleFontFace: "+mn-lt",
    showValue: true, dataLabelPosition: "outEnd", dataLabelFontSize: 11, dataLabelColor: DARK_GRAY, dataLabelFontFace: "+mn-lt",
    catAxisLabelColor: DARK_GRAY, catAxisLabelFontSize: 13, catAxisLabelFontFace: "+mn-lt", catAxisOrientation: "maxMin", catAxisLineShow: false,
    valAxisHidden: true, valGridLine: { style: "none" }, catGridLine: { style: "none" },
    showLegend: true, legendPos: "b", legendFontSize: 12, legendFontFace: "+mn-lt", legendColor: DARK_GRAY,
  });
  s.addNotes("RTK is a CLI proxy: the agent runs commands as usual and RTK condenses the output before it reaches the context. I measured these on the podium-dashboard repo. The saving compounds, because every token in the context is re-read on later turns.");

  // 9 — QA
  pres.addSection({ title: "Quality" });
  s = slide("LIGHT", "Quality is gated, not hoped for.", "Quality");
  const gates = [
    [fa.FaComments, "Grill", "Assumptions confirmed"],
    [fa.FaObjectGroup, "Mock", "UI signed off first"],
    [fa.FaFlask, "TDD", "Red, green, commit"],
    [fa.FaCodeBranch, "Gate", "Opus review, contract"],
    [fa.FaMagnifyingGlass, "Verify", "deep-qa on the real app"],
    [fa.FaCodePullRequest, "PR", "Agent, Copilot, shots"],
    [fa.FaUserCheck, "You", "Push preview first"],
  ];
  const gw = CW / gates.length;
  s.addShape(pres.shapes.LINE, { x: M + gw / 2, y: 2.15, w: CW - gw, h: 0, line: { color: "D2D2D7", width: 2 }, objectName: "gate line" });
  for (let i = 0; i < gates.length; i++) {
    const [Ic, name, desc] = gates[i];
    const cx = M + i * gw + gw / 2;
    dot(s, { x: cx - 0.4, y: 1.75, d: 0.8, fill: i === 6 ? HEX.accent5 : HEX.accent3, line: HEX.lt1, name: "gate " + name });
    await glyph(s, Ic, "FFFFFF", { x: cx - 0.19, y: 1.96, d: 0.38, name: "gate " + name });
    text(s, name, { x: cx - gw / 2, y: 2.7, w: gw, h: 0.4, fontSize: 18, bold: true, align: "center" });
    text(s, desc, { x: cx - gw / 2 + 0.05, y: 3.12, w: gw - 0.1, h: 0.35, fontSize: 13, color: GRAY, align: "center" });
  }
  text(s, "Eight QA lenses. A verdict, never a silent skip.", { x: M, y: 3.95, w: CW, h: 0.35, fontSize: 15, bold: true, color: GRAY });
  const lenses = [
    [fa.FaBug, "Defects", "static"], [fa.FaListCheck, "Spec", "static"], [fa.FaPenRuler, "Design", "static"], [fa.FaShieldHalved, "Security", "static"],
    [fa.FaFileContract, "Contract", "running app"], [fa.FaRoute, "Journeys", "running app"], [fa.FaUniversalAccess, "Accessibility", "running app"], [fa.FaGaugeHigh, "Performance", "running app"],
  ];
  const lw = (CW - 3 * 0.25) / 4;
  for (let i = 0; i < lenses.length; i++) {
    const [Ic, name, kind] = lenses[i];
    const x = M + (i % 4) * (lw + 0.25), y = 4.45 + Math.floor(i / 4) * 1.15;
    rounded(s, { x, y, w: lw, h: 0.95, fill: HEX.lt2, name: "lens " + name });
    await glyph(s, Ic, i < 4 ? HEX.accent1 : HEX.accent3, { x: x + 0.3, y: y + 0.25, d: 0.45, name: "lens " + name });
    text(s, [
      { text: name, options: { bold: true, fontSize: 17, breakLine: true } },
      { text: kind, options: { fontSize: 12, color: GRAY } },
    ], { x: x + 1.0, y, w: lw - 1.15, h: 0.95, valign: "middle" });
  }
  s.addNotes("Seven gates between an idea and a push. The grill forces assumptions into the open before code exists, as a spec brief you confirm. TDD stops vacuous tests. deep-qa only reports: pass, fixable or blocked, and a lens that can't run is reported, never dropped. The last gate is always a human.");

  // 10 — control
  s = slide("DARK", "You stay in charge. Even while away.", "Quality");
  const control = [
    [fa.FaShieldHalved, BRIGHT.blue, "Nothing leaves without a yes", "Every push starts with a preview you see. PRs open as drafts."],
    [fa.FaMoon, BRIGHT.purple, "Away mode keeps work moving", "Agents log their assumptions. You confirm or reverse each."],
    [fa.FaHand, BRIGHT.orange, "Caps hand control back", "A story failing twice stops and asks you."],
    [fa.FaLock, BRIGHT.green, "Shared runs can't run code", "A pull never executes anything. Commands are approved by digest."],
  ];
  const cwid = (CW - 3 * 0.4) / 4;
  for (let i = 0; i < control.length; i++) {
    const [Ic, hex, head, body] = control[i];
    const x = M + i * (cwid + 0.4);
    await glyph(s, Ic, hex, { x, y: 2.6, d: 0.85, name: "control " + (i + 1) });
    text(s, head, { x, y: 3.8, w: cwid, h: 0.9, fontSize: 21, bold: true, color: C.background1 });
    text(s, body, { x, y: 4.8, w: cwid, h: 1.3, fontSize: 15, color: DARK_GRAY });
  }
  s.addNotes("Autonomy without losing control. The agents keep going while I'm in meetings, but every irreversible step, and every guess they made, comes back to me.");

  // 11 — self-improvement
  pres.addSection({ title: "Payoff" });
  s = slide("LIGHT", "It gets better every week.", "Payoff");
  const ringD = 4.0, rcx = M + 2.4, rcy = 4.25;
  s.addShape(pres.shapes.OVAL, { x: rcx - ringD / 2, y: rcy - ringD / 2, w: ringD, h: ringD, fill: { type: "none" }, line: { color: "D2D2D7", width: 3 }, objectName: "loop ring" });
  text(s, [
    { text: "Every", options: { fontSize: 24, bold: true, breakLine: true } },
    { text: "week", options: { fontSize: 24, bold: true, color: C.accent5 } },
  ], { x: rcx - 1.2, y: rcy - 0.55, w: 2.4, h: 1.1, align: "center", valign: "middle" });
  const loopPos = [[0, -1], [1, 0], [0, 1], [-1, 0]];
  const loop = [
    ["Retro", "A milestone with friction turns retries, failures and denied prompts into findings."],
    ["Gather", "Findings sync per run. Colleagues share patterns, never transcripts."],
    ["Improve", "Problems seen in two runs get up to five drafted, tested fixes."],
    ["Approve", "You ship what you like. Fixes that saved no tokens get reverted."],
  ];
  loop.forEach(([head, body], i) => {
    const [dx, dy] = loopPos[i];
    const nd = 0.7, nx = rcx + dx * ringD / 2 - nd / 2, ny = rcy + dy * ringD / 2 - nd / 2;
    dot(s, { x: nx, y: ny, d: nd, fill: i === 3 ? HEX.dk1 : HEX.accent5, line: HEX.lt1, name: "loop node " + (i + 1) });
    text(s, String(i + 1), { x: nx, y: ny, w: nd, h: nd, fontSize: 20, bold: true, color: C.background1, align: "center", valign: "middle" });
    const ty = 1.75 + i * 1.2;
    text(s, String(i + 1), { x: 6.3, y: ty, w: 0.5, h: 0.45, fontSize: 22, bold: true, color: i === 3 ? C.text1 : C.accent5 });
    text(s, [
      { text: head, options: { bold: true, fontSize: 20, breakLine: true } },
      { text: body, options: { fontSize: 15, color: GRAY } },
    ], { x: 6.9, y: ty, w: W - M - 6.9, h: 1.05 });
  });
  s.addNotes("The setup learns from its own friction. The retro looks for repeated mistakes and repeated work that wastes tokens; podium tokens mines session logs for oversized output and repeated commands. /deep-improve runs as a weekly schedule with nobody watching; it asks nothing, drafts fixes on local branches and writes a report. Nothing ships without my approval.");

  // 12 — measured
  s = slide("DARK", "What it has shipped so far.", "Payoff");
  const shipped = [
    ["86", BRIGHT.blue, "milestones landed", "Across six projects, each through the same gates."],
    ["99%", BRIGHT.green, "of 413 agent-built stories", "Landed on the first dispatch. None hit the retry cap."],
    ["1,092", BRIGHT.orange, "review findings before merge", "Raised by the gates; 74% fixed before landing, the rest skipped with a reason."],
    ["4.2", BRIGHT.purple, "days for Skåne Spa", "14 milestones, up to 10 stories in parallel, about $2.50 of model time per story."],
  ];
  shipped.forEach(([num, hex, head, body], i) => {
    const x = M + (i % 2) * 6.1, y = 1.65 + Math.floor(i / 2) * 2.45;
    text(s, num, { x, y, w: 5.6, h: 1.1, fontSize: 72, bold: true, color: hex, valign: "middle" });
    text(s, head, { x, y: y + 1.15, w: 5.6, h: 0.4, fontSize: 20, bold: true, color: C.background1 });
    text(s, body, { x, y: y + 1.57, w: 5.4, h: 0.65, fontSize: 15, color: DARK_GRAY });
  });
  text(s, "Measured from Podium runs and Claude session logs. There is no same-feature build without the setup, so no \u201cX\u00d7 faster\u201d claim.", { x: M, y: 6.5, w: CW, h: 0.35, fontSize: 12, color: "6E6E73" });
  s.addNotes("Real numbers from my own runs, not a benchmark. 86 milestones landed across six projects, mostly side projects like Skåne Spa, plus one shared work run. 99% means no re-dispatch was needed; an agent may still iterate inside its one attempt. The 1,092 findings are mostly standards and spec findings, not all bugs. Skåne Spa cost about $244 at list price, $170 of it the Opus orchestrator. What I can't claim: a speed-up versus working without it, fewer escaped bugs, or fewer tokens. The model mix lowers cost per token only modestly, about 5% on a whole run, because the orchestrator stays on Opus. That's the next thing to improve.");

  // 13 — close
  s = slide("DARK", "What you get.", "Payoff");
  const wins = [
    [BRIGHT.blue, "Parallel speed", "Up to 10 agents building at once, each on the model its job needs."],
    [BRIGHT.purple, "Control you can see", "Plan, steer and approve from one screen. Every loop capped."],
    [BRIGHT.green, "Quality by default", "Gates from grill to push, not a review at the end."],
    [BRIGHT.orange, "Compounding gains", "This week's friction is next week's fix."],
  ];
  wins.forEach(([hex, head, body], i) => {
    const x = M + (i % 2) * 6.1, y = 1.85 + Math.floor(i / 2) * 1.85;
    text(s, [
      { text: head, options: { bold: true, fontSize: 32, color: hex, breakLine: true } },
      { text: body, options: { fontSize: 17, color: DARK_GRAY } },
    ], { x, y, w: 5.6, h: 1.5 });
  });
  text(s, "github.com/warriv93/podium-dashboard  ·  github.com/warriv93/deep-skills", { x: M, y: 6.0, w: CW, h: 0.4, fontSize: 15, color: C.background1 });
  s.addNotes("The four things to take away: parallel agents for speed, Podium for control, gates for quality, and a weekly pass that improves the suite itself. To try it: install Podium from github.com/warriv93/podium-dashboard and the skills with deep-skills' install.sh, then start with /deep-plan on one feature. Questions?");

  await pres.writeFile({ fileName: OUT });
  await applyTheme(OUT, THEME);
}

build().catch((e) => { console.error(e); process.exit(1); });
