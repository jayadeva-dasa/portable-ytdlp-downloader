const urlInput = document.getElementById("url");
const isPlaylistCheckbox = document.getElementById("is-playlist");
const outputDirInput = document.getElementById("output-dir");
const fetchFormatsBtn = document.getElementById("fetch-formats");
const formatsCard = document.getElementById("formats-card");
const videoTitle = document.getElementById("video-title");
const formatSelect = document.getElementById("format");
const downloadBtn = document.getElementById("download");
const progressCard = document.getElementById("progress-card");
const progressFill = document.getElementById("progress-fill");
const progressText = document.getElementById("progress-text");
const cancelBtn = document.getElementById("cancel");
const updateBtn = document.getElementById("update");
const updateOutput = document.getElementById("update-output");
const errorEl = document.getElementById("error");
const themeToggleBtn = document.getElementById("theme-toggle");
const historyList = document.getElementById("history-list");
const clearHistoryBtn = document.getElementById("clear-history");

const HISTORY_KEY = "ytdlp-downloader:history";
const THEME_KEY = "ytdlp-downloader:theme";

let currentJobId = null;
let currentEventSource = null;

// ---------- theme ----------

function applyTheme(theme) {
  if (theme) {
    document.documentElement.setAttribute("data-theme", theme);
  } else {
    document.documentElement.removeAttribute("data-theme");
  }
  const isDark =
    theme === "dark" ||
    (!theme && window.matchMedia("(prefers-color-scheme: dark)").matches);
  themeToggleBtn.textContent = isDark ? "☀️" : "🌙";
}

(function initTheme() {
  let saved = null;
  try {
    saved = localStorage.getItem(THEME_KEY);
  } catch (_) {
    // localStorage unavailable (private mode, etc.) — fall back to system theme
  }
  applyTheme(saved);
})();

themeToggleBtn.addEventListener("click", () => {
  const current = document.documentElement.getAttribute("data-theme");
  const systemDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  const currentlyDark = current === "dark" || (!current && systemDark);
  const next = currentlyDark ? "light" : "dark";
  applyTheme(next);
  try {
    localStorage.setItem(THEME_KEY, next);
  } catch (_) {
    // ignore — theme just won't persist across reloads
  }
});

// ---------- history ----------

function loadHistory() {
  try {
    return JSON.parse(localStorage.getItem(HISTORY_KEY)) || [];
  } catch (_) {
    return [];
  }
}

function saveHistory(entries) {
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(entries.slice(0, 50)));
  } catch (_) {
    // ignore — history just won't persist across reloads
  }
}

function renderHistory() {
  const entries = loadHistory();
  historyList.innerHTML = "";
  if (entries.length === 0) {
    const li = document.createElement("li");
    li.className = "muted";
    li.textContent = "No downloads yet.";
    historyList.appendChild(li);
    return;
  }
  for (const entry of entries) {
    const li = document.createElement("li");
    const when = new Date(entry.timestamp).toLocaleString();
    li.innerHTML = `<span class="status status-${entry.status}">${entry.status}</span> ${entry.title || entry.url} <span class="muted">(${when})</span>`;
    historyList.appendChild(li);
  }
}

function addHistoryEntry(entry) {
  const entries = loadHistory();
  entries.unshift(entry);
  saveHistory(entries);
  renderHistory();
}

function updateLastHistoryEntry(jobId, patch) {
  const entries = loadHistory();
  const entry = entries.find((e) => e.jobId === jobId);
  if (entry) {
    Object.assign(entry, patch);
    saveHistory(entries);
    renderHistory();
  }
}

clearHistoryBtn.addEventListener("click", () => {
  saveHistory([]);
  renderHistory();
});

renderHistory();

// ---------- errors ----------

function showError(message) {
  errorEl.textContent = message;
  errorEl.hidden = false;
}

function clearError() {
  errorEl.hidden = true;
  errorEl.textContent = "";
}

function formatSize(bytes) {
  if (!bytes) return "?";
  return `${(bytes / 1024 / 1024).toFixed(1)}MB`;
}

// ---------- formats ----------

fetchFormatsBtn.addEventListener("click", async () => {
  clearError();
  const url = urlInput.value.trim();
  if (!url) {
    showError("Enter a URL first.");
    return;
  }

  fetchFormatsBtn.disabled = true;
  try {
    const isPlaylist = isPlaylistCheckbox.checked;
    const res = await fetch(
      `/api/formats?url=${encodeURIComponent(url)}${isPlaylist ? "&playlist=1" : ""}`
    );
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Failed to fetch formats");

    formatSelect.innerHTML = "";
    if (data.is_playlist) {
      videoTitle.textContent = `${data.title} (${data.entry_count} videos)`;
      for (const [id, label] of [
        ["best", "Best (video+audio)"],
        ["bestvideo", "Best video only"],
        ["bestaudio", "Best audio only"],
        ["worst", "Worst (smallest size)"],
      ]) {
        const opt = document.createElement("option");
        opt.value = id;
        opt.textContent = label;
        formatSelect.appendChild(opt);
      }
    } else {
      videoTitle.textContent = data.title || "";
      for (const f of data.formats) {
        const opt = document.createElement("option");
        opt.value = f.format_id;
        opt.textContent = `${f.format_id} · ${f.ext} · ${f.resolution} · ${formatSize(f.filesize)}`;
        formatSelect.appendChild(opt);
      }
    }
    formatsCard.hidden = false;
  } catch (err) {
    showError(err.message);
  } finally {
    fetchFormatsBtn.disabled = false;
  }
});

// ---------- download + progress ----------

downloadBtn.addEventListener("click", async () => {
  clearError();
  const url = urlInput.value.trim();
  const format_id = formatSelect.value;
  const is_playlist = isPlaylistCheckbox.checked;
  const output_dir = outputDirInput.value.trim();

  downloadBtn.disabled = true;
  progressCard.hidden = false;
  progressFill.style.width = "0%";
  progressText.textContent = "Starting…";

  const historyEntry = {
    jobId: null,
    url,
    title: videoTitle.textContent || url,
    status: "starting",
    timestamp: Date.now(),
  };

  try {
    const res = await fetch("/api/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, format_id, output_dir, is_playlist }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Failed to start download");

    currentJobId = data.job_id;
    historyEntry.jobId = currentJobId;
    addHistoryEntry(historyEntry);

    const source = new EventSource(`/api/progress/${data.job_id}`);
    currentEventSource = source;
    source.onmessage = (event) => {
      const job = JSON.parse(event.data);
      const percent = job.percent || 0;
      progressFill.style.width = `${percent}%`;
      progressText.textContent =
        `${job.status} — ${percent}%` +
        (job.speed ? ` at ${job.speed}` : "") +
        (job.eta ? ` ETA ${job.eta}` : "");

      if (["finished", "error", "cancelled", "not_found"].includes(job.status)) {
        source.close();
        currentEventSource = null;
        currentJobId = null;
        downloadBtn.disabled = false;
        updateLastHistoryEntry(data.job_id, { status: job.status });
        if (job.status === "error") showError(job.error || "Download failed");
      }
    };
    source.onerror = () => {
      source.close();
      currentEventSource = null;
      currentJobId = null;
      downloadBtn.disabled = false;
    };
  } catch (err) {
    showError(err.message);
    downloadBtn.disabled = false;
  }
});

cancelBtn.addEventListener("click", async () => {
  if (!currentJobId) return;
  cancelBtn.disabled = true;
  try {
    await fetch(`/api/cancel/${currentJobId}`, { method: "POST" });
  } finally {
    cancelBtn.disabled = false;
  }
});

// ---------- self-update ----------

updateBtn.addEventListener("click", async () => {
  updateBtn.disabled = true;
  updateOutput.textContent = "Checking…";
  try {
    const res = await fetch("/api/update", { method: "POST" });
    const data = await res.json();
    updateOutput.textContent = data.output || "(no output)";
  } catch (err) {
    updateOutput.textContent = "Update check failed: " + err.message;
  } finally {
    updateBtn.disabled = false;
  }
});
