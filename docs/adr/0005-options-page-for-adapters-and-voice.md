# Adapters and voice move from hardcoded constants to an options page

Q4 settled on hardcoding configuration and skipping an options page, since this
is a single-user, never-published tool. That was reversed on request: an
options page (chrome.storage.sync) now holds the Sidecar URL, voice, default
speed, and the Adapter list, with DEFAULT_ADAPTERS in extension/defaults.js as
the fallback seed.

One constraint doesn't go away just because there's a form now: Chrome's
`content_scripts.matches` in manifest.json is static. Adding a new hostname's
Adapter through the options page does not get the content script injected
there -- the hostname must also be added to manifest.json and the extension
reloaded. Dynamically requesting per-site permissions at runtime
(`chrome.permissions.request` + `chrome.scripting.registerContentScripts`)
would remove that step, but it means a Chrome permission prompt per new site
and more moving parts than a personal tool with two-to-few sites warrants. The
options page states the limitation rather than working around it.
