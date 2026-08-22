import { existsSync } from "node:fs";
import { chromium } from "playwright";
const [url, out, theme = "dark", steps = "", width = "1440", height = "900"] = process.argv.slice(2);
// The pinned Playwright build and the image's Chromium can differ; launch the
// one that's actually here.
const executablePath = process.env.PW_CHROMIUM ?? "/opt/pw-browsers/chromium";
const browser = await chromium.launch(existsSync(executablePath) ? { executablePath } : {});
const page = await browser.newPage({
  viewport: { width: Number(width), height: Number(height) },
  deviceScaleFactor: 2,
  colorScheme: theme === "light" ? "light" : "dark",
});
await page.addInitScript(t => localStorage.setItem("theme", t), theme);
await page.goto(url, { waitUntil: "networkidle" });
await page.waitForSelector('[data-app-shell="ready"]', { timeout: 45000 });
// The dev-tools badge is dev-server furniture, not product surface.
await page.addStyleTag({ content: "nextjs-portal { display: none !important; }" });
for (const step of steps.split("|").filter(Boolean)) {
  if (step.startsWith("key:")) await page.keyboard.press(step.slice(4));
  else if (step.startsWith("type:")) await page.keyboard.type(step.slice(5), { delay: 12 });
  else if (step.startsWith("wait:")) await page.waitForTimeout(Number(step.slice(5)));
  else if (step.startsWith("click:")) await page.click(step.slice(6));
  else await page.getByRole("button", { name: step, exact: true }).first().click();
  await page.waitForTimeout(250);
}
await page.waitForTimeout(600);
await page.screenshot({ path: out });
console.log("wrote", out);
await browser.close();
