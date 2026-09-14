# Generic extraction is the fallback for any host without a configured Adapter

Q3 deferred this deliberately: "Generic Readability as a last-resort fallback
only if you later want unknown sites; not in v1." v1 turned out to want it --
Chrome's `content_scripts.matches` is static (ADR-0005), so a configured
Adapter alone can never make the extension work on a site you haven't already
edited the manifest for. Reading on an arbitrary hostname requires both
`<all_urls>` permission and something to extract with when no Adapter exists.

`host_permissions` and `content_scripts.matches` are now `<all_urls>`. Chrome
shows a correspondingly broad permission warning when the unpacked extension
loads ("read and change all your data on all websites") -- accepted, same as
every other decision here, because this is a single-user local tool (Q4).

The content script now runs on every page, scores `article`/`main`/`div`/
`section` elements by text-length-minus-link-text-length, and treats the
highest scorer above a floor as the Chapter if no Adapter matches the host.
Below the floor, extraction returns nothing and the Player Bar never appears --
this is also what keeps the bar off pages with no real content, without a
separate "is this a novel site" setting.

The trade-off is real, not just permission-scope: the generic path can't strip
a site's hidden watermark spans (it doesn't know they exist) and its
next-chapter guess is a keyword list, not a probed selector. A site read often
enough to be annoying is worth turning into a real Adapter
(see [docs/adapters.md](../adapters.md)) rather than tuning the heuristic.
