// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Driving the page: an ordered list of `verb:argument` steps.
 *
 * Order is the point. A screenshot of a tab three clicks deep is not describable
 * as a set of flags — `--click` twice and `--scroll` once has no defined
 * sequence — so navigation is expressed as a list that runs front to back:
 *
 *   --do click:'text=Negotiate' --do wait:.offer-grid --do scroll:bottom
 *
 * Element arguments are passed to `page.locator()` untouched, which means every
 * Playwright selector engine is available (`text=`, `role=button[name="Save"]`,
 * `#id`, `.class`, XPath) without this file knowing about any of them. A string
 * that is not valid CSS and carries no engine prefix is treated as visible text,
 * because that is what someone typing `--do click:Negotiate` meant.
 */

const ENGINE_PREFIX = /^(css|text|role|xpath|id|data-testid|internal:[a-z-]+)[=:]/;
/** Punctuation that only appears in a CSS selector, never in a visible label. */
const CSS_PUNCTUATION = /[.#\[\]>+~*]|::/;

/**
 * Resolve one element argument.
 *
 * Order matters, and the interesting case is the bare word. `--do click:Save`
 * means the button labelled Save, but "Save" is also a syntactically valid CSS
 * type selector, so handing it to `locator()` silently looks for a `<save>`
 * element and times out. A bare word is therefore matched by what it is on
 * screen: its accessible name first — buttons, links and tabs are what
 * navigation actually targets — and its visible text as the fallback.
 *
 * @param {import("playwright").Page} page
 */
export function locate(page, spec) {
  if (ENGINE_PREFIX.test(spec) || spec.startsWith("//") || spec.startsWith("(")) return page.locator(spec).first();
  if (CSS_PUNCTUATION.test(spec) || /\s/.test(spec) === false && /^[a-z]+$/.test(spec) && HTML_TAGS.has(spec)) {
    return page.locator(spec).first();
  }
  return page
    .getByRole("button", { name: spec })
    .or(page.getByRole("link", { name: spec }))
    .or(page.getByRole("tab", { name: spec }))
    .or(page.getByRole("menuitem", { name: spec }))
    .or(page.getByText(spec, { exact: true }))
    .first();
}

/** Lowercase bare words that really are element selectors rather than labels. */
const HTML_TAGS = new Set([
  "a", "article", "aside", "body", "button", "canvas", "code", "dialog", "div", "footer",
  "form", "h1", "h2", "h3", "header", "img", "input", "li", "main", "nav", "ol", "p", "pre",
  "section", "select", "span", "svg", "table", "tbody", "td", "textarea", "th", "tr", "ul", "video",
]);

/** Split `verb:rest` on the first colon. `back` and `reload` take no argument. */
export function parseAction(raw) {
  const i = raw.indexOf(":");
  if (i === -1) return { verb: raw.trim(), arg: "" };
  return { verb: raw.slice(0, i).trim(), arg: raw.slice(i + 1) };
}

const splitPair = (arg) => {
  const i = arg.indexOf("=");
  if (i === -1) throw new Error(`expected <selector>=<value>, got "${arg}"`);
  return [arg.slice(0, i), arg.slice(i + 1)];
};

/**
 * @param {import("playwright").Page} page
 * @param {string[]} actions
 * @param {{baseUrl?:string, timeout?:number, log?:(m:string)=>void}} ctx
 * @returns {Promise<{action:string, ms:number}[]>}
 */
export async function runActions(page, actions, ctx = {}) {
  const timeout = ctx.timeout ?? 15_000;
  const trace = [];
  for (const raw of actions ?? []) {
    const started = Date.now();
    const { verb, arg } = parseAction(raw);
    switch (verb) {
      case "click":
        await locate(page, arg).click({ timeout });
        break;
      case "dblclick":
        await locate(page, arg).dblclick({ timeout });
        break;
      case "hover":
        await locate(page, arg).hover({ timeout });
        break;
      case "focus":
        await locate(page, arg).focus({ timeout });
        break;
      case "check":
        await locate(page, arg).check({ timeout });
        break;
      case "uncheck":
        await locate(page, arg).uncheck({ timeout });
        break;
      case "fill": {
        const [sel, value] = splitPair(arg);
        await locate(page, sel).fill(value, { timeout });
        break;
      }
      case "select": {
        const [sel, value] = splitPair(arg);
        await locate(page, sel).selectOption(value, { timeout });
        break;
      }
      case "press":
        await page.keyboard.press(arg);
        break;
      case "typekeys":
        await page.keyboard.type(arg, { delay: 20 });
        break;
      case "goto":
        await page.goto(arg.startsWith("http") ? arg : `${ctx.baseUrl ?? ""}${arg}`, {
          waitUntil: "domcontentloaded",
          timeout,
        });
        break;
      case "back":
        await page.goBack({ waitUntil: "domcontentloaded" });
        break;
      case "forward":
        await page.goForward({ waitUntil: "domcontentloaded" });
        break;
      case "reload":
        await page.reload({ waitUntil: "domcontentloaded" });
        break;
      case "scroll":
        if (arg === "bottom") await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
        else if (arg === "top") await page.evaluate(() => window.scrollTo(0, 0));
        else if (/^-?\d+$/.test(arg)) await page.evaluate((y) => window.scrollBy(0, y), Number(arg));
        else await locate(page, arg).scrollIntoViewIfNeeded({ timeout });
        break;
      case "wait":
        await page.locator(arg).first().waitFor({ state: "visible", timeout });
        break;
      case "wait-hidden":
        await page.locator(arg).first().waitFor({ state: "hidden", timeout });
        break;
      case "wait-text":
        await page.waitForFunction((t) => document.body.innerText.includes(t), arg, { timeout });
        break;
      case "wait-url":
        await page.waitForURL(arg.includes("*") ? arg : `**${arg}`, { timeout });
        break;
      case "sleep":
        await page.waitForTimeout(Number(arg) || 0);
        break;
      case "eval":
        await page.evaluate(arg);
        break;
      case "emulate":
        // `emulate:dark` / `emulate:light` — flip the media query mid-session
        // without tearing down and rebuilding the context.
        await page.emulateMedia({ colorScheme: arg });
        break;
      default:
        throw new Error(`unknown action "${verb}" in "${raw}"`);
    }
    trace.push({ action: raw, ms: Date.now() - started });
    ctx.log?.(`${raw} (${Date.now() - started}ms)`);
  }
  return trace;
}

export const ACTION_HELP = `
  click:<sel>          click an element        hover:<sel>        hover it
  dblclick:<sel>       double click            focus:<sel>        focus it
  fill:<sel>=<text>    set an input            select:<sel>=<v>   pick an option
  check:<sel>          tick a checkbox         uncheck:<sel>      untick it
  press:<key>          keyboard key            typekeys:<text>    type into focus
  goto:<url|route>     navigate                back / forward     history
  reload               reload the page         emulate:<scheme>   dark | light
  scroll:<px|top|bottom|sel>                    sleep:<ms>
  wait:<sel>           until visible           wait-hidden:<sel>  until gone
  wait-text:<text>     until text appears      wait-url:<glob>    until routed
  eval:<js>            run JS in the page

  Selectors take any Playwright engine: text=Save, role=button[name="Save"],
  #id, .class, //xpath. A bare word is matched by accessible name, then by
  visible text — click:Save means the button labelled Save.`;
