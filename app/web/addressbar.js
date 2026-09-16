// Minimal browser chrome (address bar + back/forward) -- pywebview has no
// built-in navigation UI of its own, so the reader has no way to reach an
// arbitrary chapter URL without this. Injected the same way as content.js,
// so it persists across every navigation.
//
// ponytail: pushes the page down via documentElement margin-top instead of
// reserving real layout space -- good enough for the handful of novel sites
// this app targets, but a site with its own fixed/sticky header can still
// overlap. Revisit with a proper iframe-based shell if that becomes annoying.
(function () {
  if (document.getElementById("vn-tts-addressbar")) return; // already injected

  const bar = document.createElement("div");
  bar.id = "vn-tts-addressbar";
  bar.style.cssText =
    "position:fixed; top:0; left:0; right:0; z-index:2147483647; " +
    "display:flex; gap:4px; padding:4px; background:#222; font-family:sans-serif;";
  bar.innerHTML = `
    <button id="vn-tts-back" title="Back" style="cursor:pointer;">←</button>
    <button id="vn-tts-forward" title="Forward" style="cursor:pointer;">→</button>
    <input id="vn-tts-url" type="text" style="flex:1; padding:2px 6px;">
    <button id="vn-tts-go" style="cursor:pointer;">Go</button>
  `;
  document.documentElement.appendChild(bar);

  const urlInput = bar.querySelector("#vn-tts-url");
  urlInput.value = location.href;

  function navigate() {
    let url = urlInput.value.trim();
    if (!/^[a-zA-Z][a-zA-Z0-9+.-]*:\/\//.test(url)) url = "https://" + url;
    location.href = url;
  }

  bar.querySelector("#vn-tts-go").addEventListener("click", navigate);
  urlInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") navigate();
  });
  bar.querySelector("#vn-tts-back").addEventListener("click", () => history.back());
  bar.querySelector("#vn-tts-forward").addEventListener("click", () => history.forward());

  const currentMarginTop = parseFloat(getComputedStyle(document.documentElement).marginTop) || 0;
  document.documentElement.style.marginTop = currentMarginTop + 36 + "px";
})();
