// Unit tests for the Property card's pure brains (msStayState, msPartyRisk), run in a real browser so the exact
// shipped bundle code is exercised. Run: node tests/cards/property.test.cjs
const path = require("path");
const { chromium } = require("playwright");

(async () => {
  const fails = [];
  const ok = (cond, msg) => { if (!cond) fails.push(msg); };
  const browser = await chromium.launch();
  const page = await browser.newPage();
  page.on("pageerror", (e) => fails.push("pageerror: " + e.message));
  await page.goto("file://" + path.join(__dirname, "render.html"), { waitUntil: "load" });
  await page.waitForTimeout(300);

  const T = await page.evaluate(() => {
    const api = window.__milesightTest || {};
    const stay = (s) => { const r = api.msStayState(s); return r.key; };
    const risk = (s) => { const r = api.msPartyRisk(s); return { score: r.score, label: r.label, bars: r.bars.length }; };
    return {
      // --- stay-state machine ---
      occupied: stay({ occupied: true, people: 2, occupiedS: 7200 }),
      checkin: stay({ occupied: true, people: 1, occupiedS: 600 }),
      checkout: stay({ occupied: false, emptyS: 1800 }),
      vacant: stay({ occupied: false, emptyS: 50000 }),
      vacantUnknown: stay({ occupied: false }),
      turnover: stay({ occupied: false, doorOpen: true }),
      turnoverRecent: stay({ occupied: false, doorSinceMin: 5, emptyS: 100000 }),
      // --- party / smoking risk ---
      quiet: risk({ noiseDb: 38, noiseThreshold: 70, afterHours: false, co2: 600, people: 2, capacity: 2, vape: false }),
      vaping: risk({ noiseDb: 40, noiseThreshold: 70, co2: 650, people: 2, capacity: 2, vape: true }),
      overcap: risk({ noiseDb: 55, noiseThreshold: 70, co2: 900, people: 9, capacity: 2, vape: false }),
      loudLate: risk({ noiseDb: 82, noiseThreshold: 70, afterHours: true, co2: 1100, co2Rise: 260, people: 6, capacity: 4, vape: false }),
      empty: risk({}),
    };
  });

  ok(T.occupied === "occupied", "occupied: got " + T.occupied);
  ok(T.checkin === "checkin", "checkin: got " + T.checkin);
  ok(T.checkout === "checkout", "checkout: got " + T.checkout);
  ok(T.vacant === "vacant", "vacant: got " + T.vacant);
  ok(T.vacantUnknown === "vacant", "vacant(unknown): got " + T.vacantUnknown);
  ok(T.turnover === "turnover", "turnover(doorOpen): got " + T.turnover);
  ok(T.turnoverRecent === "turnover", "turnover(recent door): got " + T.turnoverRecent);

  ok(T.quiet.label === "Low" && T.quiet.score < 34, "quiet should be Low: " + JSON.stringify(T.quiet));
  ok(T.quiet.bars === 4, "risk has 4 bars: " + T.quiet.bars);
  ok(T.vaping.label === "High" && T.vaping.score >= 85, "vaping forces High: " + JSON.stringify(T.vaping));
  ok(T.overcap.score >= 62, "over-capacity lifts risk: " + JSON.stringify(T.overcap));
  ok(T.loudLate.label === "High", "loud + late + full = High: " + JSON.stringify(T.loudLate));
  ok(T.empty.score === 0 && T.empty.label === "Low", "no signals = 0 / Low: " + JSON.stringify(T.empty));

  await browser.close();
  if (fails.length) { console.error("PROPERTY CARD TEST FAILURES:\n  " + fails.join("\n  ")); process.exit(1); }
  console.log("property card logic: OK");
})();
