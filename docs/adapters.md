# Site findings

Probed 2026-09-14. Selectors verified against live chapter pages.

## metruyenchu.co

Server-rendered. Easiest of the three.

- **Content**: `main article` — exactly one `<article>` per page. Prose is 100-129
  direct `<p>` children, no `<br>`. ~8,000 chars/chapter.
- **Strip**: nothing. Verified clean: no script/ins/iframe/img/a/span, no hidden
  elements, no zero-width characters, no watermark lines.
- **Next**: real `<a href>` labelled `Chương sau` (previous is `Chương trước`).
- **URL**: `/truyen/{slug}/chuong-{n}`, n is the plain chapter number, computable.
- **End of novel**: the next link is **absent**.
- **Auth**: none. `credentials:'omit'` fetches return full content.

Do NOT select on the article's class — it is a hashed Next.js CSS-module name
that changes every build.

## khotruyenchu.fun

Server-rendered WordPress 6.9.4.

- **Content**: `.entry-content` (defensively `article[id^=post-] .entry-content`).
  118 direct `<p>` children. ~11,500 chars/chapter.
- **Strip**: `.story-navigation`, `.reading-tools-bar`, `.code-block`, `script`,
  `a[href*="discovernative.com"]`, plus two hidden anti-copy watermarks injected
  mid-paragraph with **randomised class names** — match on style, not class:
  - `strong[style*="height:0"]`
  - `i[style*="opacity:0"]`
  These are not `display:none`, so `innerText` includes them and TTS will read
  them aloud. Their text is padded with U+200B; after stripping, zero U+200B
  remain in the chapter — a clean self-check for the adapter.
- **Next**: `.story-navigation .nav-next a`, real absolute href, label `Chương sau »`.
  Ignore the TOC button between the nav links (`href="javascript:void(0)"`).
- **URL**: `/chuong-{n}-{title-slug}/` at site root. The title slug is
  unpredictable, so **next is not computable** — it must be scraped.
- **End of novel**: `.nav-next` renders but is **empty**. Test for a descendant
  `a`, not for the div.
- **Auth**: none.

The site warns its domain is repeatedly ISP-blocked in Vietnam and rotates.
Expect to edit the hostname key periodically.

## dichtienghoa.net

Nuxt/Vue SPA, behind Cloudflare (bot-management challenge scripts observed;
didn't block normal browsing).

- **Content**: `.chapter-content .chapter-body`. Prose is raw text nodes
  separated by ~420-460 `<br>`, zero `<p>`. ~16,300-17,000 chars/chapter.
  Scope the selector -- `.chapter-body` alone is safe today (only one element
  has that class), but `.reader-container > .chapter-stage` sits elsewhere in
  the DOM with the **exact same text**, a genuine visible duplicate. A looser
  selector risks matching it and reading every chapter twice.
- **Strip**: nothing. Verified clean: no script/ins/iframe inside the content
  element.
- **Rendering**: SSR. Raw `fetch(location.href)` returns `.chapter-body`
  already populated.
- **Next**: no `<a href>` at all. The "Chương sau ➡" control is a Vue
  `<button>` (`data-v-2db83860` scoped-style hash) with no href and no
  data-* attribute holding a target id; clicking it does a client-side route
  change (`performance.getEntriesByType('navigation')` stays at 1 entry --
  confirmed by testing), not a real navigation. The "Mục lục" (chapter list)
  panel also renders with zero real `<a>` elements.
  - **What does work**: the trailing numeric chapter id in the URL increments
    by exactly 1 between real consecutive chapters (confirmed twice against
    live chapters). `nextMode: "increment-url"` computes this by regexing the
    last number in `location.href` and adding 1 -- see the comment in
    `resolveNextUrl()` in `content.js`.
  - There's also an unauthenticated JSON API
    (`/api/models/chapter?storyId={id}&order=asc` and
    `/api/models/chapter/{id}?metaOnly=1`, no valid CSRF token required) that
    returns the real ordered chapter list and could resolve "next" more
    robustly than assuming the id never skips. Not used here -- it would need
    a new Adapter shape (an HTTP call, not a DOM/URL rule) for a problem the
    URL heuristic already solves well enough. Worth revisiting if the
    increment ever turns out wrong.
- **End of novel**: no signal at all in this mode. Past the last chapter,
  `increment-url` produces a URL for a chapter that doesn't exist; extraction
  finds no `.chapter-body`, and per ADR-0006 the Player Bar simply doesn't
  reappear. No "End of novel" message -- indistinguishable from the site
  having changed its markup. Accepted; building a existence pre-check just
  for this is more than the problem is worth.
- **Auth**: per-chapter paywall via an unauthenticated metadata endpoint
  (`/api/models/chapter/{id}?metaOnly=1` → `free`, `vipPrice`,
  `globallyUnlocked` fields). A chapter can be `free: false` yet still
  readable if `globallyUnlocked: true` (observed on the chapter this Adapter
  was probed against). Not checked by the Adapter -- a locked chapter should
  just fail the content-selector match like any other missing-content case.

Also noted, not handled: clicking the "next chapter" button fires a synthetic
clipboard write (an anti-copy trick that overwrites whatever you copied). Does
not affect this Adapter, since extraction reads `textContent`/`innerText`
directly and never uses copy/paste -- but don't be surprised if manually
testing this site changes your clipboard.

## hachoangdaide.online — DEFERRED, not in v1

Hostname confirmed 2026-09-14 (`hachhoangdaide.com` is NXDOMAIN; `.online` is the
real site). Deliberately excluded from v1 -- see the hazards at the end of this
section. Adding it means taking on origin checks after navigation, affiliate-gate
detection, paywall detection and rate limiting, none of which the other two sites
need.

Laravel + Vue 2, behind Cloudflare. The hard one.

- **Content**: `#chapter-content_s .s-content`. Prose is raw text nodes separated
  by 88-104 `<br>`, zero `<p>` — a different splitting strategy from the others.
  ~8,400 chars/chapter.
- **Strip**: `span.text-0` (3/chapter), hidden by a global `font-size:0px`
  rule and included in `innerText`.
- **Rendering**: JS. The div is `v-html`-bound and **empty in the server HTML**.
  The prose exists in the response only as a doubly-escaped JSON string inside an
  inline `JSON.parse('...')` literal. Background fetch cannot use DOM selectors
  here; the live DOM is the only robust path.
- **Next**: `a.btn-control[title="Chương tiếp"]`, rendered twice (top and bottom
  control bars) — dedupe.
- **URL**: `/{slug}/chuong-{n}` where **n is the `position` field, not the
  displayed chapter label** (`/chuong-800` is titled "Chương 428"). Never derive
  the URL from the on-page title.
- **End of novel**: next link renders with `href="#"`. Test for that, not absence.
- **Auth**: real paywall. Locked chapters return 200 with a completely different
  template — no `#chapter-content_s`, no `chaper:` blob, page drops ~945KB to
  ~118KB. Detect by absence of the content element, not by HTTP status.

Additional hazards:
- Every chapter where `position % 10 == 0 && money == 0` renders a Shopee
  affiliate gate **instead of** the prose. `.s-content` will not exist there.
- `X-RateLimit-Limit: 30`. Aggressive prefetching will trip it.
- `website_security.js` blocks F12/Ctrl/right-click and has a devtools trap that
  assigns `window.location` from an `Error.message` getter.
- Ad scripts navigate the tab away unprompted. This was observed during the probe.

## Cross-cutting

**Four different end-of-novel signals** (absent link / empty container /
`href="#"` / no signal at all, page just fails to extract). A single shared
"is there a next link" check loops forever on at least one site, so the
end-of-novel test belongs in the Adapter, not in shared code.

**Two of the three embed hidden anti-copy watermarks.** Stripping them is required
for playback to sound right, and is also deliberately removing the sites'
attribution markers. Fine for local personal playback; not fine if audio ever
leaves this machine.
