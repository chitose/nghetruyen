const adapterList = document.getElementById("adapterList");
const template = document.getElementById("adapterTemplate");

function updateNextValueState(fieldset) {
  const isIncrement = fieldset.querySelector(".nextMode").value === "increment-url";
  const nextValueInput = fieldset.querySelector(".nextValue");
  nextValueInput.disabled = isIncrement;
  nextValueInput.placeholder = isIncrement ? "(not needed for this mode)" : ".nav-next a";
}

function addAdapterCard(adapter = { hostname: "", contentSelector: "", stripSelectors: [], nextMode: "css", nextValue: "" }) {
  const node = template.content.cloneNode(true);
  const fieldset = node.querySelector("fieldset");
  fieldset.querySelector(".hostname").value = adapter.hostname;
  fieldset.querySelector(".contentSelector").value = adapter.contentSelector;
  fieldset.querySelector(".stripSelectors").value = adapter.stripSelectors.join("\n");
  fieldset.querySelector(".nextMode").value = adapter.nextMode;
  fieldset.querySelector(".nextValue").value = adapter.nextValue;
  fieldset.querySelector(".removeAdapter").addEventListener("click", () => fieldset.remove());
  fieldset.querySelector(".nextMode").addEventListener("change", () => updateNextValueState(fieldset));
  updateNextValueState(fieldset);
  adapterList.appendChild(node);
}

function readAdapterCards() {
  return [...adapterList.querySelectorAll("fieldset.adapter")]
    .map((f) => ({
      hostname: f.querySelector(".hostname").value.trim(),
      contentSelector: f.querySelector(".contentSelector").value.trim(),
      stripSelectors: f.querySelector(".stripSelectors").value.split("\n").map((s) => s.trim()).filter(Boolean),
      nextMode: f.querySelector(".nextMode").value,
      nextValue: f.querySelector(".nextValue").value.trim(),
    }))
    .filter((a) => a.hostname && a.contentSelector && (a.nextValue || a.nextMode === "increment-url"));
}

async function load() {
  const {
    sidecarUrl = DEFAULT_SIDECAR_URL,
    speaker = DEFAULT_SPEAKER,
    defaultRate = DEFAULT_RATE,
    adapters: storedAdapters,
  } = await chrome.storage.sync.get(["sidecarUrl", "speaker", "defaultRate", "adapters"]);
  const adapters = storedAdapters ? mergeDefaultAdapters(storedAdapters) : DEFAULT_ADAPTERS;
  if (storedAdapters && adapters.length !== storedAdapters.length) {
    chrome.storage.sync.set({ adapters }); // persist newly-added built-ins
  }

  document.getElementById("sidecarUrl").value = sidecarUrl;
  document.getElementById("speaker").value = speaker;
  document.getElementById("defaultRate").value = defaultRate;

  const speakerList = document.getElementById("speakerList");
  speakerList.innerHTML = KNOWN_SPEAKERS.map((s) => `<option value="${s}">`).join("");

  adapterList.innerHTML = "";
  adapters.forEach(addAdapterCard);
}

async function save() {
  const settings = {
    sidecarUrl: document.getElementById("sidecarUrl").value.trim() || DEFAULT_SIDECAR_URL,
    speaker: document.getElementById("speaker").value.trim() || DEFAULT_SPEAKER,
    defaultRate: parseFloat(document.getElementById("defaultRate").value) || DEFAULT_RATE,
    adapters: readAdapterCards(),
  };
  await chrome.storage.sync.set(settings);
  const status = document.getElementById("saveStatus");
  status.textContent = "Saved.";
  setTimeout(() => (status.textContent = ""), 2000);
}

document.getElementById("addAdapter").addEventListener("click", () => addAdapterCard());
document.getElementById("save").addEventListener("click", save);
document.getElementById("resetDefaults").addEventListener("click", async () => {
  await chrome.storage.sync.set({
    sidecarUrl: DEFAULT_SIDECAR_URL,
    speaker: DEFAULT_SPEAKER,
    defaultRate: DEFAULT_RATE,
    adapters: DEFAULT_ADAPTERS,
  });
  load();
});

document.getElementById("fetchSpeakers").addEventListener("click", async () => {
  const status = document.getElementById("speakerStatus");
  const url = document.getElementById("sidecarUrl").value.trim() || DEFAULT_SIDECAR_URL;
  status.textContent = "Fetching…";
  try {
    const res = await fetch(`${url}/speakers`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const { speakers } = await res.json();
    const list = document.getElementById("speakerList");
    list.innerHTML = "";
    for (const s of speakers) {
      const opt = document.createElement("option");
      opt.value = s;
      list.appendChild(opt);
    }
    status.textContent = `Found: ${speakers.join(", ")}`;
  } catch (err) {
    status.textContent = `Couldn't reach sidecar (${err.message}). Is it running?`;
  }
});

load();
