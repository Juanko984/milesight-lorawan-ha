// Headless render guard for the Lovelace card bundle.
// Loads tests/cards/render.html (which instantiates every card + every table preset against fake `hass`),
// and fails if the bundle throws, logs a console error, or a card renders nothing into its shadow DOM.
// Run: node tests/cards/render.cjs   (CI installs playwright + chromium first)
const path = require("path");
const { chromium } = require("playwright");

(async () => {
  const errs = [];
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 900, height: 800 } });
  page.on("console", (m) => { if (m.type() === "error") errs.push("console: " + m.text()); });
  page.on("pageerror", (e) => errs.push("pageerror: " + e.message));

  const file = "file://" + path.join(__dirname, "render.html");
  await page.goto(file, { waitUntil: "load" });
  await page.waitForTimeout(800);

  // every custom element should have produced a non-empty shadow root (except onboarding, which may hide itself)
  const empties = await page.evaluate(() => {
    const out = [];
    document.querySelectorAll("#root > *").forEach((el) => {
      const tag = el.tagName.toLowerCase();
      if (!tag.startsWith("milesight-")) return;
      if (tag === "milesight-onboarding") return;                 // legitimately renders nothing when all set up
      const sr = el.shadowRoot;
      if (!sr || sr.childElementCount === 0 || !sr.textContent.trim()) out.push(tag);
    });
    return out;
  });
  empties.forEach((t) => errs.push("empty render: " + t));

  const n = await page.evaluate(() => window.__rendered || 0);
  if (!n) errs.push("page did not render");

  await browser.close();
  if (errs.length) {
    console.error("CARD RENDER FAILURES:\n  " + errs.join("\n  "));
    process.exit(1);
  }
  console.log("card render guard: OK (" + n + " nodes, no console/page errors)");
})();
