# Advance by navigating the tab; play audio in an offscreen document

To reach the next Chapter the extension navigates the tab to its URL rather than
fetching it in the background, so the browser keeps supplying cookies, history
and referer, and the address bar keeps telling the truth about where the reader is.

Navigation destroys the content script, so audio cannot live there. It lives in
an MV3 offscreen document owned by the extension, which survives navigation and
keeps playing across the Chapter boundary. The content script only extracts text
and drives the Player Bar.

The alternative -- background-fetching the next Chapter and never navigating --
was rejected: it re-implements navigation and desynchronises the tab from what is
being read.
