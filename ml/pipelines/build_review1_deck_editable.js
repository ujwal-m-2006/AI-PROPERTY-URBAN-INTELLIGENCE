/*  Project Review 1 deck — Bengaluru AI Property & Urban Intelligence Platform
 *  Every statistic here is read from ml/artifacts/review1_stats.json, which is
 *  written by an actual run over the dataset. Nothing is illustrative.
 */
const pptxgen = require("pptxgenjs");
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..", "..");
const IMG = path.join(ROOT, "ml", "artifacts", "review1");
const S = JSON.parse(fs.readFileSync(path.join(ROOT, "ml", "artifacts", "review1_stats.json"), "utf8"));
const C = JSON.parse(fs.readFileSync(path.join(ROOT, "ml", "artifacts", "review1_chartdata.json"), "utf8"));

const NAVY = "1B365D";
const NAVY_D = "12243F";
const ACCENT = "C2703A";
const INK = "1F2430";
const MUTED = "5C6675";
const LINE = "D6DCE5";
const PANEL = "F4F6F9";

const HEAD = "Cambria";
const BODY = "Calibri";

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE";           // 13.3 x 7.5
pres.author = "UJWAL M";
pres.title = "Bengaluru AI Property & Urban Intelligence Platform — Review 1";

const W = 13.3, H = 7.5, M = 0.62;

function fmt(n, d = 0) {
  return Number(n).toLocaleString("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d });
}

/* Slide scaffold: title, optional kicker, page number. No accent rules. */
function base(titleText, kicker) {
  const s = pres.addSlide();
  s.background = { color: "FFFFFF" };
  if (kicker) {
    s.addText(kicker.toUpperCase(), {
      x: M, y: 0.34, w: 9, h: 0.26, fontFace: BODY, fontSize: 11,
      color: ACCENT, bold: true, charSpacing: 1.6, margin: 0,
    });
  }
  s.addText(titleText, {
    x: M, y: kicker ? 0.62 : 0.45, w: W - 2 * M, h: 0.62,
    fontFace: HEAD, fontSize: 30, bold: true, color: NAVY, margin: 0,
  });
  return s;
}

let pageNo = 0;
function foot(s) {
  pageNo += 1;
  if (pageNo === 1) return;
  s.addText(String(pageNo), {
    x: W - M - 0.6, y: H - 0.48, w: 0.6, h: 0.28,
    fontFace: BODY, fontSize: 10, color: MUTED, align: "right", margin: 0,
  });
  s.addText("Project Review 1  ·  B.Tech CSE (AI & ML)  ·  SRMIST", {
    x: M, y: H - 0.48, w: 8, h: 0.28,
    fontFace: BODY, fontSize: 10, color: MUTED, margin: 0,
  });
}

/* Numbered navy circle — the deck's single repeated motif. */
function stepCircle(s, n, x, y, d = 0.44) {
  s.addShape(pres.ShapeType.ellipse, {
    x, y, w: d, h: d, fill: { color: NAVY }, line: { color: NAVY },
  });
  s.addText(String(n), {
    x, y, w: d, h: d, align: "center", valign: "middle",
    fontFace: BODY, fontSize: 13, bold: true, color: "FFFFFF", margin: 0,
  });
}

function panel(s, x, y, w, h, fill = PANEL) {
  s.addShape(pres.ShapeType.roundRect, {
    x, y, w, h, rectRadius: 0.06,
    fill: { color: fill }, line: { color: LINE, width: 1 },
  });
}

function tbl(s, rows, opts) {
  s.addTable(rows, Object.assign({
    fontFace: BODY, fontSize: 12, color: INK,
    border: { type: "solid", color: LINE, pt: 1 },
    align: "left", valign: "middle",
    autoPage: false,
  }, opts));
}


/* Native PowerPoint chart defaults — every chart below is a real chart object,
   editable in PowerPoint (right-click > Edit Data), not a picture. */
function chartBase(title) {
  return {
    showTitle: true, title, titleColor: NAVY, titleFontSize: 12,
    titleFontFace: BODY,
    chartColors: [NAVY],
    varyColors: false,   // one series = one colour, not a rainbow
    showLegend: false,
    catAxisLabelColor: MUTED, valAxisLabelColor: MUTED,
    catAxisLabelFontSize: 9, valAxisLabelFontSize: 9,
    catAxisLabelFontFace: BODY, valAxisLabelFontFace: BODY,
    valGridLine: { color: "E6EAF0", size: 1 },
    catGridLine: { style: "none" },
    border: { pt: 0, color: "FFFFFF" },
    dataBorder: { pt: 0, color: "FFFFFF" },
  };
}

function head(cells) {
  return cells.map((t) => ({
    text: t,
    options: { bold: true, color: "FFFFFF", fill: { color: NAVY }, fontSize: 12 },
  }));
}

/* ============================ 1 — TITLE ============================ */
{
  const s = pres.addSlide();
  s.background = { color: NAVY };

  s.addShape(pres.ShapeType.ellipse, {
    x: 10.4, y: -1.5, w: 4.6, h: 4.6,
    fill: { color: NAVY_D }, line: { color: NAVY_D },
  });
  s.addShape(pres.ShapeType.ellipse, {
    x: 11.6, y: 5.1, w: 3.0, h: 3.0,
    fill: { color: NAVY_D }, line: { color: NAVY_D },
  });

  s.addText("SRM INSTITUTE OF SCIENCE AND TECHNOLOGY", {
    x: M, y: 0.75, w: 11, h: 0.3, fontFace: BODY, fontSize: 12.5,
    color: "9FB3D1", bold: true, charSpacing: 1.8, margin: 0,
  });

  s.addText("Bengaluru AI Property &\nUrban Intelligence Platform", {
    x: M, y: 1.55, w: 10.4, h: 1.9, fontFace: HEAD, fontSize: 40,
    bold: true, color: "FFFFFF", lineSpacing: 46, margin: 0,
  });

  s.addText("Machine Learning Based Property Price Prediction", {
    x: M, y: 3.55, w: 10.4, h: 0.42, fontFace: BODY, fontSize: 18,
    color: "E8B98C", italic: true, margin: 0,
  });

  s.addShape(pres.ShapeType.roundRect, {
    x: M, y: 4.32, w: 2.5, h: 0.44, rectRadius: 0.06,
    fill: { color: "FFFFFF" }, line: { color: "FFFFFF" },
  });
  s.addText("PROJECT REVIEW – 1", {
    x: M, y: 4.32, w: 2.5, h: 0.44, align: "center", valign: "middle",
    fontFace: BODY, fontSize: 11.5, bold: true, color: NAVY, charSpacing: 0.8, margin: 0,
  });

  s.addText("B.Tech — Computer Science and Engineering\nArtificial Intelligence and Machine Learning",
    { x: M, y: 5.05, w: 6, h: 0.7, fontFace: BODY, fontSize: 13.5,
      color: "C9D6E8", lineSpacing: 20, margin: 0 });

  s.addText(
    [
      { text: "Submitted by\n", options: { fontSize: 10.5, color: "8FA6C4", bold: true, breakLine: true } },
      { text: "UJWAL M\n", options: { fontSize: 15, color: "FFFFFF", bold: true, breakLine: true } },
      { text: "Register Number: [Register Number]", options: { fontSize: 11.5, color: "C9D6E8" } },
    ],
    { x: 7.6, y: 5.02, w: 2.6, h: 1.1, fontFace: BODY, margin: 0 });

  s.addText(
    [
      { text: "Faculty Guide\n", options: { fontSize: 10.5, color: "8FA6C4", bold: true, breakLine: true } },
      { text: "[Faculty Name]\n", options: { fontSize: 15, color: "FFFFFF", bold: true, breakLine: true } },
      { text: "Department of Computing Technologies", options: { fontSize: 11.5, color: "C9D6E8" } },
    ],
    { x: 10.3, y: 5.02, w: 2.4, h: 1.1, fontFace: BODY, margin: 0 });

  s.addNotes("Project Review 1. The application has not been developed yet; this review covers problem definition, the dataset, statistical analysis, EDA and the proposed ML methodology.");
  foot(s);
}

/* ========================= 2 — INTRODUCTION ========================= */
{
  const s = base("Introduction", "Overview");
  s.addText(
    "The proposed project applies machine learning to estimate residential property prices in Bengaluru using property characteristics together with location-related features. Property price is treated as a continuous target, making this a supervised regression problem.",
    { x: M, y: 1.5, w: 7.1, h: 1.0, fontFace: BODY, fontSize: 14.5, color: INK, lineSpacing: 22, margin: 0 });

  s.addText("Property price is influenced simultaneously by several groups of factors:", {
    x: M, y: 2.62, w: 7.1, h: 0.3, fontFace: BODY, fontSize: 13, color: MUTED, italic: true, margin: 0 });

  const groups = [
    ["Physical attributes", "Built-up area, configuration (BHK), bathrooms, balconies"],
    ["Location", "Locality, and the market conditions specific to that locality"],
    ["Accessibility", "Proximity to transport, healthcare, education and road network"],
  ];
  let gy = 3.06;
  groups.forEach((g, i) => {
    stepCircle(s, i + 1, M, gy, 0.40);
    s.addText(g[0], { x: M + 0.58, y: gy - 0.03, w: 6.4, h: 0.26,
      fontFace: BODY, fontSize: 13.5, bold: true, color: NAVY, margin: 0 });
    s.addText(g[1], { x: M + 0.58, y: gy + 0.24, w: 6.4, h: 0.26,
      fontFace: BODY, fontSize: 12, color: MUTED, margin: 0 });
    gy += 0.78;
  });

  s.addText(
    "The broader intent is to combine the resulting model with location intelligence and GIS-derived information in a later stage of the project.",
    { x: M, y: 5.6, w: 7.1, h: 0.6, fontFace: BODY, fontSize: 12.5, color: MUTED, italic: true, lineSpacing: 18, margin: 0 });

  panel(s, 8.15, 1.5, 4.55, 4.5);
  s.addText("Scope of Review 1", { x: 8.45, y: 1.72, w: 4, h: 0.3,
    fontFace: HEAD, fontSize: 15, bold: true, color: NAVY, margin: 0 });
  s.addText(
    [
      { text: "Covered in this review", options: { bold: true, color: NAVY, fontSize: 12, breakLine: true } },
      { text: "Problem definition and objectives", options: { bullet: true, breakLine: true } },
      { text: "Dataset description", options: { bullet: true, breakLine: true } },
      { text: "Statistical analysis", options: { bullet: true, breakLine: true } },
      { text: "Exploratory data analysis", options: { bullet: true, breakLine: true } },
      { text: "Proposed ML methodology", options: { bullet: true, breakLine: true } },
      { text: "\nTo be carried out next", options: { bold: true, color: NAVY, fontSize: 12, breakLine: true } },
      { text: "Model training and comparison", options: { bullet: true, breakLine: true } },
      { text: "Evaluation and tuning", options: { bullet: true, breakLine: true } },
      { text: "Explainability analysis", options: { bullet: true, breakLine: true } },
      { text: "Application interface", options: { bullet: true } },
    ],
    { x: 8.45, y: 2.15, w: 4.0, h: 3.6, fontFace: BODY, fontSize: 12,
      color: INK, paraSpaceAfter: 5, margin: 0 });

  s.addNotes("Regression problem. Review 1 stops at methodology; model results come in Review 2.");
  foot(s);
}

/* ==================== 3 — UNDERSTANDING THE PROBLEM ==================== */
{
  const s = base("Understanding the Problem", "Motivation");
  s.addText(
    "A prospective buyer typically knows the asking price, the built-up area, the configuration and the locality. Judging whether that asking price is reasonable requires comparing the property against a large number of historical records across several variables at once.",
    { x: M, y: 1.5, w: 12.06, h: 0.75, fontFace: BODY, fontSize: 14, color: INK, lineSpacing: 21, margin: 0 });

  const boxes = [
    ["Property Data", "Area, BHK, bathrooms,\nbalcony, property type", 0.62],
    ["Location Data", "Locality and\ngeographic position", 3.68],
    ["Infrastructure Data", "Transport, healthcare,\neducation, road access", 6.74],
  ];
  boxes.forEach((b) => {
    panel(s, b[2], 2.5, 2.76, 1.15);
    s.addText(b[0], { x: b[2] + 0.16, y: 2.66, w: 2.44, h: 0.3,
      fontFace: BODY, fontSize: 13.5, bold: true, color: NAVY, margin: 0 });
    s.addText(b[1], { x: b[2] + 0.16, y: 2.98, w: 2.44, h: 0.6,
      fontFace: BODY, fontSize: 11.5, color: MUTED, lineSpacing: 15, margin: 0 });
  });

  [3.38, 6.44].forEach((x) => {
    s.addShape(pres.ShapeType.line, { x, y: 3.07, w: 0.3, h: 0,
      line: { color: LINE, width: 1.5 } });
  });

  s.addShape(pres.ShapeType.line, { x: 4.0, y: 3.65, w: 0, h: 0.5,
    line: { color: MUTED, width: 1.5, endArrowType: "triangle" } });

  s.addShape(pres.ShapeType.roundRect, {
    x: 0.62, y: 4.24, w: 8.88, h: 0.86, rectRadius: 0.06,
    fill: { color: NAVY }, line: { color: NAVY } });
  s.addText("Machine Learning  —  Supervised Regression", {
    x: 0.62, y: 4.24, w: 8.88, h: 0.86, align: "center", valign: "middle",
    fontFace: HEAD, fontSize: 17, bold: true, color: "FFFFFF", margin: 0 });

  s.addShape(pres.ShapeType.line, { x: 4.0, y: 5.16, w: 0, h: 0.44,
    line: { color: MUTED, width: 1.5, endArrowType: "triangle" } });

  s.addShape(pres.ShapeType.roundRect, {
    x: 0.62, y: 5.68, w: 8.88, h: 0.7, rectRadius: 0.06,
    fill: { color: "FFFFFF" }, line: { color: ACCENT, width: 1.6 } });
  s.addText("Estimated Property Price", {
    x: 0.62, y: 5.68, w: 8.88, h: 0.7, align: "center", valign: "middle",
    fontFace: HEAD, fontSize: 16, bold: true, color: ACCENT, margin: 0 });

  panel(s, 9.9, 2.5, 2.78, 3.88);
  s.addText("Why an ML problem?", { x: 10.12, y: 2.7, w: 2.4, h: 0.3,
    fontFace: HEAD, fontSize: 13.5, bold: true, color: NAVY, margin: 0 });
  s.addText(
    [
      { text: "The target is continuous", options: { bullet: true, breakLine: true } },
      { text: "Many predictors act together", options: { bullet: true, breakLine: true } },
      { text: "Relationships are not purely linear", options: { bullet: true, breakLine: true } },
      { text: "Historical labelled records are available", options: { bullet: true, breakLine: true } },
      { text: "Patterns can be learned rather than hand-coded", options: { bullet: true } },
    ],
    { x: 10.12, y: 3.12, w: 2.36, h: 3.1, fontFace: BODY, fontSize: 11.5,
      color: INK, paraSpaceAfter: 7, margin: 0 });

  foot(s);
}

/* ====================== 4 — PROBLEM STATEMENT ====================== */
{
  const s = base("Problem Statement", "Definition");

  s.addShape(pres.ShapeType.roundRect, {
    x: M, y: 1.5, w: 12.06, h: 1.42, rectRadius: 0.06,
    fill: { color: NAVY }, line: { color: NAVY } });
  s.addText(
    "“To develop a machine learning based system that can estimate residential property prices using property characteristics and location-related features, while identifying the factors that influence the prediction.”",
    { x: M + 0.35, y: 1.5, w: 12.06 - 0.7, h: 1.42, valign: "middle",
      fontFace: HEAD, fontSize: 17, color: "FFFFFF", italic: true, lineSpacing: 26, margin: 0 });

  const points = [
    ["Multiple influencing variables", "Price depends on area, configuration, locality and accessibility acting together rather than in isolation."],
    ["Non-linear relationships", "The effect of one variable may change depending on the value of another, which limits simple linear estimation."],
    ["Difficulty of manual estimation", "Comparing a property against thousands of historical records by hand is impractical for an individual buyer."],
    ["Learning from historical data", "A regression model can learn these patterns from labelled records and generalise to unseen properties."],
    ["Interpretability requirement", "The system should indicate which features influenced a prediction, not only produce a number."],
  ];
  let y = 3.22;
  points.forEach((p, i) => {
    stepCircle(s, i + 1, M, y, 0.40);
    s.addText(p[0], { x: M + 0.6, y: y - 0.04, w: 11.3, h: 0.27,
      fontFace: BODY, fontSize: 13.5, bold: true, color: NAVY, margin: 0 });
    s.addText(p[1], { x: M + 0.6, y: y + 0.23, w: 11.3, h: 0.27,
      fontFace: BODY, fontSize: 11.8, color: MUTED, margin: 0 });
    y += 0.72;
  });

  foot(s);
}

/* ========================== 5 — OBJECTIVES ========================== */
{
  const s = base("Objectives", "Aim and Scope");

  s.addShape(pres.ShapeType.roundRect, {
    x: M, y: 1.48, w: 12.06, h: 0.78, rectRadius: 0.06,
    fill: { color: PANEL }, line: { color: ACCENT, width: 1.4 } });
  s.addText(
    [
      { text: "Primary objective:  ", options: { bold: true, color: ACCENT } },
      { text: "to develop and evaluate a machine learning model for residential property price prediction.", options: { color: INK } },
    ],
    { x: M + 0.3, y: 1.48, w: 12.06 - 0.6, h: 0.78, valign: "middle",
      fontFace: BODY, fontSize: 14, margin: 0 });

  const objs = [
    "Understand and preprocess the selected dataset.",
    "Perform statistical analysis and exploratory data analysis.",
    "Identify the features that influence property price.",
    "Engineer property-level and location-level features.",
    "Train several regression models on the prepared data.",
    "Compare model performance under a common evaluation protocol.",
    "Evaluate predictions using MAE, RMSE and R².",
    "Analyse feature importance for the selected model.",
    "Explore explainable AI methods for interpreting predictions.",
    "Use the resulting model as the basis for a future application.",
  ];
  objs.forEach((o, i) => {
    const col = i < 5 ? 0 : 1;
    const row = i % 5;
    const x = M + col * 6.15;
    const y2 = 2.62 + row * 0.74;
    stepCircle(s, i + 1, x, y2, 0.40);
    s.addText(o, { x: x + 0.58, y: y2 - 0.02, w: 5.3, h: 0.52,
      fontFace: BODY, fontSize: 12.5, color: INK, lineSpacing: 16, margin: 0 });
  });

  foot(s);
}

/* ====================== 6 — DATASET DESCRIPTION ====================== */
{
  const s = base("Dataset Description", "Data");

  const rows = [
    head(["Parameter", "Details"]),
    ["Dataset", "Bengaluru House Price dataset (public, tabular)"],
    ["Source", "Publicly mirrored CSV (GitHub); licence unconfirmed"],
    ["Records (raw)", `${fmt(S.raw.rows)} rows`],
    ["Attributes (raw)", `${S.raw.cols} columns`],
    ["Records after cleaning", `${fmt(S.clean.rows)} rows`],
    ["Distinct localities", `${fmt(S.clean.localities)}`],
    ["Target variable", "Price per sq.ft (derived from price and area)"],
    ["Task type", "Supervised regression"],
    ["Domain", "Residential real estate"],
  ];
  tbl(s, rows, { x: M, y: 1.5, w: 7.5, colW: [2.5, 5.0], rowH: 0.335 });

  panel(s, 8.42, 1.5, 4.28, 2.35);
  s.addText("Raw attributes", { x: 8.68, y: 1.68, w: 3.8, h: 0.28,
    fontFace: HEAD, fontSize: 13.5, bold: true, color: NAVY, margin: 0 });
  s.addText(S.raw.columns.join("  ·  "), {
    x: 8.68, y: 2.02, w: 3.78, h: 1.7, fontFace: BODY, fontSize: 12,
    color: INK, lineSpacing: 19, margin: 0 });

  panel(s, 8.42, 4.02, 4.28, 2.32, "FDF6EF");
  s.addText("Note on data provenance", { x: 8.68, y: 4.2, w: 3.8, h: 0.28,
    fontFace: HEAD, fontSize: 13.5, bold: true, color: ACCENT, margin: 0 });
  s.addText(
    "The dataset contains listed asking prices rather than registered transaction values. Registered transaction prices are not published publicly in Karnataka. This distinction is stated explicitly and will be carried into the interpretation of results.",
    { x: 8.68, y: 4.54, w: 3.78, h: 1.7, fontFace: BODY, fontSize: 11.5,
      color: INK, lineSpacing: 17, margin: 0 });

  s.addNotes("Asking price, not transaction price. Karnataka does not publish transaction prices. This is a stated limitation, not an oversight.");
  foot(s);
}

/* ======================= 7 — DATASET FEATURES ======================= */
{
  const s = base("Dataset Features", "Feature Groups");
  s.addText("Attributes are grouped by the aspect of the property they describe. Accessibility features are to be derived in the feature-engineering stage.",
    { x: M, y: 1.46, w: 12.06, h: 0.3, fontFace: BODY, fontSize: 12.5, color: MUTED, italic: true, margin: 0 });

  const cards = [
    ["Property Features", NAVY, ["Configuration (BHK)", "Built-up area", "Bathrooms", "Balcony", "Area type", "Availability status"], "Available in the dataset"],
    ["Location Features", NAVY, ["Locality name", "Latitude — to be derived", "Longitude — to be derived"], "Partly to be derived"],
    ["Accessibility Features", ACCENT, ["Distance to metro", "Distance to railway station", "Distance to bus stop", "Distance to hospital", "Distance to school", "Distance to major road"], "To be computed"],
  ];
  cards.forEach((c, i) => {
    const x = M + i * 4.08;
    panel(s, x, 1.92, 3.82, 3.55);
    s.addText(c[0], { x: x + 0.24, y: 2.14, w: 3.4, h: 0.3,
      fontFace: HEAD, fontSize: 14.5, bold: true, color: c[1], margin: 0 });
    s.addText(c[2].map((t, j) => ({
      text: t, options: { bullet: true, breakLine: j < c[2].length - 1 } })),
      { x: x + 0.24, y: 2.52, w: 3.36, h: 2.3, fontFace: BODY, fontSize: 12,
        color: INK, paraSpaceAfter: 6, margin: 0 });
    s.addText(c[3], { x: x + 0.24, y: 5.05, w: 3.36, h: 0.26,
      fontFace: BODY, fontSize: 10.5, color: MUTED, italic: true, margin: 0 });
  });

  s.addShape(pres.ShapeType.roundRect, {
    x: M, y: 5.68, w: 12.06, h: 0.72, rectRadius: 0.06,
    fill: { color: NAVY }, line: { color: NAVY } });
  s.addText(
    [
      { text: "Target variable:   ", options: { bold: true, color: "E8B98C" } },
      { text: "Price per sq.ft (INR)", options: { bold: true, color: "FFFFFF" } },
      { text: "     — chosen over total price so that properties of different sizes remain comparable.", options: { color: "C9D6E8" } },
    ],
    { x: M + 0.32, y: 5.68, w: 12.06 - 0.64, h: 0.72, valign: "middle",
      fontFace: BODY, fontSize: 13.5, margin: 0 });

  foot(s);
}

/* ===================== 8 — STATISTICAL ANALYSIS ===================== */
{
  const s = base("Statistical Analysis of the Dataset", "Descriptive Statistics");
  s.addText(`Descriptive statistics computed on the cleaned dataset (n = ${fmt(S.clean.rows)}).`,
    { x: M, y: 1.44, w: 12.06, h: 0.28, fontFace: BODY, fontSize: 12.5, color: MUTED, italic: true, margin: 0 });

  const d = S.descriptive;
  const rows = [head(["Variable", "Count", "Mean", "Median", "Std. Dev.", "Min", "Q1", "Q3", "Max"])];
  d.forEach((r) => {
    const dec = r.variable.includes("BHK") || r.variable.includes("Bath") || r.variable.includes("Balcony") ? 1 : 0;
    rows.push([
      { text: r.variable, options: { bold: true, color: NAVY } },
      fmt(r.count), fmt(r.mean, dec), fmt(r.median, dec), fmt(r.std, dec),
      fmt(r.min, dec), fmt(r.q1, dec), fmt(r.q3, dec), fmt(r.max, dec),
    ]);
  });
  tbl(s, rows, {
    x: M, y: 1.84, w: 12.06, rowH: 0.34,
    colW: [2.42, 1.06, 1.42, 1.26, 1.34, 1.06, 1.16, 1.22, 1.12],
    align: "right",
  });

  const obs = [
    [`Price per sq.ft is positively skewed (skewness = ${S.descriptive[5].skew}).`,
     `The mean (${fmt(S.descriptive[5].mean)}) exceeds the median (${fmt(S.descriptive[5].median)}), indicating a minority of high-priced properties pulling the average upward.`],
    [`Built-up area is strongly right-skewed (skewness = ${S.descriptive[0].skew}).`,
     `Values range from ${fmt(S.descriptive[0].min)} to ${fmt(S.descriptive[0].max)} sq.ft, so the median is the more representative measure of central tendency.`],
    ["Configuration is concentrated in a narrow band.",
     `Mean BHK is ${fmt(S.descriptive[2].mean, 1)} with a standard deviation of ${fmt(S.descriptive[2].std, 1)}, indicating that 2 and 3 BHK properties dominate the dataset.`],
  ];
  s.addText("Observations", { x: M, y: 4.28, w: 6, h: 0.3,
    fontFace: HEAD, fontSize: 15, bold: true, color: NAVY, margin: 0 });
  let oy = 4.68;
  obs.forEach((o, i) => {
    stepCircle(s, i + 1, M, oy, 0.38);
    s.addText(o[0], { x: M + 0.56, y: oy - 0.04, w: 11.4, h: 0.26,
      fontFace: BODY, fontSize: 12.5, bold: true, color: INK, margin: 0 });
    s.addText(o[1], { x: M + 0.56, y: oy + 0.21, w: 11.4, h: 0.26,
      fontFace: BODY, fontSize: 11.5, color: MUTED, margin: 0 });
    oy += 0.66;
  });

  foot(s);
}

/* ==================== 9 — DATA QUALITY ANALYSIS ==================== */
{
  const s = base("Data Quality Analysis", "Preprocessing");

  s.addChart(pres.ChartType.bar, [{
    name: "Missing records",
    labels: C.missing.labels,
    values: C.missing.values,
  }], Object.assign(chartBase("Missing values by column (raw dataset, n = 13,320)"), {
    x: M, y: 1.46, w: 5.9, h: 2.6, barDir: "bar",
    showValue: true, dataLabelPosition: "outEnd",
    dataLabelColor: MUTED, dataLabelFontSize: 9, dataLabelFontFace: BODY,
    valAxisMinVal: 0, valAxisMaxVal: 6400,
  }));

  const fnRows = [head(["Variable", "Min", "Q1", "Median", "Q3", "Max", "Outliers"])];
  C.five_number.forEach((f) => {
    fnRows.push([
      { text: f.name, options: { bold: true, color: NAVY, fontSize: 10.5 } },
      { text: fmt(f.min), options: { align: "right" } },
      { text: fmt(f.q1), options: { align: "right" } },
      { text: fmt(f.median), options: { align: "right" } },
      { text: fmt(f.q3), options: { align: "right" } },
      { text: fmt(f.max), options: { align: "right" } },
      { text: fmt(f.outliers), options: { align: "right", bold: true, color: ACCENT } },
    ]);
  });
  s.addText("Five-number summary and outlier count (1.5 × IQR rule)", {
    x: M, y: 4.24, w: 5.9, h: 0.26, fontFace: BODY, fontSize: 11.5,
    bold: true, color: NAVY, margin: 0 });
  tbl(s, fnRows, { x: M, y: 4.56, w: 5.9, rowH: 0.36, fontSize: 10.5,
    colW: [1.62, 0.66, 0.66, 0.74, 0.66, 0.76, 0.80] });

  s.addText(
    "The wide gap between Q3 and the maximum in both variables confirms the right-skew identified in the descriptive statistics.",
    { x: M, y: 5.86, w: 5.9, h: 0.5, fontFace: BODY, fontSize: 10.8,
      color: MUTED, italic: true, lineSpacing: 14, margin: 0 });

  const rows = [
    head(["Quality check", "Observation"]),
    ["Duplicate records", `${fmt(S.raw.duplicates)} exact duplicate rows in the raw data`],
    ["Missing — society", `${fmt(S.raw.missing.society)} (${(S.raw.missing.society / S.raw.rows * 100).toFixed(1)}%) — column excluded`],
    ["Missing — balcony", `${fmt(S.raw.missing.balcony)} (${(S.raw.missing.balcony / S.raw.rows * 100).toFixed(1)}%) — to be imputed`],
    ["Missing — bath", `${fmt(S.raw.missing.bath)} — to be imputed`],
    ["Missing — size", `${fmt(S.raw.missing.size)} — records removed`],
    ["Outliers — area", `${fmt(S.outliers_area_iqr)} beyond 1.5 × IQR`],
    ["Outliers — price/sq.ft", `${fmt(S.outliers_price_psf_iqr)} beyond 1.5 × IQR`],
  ];
  tbl(s, rows, { x: 6.78, y: 1.5, w: 5.9, colW: [2.15, 3.75], rowH: 0.33, fontSize: 11.5 });

  panel(s, 6.78, 4.34, 5.9, 2.54);
  s.addText("Data type handling", { x: 7.02, y: 4.52, w: 5.4, h: 0.28,
    fontFace: HEAD, fontSize: 13.5, bold: true, color: NAVY, margin: 0 });
  s.addText(
    [
      { text: "total_sqft is stored as text and contains ranges (e.g. “1195 - 1440”) and alternative units, requiring parsing to a numeric value.", options: { bullet: true, breakLine: true } },
      { text: "size is text (e.g. “2 BHK”, “4 Bedroom”) and must be converted to an integer room count.", options: { bullet: true, breakLine: true } },
      { text: "area_type, availability and location are categorical and require encoding before model training.", options: { bullet: true, breakLine: true } },
      { text: "Data quality is addressed before training because unparsed and inconsistent values would otherwise propagate directly into the model.", options: { bullet: true } },
    ],
    { x: 7.02, y: 4.86, w: 5.4, h: 1.9, fontFace: BODY, fontSize: 11.5,
      color: INK, paraSpaceAfter: 6, lineSpacing: 15, margin: 0 });

  foot(s);
}

/* ================ 10 — EDA: DISTRIBUTION AND AREA ================ */
{
  const s = base("Exploratory Data Analysis", "Distribution and Area");

  s.addChart(pres.ChartType.bar, [{
    name: "Properties",
    labels: C.price_hist.labels,
    values: C.price_hist.values,
  }], Object.assign(chartBase("Price per sq.ft distribution (INR, thousands)"), {
    x: M, y: 1.46, w: 6.0, h: 3.5, barDir: "col", barGapWidthPct: 12,
    catAxisLabelRotate: 300, catAxisLabelFontSize: 8.5,
  }));

  s.addChart(pres.ChartType.scatter, [
    { name: "X-Axis", values: C.scatter.x },
    { name: "Price (INR lakh)", values: C.scatter.y },
  ], Object.assign(chartBase("Built-up area (sq.ft) vs price (INR lakh)"), {
    x: 6.86, y: 1.46, w: 5.82, h: 3.5,
    lineSize: 0, lineDataSymbol: "circle", lineDataSymbolSize: 4,
    chartColors: [NAVY],
    valAxisTitle: "Price (INR lakh)", showValAxisTitle: true,
    valAxisTitleColor: MUTED, valAxisTitleFontSize: 9,
    catAxisTitle: "Built-up area (sq.ft)", showCatAxisTitle: true,
    catAxisTitleColor: MUTED, catAxisTitleFontSize: 9,
  }));

  panel(s, M, 5.12, 6.0, 1.6);
  s.addText("Price per sq.ft distribution", { x: M + 0.22, y: 5.28, w: 5.5, h: 0.26,
    fontFace: BODY, fontSize: 12.5, bold: true, color: NAVY, margin: 0 });
  s.addText(
    `The distribution is positively skewed (skewness = ${S.descriptive[5].skew}), with the majority of properties concentrated below the mean of ₹${fmt(S.descriptive[5].mean)} and a long right tail. This supports the use of the median as the representative measure.`,
    { x: M + 0.22, y: 5.58, w: 5.56, h: 1.0, fontFace: BODY, fontSize: 11.5,
      color: INK, lineSpacing: 16, margin: 0 });

  panel(s, 6.86, 5.12, 5.82, 1.6);
  s.addText("Area versus price", { x: 7.08, y: 5.28, w: 5.4, h: 0.26,
    fontFace: BODY, fontSize: 12.5, bold: true, color: NAVY, margin: 0 });
  s.addText(
    `Price increases with built-up area, but the relationship shows widening dispersion at larger areas, indicating that area alone does not determine price. The Pearson correlation between area and price per sq.ft is ${S.corr_with_target.sqft}.`,
    { x: 7.08, y: 5.58, w: 5.38, h: 1.0, fontFace: BODY, fontSize: 11.5,
      color: INK, lineSpacing: 16, margin: 0 });

  foot(s);
}

/* ============= 11 — EDA: CONFIGURATION AND LOCATION ============= */
{
  const s = base("Configuration and Location Analysis", "Exploratory Data Analysis");

  s.addChart(pres.ChartType.bar, [{
    name: "Median price (INR lakh)",
    labels: C.bhk.labels,
    values: C.bhk.values,
  }], Object.assign(chartBase("Median price by configuration (INR lakh)"), {
    x: M, y: 1.44, w: 6.0, h: 3.66, barDir: "col", barGapWidthPct: 60,
    showValue: true, dataLabelPosition: "outEnd",
    dataLabelColor: MUTED, dataLabelFontSize: 9, dataLabelFontFace: BODY,
  }));

  s.addChart(pres.ChartType.bar, [{
    name: "Median price per sq.ft (INR)",
    labels: C.locality.labels,
    values: C.locality.values,
  }], Object.assign(chartBase("Median price per sq.ft — 12 most represented localities"), {
    x: 6.86, y: 1.44, w: 5.82, h: 3.66, barDir: "bar", barGapWidthPct: 40,
    catAxisLabelFontSize: 8,
  }));

  const b = S.bhk_price;
  const bhkLine = b.map((r) => `${r.bhk} BHK — ₹${fmt(r.median_price / 100000, 1)} L`).join("   ·   ");

  panel(s, M, 5.26, 6.0, 1.46);
  s.addText("Configuration", { x: M + 0.22, y: 5.4, w: 5.5, h: 0.26,
    fontFace: BODY, fontSize: 12.5, bold: true, color: NAVY, margin: 0 });
  s.addText(
    `Median price rises consistently with configuration:\n${bhkLine}.\nMedian price roughly doubles between 3 and 4 BHK, indicating a non-linear relationship with configuration.`,
    { x: M + 0.22, y: 5.66, w: 5.56, h: 0.94, fontFace: BODY, fontSize: 11,
      color: INK, lineSpacing: 15, margin: 0 });

  panel(s, 6.86, 5.26, 5.82, 1.46);
  s.addText("Location", { x: 7.08, y: 5.4, w: 5.4, h: 0.26,
    fontFace: BODY, fontSize: 12.5, bold: true, color: NAVY, margin: 0 });
  s.addText(
    `Median price per sq.ft differs substantially across the most represented localities, indicating that locality captures variation not explained by the physical attributes alone. Location may reflect differences in accessibility, infrastructure and local market conditions; this is an association and does not establish causation.`,
    { x: 7.08, y: 5.66, w: 5.38, h: 0.94, fontFace: BODY, fontSize: 11,
      color: INK, lineSpacing: 15, margin: 0 });

  foot(s);
}

/* ===================== 12 — CORRELATION ANALYSIS ===================== */
{
  const s = base("Correlation Analysis", "Feature Relationships");

  // Correlation matrix as a native table with graded cell fills. PowerPoint has
  // no heatmap chart type, and a table keeps the values selectable and editable.
  const cl = C.corr.labels;
  const shade = (v) => {
    const a = Math.abs(v);
    if (v >= 0.999) return { fill: NAVY, color: "FFFFFF" };
    if (a >= 0.55) return { fill: "9FB3D1", color: INK };
    if (a >= 0.35) return { fill: "C7D4E6", color: INK };
    if (a >= 0.15) return { fill: "E3EAF3", color: INK };
    return { fill: "FFFFFF", color: MUTED };
  };
  const corrRows = [[{ text: "", options: { fill: { color: "FFFFFF" } } }].concat(
    cl.map((l) => ({ text: l, options: { bold: true, color: "FFFFFF",
      fill: { color: NAVY }, fontSize: 10, align: "center" } })))];
  C.corr.matrix.forEach((row, i) => {
    corrRows.push([{ text: cl[i], options: { bold: true, color: NAVY, fontSize: 10 } }]
      .concat(row.map((v) => {
        const sh = shade(v);
        return { text: v.toFixed(2), options: { align: "center", fontSize: 10,
          color: sh.color, fill: { color: sh.fill } } };
      })));
  });
  s.addText("Correlation matrix — numerical variables (Pearson r)", {
    x: M, y: 1.58, w: 5.5, h: 0.28, fontFace: BODY, fontSize: 11.5,
    bold: true, color: NAVY, margin: 0 });
  tbl(s, corrRows, { x: M, y: 1.92, w: 5.5, rowH: 0.42, fontSize: 10,
    colW: [1.3, 0.84, 0.84, 0.84, 0.84, 0.84] });

  const c = S.corr_with_target;
  const rows = [head(["Variable", "Pearson r with price per sq.ft"])];
  Object.entries(c).forEach(([k, v]) => {
    const label = { bath: "Bathrooms", sqft: "Built-up area", rooms: "Configuration (BHK)", balcony: "Balcony" }[k] || k;
    rows.push([{ text: label, options: { bold: true, color: NAVY } },
               { text: String(v), options: { align: "right" } }]);
  });
  tbl(s, rows, { x: 6.42, y: 1.92, w: 6.26, colW: [3.9, 2.36], rowH: 0.36 });

  s.addText("Interpretation", { x: 6.42, y: 3.92, w: 6.26, h: 0.3,
    fontFace: HEAD, fontSize: 15, bold: true, color: NAVY, margin: 0 });
  s.addText(
    [
      { text: `No single numerical variable is strongly correlated with the target; the highest is bathrooms at r = ${c.bath}.`, options: { bullet: true, breakLine: true } },
      { text: "This indicates that price per sq.ft is not explained by any one attribute in isolation, which supports the use of multivariate models over simple linear estimation.", options: { bullet: true, breakLine: true } },
      { text: "Area, configuration and bathrooms are themselves inter-related, so multicollinearity is expected among the input variables and will be considered during feature selection.", options: { bullet: true, breakLine: true } },
      { text: "Correlation measures linear association only. It does not capture non-linear relationships, and it does not establish causation.", options: { bullet: true } },
    ],
    { x: 6.42, y: 4.32, w: 6.26, h: 2.1, fontFace: BODY, fontSize: 11.8,
      color: INK, paraSpaceAfter: 8, lineSpacing: 16, margin: 0 });

  s.addNotes("Weak individual correlations are themselves a finding: they justify multivariate, non-linear models.");
  foot(s);
}

/* ====================== 13 — FEATURE ENGINEERING ====================== */
{
  const s = base("Feature Engineering", "Proposed Features");

  const flow = [["Raw Data", NAVY], ["Feature Engineering", ACCENT], ["ML-Ready Features", NAVY]];
  flow.forEach((f, i) => {
    const x = M + i * 4.3;
    s.addShape(pres.ShapeType.roundRect, {
      x, y: 1.5, w: 3.62, h: 0.68, rectRadius: 0.06,
      fill: { color: i === 1 ? "FDF6EF" : PANEL },
      line: { color: f[1], width: 1.4 } });
    s.addText(f[0], { x, y: 1.5, w: 3.62, h: 0.68, align: "center", valign: "middle",
      fontFace: BODY, fontSize: 14, bold: true, color: f[1], margin: 0 });
    if (i < 2) {
      s.addShape(pres.ShapeType.line, { x: x + 3.72, y: 1.84, w: 0.48, h: 0,
        line: { color: MUTED, width: 1.5, endArrowType: "triangle" } });
    }
  });

  const groups = [
    ["Derived property features", ["Price per sq.ft — target normalisation", "Area per room", "Bathrooms per room", "Property age (where date data exists)"]],
    ["Derived location features", ["Locality-level median price", "Locality-level record count", "Administrative ward and zone"]],
    ["Derived accessibility features", ["Distance to nearest metro station", "Distance to nearest railway station", "Distance to nearest bus stop", "Distance to nearest hospital and school", "Count of amenities within a fixed radius"]],
  ];
  groups.forEach((g, i) => {
    const x = M + i * 4.08;
    panel(s, x, 2.5, 3.82, 3.1);
    s.addText(g[0], { x: x + 0.24, y: 2.7, w: 3.4, h: 0.3,
      fontFace: BODY, fontSize: 13, bold: true, color: NAVY, margin: 0 });
    s.addText(g[1].map((t, j) => ({
      text: t, options: { bullet: true, breakLine: j < g[1].length - 1 } })),
      { x: x + 0.24, y: 3.06, w: 3.36, h: 2.3, fontFace: BODY, fontSize: 11.5,
        color: INK, paraSpaceAfter: 6, lineSpacing: 15, margin: 0 });
  });

  s.addText(
    "The final feature set will depend on data availability and on the results of preprocessing. Features derived from the target variable will be excluded to avoid target leakage.",
    { x: M, y: 5.84, w: 12.06, h: 0.6, fontFace: BODY, fontSize: 12,
      color: MUTED, italic: true, lineSpacing: 17, margin: 0 });

  foot(s);
}

/* ================== 14 — PROPOSED ML METHODOLOGY ================== */
{
  const s = base("Proposed Machine Learning Methodology", "Workflow");

  const steps = [
    "Dataset", "Data Cleaning", "Exploratory Data Analysis", "Feature Engineering",
    "Feature Selection", "Train / Validation / Test Split", "Model Training",
    "Cross Validation", "Hyperparameter Tuning", "Model Evaluation",
    "Best Performing Model", "Prediction", "Explainability",
  ];

  const colX = [M, 4.72, 8.84];
  const perCol = [5, 5, 3];
  let idx = 0;
  colX.forEach((x, ci) => {
    for (let r = 0; r < perCol[ci]; r++) {
      const y = 1.62 + r * 0.92;
      const isLast = idx === steps.length - 1;
      const emph = idx === 10 || isLast;
      s.addShape(pres.ShapeType.roundRect, {
        x, y, w: 3.5, h: 0.62, rectRadius: 0.05,
        fill: { color: emph ? NAVY : PANEL },
        line: { color: emph ? NAVY : LINE, width: 1.2 } });
      s.addText(`${idx + 1}.  ${steps[idx]}`, {
        x: x + 0.16, y, w: 3.2, h: 0.62, valign: "middle",
        fontFace: BODY, fontSize: 12.5, bold: emph,
        color: emph ? "FFFFFF" : INK, margin: 0 });
      if (r < perCol[ci] - 1) {
        s.addShape(pres.ShapeType.line, { x: x + 1.75, y: y + 0.66, w: 0, h: 0.22,
          line: { color: MUTED, width: 1.2, endArrowType: "triangle" } });
      }
      idx++;
    }
    // Order across columns is carried by the step numbers. A horizontal arrow
    // here would point at whatever sits at that height in the next column,
    // which is not the next step.
  });

  panel(s, 8.84, 4.5, 3.86, 1.86, "FDF6EF");
  s.addText("Evaluation protocol", { x: 9.06, y: 4.66, w: 3.4, h: 0.28,
    fontFace: BODY, fontSize: 12.5, bold: true, color: ACCENT, margin: 0 });
  s.addText(
    "All candidate models will be trained and evaluated under an identical preprocessing pipeline and data split, so that the comparison reflects the algorithm rather than differences in preparation.",
    { x: 9.06, y: 4.96, w: 3.42, h: 1.3, fontFace: BODY, fontSize: 11.5,
      color: INK, lineSpacing: 16, margin: 0 });

  foot(s);
}

/* ==================== 15 — MACHINE LEARNING ALGORITHMS ==================== */
{
  const s = base("Candidate Machine Learning Algorithms", "Regression Models");
  s.addText("Four regression algorithms are proposed. The intention is to compare them under a common protocol rather than to assume in advance which will perform best.",
    { x: M, y: 1.46, w: 12.06, h: 0.3, fontFace: BODY, fontSize: 12.5, color: MUTED, italic: true, margin: 0 });

  const algos = [
    ["Linear Regression", "Baseline model", "Fits a linear relationship between the input features and the target. Included as a reference point against which the more complex models are judged.", "Assumes linearity and independence of predictors."],
    ["Random Forest Regressor", "Bagging ensemble", "Averages the predictions of many decision trees trained on bootstrap samples. Captures non-linear relationships and interactions between features.", "Less sensitive to outliers; harder to interpret directly."],
    ["Gradient Boosting Regressor", "Sequential ensemble", "Builds trees sequentially, with each tree fitted to the residual errors of the previous ones, progressively reducing prediction error.", "Often accurate; sensitive to hyperparameter settings."],
    ["XGBoost Regressor", "Regularised boosting", "An optimised gradient boosting implementation with regularisation, widely used for structured and tabular datasets.", "Efficient on tabular data; requires tuning."],
  ];
  algos.forEach((a, i) => {
    const x = M + (i % 2) * 6.14;
    const y = 1.9 + Math.floor(i / 2) * 2.42;
    panel(s, x, y, 5.88, 2.22);
    stepCircle(s, i + 1, x + 0.24, y + 0.22, 0.4);
    s.addText(a[0], { x: x + 0.76, y: y + 0.2, w: 3.6, h: 0.28,
      fontFace: BODY, fontSize: 14, bold: true, color: NAVY, margin: 0 });
    s.addText(a[1], { x: x + 0.76, y: y + 0.48, w: 4.9, h: 0.24,
      fontFace: BODY, fontSize: 10.5, color: ACCENT, bold: true, charSpacing: 0.6, margin: 0 });
    s.addText(a[2], { x: x + 0.24, y: y + 0.82, w: 5.4, h: 0.84,
      fontFace: BODY, fontSize: 11.5, color: INK, lineSpacing: 16, margin: 0 });
    s.addText(a[3], { x: x + 0.24, y: y + 1.72, w: 5.4, h: 0.34,
      fontFace: BODY, fontSize: 10.5, color: MUTED, italic: true, margin: 0 });
  });

  foot(s);
}

/* ======================= 16 — MODEL EVALUATION ======================= */
{
  const s = base("Model Evaluation", "Metrics and Comparison");

  const metrics = [
    ["MAE", "Mean Absolute Error", "The average magnitude of the prediction error, expressed in the same unit as the target. Treats all errors equally."],
    ["RMSE", "Root Mean Squared Error", "Penalises larger errors more heavily than smaller ones, and is therefore sensitive to occasional large mistakes."],
    ["R²", "Coefficient of Determination", "The proportion of variance in the target explained by the model. A value of 0 corresponds to predicting the mean."],
    ["MAPE", "Mean Absolute Percentage Error", "Expresses error as a percentage of the actual value, allowing comparison across differently priced properties."],
  ];
  metrics.forEach((m, i) => {
    const y = 1.52 + i * 1.16;
    panel(s, M, y, 6.0, 1.02);
    s.addText(m[0], { x: M + 0.2, y: y + 0.12, w: 1.1, h: 0.4,
      fontFace: HEAD, fontSize: 19, bold: true, color: ACCENT, margin: 0 });
    s.addText(m[1], { x: M + 1.36, y: y + 0.13, w: 4.4, h: 0.26,
      fontFace: BODY, fontSize: 12.5, bold: true, color: NAVY, margin: 0 });
    s.addText(m[2], { x: M + 1.36, y: y + 0.4, w: 4.44, h: 0.54,
      fontFace: BODY, fontSize: 10.8, color: MUTED, lineSpacing: 14, margin: 0 });
  });

  const rows = [
    head(["Model", "MAE", "RMSE", "R²"]),
    ["Linear Regression", "To be calculated", "To be calculated", "To be calculated"],
    ["Random Forest Regressor", "To be calculated", "To be calculated", "To be calculated"],
    ["Gradient Boosting Regressor", "To be calculated", "To be calculated", "To be calculated"],
    ["XGBoost Regressor", "To be calculated", "To be calculated", "To be calculated"],
  ];
  tbl(s, rows, { x: 6.86, y: 1.52, w: 5.82, colW: [2.28, 1.18, 1.18, 1.18],
    rowH: 0.42, fontSize: 11 });

  panel(s, 6.86, 4.0, 5.82, 2.62, "FDF6EF");
  s.addText("Note on the comparison", { x: 7.08, y: 4.18, w: 5.4, h: 0.28,
    fontFace: HEAD, fontSize: 13.5, bold: true, color: ACCENT, margin: 0 });
  s.addText(
    [
      { text: "Values are not reported in this review because model training has not yet been carried out. Results will be presented in the next review.", options: { breakLine: true } },
      { text: "", options: { breakLine: true } },
      { text: "Because properties in the same locality share price characteristics, a random train-test split can place closely related records on both sides of the split and overstate performance. A grouped split by locality will therefore be used alongside the random split, and both results will be reported.", options: {} },
    ],
    { x: 7.08, y: 4.5, w: 5.4, h: 2.0, fontFace: BODY, fontSize: 11.3,
      color: INK, lineSpacing: 16, margin: 0 });

  s.addNotes("No values are invented. Preliminary experiments have been carried out; results are reserved for Review 2.");
  foot(s);
}

/* ======================== 17 — EXPLAINABLE AI ======================== */
{
  const s = base("Understanding the Prediction", "Explainable AI — Planned Analysis");

  s.addShape(pres.ShapeType.roundRect, {
    x: M, y: 1.5, w: 3.5, h: 0.72, rectRadius: 0.06,
    fill: { color: NAVY }, line: { color: NAVY } });
  s.addText("Predicted Property Price", { x: M, y: 1.5, w: 3.5, h: 0.72,
    align: "center", valign: "middle", fontFace: BODY, fontSize: 13,
    bold: true, color: "FFFFFF", margin: 0 });

  s.addShape(pres.ShapeType.line, { x: M + 3.6, y: 1.86, w: 0.5, h: 0,
    line: { color: MUTED, width: 1.5, endArrowType: "triangle" } });

  s.addShape(pres.ShapeType.roundRect, {
    x: 4.72, y: 1.5, w: 4.3, h: 0.72, rectRadius: 0.06,
    fill: { color: "FDF6EF" }, line: { color: ACCENT, width: 1.5 } });
  s.addText("Which features influenced it?", { x: 4.72, y: 1.5, w: 4.3, h: 0.72,
    align: "center", valign: "middle", fontFace: BODY, fontSize: 13,
    bold: true, color: ACCENT, margin: 0 });

  s.addShape(pres.ShapeType.line, { x: 9.12, y: 1.86, w: 0.5, h: 0,
    line: { color: MUTED, width: 1.5, endArrowType: "triangle" } });

  s.addShape(pres.ShapeType.roundRect, {
    x: 9.74, y: 1.5, w: 2.96, h: 0.72, rectRadius: 0.06,
    fill: { color: PANEL }, line: { color: LINE, width: 1.2 } });
  s.addText("Ranked contributions", { x: 9.74, y: 1.5, w: 2.96, h: 0.72,
    align: "center", valign: "middle", fontFace: BODY, fontSize: 13,
    bold: true, color: NAVY, margin: 0 });

  const methods = [
    ["Feature importance", "Measures how much model performance degrades when a feature's values are randomly permuted, indicating the model's reliance on that feature."],
    ["SHAP (SHapley Additive exPlanations)", "Attributes a contribution value to each feature for an individual prediction, showing which attributes pushed the estimate above or below the baseline."],
  ];
  methods.forEach((m, i) => {
    const y = 2.62 + i * 1.34;
    panel(s, M, y, 6.0, 1.16);
    s.addText(m[0], { x: M + 0.24, y: y + 0.16, w: 5.5, h: 0.28,
      fontFace: BODY, fontSize: 13, bold: true, color: NAVY, margin: 0 });
    s.addText(m[1], { x: M + 0.24, y: y + 0.46, w: 5.54, h: 0.62,
      fontFace: BODY, fontSize: 11.3, color: MUTED, lineSpacing: 15, margin: 0 });
  });

  panel(s, 6.86, 2.62, 5.82, 2.66);
  s.addText("Features expected to be examined", { x: 7.08, y: 2.8, w: 5.4, h: 0.28,
    fontFace: BODY, fontSize: 13, bold: true, color: NAVY, margin: 0 });
  s.addText(
    ["Built-up area", "Locality", "Configuration (BHK)", "Connectivity and accessibility", "Property age", "Amenity availability"]
      .map((t, j, arr) => ({ text: t, options: { bullet: true, breakLine: j < arr.length - 1 } })),
    { x: 7.08, y: 3.14, w: 5.4, h: 2.0, fontFace: BODY, fontSize: 12,
      color: INK, paraSpaceAfter: 6, margin: 0 });

  s.addShape(pres.ShapeType.roundRect, {
    x: M, y: 5.5, w: 12.06, h: 0.86, rectRadius: 0.06,
    fill: { color: "FDF6EF" }, line: { color: ACCENT, width: 1.4 } });
  s.addText(
    "This slide describes planned analysis. No explainability results are reported at this stage, as model training has not yet been completed.",
    { x: M + 0.3, y: 5.5, w: 12.06 - 0.6, h: 0.86, valign: "middle",
      fontFace: BODY, fontSize: 12.5, color: "8A4A22", italic: true, margin: 0 });

  foot(s);
}

/* =================== 18 — PROPOSED SYSTEM ARCHITECTURE =================== */
{
  const s = base("Proposed System Architecture", "Technical Design");

  const layers = [
    ["Data Sources", ["Property dataset (CSV)", "Location data", "GIS boundary data"], NAVY],
    ["Data Processing", ["Python", "Pandas / NumPy", "GeoPandas"], NAVY],
    ["Machine Learning", ["Preprocessing", "Feature engineering", "Model training and evaluation"], ACCENT],
    ["Explainability", ["Feature importance", "SHAP analysis"], NAVY],
    ["Future Application", ["Web-based interface", "Not developed in this phase"], MUTED],
  ];

  const bw = 2.28, gap = 0.2;
  layers.forEach((l, i) => {
    const x = M + i * (bw + gap);
    const isFuture = i === 4;
    s.addShape(pres.ShapeType.roundRect, {
      x, y: 1.72, w: bw, h: 0.66, rectRadius: 0.05,
      fill: { color: i === 2 ? ACCENT : (isFuture ? "FFFFFF" : NAVY) },
      line: { color: isFuture ? LINE : (i === 2 ? ACCENT : NAVY), width: 1.4 } });
    s.addText(l[0], { x, y: 1.72, w: bw, h: 0.66, align: "center", valign: "middle",
      fontFace: BODY, fontSize: 12.5, bold: true,
      color: isFuture ? MUTED : "FFFFFF", margin: 0 });

    panel(s, x, 2.52, bw, 1.98, isFuture ? "FAFBFC" : PANEL);
    s.addText(l[1].map((t, j, arr) => ({
      text: t, options: { bullet: true, breakLine: j < arr.length - 1 } })),
      { x: x + 0.18, y: 2.68, w: bw - 0.34, h: 1.7, fontFace: BODY,
        fontSize: 11, color: isFuture ? MUTED : INK, paraSpaceAfter: 6,
        lineSpacing: 14, margin: 0 });

    if (i < 4) {
      s.addShape(pres.ShapeType.line, { x: x + bw + 0.03, y: 2.05, w: 0.14, h: 0,
        line: { color: MUTED, width: 1.4, endArrowType: "triangle" } });
    }
  });

  panel(s, M, 4.8, 12.06, 1.6);
  s.addText("Relationship between components", { x: M + 0.28, y: 4.98, w: 6, h: 0.28,
    fontFace: HEAD, fontSize: 14, bold: true, color: NAVY, margin: 0 });
  s.addText(
    "Property records supply the labelled examples for supervised learning, while location and GIS data are used to derive accessibility features that are not present in the original dataset. These layers feed a single preprocessing and model-training pipeline. Explainability operates on the trained model rather than on the raw data. The web interface is shown for completeness and is not part of the current phase.",
    { x: M + 0.28, y: 5.3, w: 11.5, h: 1.0, fontFace: BODY, fontSize: 12,
      color: INK, lineSpacing: 17, margin: 0 });

  foot(s);
}

/* ============== 19 — EXPECTED OUTCOME AND FUTURE SCOPE ============== */
{
  const s = base("Expected Outcome and Future Scope", "Deliverables");

  panel(s, M, 1.52, 5.9, 4.9);
  s.addText("Expected Outcome", { x: M + 0.28, y: 1.74, w: 5.3, h: 0.32,
    fontFace: HEAD, fontSize: 16, bold: true, color: NAVY, margin: 0 });
  const outcomes = [
    "A cleaned and statistically analysed property dataset",
    "A documented set of property and location features",
    "A comparison of four regression algorithms under a common evaluation protocol",
    "Reported performance using MAE, RMSE and R²",
    "A selected model for property price prediction",
    "Interpretable information on the features influencing predictions",
  ];
  outcomes.forEach((o, i) => {
    const y = 2.24 + i * 0.66;
    stepCircle(s, i + 1, M + 0.28, y, 0.36);
    s.addText(o, { x: M + 0.78, y: y - 0.03, w: 5.0, h: 0.5,
      fontFace: BODY, fontSize: 11.8, color: INK, lineSpacing: 15, margin: 0 });
  });

  panel(s, 6.86, 1.52, 5.82, 4.9, "FDF6EF");
  s.addText("Future Scope", { x: 7.14, y: 1.74, w: 5.3, h: 0.32,
    fontFace: HEAD, fontSize: 16, bold: true, color: ACCENT, margin: 0 });
  s.addText(
    [
      { text: "GIS integration for accessibility and boundary-based features", options: { bullet: true, breakLine: true } },
      { text: "Incorporation of updated property information", options: { bullet: true, breakLine: true } },
      { text: "Development of a web-based application interface", options: { bullet: true, breakLine: true } },
      { text: "Decision support for prospective buyers", options: { bullet: true, breakLine: true } },
      { text: "Investment and appreciation analysis", options: { bullet: true, breakLine: true } },
      { text: "Development feasibility analysis for builders", options: { bullet: true, breakLine: true } },
      { text: "Extension of the methodology to an additional city, with a separately trained model", options: { bullet: true, breakLine: true } },
      { text: "Additional urban and location intelligence layers", options: { bullet: true } },
    ],
    { x: 7.14, y: 2.24, w: 5.32, h: 3.4, fontFace: BODY, fontSize: 12.2,
      color: INK, paraSpaceAfter: 9, lineSpacing: 16, margin: 0 });

  s.addText("These components are proposed for subsequent phases and are not implemented at this stage.",
    { x: 7.14, y: 5.86, w: 5.32, h: 0.4, fontFace: BODY, fontSize: 10.8,
      color: MUTED, italic: true, margin: 0 });

  foot(s);
}

/* ========================== 20 — CONCLUSION ========================== */
{
  const s = pres.addSlide();
  s.background = { color: NAVY };

  s.addShape(pres.ShapeType.ellipse, {
    x: 11.2, y: -1.2, w: 3.8, h: 3.8,
    fill: { color: NAVY_D }, line: { color: NAVY_D } });

  s.addText("CONCLUSION", { x: M, y: 0.92, w: 9, h: 0.3, fontFace: BODY,
    fontSize: 11.5, color: "E8B98C", bold: true, charSpacing: 1.8, margin: 0 });

  s.addText("Conclusion", { x: M, y: 1.28, w: 10, h: 0.6,
    fontFace: HEAD, fontSize: 32, bold: true, color: "FFFFFF", margin: 0 });

  s.addText(
    "The project addresses the problem of residential property price estimation using machine learning. The work carried out in this phase focuses on understanding the dataset through statistical analysis and exploratory data analysis, identifying the variables relevant to the target, and defining a regression-based machine learning methodology.",
    { x: M, y: 2.16, w: 11.4, h: 1.1, fontFace: BODY, fontSize: 14.5,
      color: "D6E0EE", lineSpacing: 23, margin: 0 });

  s.addText(
    "The analysis indicates that the target variable is positively skewed and that no single numerical attribute is strongly correlated with price, which supports the use of multivariate, non-linear regression models. The next stages will involve feature engineering, model development, comparison and evaluation, followed by integration into the proposed application.",
    { x: M, y: 3.36, w: 11.4, h: 1.2, fontFace: BODY, fontSize: 14.5,
      color: "D6E0EE", lineSpacing: 23, margin: 0 });

  const chain = ["Property Data", "Statistical Analysis", "Machine Learning", "Prediction", "Explainability"];
  chain.forEach((c, i) => {
    const bw2 = 2.24, gap2 = 0.24;
    const x = M + i * (bw2 + gap2);
    s.addShape(pres.ShapeType.roundRect, {
      x, y: 5.0, w: bw2, h: 0.72, rectRadius: 0.05,
      fill: { color: i === 2 ? "FFFFFF" : NAVY_D },
      line: { color: i === 2 ? "FFFFFF" : "35507A", width: 1.2 } });
    s.addText(c, { x: x + 0.06, y: 5.0, w: bw2 - 0.12, h: 0.72,
      align: "center", valign: "middle", fontFace: BODY, fontSize: 11.5,
      bold: i === 2, color: i === 2 ? NAVY : "C9D6E8", margin: 0 });
    if (i < chain.length - 1) {
      s.addText("›", { x: x + bw2, y: 5.0, w: gap2, h: 0.72,
        align: "center", valign: "middle", fontFace: BODY, fontSize: 17,
        color: "6E86AC", margin: 0 });
    }
  });

  s.addText("Thank you", { x: M, y: 6.16, w: 5, h: 0.44,
    fontFace: HEAD, fontSize: 20, bold: true, color: "FFFFFF", margin: 0 });

  foot(s);
}

const OUT = path.join(ROOT, "Project_Review_1_Bengaluru_Property_ML_Editable.pptx");
pres.writeFile({ fileName: OUT }).then(() => console.log("written:", OUT));
