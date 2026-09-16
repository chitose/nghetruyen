# The Controls strip reports the Sidecar's startup

**Amended:** a startup window was added after all (`app/splash.py`), because
the strip is not on screen for the first stretch of a launch: a onefile exe
unpacks before Python runs, and the chrome has to be serving before pywebview
can show anything, so the part that looked like "nothing happens" was exactly
the part the strip could not cover. It is small, always-on-top and takes the
same status the strip does, and `main.py` takes it down when the reader window
appears -- so the strip is still the surface that carries Retry, and nothing
about that decision below changes for the minute after launch. It is not a
third pywebview window: that is what would have entangled it with `docking.py`,
so it is a plain Win32 window that owns no App state.

Starting the App used to say nothing about the Sidecar. `main.py` spawned it,
a background thread polled `/speakers`, and a Sidecar that never answered left
one line in `%APPDATA%\reading-web\nghetruyen.log` -- a file nothing points at
until something else goes wrong. What the reader saw was an App where Play did
nothing, and a log they had no reason to open.

Now the Controls strip's status line carries the startup: "Starting the
Sidecar…" from launch, then the usual Chapter position once `/speakers`
answers. If it never does, the line says what happened, names
`sidecar/sidecar.log`, and a **Retry** button appears beside it.

The existing status line is what shows it, rather than a splash window. The
strip is already on screen when the Sidecar starts, and a third window would
need its own show/hide lifecycle threaded through `docking.py` to display a
single line of text that only matters for the first minute.

Four things are worth recording, because they are where this is not obvious:

- **Retry never restarts a Sidecar that is merely slow.** A first run
  downloads the voice model from Hugging Face, so a timeout is not proof of
  death, and killing the process to respawn it would throw that download away.
  `SidecarManager.ensure_running()` waits again on a Sidecar this App already
  spawned; it spawns only when nothing was started, or when the process it
  spawned has since exited. The timeout message says "still starting" in that
  case instead of pretending the Sidecar is broken.
- **Quitting cancels a Retry that has not spawned yet.** The spawn now happens
  on the startup thread rather than on the launch path, so it can race the
  reader window closing; `SidecarStartup.stop()` takes the lock that spawn runs
  under. Without it the App could exit just after a Retry started a Sidecar
  that nothing would stop, and it would hold port 8934 against the next launch.
- **A failure does not block startup.** The App opens, and the reader can
  browse and read the Chapter; only playback needs the Sidecar. That is also
  why recovery is not limited to Retry: a Sidecar started by hand (or the
  Docker image) satisfies the next watch, and the first Chunk that synthesizes
  clears the banner on its own -- audio is proof the Sidecar answered.
- **The status line has an order.** A Sidecar failure outranks the
  per-Paragraph position, because nothing can play and the fix is in that line;
  a playback error outranks the "starting" notice, because it is the more
  specific thing to have just happened. `ui.status_text` holds that rule and is
  unit-tested, since the rest of the view is not.

The Sidecar's startup also moved off the launch path: `main.py` hands it to
`SidecarStartup` (in `sidecar_manager.py`), which owns the spawn, the wait, and
the reporting, and exposes one call that both launch and Retry use. `Controller`
holds the state the chrome polls, as it does for playback -- there is still one
source of truth, and the chrome still only reads.
