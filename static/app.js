const form = document.querySelector("#lookup");
const input = document.querySelector("#q");
const suggest = document.querySelector("#suggest");
const status = document.querySelector("#status");
const results = document.querySelector("#results");

function setStatus(text, isError) {
  status.textContent = text || "";
  status.classList.toggle("error", Boolean(isError));
}

function clock(seconds) {
  if (!seconds && seconds !== 0) return "";
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return m + ":" + String(s).padStart(2, "0");
}

function isLink(value) {
  return /^(https?:\/\/)?(www\.|m\.)?(youtube\.com|youtu\.be|music\.youtube\.com)\//i.test(value.trim())
    || /^[A-Za-z0-9_-]{11}$/.test(value.trim());
}

function card(item) {
  const node = document.createElement("article");
  node.className = "card";
  node.innerHTML = `
    <img alt="" src="${item.thumbnail}">
    <div>
      <h2></h2>
      <p class="meta"></p>
      <div class="actions">
        <button type="button" data-format="mp3">Save MP3</button>
        <button type="button" data-format="mp4">Save MP4</button>
      </div>
      <p class="progress"></p>
    </div>`;
  node.querySelector("h2").textContent = item.title;
  node.querySelector(".meta").textContent = [item.channel, clock(item.duration)].filter(Boolean).join(" · ");
  node.querySelectorAll(".choice, button[data-format]").forEach((button) => {
    button.addEventListener("click", () => save(item.url, button.dataset.format, node));
  });
  return node;
}

async function save(url, format, node) {
  const buttons = node.querySelectorAll("button");
  const progress = node.querySelector(".progress");
  buttons.forEach((button) => { button.disabled = true; });
  progress.textContent = "Starting " + format.toUpperCase() + "…";
  setStatus("");
  try {
    const created = await fetch("/api/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, format }),
    });
    const payload = await created.json();
    if (!created.ok) throw new Error(payload.error || "Could not start");
    await poll(payload.id, progress);
  } catch (error) {
    progress.textContent = "";
    setStatus(error.message, true);
  } finally {
    buttons.forEach((button) => { button.disabled = false; });
  }
}

async function poll(id, progress) {
  for (;;) {
    await new Promise((resolve) => setTimeout(resolve, 1000));
    const response = await fetch("/api/jobs/" + id);
    const job = await response.json();
    if (!response.ok) throw new Error(job.error || "Lost track of that save");
    if (job.status === "error") throw new Error(job.error || "Save failed");
    progress.textContent = job.progress || "Working…";
    if (job.status === "done") {
      const file = await fetch("/api/jobs/" + id + "/file");
      if (!file.ok) throw new Error("The file was saved on disk but the browser could not fetch it");
      const blob = await file.blob();
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = job.filename || "download";
      link.click();
      URL.revokeObjectURL(link.href);
      progress.textContent = "Saved " + (job.filename || "file");
      return;
    }
  }
}

function showItem(item) {
  results.replaceChildren(card(item));
}

async function lookup(value) {
  results.replaceChildren();
  setStatus(isLink(value) ? "Reading that video…" : "Searching…");
  const endpoint = isLink(value)
    ? "/api/info?url=" + encodeURIComponent(value.trim())
    : "/api/search?q=" + encodeURIComponent(value.trim());
  const response = await fetch(endpoint);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || "Lookup failed");
  if (payload.items) {
    if (!payload.items.length) {
      setStatus("Nothing matched. Try a more specific title.");
      return;
    }
    const list = document.createElement("div");
    list.className = "results";
    payload.items.forEach((item) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "hit";
      button.innerHTML = `<img alt="" src="${item.thumbnail}"><div><h2></h2><p class="meta"></p></div>`;
      button.querySelector("h2").textContent = item.title;
      button.querySelector(".meta").textContent = [item.channel, clock(item.duration)].filter(Boolean).join(" · ");
      button.addEventListener("click", () => showItem(item));
      list.appendChild(button);
    });
    results.replaceChildren(list);
    setStatus(payload.items.length + " results. Open one, then choose MP3 or MP4.");
    return;
  }
  showItem(payload);
  setStatus("Choose MP3 for audio, or MP4 to keep the picture.");
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  closeSuggestions();
  try {
    await lookup(input.value);
  } catch (error) {
    setStatus(error.message, true);
  }
});

let suggestTimer = 0;
let suggestGen = 0;

function closeSuggestions() {
  suggestGen += 1;
  suggest.hidden = true;
  suggest.replaceChildren();
}

input.addEventListener("input", () => {
  window.clearTimeout(suggestTimer);
  const query = input.value.trim();
  if (query.length < 2 || isLink(query)) {
    closeSuggestions();
    return;
  }
  suggestTimer = window.setTimeout(() => loadSuggestions(query), 220);
});

function loadSuggestions(query) {
  const gen = ++suggestGen;
  const callback = "ytSuggest_" + Date.now();
  window[callback] = (data) => {
    delete window[callback];
    script.remove();
    if (gen !== suggestGen) return;
    const rows = (data && data[1] ? data[1] : []).slice(0, 6);
    suggest.replaceChildren();
    rows.forEach((row) => {
      const text = Array.isArray(row) ? row[0] : row;
      if (!text) return;
      const item = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = text;
      button.addEventListener("click", () => {
        input.value = text;
        closeSuggestions();
        form.requestSubmit();
      });
      item.appendChild(button);
      suggest.appendChild(item);
    });
    suggest.hidden = suggest.children.length === 0;
  };
  const script = document.createElement("script");
  script.src = "https://suggestqueries.google.com/complete/search?client=youtube-reduced&ds=yt&hl=en&q="
    + encodeURIComponent(query) + "&callback=" + callback;
  script.onerror = () => { suggest.hidden = true; };
  document.body.appendChild(script);
}

document.addEventListener("click", (event) => {
  if (!form.contains(event.target)) suggest.hidden = true;
});
