const pptxgen = require("pptxgenjs");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");

// Icon imports
const { FaBrain, FaGamepad, FaChartLine, FaNetworkWired, FaRobot, FaEye, FaExchangeAlt, FaBolt, FaGlobe, FaCheckCircle, FaCrosshairs, FaProjectDiagram, FaLayerGroup, FaCogs, FaServer, FaArrowRight, FaShieldAlt, FaStar, FaLightbulb, FaFlask, FaBookOpen, FaUsers } = require("react-icons/fa");

// ──────────────────────────────────────────────
// Icon rendering helpers
// ──────────────────────────────────────────────
function renderIconSvg(IconComponent, color = "#000000", size = 256) {
  return ReactDOMServer.renderToStaticMarkup(
    React.createElement(IconComponent, { color, size: String(size) })
  );
}

async function iconToBase64Png(IconComponent, color, size = 256) {
  const svg = renderIconSvg(IconComponent, color, size);
  const pngBuffer = await sharp(Buffer.from(svg)).png().toBuffer();
  return "image/png;base64," + pngBuffer.toString("base64");
}

// ──────────────────────────────────────────────
// Palette — Deep Ocean + Electric Teal
// ──────────────────────────────────────────────
const C = {
  darkNavy:    "0B1426",
  navy:        "121E36",
  midNavy:     "1A2A4A",
  deepTeal:    "0D4F5C",
  teal:        "0891B2",
  brightTeal:  "22D3EE",
  mint:        "5EEAD4",
  white:       "FFFFFF",
  offWhite:    "F0F9FF",
  lightGray:   "CBD5E1",
  mutedGray:   "94A3B8",
  textDark:    "1E293B",
  textMid:     "475569",
  cardBg:      "F8FAFC",
  accentOrange:"F59E0B",
  accentRed:   "EF4444",
  accentGreen: "10B981",
  accentPurple:"8B5CF6",
};

const makeShadow = () => ({
  type: "outer", color: "000000", blur: 8, offset: 3, angle: 135, opacity: 0.12
});

async function buildPresentation() {
  // Pre-render all icons
  const icons = {
    brain:      await iconToBase64Png(FaBrain, "#22D3EE"),
    gamepad:    await iconToBase64Png(FaGamepad, "#22D3EE"),
    chart:      await iconToBase64Png(FaChartLine, "#22D3EE"),
    network:    await iconToBase64Png(FaNetworkWired, "#22D3EE"),
    robot:      await iconToBase64Png(FaRobot, "#22D3EE"),
    eye:        await iconToBase64Png(FaEye, "#22D3EE"),
    exchange:   await iconToBase64Png(FaExchangeAlt, "#22D3EE"),
    bolt:       await iconToBase64Png(FaBolt, "#22D3EE"),
    globe:      await iconToBase64Png(FaGlobe, "#22D3EE"),
    check:      await iconToBase64Png(FaCheckCircle, "#10B981"),
    crosshairs: await iconToBase64Png(FaCrosshairs, "#22D3EE"),
    project:    await iconToBase64Png(FaProjectDiagram, "#22D3EE"),
    layers:     await iconToBase64Png(FaLayerGroup, "#22D3EE"),
    cogs:       await iconToBase64Png(FaCogs, "#22D3EE"),
    server:     await iconToBase64Png(FaServer, "#22D3EE"),
    arrow:      await iconToBase64Png(FaArrowRight, "#22D3EE"),
    shield:     await iconToBase64Png(FaShieldAlt, "#22D3EE"),
    star:       await iconToBase64Png(FaStar, "#F59E0B"),
    lightbulb:  await iconToBase64Png(FaLightbulb, "#F59E0B"),
    flask:      await iconToBase64Png(FaFlask, "#22D3EE"),
    book:       await iconToBase64Png(FaBookOpen, "#22D3EE"),
    users:      await iconToBase64Png(FaUsers, "#22D3EE"),
    // White versions for dark backgrounds
    brainW:     await iconToBase64Png(FaBrain, "#FFFFFF"),
    gamepadW:   await iconToBase64Png(FaGamepad, "#FFFFFF"),
    robotW:     await iconToBase64Png(FaRobot, "#FFFFFF"),
    eyeW:       await iconToBase64Png(FaEye, "#FFFFFF"),
    boltW:      await iconToBase64Png(FaBolt, "#FFFFFF"),
    chartW:     await iconToBase64Png(FaChartLine, "#FFFFFF"),
    flaskW:     await iconToBase64Png(FaFlask, "#FFFFFF"),
    starW:      await iconToBase64Png(FaStar, "#F59E0B"),
    checkW:     await iconToBase64Png(FaCheckCircle, "#5EEAD4"),
    lightbulbW: await iconToBase64Png(FaLightbulb, "#F59E0B"),
    shieldW:    await iconToBase64Png(FaShieldAlt, "#FFFFFF"),
    cogsW:      await iconToBase64Png(FaCogs, "#FFFFFF"),
    networkW:   await iconToBase64Png(FaNetworkWired, "#FFFFFF"),
    usersW:     await iconToBase64Png(FaUsers, "#FFFFFF"),
    layersW:    await iconToBase64Png(FaLayerGroup, "#FFFFFF"),
    arrowW:     await iconToBase64Png(FaArrowRight, "#5EEAD4"),
    exchangeW:  await iconToBase64Png(FaExchangeAlt, "#FFFFFF"),
    globeW:     await iconToBase64Png(FaGlobe, "#FFFFFF"),
    bookW:      await iconToBase64Png(FaBookOpen, "#FFFFFF"),
    crosshairsW:await iconToBase64Png(FaCrosshairs, "#FFFFFF"),
    projectW:   await iconToBase64Png(FaProjectDiagram, "#FFFFFF"),
    // Colored icons for cards
    brainTeal:  await iconToBase64Png(FaBrain, "#0891B2"),
    robotTeal:  await iconToBase64Png(FaRobot, "#0891B2"),
    eyeTeal:    await iconToBase64Png(FaEye, "#0891B2"),
    boltTeal:   await iconToBase64Png(FaBolt, "#0891B2"),
    chartTeal:  await iconToBase64Png(FaChartLine, "#0891B2"),
    networkTeal:await iconToBase64Png(FaNetworkWired, "#0891B2"),
    shieldTeal: await iconToBase64Png(FaShieldAlt, "#0891B2"),
    cogsTeal:   await iconToBase64Png(FaCogs, "#0891B2"),
    exchangeTeal:await iconToBase64Png(FaExchangeAlt, "#0891B2"),
    usersTeal:  await iconToBase64Png(FaUsers, "#0891B2"),
    flaskTeal:  await iconToBase64Png(FaFlask, "#0891B2"),
    globeTeal:  await iconToBase64Png(FaGlobe, "#0891B2"),
  };

  let pres = new pptxgen();
  pres.layout = "LAYOUT_16x9";
  pres.author = "GAME_CORE";
  pres.title = "Adaptive Boss AI: A Novel Multi-System RL Framework for Real-Time Combat";

  // ════════════════════════════════════════════
  // SLIDE 1 — Title
  // ════════════════════════════════════════════
  {
    let s = pres.addSlide();
    s.background = { color: C.darkNavy };

    // Subtle grid pattern via thin lines
    for (let i = 0; i < 10; i++) {
      s.addShape(pres.shapes.LINE, { x: i + 0.5, y: 0, w: 0, h: 5.625, line: { color: C.midNavy, width: 0.5 } });
    }
    for (let i = 0; i < 6; i++) {
      s.addShape(pres.shapes.LINE, { x: 0, y: i, w: 10, h: 0, line: { color: C.midNavy, width: 0.5 } });
    }

    // Teal accent bar at top
    s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 10, h: 0.06, fill: { color: C.brightTeal } });

    // Main icon
    s.addImage({ data: icons.brainW, x: 4.25, y: 0.7, w: 1.5, h: 1.5 });

    // Title
    s.addText("Adaptive Boss AI", {
      x: 0.5, y: 2.2, w: 9, h: 0.9,
      fontSize: 44, fontFace: "Trebuchet MS", color: C.white,
      bold: true, align: "center", margin: 0
    });

    // Subtitle
    s.addText("A Novel Multi-System Reinforcement Learning Framework\nfor Real-Time Combat Adaptation", {
      x: 1, y: 3.1, w: 8, h: 0.9,
      fontSize: 18, fontFace: "Calibri", color: C.brightTeal,
      align: "center", margin: 0
    });

    // Tech stack pills
    const pills = ["Unreal Engine 5.7", "C++", "Python", "PyTorch", "Stable Baselines3"];
    const pillW = 1.65;
    const totalW = pills.length * pillW + (pills.length - 1) * 0.15;
    const startX = (10 - totalW) / 2;
    pills.forEach((label, i) => {
      const px = startX + i * (pillW + 0.15);
      s.addShape(pres.shapes.RECTANGLE, {
        x: px, y: 4.3, w: pillW, h: 0.35,
        fill: { color: C.midNavy },
        line: { color: C.deepTeal, width: 1 }
      });
      s.addText(label, {
        x: px, y: 4.3, w: pillW, h: 0.35,
        fontSize: 10, fontFace: "Calibri", color: C.lightGray,
        align: "center", valign: "middle", margin: 0
      });
    });

    // Bottom bar
    s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 5.4, w: 10, h: 0.225, fill: { color: C.teal, transparency: 30 } });
    s.addText("GAME_CORE Project", {
      x: 0.5, y: 5.4, w: 9, h: 0.225,
      fontSize: 9, fontFace: "Calibri", color: C.mutedGray, align: "center", valign: "middle", margin: 0
    });
  }

  // ════════════════════════════════════════════
  // SLIDE 2 — Project Overview
  // ════════════════════════════════════════════
  {
    let s = pres.addSlide();
    s.background = { color: C.offWhite };
    // Top teal bar
    s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 10, h: 0.06, fill: { color: C.teal } });

    s.addImage({ data: icons.gamepad, x: 0.6, y: 0.35, w: 0.4, h: 0.4 });
    s.addText("Project Overview", {
      x: 1.1, y: 0.3, w: 6, h: 0.5,
      fontSize: 28, fontFace: "Trebuchet MS", color: C.textDark, bold: true, margin: 0
    });

    // Left column — description
    s.addText("What Is GAME_CORE?", {
      x: 0.6, y: 1.1, w: 4.2, h: 0.4,
      fontSize: 16, fontFace: "Calibri", color: C.teal, bold: true, margin: 0
    });
    s.addText([
      { text: "A real-time action combat game built in Unreal Engine 5.7 where a ", options: { breakLine: false } },
      { text: "boss character learns and adapts", options: { bold: true, breakLine: false } },
      { text: " to each player's unique fighting style through deep reinforcement learning.", options: {} },
    ], {
      x: 0.6, y: 1.5, w: 4.2, h: 1.0,
      fontSize: 13, fontFace: "Calibri", color: C.textMid, margin: 0
    });

    s.addText("The Core Idea", {
      x: 0.6, y: 2.5, w: 4.2, h: 0.4,
      fontSize: 16, fontFace: "Calibri", color: C.teal, bold: true, margin: 0
    });
    s.addText("Instead of scripted enemy behavior, the boss uses a portfolio of ML techniques — profiling, memory, hierarchical strategies, player modeling, and meta-learning — to deliver dynamically challenging and engaging fights.", {
      x: 0.6, y: 2.9, w: 4.2, h: 1.2,
      fontSize: 13, fontFace: "Calibri", color: C.textMid, margin: 0
    });

    // Right column — key facts card
    s.addShape(pres.shapes.RECTANGLE, {
      x: 5.3, y: 1.1, w: 4.2, h: 4.1,
      fill: { color: C.white },
      shadow: makeShadow()
    });
    // Teal left accent on card
    s.addShape(pres.shapes.RECTANGLE, { x: 5.3, y: 1.1, w: 0.07, h: 4.1, fill: { color: C.teal } });

    s.addText("Key Facts", {
      x: 5.65, y: 1.25, w: 3.6, h: 0.35,
      fontSize: 15, fontFace: "Calibri", color: C.teal, bold: true, margin: 0
    });

    const facts = [
      ["Engine", "Unreal Engine 5.7 (C++)"],
      ["RL Framework", "Stable Baselines3 + PyTorch"],
      ["Communication", "TCP socket, JSON @ 15 Hz"],
      ["Observation", "Up to 29-dim dynamic vector"],
      ["Action Space", "Discrete(5): Attack/Block/Dodge/Approach/Retreat"],
      ["Extensions", "9 layered ML systems"],
      ["Novel Systems", "4 (MAML, IRL, World Model, Emotion)"],
    ];
    facts.forEach((f, i) => {
      const fy = 1.7 + i * 0.48;
      s.addText(f[0], {
        x: 5.65, y: fy, w: 1.6, h: 0.3,
        fontSize: 11, fontFace: "Calibri", color: C.teal, bold: true, margin: 0
      });
      s.addText(f[1], {
        x: 7.2, y: fy, w: 2.15, h: 0.3,
        fontSize: 11, fontFace: "Calibri", color: C.textMid, margin: 0
      });
      if (i < facts.length - 1) {
        s.addShape(pres.shapes.LINE, { x: 5.65, y: fy + 0.38, w: 3.5, h: 0, line: { color: "E2E8F0", width: 0.5 } });
      }
    });

    // Bottom highlight strip
    s.addShape(pres.shapes.RECTANGLE, { x: 0.6, y: 4.6, w: 8.8, h: 0.55, fill: { color: C.teal, transparency: 8 } });
    s.addImage({ data: icons.lightbulb, x: 0.8, y: 4.67, w: 0.35, h: 0.35 });
    s.addText("No existing paper combines all these systems in a real-time action combat context.", {
      x: 1.3, y: 4.6, w: 7.8, h: 0.55,
      fontSize: 12, fontFace: "Calibri", color: C.textDark, bold: true, italic: true,
      valign: "middle", margin: 0
    });
  }

  // ════════════════════════════════════════════
  // SLIDE 3 — System Architecture / RL Loop
  // ════════════════════════════════════════════
  {
    let s = pres.addSlide();
    s.background = { color: C.offWhite };
    s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 10, h: 0.06, fill: { color: C.teal } });

    s.addImage({ data: icons.project, x: 0.6, y: 0.35, w: 0.4, h: 0.4 });
    s.addText("System Architecture", {
      x: 1.1, y: 0.3, w: 6, h: 0.5,
      fontSize: 28, fontFace: "Trebuchet MS", color: C.textDark, bold: true, margin: 0
    });

    // UE5 Box (left)
    s.addShape(pres.shapes.RECTANGLE, {
      x: 0.5, y: 1.15, w: 4.0, h: 3.8,
      fill: { color: C.white }, shadow: makeShadow()
    });
    s.addShape(pres.shapes.RECTANGLE, { x: 0.5, y: 1.15, w: 4.0, h: 0.45, fill: { color: C.navy } });
    s.addImage({ data: icons.cogsW, x: 0.7, y: 1.22, w: 0.3, h: 0.3 });
    s.addText("Unreal Engine 5.7 (C++)", {
      x: 1.05, y: 1.15, w: 3.3, h: 0.45,
      fontSize: 13, fontFace: "Calibri", color: C.white, bold: true, valign: "middle", margin: 0
    });

    // BP_Boss components
    s.addText("BP_Boss", {
      x: 0.75, y: 1.75, w: 3.5, h: 0.3,
      fontSize: 12, fontFace: "Calibri", color: C.teal, bold: true, margin: 0
    });
    const bossComps = [
      "CombatComponent (health, combos, warping)",
      "StateObservationComponent (17-dim obs)",
      "RLBridgeComponent (TCP server)",
      "BossActionComponent (5 actions)",
      "EmotionEstimationComponent (affect)",
      "PlayerMemoryComponent (cross-encounter)",
    ];
    bossComps.forEach((comp, i) => {
      s.addText(comp, {
        x: 0.85, y: 2.05 + i * 0.3, w: 3.4, h: 0.28,
        fontSize: 9.5, fontFace: "Calibri", color: C.textMid, margin: 0
      });
    });

    // BP_NeuralHero
    s.addText("BP_NeuralHero", {
      x: 0.75, y: 3.95, w: 3.5, h: 0.3,
      fontSize: 12, fontFace: "Calibri", color: C.teal, bold: true, margin: 0
    });
    s.addText("CombatComponent, PlayerProfileComponent,\nHitReaction, HitFeedback, CombatState", {
      x: 0.85, y: 4.2, w: 3.4, h: 0.55,
      fontSize: 9.5, fontFace: "Calibri", color: C.textMid, margin: 0
    });

    // Arrow between boxes
    s.addShape(pres.shapes.RECTANGLE, {
      x: 4.65, y: 2.5, w: 0.7, h: 0.6,
      fill: { color: C.teal }
    });
    s.addText("TCP\n5555", {
      x: 4.65, y: 2.5, w: 0.7, h: 0.6,
      fontSize: 9, fontFace: "Calibri", color: C.white, bold: true,
      align: "center", valign: "middle", margin: 0
    });

    // Python Box (right)
    s.addShape(pres.shapes.RECTANGLE, {
      x: 5.5, y: 1.15, w: 4.0, h: 3.8,
      fill: { color: C.white }, shadow: makeShadow()
    });
    s.addShape(pres.shapes.RECTANGLE, { x: 5.5, y: 1.15, w: 4.0, h: 0.45, fill: { color: C.navy } });
    s.addImage({ data: icons.brainW, x: 5.7, y: 1.22, w: 0.3, h: 0.3 });
    s.addText("Python RL System", {
      x: 6.05, y: 1.15, w: 3.3, h: 0.45,
      fontSize: 13, fontFace: "Calibri", color: C.white, bold: true, valign: "middle", margin: 0
    });

    const pyComps = [
      ["BossEnv", "gymnasium.Env (dynamic obs)"],
      ["ConstrainedBossEnv", "win-rate cap + emotion"],
      ["HierarchicalAgent", "strategist + tactician"],
      ["MaxEntIRL", "player reward recovery"],
      ["WorldModel + Planner", "dynamics + lookahead"],
      ["MAMLTrainer", "meta-learning adaptation"],
      ["ReplayBufferManager", "per-player .npz data"],
    ];
    pyComps.forEach((comp, i) => {
      s.addText(comp[0], {
        x: 5.75, y: 1.75 + i * 0.42, w: 1.65, h: 0.25,
        fontSize: 9.5, fontFace: "Calibri", color: C.teal, bold: true, margin: 0
      });
      s.addText(comp[1], {
        x: 7.4, y: 1.75 + i * 0.42, w: 1.9, h: 0.25,
        fontSize: 9, fontFace: "Calibri", color: C.textMid, margin: 0
      });
    });

    // RL Loop label at bottom
    s.addShape(pres.shapes.RECTANGLE, { x: 0.5, y: 5.1, w: 9.0, h: 0.4, fill: { color: C.teal, transparency: 8 } });
    s.addText("RL Loop:  Observe (JSON) \u2192 Python selects action \u2192 UE5 executes \u2192 Reward feedback  |  ~15 Hz tick rate", {
      x: 0.7, y: 5.1, w: 8.6, h: 0.4,
      fontSize: 11, fontFace: "Calibri", color: C.textDark, bold: true,
      align: "center", valign: "middle", margin: 0
    });
  }

  // ════════════════════════════════════════════
  // SLIDE 4 — Main Objectives
  // ════════════════════════════════════════════
  {
    let s = pres.addSlide();
    s.background = { color: C.darkNavy };
    s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 10, h: 0.06, fill: { color: C.brightTeal } });

    s.addImage({ data: icons.crosshairsW, x: 0.6, y: 0.3, w: 0.4, h: 0.4 });
    s.addText("Main Objectives", {
      x: 1.1, y: 0.25, w: 6, h: 0.5,
      fontSize: 28, fontFace: "Trebuchet MS", color: C.white, bold: true, margin: 0
    });

    const objectives = [
      { icon: icons.robotW, title: "Adaptive Boss Behavior", desc: "Train a boss AI via RL that learns combat tactics in real-time rather than using hand-scripted patterns" },
      { icon: icons.usersW, title: "Per-Player Personalization", desc: "Profile each player's style (8-dim EMA) and adapt difficulty, strategy, and behavior to individual players" },
      { icon: icons.shieldW, title: "Engagement Over Domination", desc: "Constrain the boss to maintain fun: cap win rate at ~45%, ensure close fights, and reward spectacle over efficiency" },
      { icon: icons.layersW, title: "Hierarchical Decision-Making", desc: "Separate high-level strategy (aggressive, defensive, hit-and-run, counter) from moment-to-moment tactics" },
      { icon: icons.exchangeW, title: "Rapid Adaptation to New Players", desc: "Transfer learning and MAML meta-learning let the boss adapt in 2\u20133 gradient steps instead of 50k+" },
      { icon: icons.eyeW, title: "Understand Player Intent", desc: "Use IRL, world models, and emotion estimation to predict why the player acts, not just what they do" },
    ];

    objectives.forEach((obj, i) => {
      const row = Math.floor(i / 2);
      const col = i % 2;
      const cx = 0.5 + col * 4.75;
      const cy = 1.05 + row * 1.5;

      s.addShape(pres.shapes.RECTANGLE, {
        x: cx, y: cy, w: 4.5, h: 1.3,
        fill: { color: C.navy },
        line: { color: C.midNavy, width: 1 }
      });
      // Teal left accent
      s.addShape(pres.shapes.RECTANGLE, { x: cx, y: cy, w: 0.06, h: 1.3, fill: { color: C.brightTeal } });

      s.addImage({ data: obj.icon, x: cx + 0.25, y: cy + 0.2, w: 0.4, h: 0.4 });
      s.addText(obj.title, {
        x: cx + 0.8, y: cy + 0.12, w: 3.4, h: 0.35,
        fontSize: 13, fontFace: "Calibri", color: C.brightTeal, bold: true, margin: 0
      });
      s.addText(obj.desc, {
        x: cx + 0.8, y: cy + 0.5, w: 3.4, h: 0.7,
        fontSize: 10.5, fontFace: "Calibri", color: C.lightGray, margin: 0
      });
    });
  }

  // ════════════════════════════════════════════
  // SLIDE 5 — The 9 Extension Systems (Overview)
  // ════════════════════════════════════════════
  {
    let s = pres.addSlide();
    s.background = { color: C.offWhite };
    s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 10, h: 0.06, fill: { color: C.teal } });

    s.addImage({ data: icons.layers, x: 0.6, y: 0.35, w: 0.4, h: 0.4 });
    s.addText("The 9 Layered ML Systems", {
      x: 1.1, y: 0.3, w: 7, h: 0.5,
      fontSize: 28, fontFace: "Trebuchet MS", color: C.textDark, bold: true, margin: 0
    });

    const systems = [
      { num: "1", name: "Player Profiling", desc: "8-dim EMA behavioral vector", clr: C.teal },
      { num: "2", name: "Cross-Encounter Memory", desc: "Per-dimension decay prevents all-knowing boss", clr: C.teal },
      { num: "3", name: "Hierarchical RL", desc: "Strategist (4 archetypes) + Tactician (5 actions)", clr: C.teal },
      { num: "4", name: "Constrained Learning", desc: "Win-rate cap + incompetence budget for fun", clr: C.teal },
      { num: "5", name: "Explainability", desc: "Profile-driven taunts reveal boss reasoning", clr: C.teal },
      { num: "6", name: "Transfer Learning", desc: "Base model + per-player fine-tuning from replays", clr: C.teal },
      { num: "7", name: "MAML Meta-Learning", desc: "Adapt in 2\u20133 gradient steps (novel)", clr: C.accentOrange },
      { num: "8", name: "IRL Player Modeling", desc: "Recover player reward function (novel)", clr: C.accentOrange },
      { num: "9a", name: "World Model + Planning", desc: "Learned dynamics for lookahead (novel)", clr: C.accentOrange },
      { num: "9b", name: "Emotion-Aware AI", desc: "Behavioral frustration/flow/boredom (novel)", clr: C.accentOrange },
    ];

    // 2 columns of 5
    systems.forEach((sys, i) => {
      const col = i < 5 ? 0 : 1;
      const row = i < 5 ? i : i - 5;
      const cx = 0.5 + col * 4.8;
      const cy = 1.05 + row * 0.88;

      s.addShape(pres.shapes.RECTANGLE, {
        x: cx, y: cy, w: 4.5, h: 0.72,
        fill: { color: C.white }, shadow: makeShadow()
      });

      // Number circle
      s.addShape(pres.shapes.OVAL, {
        x: cx + 0.15, y: cy + 0.14, w: 0.44, h: 0.44,
        fill: { color: sys.clr }
      });
      s.addText(sys.num, {
        x: cx + 0.15, y: cy + 0.14, w: 0.44, h: 0.44,
        fontSize: 12, fontFace: "Calibri", color: C.white, bold: true,
        align: "center", valign: "middle", margin: 0
      });

      s.addText(sys.name, {
        x: cx + 0.72, y: cy + 0.08, w: 3.5, h: 0.3,
        fontSize: 12.5, fontFace: "Calibri", color: C.textDark, bold: true, margin: 0
      });
      s.addText(sys.desc, {
        x: cx + 0.72, y: cy + 0.38, w: 3.5, h: 0.28,
        fontSize: 10, fontFace: "Calibri", color: C.textMid, margin: 0
      });
    });

    // Legend
    s.addShape(pres.shapes.OVAL, { x: 3.5, y: 5.2, w: 0.2, h: 0.2, fill: { color: C.teal } });
    s.addText("Established techniques", {
      x: 3.78, y: 5.15, w: 2, h: 0.3,
      fontSize: 10, fontFace: "Calibri", color: C.textMid, margin: 0
    });
    s.addShape(pres.shapes.OVAL, { x: 5.9, y: 5.2, w: 0.2, h: 0.2, fill: { color: C.accentOrange } });
    s.addText("Novel contributions", {
      x: 6.18, y: 5.15, w: 2, h: 0.3,
      fontSize: 10, fontFace: "Calibri", color: C.textMid, bold: true, margin: 0
    });
  }

  // ════════════════════════════════════════════
  // SLIDE 6 — Novel Contribution 1: MAML Meta-Learning
  // ════════════════════════════════════════════
  {
    let s = pres.addSlide();
    s.background = { color: C.offWhite };
    s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 10, h: 0.06, fill: { color: C.teal } });
    // "Novel" badge
    s.addShape(pres.shapes.RECTANGLE, { x: 8.3, y: 0.25, w: 1.3, h: 0.35, fill: { color: C.accentOrange } });
    s.addText("NOVEL", {
      x: 8.3, y: 0.25, w: 1.3, h: 0.35,
      fontSize: 11, fontFace: "Calibri", color: C.white, bold: true,
      align: "center", valign: "middle", margin: 0
    });

    s.addImage({ data: icons.bolt, x: 0.6, y: 0.3, w: 0.4, h: 0.4 });
    s.addText("MAML Meta-Learning for Boss AI", {
      x: 1.1, y: 0.25, w: 6.5, h: 0.5,
      fontSize: 26, fontFace: "Trebuchet MS", color: C.textDark, bold: true, margin: 0
    });

    s.addText("First application of Model-Agnostic Meta-Learning to game enemy adaptation", {
      x: 0.6, y: 0.85, w: 8.5, h: 0.35,
      fontSize: 13, fontFace: "Calibri", color: C.teal, italic: true, margin: 0
    });

    // Left — How it works
    s.addText("How It Works", {
      x: 0.6, y: 1.35, w: 4.2, h: 0.35,
      fontSize: 15, fontFace: "Calibri", color: C.textDark, bold: true, margin: 0
    });

    const steps = [
      "Collect replay data from 8+ distinct players (3+ episodes each)",
      "Meta-train: learn initial weights \u03B8 designed for fast adaptation",
      "Inner loop: N gradient steps on player-specific support data",
      "Outer loop: evaluate on query data, backprop through inner loop",
      "At runtime: adapt to any new player in 2\u20133 gradient steps (seconds)",
    ];
    steps.forEach((step, i) => {
      s.addShape(pres.shapes.OVAL, {
        x: 0.65, y: 1.82 + i * 0.45, w: 0.28, h: 0.28,
        fill: { color: C.teal }
      });
      s.addText(String(i + 1), {
        x: 0.65, y: 1.82 + i * 0.45, w: 0.28, h: 0.28,
        fontSize: 10, fontFace: "Calibri", color: C.white, bold: true,
        align: "center", valign: "middle", margin: 0
      });
      s.addText(step, {
        x: 1.05, y: 1.78 + i * 0.45, w: 3.75, h: 0.35,
        fontSize: 11, fontFace: "Calibri", color: C.textMid, margin: 0
      });
    });

    // Right — Key metric card
    s.addShape(pres.shapes.RECTANGLE, {
      x: 5.3, y: 1.35, w: 4.2, h: 2.0,
      fill: { color: C.white }, shadow: makeShadow()
    });
    s.addShape(pres.shapes.RECTANGLE, { x: 5.3, y: 1.35, w: 4.2, h: 0.4, fill: { color: C.navy } });
    s.addText("Key Differentiator", {
      x: 5.5, y: 1.35, w: 3.8, h: 0.4,
      fontSize: 12, fontFace: "Calibri", color: C.white, bold: true, valign: "middle", margin: 0
    });
    s.addText("3", {
      x: 5.5, y: 1.85, w: 1.5, h: 0.95,
      fontSize: 54, fontFace: "Trebuchet MS", color: C.teal, bold: true,
      align: "center", valign: "middle", margin: 0
    });
    s.addText("gradient\nsteps", {
      x: 6.7, y: 1.95, w: 1.2, h: 0.7,
      fontSize: 13, fontFace: "Calibri", color: C.textMid, margin: 0
    });
    s.addText("vs", {
      x: 7.7, y: 2.1, w: 0.4, h: 0.4,
      fontSize: 12, fontFace: "Calibri", color: C.mutedGray, align: "center", valign: "middle", margin: 0
    });
    s.addText("50k+", {
      x: 8.0, y: 1.95, w: 1.2, h: 0.5,
      fontSize: 28, fontFace: "Trebuchet MS", color: C.accentRed, bold: true, margin: 0
    });
    s.addText("fine-tune steps\n(transfer learning)", {
      x: 8.0, y: 2.4, w: 1.3, h: 0.5,
      fontSize: 10, fontFace: "Calibri", color: C.textMid, margin: 0
    });

    // Novelty claim card
    s.addShape(pres.shapes.RECTANGLE, {
      x: 5.3, y: 3.55, w: 4.2, h: 1.25,
      fill: { color: C.white }, shadow: makeShadow()
    });
    s.addShape(pres.shapes.RECTANGLE, { x: 5.3, y: 3.55, w: 0.07, h: 1.25, fill: { color: C.accentOrange } });
    s.addImage({ data: icons.star, x: 5.55, y: 3.65, w: 0.3, h: 0.3 });
    s.addText("Why It's Novel", {
      x: 5.95, y: 3.62, w: 3.3, h: 0.3,
      fontSize: 12, fontFace: "Calibri", color: C.accentOrange, bold: true, margin: 0
    });
    s.addText("Finn et al. 2017 introduced MAML for locomotion tasks. No published work applies meta-learning to game boss AI. This is the first real-time combat application.", {
      x: 5.55, y: 4.0, w: 3.75, h: 0.7,
      fontSize: 10.5, fontFace: "Calibri", color: C.textMid, margin: 0
    });

    // Technical detail strip
    s.addShape(pres.shapes.RECTANGLE, { x: 0.5, y: 4.95, w: 9.0, h: 0.5, fill: { color: C.teal, transparency: 8 } });
    s.addText("Implementation: MamlPolicy (actor-critic MLP) + differentiable inner loop via torch.autograd.grad(create_graph=True)", {
      x: 0.7, y: 4.95, w: 8.6, h: 0.5,
      fontSize: 11, fontFace: "Calibri", color: C.textDark,
      valign: "middle", margin: 0
    });
  }

  // ════════════════════════════════════════════
  // SLIDE 7 — Novel Contribution 2: IRL Player Modeling
  // ════════════════════════════════════════════
  {
    let s = pres.addSlide();
    s.background = { color: C.offWhite };
    s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 10, h: 0.06, fill: { color: C.teal } });
    s.addShape(pres.shapes.RECTANGLE, { x: 8.3, y: 0.25, w: 1.3, h: 0.35, fill: { color: C.accentOrange } });
    s.addText("NOVEL", {
      x: 8.3, y: 0.25, w: 1.3, h: 0.35,
      fontSize: 11, fontFace: "Calibri", color: C.white, bold: true,
      align: "center", valign: "middle", margin: 0
    });

    s.addImage({ data: icons.eye, x: 0.6, y: 0.3, w: 0.4, h: 0.4 });
    s.addText("IRL Player Modeling", {
      x: 1.1, y: 0.25, w: 6.5, h: 0.5,
      fontSize: 26, fontFace: "Trebuchet MS", color: C.textDark, bold: true, margin: 0
    });
    s.addText("Inverse Reinforcement Learning recovers the player's implicit reward function", {
      x: 0.6, y: 0.85, w: 8.5, h: 0.35,
      fontSize: 13, fontFace: "Calibri", color: C.teal, italic: true, margin: 0
    });

    // Left — Algorithm
    s.addShape(pres.shapes.RECTANGLE, {
      x: 0.5, y: 1.35, w: 4.3, h: 3.1,
      fill: { color: C.white }, shadow: makeShadow()
    });
    s.addShape(pres.shapes.RECTANGLE, { x: 0.5, y: 1.35, w: 4.3, h: 0.4, fill: { color: C.navy } });
    s.addText("Maximum Entropy IRL (Ziebart et al. 2008)", {
      x: 0.7, y: 1.35, w: 3.9, h: 0.4,
      fontSize: 11, fontFace: "Calibri", color: C.white, bold: true, valign: "middle", margin: 0
    });

    s.addText("R(s) = \u03B8\u1D40 \u00B7 \u03C6(s)", {
      x: 0.7, y: 1.95, w: 3.9, h: 0.45,
      fontSize: 22, fontFace: "Consolas", color: C.teal, bold: true, align: "center", margin: 0
    });

    const irlDetails = [
      ["\u03B8", "20-dim learned reward weight vector"],
      ["\u03C6(s)", "Feature vector: HP diff, range, advantage, profile..."],
      ["Output", "P(a|s) for 5 actions via soft Q-values"],
      ["Target", "35\u201350% top-1 accuracy (vs 20% random)"],
    ];
    irlDetails.forEach((d, i) => {
      s.addText(d[0], {
        x: 0.75, y: 2.5 + i * 0.45, w: 0.7, h: 0.3,
        fontSize: 11, fontFace: "Consolas", color: C.teal, bold: true, margin: 0
      });
      s.addText(d[1], {
        x: 1.5, y: 2.5 + i * 0.45, w: 3.1, h: 0.3,
        fontSize: 10.5, fontFace: "Calibri", color: C.textMid, margin: 0
      });
    });

    // Right — What & Why
    s.addText("Predicts WHY, Not Just WHAT", {
      x: 5.3, y: 1.35, w: 4.2, h: 0.4,
      fontSize: 15, fontFace: "Calibri", color: C.textDark, bold: true, margin: 0
    });
    s.addText("Standard profiling measures what actions a player takes. IRL recovers the underlying reward function\u2014why they prefer certain actions\u2014enabling prediction in novel situations the boss hasn't seen before.", {
      x: 5.3, y: 1.8, w: 4.2, h: 1.0,
      fontSize: 12, fontFace: "Calibri", color: C.textMid, margin: 0
    });

    // Integration points
    s.addText("Integration Points", {
      x: 5.3, y: 2.9, w: 4.2, h: 0.35,
      fontSize: 13, fontFace: "Calibri", color: C.teal, bold: true, margin: 0
    });
    const intPoints = [
      "+5 dims added to observation (player action probs)",
      "Feeds BossPlanner with predicted player responses",
      "Enables world model to simulate player behavior",
    ];
    intPoints.forEach((pt, i) => {
      s.addImage({ data: icons.check, x: 5.35, y: 3.35 + i * 0.4, w: 0.22, h: 0.22 });
      s.addText(pt, {
        x: 5.65, y: 3.3 + i * 0.4, w: 3.7, h: 0.35,
        fontSize: 11, fontFace: "Calibri", color: C.textMid, margin: 0
      });
    });

    // Novelty strip
    s.addShape(pres.shapes.RECTANGLE, { x: 0.5, y: 4.75, w: 9.0, h: 0.65, fill: { color: C.teal, transparency: 8 } });
    s.addImage({ data: icons.star, x: 0.7, y: 4.87, w: 0.3, h: 0.3 });
    s.addText([
      { text: "Novelty: ", options: { bold: true, color: C.accentOrange } },
      { text: "No paper uses IRL for real-time action combat player modeling. Closest work (Wang et al. 2019) targets MMO economies\u2014a fundamentally different domain.", options: { color: C.textDark } },
    ], {
      x: 1.15, y: 4.75, w: 8.2, h: 0.65,
      fontSize: 11, fontFace: "Calibri", valign: "middle", margin: 0
    });
  }

  // ════════════════════════════════════════════
  // SLIDE 8 — Novel Contribution 3: World Model + Planning
  // ════════════════════════════════════════════
  {
    let s = pres.addSlide();
    s.background = { color: C.offWhite };
    s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 10, h: 0.06, fill: { color: C.teal } });
    s.addShape(pres.shapes.RECTANGLE, { x: 8.3, y: 0.25, w: 1.3, h: 0.35, fill: { color: C.accentOrange } });
    s.addText("NOVEL", {
      x: 8.3, y: 0.25, w: 1.3, h: 0.35,
      fontSize: 11, fontFace: "Calibri", color: C.white, bold: true,
      align: "center", valign: "middle", margin: 0
    });

    s.addImage({ data: icons.globe, x: 0.6, y: 0.3, w: 0.4, h: 0.4 });
    s.addText("World Model & Deliberative Planning", {
      x: 1.1, y: 0.25, w: 7, h: 0.5,
      fontSize: 26, fontFace: "Trebuchet MS", color: C.textDark, bold: true, margin: 0
    });
    s.addText("Transforms the boss from purely reactive to deliberative: think before acting", {
      x: 0.6, y: 0.85, w: 8.5, h: 0.35,
      fontSize: 13, fontFace: "Calibri", color: C.teal, italic: true, margin: 0
    });

    // Flow diagram: obs -> world model -> plan -> action
    const flowY = 1.5;
    const boxes = [
      { x: 0.5, w: 1.8, label: "Current\nObservation", sub: "17-dim state" },
      { x: 2.8, w: 2.2, label: "World Model\n(MLP Dynamics)", sub: "f(s, a_boss, a_player) \u2192 s', r" },
      { x: 5.5, w: 1.9, label: "BossPlanner\n(1-2 step look.)", sub: "5 actions \u00D7 top-K player" },
      { x: 7.9, w: 1.6, label: "Best\nAction", sub: "Blended with policy" },
    ];
    boxes.forEach((b) => {
      s.addShape(pres.shapes.RECTANGLE, {
        x: b.x, y: flowY, w: b.w, h: 1.1,
        fill: { color: C.white }, shadow: makeShadow()
      });
      s.addShape(pres.shapes.RECTANGLE, { x: b.x, y: flowY, w: b.w, h: 0.04, fill: { color: C.teal } });
      s.addText(b.label, {
        x: b.x + 0.1, y: flowY + 0.12, w: b.w - 0.2, h: 0.55,
        fontSize: 11, fontFace: "Calibri", color: C.textDark, bold: true,
        align: "center", valign: "middle", margin: 0
      });
      s.addText(b.sub, {
        x: b.x + 0.1, y: flowY + 0.7, w: b.w - 0.2, h: 0.3,
        fontSize: 9, fontFace: "Calibri", color: C.mutedGray,
        align: "center", margin: 0
      });
    });
    // Arrows between boxes
    [2.35, 5.05, 7.45].forEach(ax => {
      s.addImage({ data: icons.arrowW, x: ax, y: flowY + 0.35, w: 0.35, h: 0.35 });
    });

    // Bottom section — two cards
    // Card 1: Architecture
    s.addShape(pres.shapes.RECTANGLE, {
      x: 0.5, y: 2.9, w: 4.3, h: 2.3,
      fill: { color: C.white }, shadow: makeShadow()
    });
    s.addShape(pres.shapes.RECTANGLE, { x: 0.5, y: 2.9, w: 0.07, h: 2.3, fill: { color: C.teal } });
    s.addText("World Model Architecture", {
      x: 0.75, y: 3.0, w: 3.8, h: 0.35,
      fontSize: 13, fontFace: "Calibri", color: C.teal, bold: true, margin: 0
    });
    const archDetails = [
      "Input: obs(17) + boss_action(5) + player_action(6) = 28 dims",
      "Hidden: 128 \u2192 ReLU \u2192 128 \u2192 ReLU",
      "Output: predicted next_obs(17) + reward(1) = 18 dims",
      "Training: supervised MSE on replay data",
      "Hero action estimated C++-side from observation deltas",
    ];
    archDetails.forEach((d, i) => {
      s.addText(d, {
        x: 0.85, y: 3.4 + i * 0.33, w: 3.75, h: 0.32,
        fontSize: 10, fontFace: "Calibri", color: C.textMid, margin: 0
      });
    });

    // Card 2: Novelty
    s.addShape(pres.shapes.RECTANGLE, {
      x: 5.2, y: 2.9, w: 4.3, h: 2.3,
      fill: { color: C.white }, shadow: makeShadow()
    });
    s.addShape(pres.shapes.RECTANGLE, { x: 5.2, y: 2.9, w: 0.07, h: 2.3, fill: { color: C.accentOrange } });
    s.addImage({ data: icons.star, x: 5.45, y: 3.0, w: 0.25, h: 0.25 });
    s.addText("Why It's Novel", {
      x: 5.8, y: 3.0, w: 3.5, h: 0.3,
      fontSize: 13, fontFace: "Calibri", color: C.accentOrange, bold: true, margin: 0
    });
    s.addText("DreamerV3 (2023) demonstrated world models in Atari/Minecraft but for player agents, not combat enemy AI. No paper applies learned dynamics to boss action planning in real-time melee combat.", {
      x: 5.45, y: 3.4, w: 3.85, h: 0.9,
      fontSize: 11, fontFace: "Calibri", color: C.textMid, margin: 0
    });
    s.addText("IRL + World Model synergy:", {
      x: 5.45, y: 4.3, w: 3.85, h: 0.3,
      fontSize: 11, fontFace: "Calibri", color: C.teal, bold: true, margin: 0
    });
    s.addText("IRL predicts what the player will do. The world model predicts what happens next. Together they enable the boss to think ahead.", {
      x: 5.45, y: 4.6, w: 3.85, h: 0.5,
      fontSize: 10.5, fontFace: "Calibri", color: C.textMid, margin: 0
    });
  }

  // ════════════════════════════════════════════
  // SLIDE 9 — Novel Contribution 4: Emotion-Aware AI
  // ════════════════════════════════════════════
  {
    let s = pres.addSlide();
    s.background = { color: C.offWhite };
    s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 10, h: 0.06, fill: { color: C.teal } });
    s.addShape(pres.shapes.RECTANGLE, { x: 8.3, y: 0.25, w: 1.3, h: 0.35, fill: { color: C.accentOrange } });
    s.addText("NOVEL", {
      x: 8.3, y: 0.25, w: 1.3, h: 0.35,
      fontSize: 11, fontFace: "Calibri", color: C.white, bold: true,
      align: "center", valign: "middle", margin: 0
    });

    s.addImage({ data: icons.chart, x: 0.6, y: 0.3, w: 0.4, h: 0.4 });
    s.addText("Emotion-Aware Adaptive AI", {
      x: 1.1, y: 0.25, w: 7, h: 0.5,
      fontSize: 26, fontFace: "Trebuchet MS", color: C.textDark, bold: true, margin: 0
    });
    s.addText("Behavioral proxy for player affect \u2014 no hardware required", {
      x: 0.6, y: 0.85, w: 8.5, h: 0.35,
      fontSize: 13, fontFace: "Calibri", color: C.teal, italic: true, margin: 0
    });

    // Three emotion cards
    const emotions = [
      {
        name: "Frustration", color: C.accentRed, icon: icons.crosshairs,
        signals: "3+ loss streak, fight duration\u2193,\naction spam, low action entropy",
        response: "Boss gets easier:\nepsilon += 0.15, damage reward \u00D7 0.5"
      },
      {
        name: "Flow", color: C.accentGreen, icon: icons.check,
        signals: "40\u201360% win rate, close HP at end,\nhigh action variety, stable duration",
        response: "Boss maintains difficulty:\nstability bonus, strategy preserved"
      },
      {
        name: "Boredom", color: C.accentPurple, icon: icons.users,
        signals: "Low action rate, high idle time,\nretreat-heavy play, easy wins",
        response: "Boss gets harder:\nepsilon \u2192 0, aggression bonus +0.3"
      },
    ];
    emotions.forEach((em, i) => {
      const cx = 0.5 + i * 3.15;
      s.addShape(pres.shapes.RECTANGLE, {
        x: cx, y: 1.4, w: 2.95, h: 3.35,
        fill: { color: C.white }, shadow: makeShadow()
      });
      // Top color strip
      s.addShape(pres.shapes.RECTANGLE, { x: cx, y: 1.4, w: 2.95, h: 0.45, fill: { color: em.color } });
      s.addText(em.name, {
        x: cx, y: 1.4, w: 2.95, h: 0.45,
        fontSize: 14, fontFace: "Calibri", color: C.white, bold: true,
        align: "center", valign: "middle", margin: 0
      });

      s.addText("Behavioral Signals", {
        x: cx + 0.15, y: 2.0, w: 2.65, h: 0.3,
        fontSize: 10, fontFace: "Calibri", color: C.teal, bold: true, margin: 0
      });
      s.addText(em.signals, {
        x: cx + 0.15, y: 2.3, w: 2.65, h: 0.85,
        fontSize: 10, fontFace: "Calibri", color: C.textMid, margin: 0
      });

      // Divider
      s.addShape(pres.shapes.LINE, {
        x: cx + 0.3, y: 3.2, w: 2.35, h: 0,
        line: { color: "E2E8F0", width: 1 }
      });

      s.addText("Boss Response", {
        x: cx + 0.15, y: 3.35, w: 2.65, h: 0.3,
        fontSize: 10, fontFace: "Calibri", color: em.color, bold: true, margin: 0
      });
      s.addText(em.response, {
        x: cx + 0.15, y: 3.65, w: 2.65, h: 0.8,
        fontSize: 10, fontFace: "Calibri", color: C.textMid, margin: 0
      });
    });

    // Novelty strip
    s.addShape(pres.shapes.RECTANGLE, { x: 0.5, y: 4.95, w: 9.0, h: 0.55, fill: { color: C.teal, transparency: 8 } });
    s.addImage({ data: icons.star, x: 0.7, y: 5.05, w: 0.3, h: 0.3 });
    s.addText([
      { text: "Novelty: ", options: { bold: true, color: C.accentOrange } },
      { text: "Yannakakis (2011) proposed affect-driven game AI as a framework but never implemented it with RL. This is the first working implementation combining behavioral emotion estimation with constrained RL boss behavior.", options: { color: C.textDark } },
    ], {
      x: 1.15, y: 4.95, w: 8.2, h: 0.55,
      fontSize: 10.5, fontFace: "Calibri", valign: "middle", margin: 0
    });
  }

  // ════════════════════════════════════════════
  // SLIDE 10 — Novelty Summary Table
  // ════════════════════════════════════════════
  {
    let s = pres.addSlide();
    s.background = { color: C.darkNavy };
    s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 10, h: 0.06, fill: { color: C.brightTeal } });

    s.addImage({ data: icons.lightbulbW, x: 0.6, y: 0.3, w: 0.4, h: 0.4 });
    s.addText("Why This Project Is Novel", {
      x: 1.1, y: 0.25, w: 7, h: 0.5,
      fontSize: 28, fontFace: "Trebuchet MS", color: C.white, bold: true, margin: 0
    });
    s.addText("No existing publication combines these systems in real-time action combat", {
      x: 0.6, y: 0.8, w: 8.5, h: 0.35,
      fontSize: 13, fontFace: "Calibri", color: C.brightTeal, italic: true, margin: 0
    });

    // Table
    const headers = ["Extension", "Novelty Claim", "Closest Published Work", "Gap"];
    const rows = [
      ["MAML for\nBoss AI", "First meta-learning\napplication to game\nenemy adaptation", "Finn et al. 2017\n(locomotion only)", "Zero game AI\napplications"],
      ["IRL for Combat\nProfiling", "First IRL-based\nreal-time action\ncombat modeling", "Wang et al. 2019\n(MMO economies)", "Different domain\nentirely"],
      ["World Model\nfor Boss Planning", "First learned dynamics\napplied to boss\naction planning", "DreamerV3 2023\n(Atari/Minecraft)", "Never applied to\ncombat AI"],
      ["Emotion-Aware\nRL Boss", "First affect-driven\nboss behavior with\nRL + constraints", "Yannakakis EDPCG\n2011 (theoretical)", "Framework proposed\nbut never\nimplemented"],
    ];

    const colW = [1.6, 2.0, 2.0, 1.8];
    const tableX = 0.75;
    const tableY = 1.3;
    const headerH = 0.45;
    const rowH = 0.88;

    // Header row
    let hx = tableX;
    headers.forEach((h, i) => {
      s.addShape(pres.shapes.RECTANGLE, {
        x: hx, y: tableY, w: colW[i], h: headerH,
        fill: { color: C.teal }
      });
      s.addText(h, {
        x: hx, y: tableY, w: colW[i], h: headerH,
        fontSize: 11, fontFace: "Calibri", color: C.white, bold: true,
        align: "center", valign: "middle", margin: 0
      });
      hx += colW[i] + 0.1;
    });

    // Data rows
    rows.forEach((row, ri) => {
      let rx = tableX;
      const ry = tableY + headerH + 0.08 + ri * (rowH + 0.08);
      row.forEach((cell, ci) => {
        s.addShape(pres.shapes.RECTANGLE, {
          x: rx, y: ry, w: colW[ci], h: rowH,
          fill: { color: C.navy },
          line: { color: C.midNavy, width: 0.5 }
        });
        s.addText(cell, {
          x: rx + 0.1, y: ry, w: colW[ci] - 0.2, h: rowH,
          fontSize: 10, fontFace: "Calibri",
          color: ci === 0 ? C.brightTeal : C.lightGray,
          bold: ci === 0,
          align: "center", valign: "middle", margin: 0
        });
        rx += colW[ci] + 0.1;
      });
    });
  }

  // ════════════════════════════════════════════
  // SLIDE 11 — Observation Pipeline Detail
  // ════════════════════════════════════════════
  {
    let s = pres.addSlide();
    s.background = { color: C.offWhite };
    s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 10, h: 0.06, fill: { color: C.teal } });

    s.addImage({ data: icons.server, x: 0.6, y: 0.35, w: 0.4, h: 0.4 });
    s.addText("Dynamic Observation Pipeline", {
      x: 1.1, y: 0.3, w: 7, h: 0.5,
      fontSize: 28, fontFace: "Trebuchet MS", color: C.textDark, bold: true, margin: 0
    });

    // Observation vector visualization as stacked bars
    const segments = [
      { label: "Hero Velocity (3)", w: 1.05, color: "3B82F6" },
      { label: "Combo/Attack (2)", w: 0.7, color: "6366F1" },
      { label: "Hero HP (1)", w: 0.35, color: "8B5CF6" },
      { label: "Dist/Angle (2)", w: 0.7, color: "A855F7" },
      { label: "Boss HP (1)", w: 0.35, color: "D946EF" },
      { label: "Player Profile (8)", w: 2.8, color: C.teal },
    ];

    let barX = 0.5;
    const barY = 1.15;
    const barH = 0.6;
    segments.forEach(seg => {
      s.addShape(pres.shapes.RECTANGLE, {
        x: barX, y: barY, w: seg.w, h: barH,
        fill: { color: seg.color }
      });
      if (seg.w > 0.5) {
        s.addText(seg.label, {
          x: barX, y: barY, w: seg.w, h: barH,
          fontSize: 8, fontFace: "Calibri", color: C.white, bold: true,
          align: "center", valign: "middle", margin: 0
        });
      }
      barX += seg.w;
    });
    s.addText("Base 17 dims", {
      x: 0.5, y: barY + barH + 0.05, w: barX - 0.5, h: 0.25,
      fontSize: 10, fontFace: "Calibri", color: C.textMid, align: "center", margin: 0
    });

    // Optional augmentations
    const augY = barY + barH + 0.4;
    const augs = [
      { label: "IRL P(a|s) (+5)", w: 1.75, color: C.accentOrange, flag: "irl.enabled" },
      { label: "Emotion (+3)", w: 1.05, color: C.accentRed, flag: "emotion.enabled" },
      { label: "Strategy One-Hot (+4)", w: 1.4, color: C.accentGreen, flag: "hierarchical" },
    ];
    let augX = 0.5;
    augs.forEach(aug => {
      s.addShape(pres.shapes.RECTANGLE, {
        x: augX, y: augY, w: aug.w, h: 0.5,
        fill: { color: aug.color, transparency: 20 },
        line: { color: aug.color, width: 1.5, dashType: "dash" }
      });
      s.addText(aug.label, {
        x: augX, y: augY, w: aug.w, h: 0.3,
        fontSize: 9, fontFace: "Calibri", color: C.textDark, bold: true,
        align: "center", margin: 0
      });
      s.addText(aug.flag, {
        x: augX, y: augY + 0.28, w: aug.w, h: 0.2,
        fontSize: 8, fontFace: "Consolas", color: C.mutedGray,
        align: "center", margin: 0
      });
      augX += aug.w + 0.15;
    });
    s.addText("Optional augmentations (toggled in config.yaml)", {
      x: augX + 0.2, y: augY, w: 3.5, h: 0.5,
      fontSize: 10, fontFace: "Calibri", color: C.textMid, italic: true,
      valign: "middle", margin: 0
    });

    // Config table
    const cfgY = 3.0;
    s.addText("Observation Dimensions by Configuration", {
      x: 0.6, y: cfgY, w: 5, h: 0.4,
      fontSize: 15, fontFace: "Calibri", color: C.textDark, bold: true, margin: 0
    });

    const cfgRows = [
      ["Base only", "17", "9 game state + 8 player profile"],
      ["+ IRL", "22", "+ 5 predicted player action probs"],
      ["+ Emotion", "25", "+ 3 frustration/flow/boredom scores"],
      ["+ Hierarchical", "29", "+ 4 strategy one-hot encoding"],
    ];
    const cfgHeaders = ["Configuration", "Dims", "Breakdown"];
    const cfgColW = [2.2, 0.8, 5.5];

    // Headers
    let chx = 0.6;
    cfgHeaders.forEach((h, i) => {
      s.addShape(pres.shapes.RECTANGLE, {
        x: chx, y: cfgY + 0.45, w: cfgColW[i], h: 0.4,
        fill: { color: C.teal }
      });
      s.addText(h, {
        x: chx, y: cfgY + 0.45, w: cfgColW[i], h: 0.4,
        fontSize: 11, fontFace: "Calibri", color: C.white, bold: true,
        align: "center", valign: "middle", margin: 0
      });
      chx += cfgColW[i] + 0.05;
    });

    cfgRows.forEach((row, ri) => {
      let crx = 0.6;
      row.forEach((cell, ci) => {
        const rowColor = ri % 2 === 0 ? C.white : C.cardBg;
        s.addShape(pres.shapes.RECTANGLE, {
          x: crx, y: cfgY + 0.9 + ri * 0.4, w: cfgColW[ci], h: 0.4,
          fill: { color: rowColor }
        });
        s.addText(cell, {
          x: crx + 0.1, y: cfgY + 0.9 + ri * 0.4, w: cfgColW[ci] - 0.2, h: 0.4,
          fontSize: 11, fontFace: "Calibri",
          color: ci === 1 ? C.teal : C.textMid,
          bold: ci === 1,
          align: ci === 1 ? "center" : "left", valign: "middle", margin: 0
        });
        crx += cfgColW[ci] + 0.05;
      });
    });
  }

  // ════════════════════════════════════════════
  // SLIDE 12 — Conclusion / Target Venues
  // ════════════════════════════════════════════
  {
    let s = pres.addSlide();
    s.background = { color: C.darkNavy };

    // Grid pattern
    for (let i = 0; i < 10; i++) {
      s.addShape(pres.shapes.LINE, { x: i + 0.5, y: 0, w: 0, h: 5.625, line: { color: C.midNavy, width: 0.5 } });
    }
    for (let i = 0; i < 6; i++) {
      s.addShape(pres.shapes.LINE, { x: 0, y: i, w: 10, h: 0, line: { color: C.midNavy, width: 0.5 } });
    }
    s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 10, h: 0.06, fill: { color: C.brightTeal } });

    s.addImage({ data: icons.flaskW, x: 4.35, y: 0.4, w: 1.3, h: 1.3 });

    s.addText("Summary & Research Contribution", {
      x: 0.5, y: 1.8, w: 9, h: 0.6,
      fontSize: 30, fontFace: "Trebuchet MS", color: C.white, bold: true,
      align: "center", margin: 0
    });

    // Four key stats
    const stats = [
      { num: "9", label: "Layered ML\nSystems" },
      { num: "4", label: "Novel\nContributions" },
      { num: "3", label: "Gradient Steps\nto Adapt" },
      { num: "29", label: "Max Obs\nDimensions" },
    ];
    stats.forEach((st, i) => {
      const sx = 0.7 + i * 2.35;
      s.addShape(pres.shapes.RECTANGLE, {
        x: sx, y: 2.55, w: 2.0, h: 1.15,
        fill: { color: C.navy },
        line: { color: C.deepTeal, width: 1 }
      });
      s.addText(st.num, {
        x: sx, y: 2.6, w: 2.0, h: 0.6,
        fontSize: 36, fontFace: "Trebuchet MS", color: C.brightTeal, bold: true,
        align: "center", valign: "middle", margin: 0
      });
      s.addText(st.label, {
        x: sx, y: 3.2, w: 2.0, h: 0.45,
        fontSize: 10, fontFace: "Calibri", color: C.lightGray,
        align: "center", valign: "top", margin: 0
      });
    });

    // Target venues
    s.addText("Target Publication Venues", {
      x: 0.5, y: 3.9, w: 9, h: 0.4,
      fontSize: 14, fontFace: "Calibri", color: C.brightTeal, bold: true,
      align: "center", margin: 0
    });

    const venues = [
      "IEEE Conference on Games (CoG)",
      "AAAI Conference on AI & Interactive Digital Entertainment (AIIDE)",
      "NeurIPS Games Workshop",
    ];
    venues.forEach((v, i) => {
      s.addImage({ data: icons.checkW, x: 2.4, y: 4.35 + i * 0.35, w: 0.2, h: 0.2 });
      s.addText(v, {
        x: 2.7, y: 4.32 + i * 0.35, w: 5.5, h: 0.33,
        fontSize: 12, fontFace: "Calibri", color: C.lightGray, margin: 0
      });
    });

    // Bottom
    s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 5.35, w: 10, h: 0.275, fill: { color: C.teal, transparency: 30 } });
    s.addText("GAME_CORE  \u2014  Adaptive Boss AI: A Novel Multi-System RL Framework for Real-Time Combat", {
      x: 0.5, y: 5.35, w: 9, h: 0.275,
      fontSize: 9, fontFace: "Calibri", color: C.mutedGray,
      align: "center", valign: "middle", margin: 0
    });
  }

  // Write file
  await pres.writeFile({ fileName: "D:\\GAME_CORE\\Docs\\GAME_CORE_Project_Overview.pptx" });
  console.log("Presentation saved to D:\\GAME_CORE\\Docs\\GAME_CORE_Project_Overview.pptx");
}

buildPresentation().catch(err => {
  console.error("Error:", err);
  process.exit(1);
});
