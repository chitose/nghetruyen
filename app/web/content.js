// Extraction and next-chapter navigation only. The address bar and Player Bar
// now live in the NiceGUI chrome (docs/adr/0010-nicegui-chrome.md); chunking,
// playback state, and config still live in the Python host. This file does
// what needs a live DOM: read the Page, report it, and (at Python's command)
// re-query the next-chapter link to click or navigate it.

function findNextTarget(adapter) {
  if (!adapter) return findGenericNextTarget();
  if (adapter.nextMode === "generic") return findGenericNextTarget();
  if (adapter.nextMode === "increment-url") {
    return { url: location.href.replace(/(\d+)(?!.*\d)/, (m) => String(Number(m) + 1)) };
  }
  if (adapter.nextMode === "text") {
    const links = [...document.querySelectorAll("a")];
    const el = links.find((a) => a.textContent.trim() === adapter.nextValue);
    return el ? { el } : null;
  }
  const match = document.querySelector(adapter.nextValue);
  if (!match) return null;
  return { el: match.tagName === "A" ? match : match.querySelector("a") || match };
}

function paragraphsFromInnerText(text) {
  return text.split(/\n+/).map((p) => p.replace(/\s+/g, " ").trim()).filter(Boolean);
}

function extractWithAdapter(adapter) {
  const container = document.querySelector(adapter.contentSelector);
  if (!container) return null;
  const clone = container.cloneNode(true);
  for (const sel of adapter.stripSelectors) {
    clone.querySelectorAll(sel).forEach((el) => el.remove());
  }
  clone.style.cssText = "position:fixed; left:-99999px; top:0;";
  document.body.appendChild(clone);
  const paragraphs = paragraphsFromInnerText(clone.innerText || "");
  clone.remove();
  return paragraphs;
}

const GENERIC_MIN_SCORE = 200;
const NEXT_LINK_KEYWORDS = ["chương sau", "chương tiếp", "tiếp theo", "next chapter", "next", "»", ">>"];

function scoreElement(el) {
  const text = el.innerText || "";
  let linkText = 0;
  el.querySelectorAll("a").forEach((a) => (linkText += (a.innerText || "").length));
  return text.length - linkText * 2;
}

function findGenericNextTarget() {
  const relNext = document.querySelector('a[rel="next"]');
  if (relNext) return { el: relNext };
  const links = [...document.querySelectorAll("a")];
  for (const kw of NEXT_LINK_KEYWORDS) {
    const match = links.find((a) => a.textContent.trim().toLowerCase() === kw);
    if (match) return { el: match };
  }
  return null;
}

function genericExtract() {
  if (typeof isProbablyReaderable === "function" && !isProbablyReaderable(document)) return null;
  const candidates = document.querySelectorAll("article, main, div, section");
  let best = null;
  let bestScore = GENERIC_MIN_SCORE;
  for (const el of candidates) {
    const score = scoreElement(el);
    if (score > bestScore) {
      bestScore = score;
      best = el;
    }
  }
  if (!best) return null;
  return paragraphsFromInnerText(best.innerText || "");
}

// The adapter is resolved once per Page, at load, and re-used when Python asks
// for the next chapter later -- so __vnTtsGoNext never has to re-ask for it.
let storedNextAdapter = null;

// Python -> JS: follow this Page's next-chapter link. Returns false when there
// is genuinely no next link (end of novel), which the chrome reports.
window.__vnTtsGoNext = function () {
  const target = findNextTarget(storedNextAdapter);
  if (!target) return false;
  if (target.url) location.href = target.url;
  else target.el.click();
  return true;
};

(async function init() {
  const init = await window.pywebview.api.get_init_data(location.hostname);
  storedNextAdapter = init.adapter;
  let paragraphs = null;
  try {
    paragraphs = init.adapter ? extractWithAdapter(init.adapter) : genericExtract();
  } catch (err) {
    paragraphs = null;
  }
  // Report every Page, readable or not, so the chrome can say where it is and
  // when a Page has nothing to read.
  await window.pywebview.api.page_loaded(location.href, document.title, paragraphs ? paragraphs.length : 0);
  if (!paragraphs || !paragraphs.length) return; // nothing readable here
  await window.pywebview.api.chapter_ready(paragraphs, document.title);
})();
