// Vendored from @mozilla/readability (Apache-2.0) -- the same heuristic
// Firefox's Reader View button uses to decide a page is reader-view-eligible.
// Scores <p>/<pre>/<article> nodes (plus <div> holding <br>-separated text)
// by content length, skipping nav/sidebar/comment-shaped candidates.

const READERABLE_REGEXPS = {
  unlikelyCandidates:
    /-ad-|ai2html|banner|combx|comment|community|cover-wrap|disqus|extra|footer|gdpr|header|legends|menu|related|remark|replies|rss|shoutbox|sidebar|skyscraper|social|sponsor|supplemental|ad-break|agegate|pagination|pager|popup|yom-remote/i,
  okMaybeItsACandidate: /and|article|body|column|content|main|shadow/i,
};

function isNodeVisible(node) {
  return (
    (!node.style || node.style.display != "none") &&
    !node.hasAttribute("hidden") &&
    (!node.hasAttribute("aria-hidden") ||
      node.getAttribute("aria-hidden") != "true" ||
      (node.className && node.className.indexOf && node.className.indexOf("fallback-image") !== -1))
  );
}

function isProbablyReaderable(doc, minContentLength = 140, minScore = 20) {
  let nodes = [...doc.documentElement.querySelectorAll("p, pre, article")];
  const brNodes = doc.documentElement.querySelectorAll("div > br");
  if (brNodes.length) {
    const set = new Set(nodes);
    brNodes.forEach((node) => set.add(node.parentNode));
    nodes = [...set];
  }

  let score = 0;
  return nodes.some((node) => {
    if (!isNodeVisible(node)) return false;
    const matchString = node.className + " " + node.id;
    if (
      READERABLE_REGEXPS.unlikelyCandidates.test(matchString) &&
      !READERABLE_REGEXPS.okMaybeItsACandidate.test(matchString)
    ) {
      return false;
    }
    if (node.matches("li p")) return false;
    const textContentLength = node.textContent.trim().length;
    if (textContentLength < minContentLength) return false;
    score += Math.sqrt(textContentLength - minContentLength);
    return score > minScore;
  });
}
