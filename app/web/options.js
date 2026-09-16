async function load() {
  const settings = await window.pywebview.api.get_settings();
  document.getElementById("sidecarUrl").value = settings.sidecarUrl;
  document.getElementById("speaker").value = settings.speaker;
  document.getElementById("defaultRate").value = settings.defaultRate;

  const adapters = await window.pywebview.api.get_adapters();
  document.getElementById("adapters").value = JSON.stringify(adapters, null, 2);
}

function status(msg) {
  document.getElementById("status").textContent = msg;
  setTimeout(() => (document.getElementById("status").textContent = ""), 2000);
}

document.getElementById("saveSettings").addEventListener("click", async () => {
  await window.pywebview.api.save_settings({
    sidecarUrl: document.getElementById("sidecarUrl").value,
    speaker: document.getElementById("speaker").value,
    defaultRate: parseFloat(document.getElementById("defaultRate").value),
  });
  status("Settings saved.");
});

document.getElementById("saveAdapters").addEventListener("click", async () => {
  let parsed;
  try {
    parsed = JSON.parse(document.getElementById("adapters").value);
  } catch (err) {
    status(`Invalid JSON: ${err.message}`);
    return;
  }
  await window.pywebview.api.save_adapters(parsed);
  status("Adapters saved.");
});

window.addEventListener("pywebviewready", load);
