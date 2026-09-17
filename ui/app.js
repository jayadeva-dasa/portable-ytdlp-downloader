const urlInput = document.getElementById("url");
const isPlaylistCheckbox = document.getElementById("is-playlist");
const outputDirInput = document.getElementById("output-dir");
const browseFolderBtn = document.getElementById("browse-folder");
const clipStartInput = document.getElementById("clip-start");
const clipEndInput = document.getElementById("clip-end");
const clipSizeHint = document.getElementById("clip-size-hint");
const fetchFormatsBtn = document.getElementById("fetch-formats");
const formatsCard = document.getElementById("formats-card");
const videoTitle = document.getElementById("video-title");
const formatSelect = document.getElementById("format");
const downloadBtn = document.getElementById("download");
const progressCard = document.getElementById("progress-card");
const progressView = document.getElementById("progress-view");
const progressFill = document.getElementById("progress-fill");
const progressBar = progressFill.parentElement;
const progressText = document.getElementById("progress-text");
const cancelBtn = document.getElementById("cancel");
const resultView = document.getElementById("result-view");
const resultText = document.getElementById("result-text");
const resultRevealBtn = document.getElementById("result-reveal");
const updateBtn = document.getElementById("update");
const updateOutput = document.getElementById("update-output");
const errorEl = document.getElementById("error");
const themeToggleBtn = document.getElementById("theme-toggle");
const settingsToggleBtn = document.getElementById("settings-toggle");
const settingsPanel = document.getElementById("settings-panel");
const historyList = document.getElementById("history-list");
const clearHistoryBtn = document.getElementById("clear-history");
const emptyState = document.getElementById("empty-state");
const downloadTabBadge = document.getElementById("download-tab-badge");
const tabButtons = document.querySelectorAll(".tab");
const tabPanels = document.querySelectorAll(".tab-panel");

const HISTORY_KEY = "ytdlp-downloader:history";
const THEME_KEY = "ytdlp-downloader:theme";

let currentJobId = null;
let currentEventSource = null;

// ---------- tabs ----------

function switchTab(name) {
  for (const btn of tabButtons) {
    const active = btn.dataset.tab === name;
    btn.classList.toggle("active", active);
    btn.setAttribute("aria-selected", String(active));
  }
  for (const panel of tabPanels) {
    panel.classList.toggle("active", panel.id === `tab-${name}`);
  }
}

for (const btn of tabButtons) {
  btn.addEventListener("click", () => switchTab(btn.dataset.tab));
}

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

// ---------- settings menu ----------

function closeSettingsPanel() {
  settingsPanel.hidden = true;
  settingsToggleBtn.setAttribute("aria-expanded", "false");
}

settingsToggleBtn.addEventListener("click", (event) => {
  event.stopPropagation();
  const willOpen = settingsPanel.hidden;
  settingsPanel.hidden = !willOpen;
  settingsToggleBtn.setAttribute("aria-expanded", String(willOpen));
});

document.addEventListener("click", (event) => {
  if (!settingsPanel.hidden && !event.composedPath().includes(settingsPanel)) {
    closeSettingsPanel();
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !settingsPanel.hidden) closeSettingsPanel();
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
    li.className = "history-item";
    const when = new Date(entry.timestamp).toLocaleString();

    const info = document.createElement("span");
    info.className = "history-info";

    const statusSpan = document.createElement("span");
    statusSpan.className = `status status-${entry.status}`;
    statusSpan.textContent = entry.status;
    info.appendChild(statusSpan);

    // Title/url come from yt-dlp metadata fetched from the target site, so
    // it's untrusted - build the row with text nodes rather than innerHTML
    // to avoid a stored-XSS vector from a malicious video title.
    info.appendChild(document.createTextNode(` ${entry.title || entry.url}`));

    if (entry.clip) {
      const clipSpan = document.createElement("span");
      clipSpan.className = "muted";
      clipSpan.textContent = ` [clip ${entry.clip}]`;
      info.appendChild(clipSpan);
    }

    const whenSpan = document.createElement("span");
    whenSpan.className = "muted";
    whenSpan.textContent = ` (${when})`;
    info.appendChild(whenSpan);

    li.appendChild(info);

    const revealBtn = document.createElement("button");
    revealBtn.type = "button";
    revealBtn.className = "icon-btn history-reveal-btn";
    revealBtn.title = "Show in folder";
    revealBtn.setAttribute("aria-label", "Show in folder");
    revealBtn.textContent = "📁";
    revealBtn.addEventListener("click", () => revealHistoryEntry(entry));
    li.appendChild(revealBtn);

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

// ---------- folder browse + reveal ----------

browseFolderBtn.addEventListener("click", async () => {
  clearError();
  browseFolderBtn.disabled = true;
  try {
    const res = await fetch("/api/browse-folder", { method: "POST" });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || "Failed to open folder browser");
    if (data.path) outputDirInput.value = data.path;
  } catch (err) {
    showError(err.message);
  } finally {
    browseFolderBtn.disabled = false;
  }
});

// Backs each History row's folder icon. Prefers the exact downloaded file
// (entry.filepath); falls back to the chosen output folder (entry.outputDir)
// for jobs that never resolved a specific file (e.g. a playlist run, or one
// that errored/was cancelled before any file was written). Reveals through
// the same /api/reveal endpoint - and so the same OS file-manager command -
// used by the "Browse…" folder picker, so results are always consistent.
async function revealHistoryEntry(entry) {
  clearError();
  const target = entry.filepath || entry.outputDir;
  if (!target) {
    showError("No save location was recorded for this download.");
    return;
  }
  try {
    const res = await fetch("/api/reveal", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: target }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      if (res.status === 404) {
        showError(
          entry.filepath
            ? "That file couldn't be found — it may have been moved, renamed, or deleted."
            : "That folder couldn't be found — it may have been moved or deleted."
        );
      } else {
        showError(data.error || "Failed to open file location");
      }
      return;
    }
  } catch (err) {
    showError(err.message);
  }
}

// Accepts plain seconds ("90"), "MM:SS", or "HH:MM:SS". Returns null for an
// empty/blank field (no clip boundary), the trimmed string if it looks like
// a time, or undefined to signal an invalid value the caller should reject.
function parseClipTime(value) {
  const trimmed = (value || "").trim();
  if (!trimmed) return null;
  return /^\d{1,4}(:\d{1,2}){0,2}$/.test(trimmed) ? trimmed : undefined;
}

// Converts an already-validated parseClipTime() result ("SS", "MM:SS", or
// "HH:MM:SS") to total seconds, for comparing start/end ordering.
function clipTimeToSeconds(value) {
  return value.split(":").reduce((total, part) => total * 60 + Number(part), 0);
}

// Calculator/stopwatch-style duration mask: digits fill in from the right
// (0:02 -> 0:23 -> 2:30 as "2", "3", "0" are typed) so clip-time fields never
// need a manually-typed colon. Up to 6 digits = H(H):MM:SS.
function formatDurationDigits(digits) {
  if (!digits) return "";
  if (digits.length <= 2) return `0:${digits.padStart(2, "0")}`;
  if (digits.length <= 4) return `${digits.slice(0, -2)}:${digits.slice(-2)}`;
  return `${digits.slice(0, -4)}:${digits.slice(-4, -2)}:${digits.slice(-2)}`;
}

const PASSTHROUGH_KEYS = new Set([
  "Tab", "Shift", "Control", "Alt", "Meta", "ArrowLeft", "ArrowRight", "Home", "End", "Enter",
]);

function setupDurationMask(inputEl) {
  let digits = "";

  inputEl.addEventListener("keydown", (event) => {
    if (event.ctrlKey || event.metaKey || event.altKey || PASSTHROUGH_KEYS.has(event.key)) return;
    event.preventDefault();
    if (/^[0-9]$/.test(event.key)) {
      digits = (digits + event.key).slice(-6);
    } else if (event.key === "Backspace" || event.key === "Delete") {
      digits = digits.slice(0, -1);
    } else {
      return;
    }
    inputEl.value = formatDurationDigits(digits);
    updateClipSizeHint();
  });

  inputEl.addEventListener("paste", (event) => {
    event.preventDefault();
    const text = (event.clipboardData || window.clipboardData).getData("text");
    const pasted = text.replace(/\D/g, "").slice(-6);
    if (!pasted) return;
    digits = pasted;
    inputEl.value = formatDurationDigits(digits);
    updateClipSizeHint();
  });
}

// The format dropdown's size ("1440p · 700 MB") is always the *full*
// video's size - fetched once up front, with no idea a clip range exists.
// Without this, a clip finishing in a fraction of the time/size that
// number implies looks broken rather than merely smaller than expected.
function updateClipSizeHint() {
  clipSizeHint.hidden = !clipStartInput.value && !clipEndInput.value;
}

setupDurationMask(clipStartInput);
setupDurationMask(clipEndInput);

function formatSize(bytes) {
  if (!bytes) return "size unknown";
  const mb = bytes / 1024 / 1024;
  if (mb >= 1024) return `${(mb / 1024).toFixed(2)} GB`;
  return `${mb.toFixed(1)} MB`;
}

function isVideoOnly(f) {
  return f.acodec === "none" || !f.acodec;
}

function formatOptionLabel(f) {
  const size = formatSize(f.filesize);
  if (f.height) {
    const fps = f.fps && f.fps > 30 ? `${Math.round(f.fps)}fps` : null;
    const heightPart = fps ? `${f.height}p${fps}` : `${f.height}p`;
    return `${heightPart} · ${size}`;
  }
  if (f.abr) {
    return `${Math.round(f.abr)} kbps · ${size}`;
  }
  return size;
}

function formatOptionValue(f) {
  return isVideoOnly(f) ? `${f.format_id}+bestaudio/best` : f.format_id;
}

// ---------- formats ----------

const MP3_QUALITIES = [
  ["mp3:best", "🎵 MP3 — Best (VBR ~245kbps)"],
  ["mp3:320", "🎵 MP3 — 320 kbps"],
  ["mp3:256", "🎵 MP3 — 256 kbps"],
  ["mp3:192", "🎵 MP3 — 192 kbps"],
  ["mp3:128", "🎵 MP3 — 128 kbps"],
  ["mp3:96", "🎵 MP3 — 96 kbps"],
  ["mp3:64", "🎵 MP3 — 64 kbps (smallest)"],
];

function appendMp3Options(selectEl) {
  const group = document.createElement("optgroup");
  group.label = "Audio only (MP3)";
  for (const [id, label] of MP3_QUALITIES) {
    const opt = document.createElement("option");
    opt.value = id;
    opt.textContent = label;
    group.appendChild(opt);
  }
  selectEl.appendChild(group);
}

function appendFormatGroup(selectEl, label, formats) {
  const group = document.createElement("optgroup");
  group.label = label;
  for (const f of formats) {
    const opt = document.createElement("option");
    opt.value = formatOptionValue(f);
    opt.textContent = formatOptionLabel(f);
    group.appendChild(opt);
  }
  selectEl.appendChild(group);
}

// Buckets every raw yt-dlp format into "Video (<ext>)" / "Audio (<ext>)"
// groups, most-common containers first, so nothing lands in a vague
// catch-all "other" bucket.
function classifyFormats(formats) {
  const isAudioOnly = (f) => f.vcodec === "none" || !f.vcodec || f.resolution === "audio only";
  const video = formats.filter((f) => !isAudioOnly(f));
  const audio = formats.filter(isAudioOnly);

  const groupByExt = (list, extPriority) => {
    const byExt = new Map();
    for (const f of list) {
      const ext = f.ext || "unknown";
      if (!byExt.has(ext)) byExt.set(ext, []);
      byExt.get(ext).push(f);
    }
    const orderedExts = [...byExt.keys()].sort((a, b) => {
      const pa = extPriority.indexOf(a);
      const pb = extPriority.indexOf(b);
      if (pa === -1 && pb === -1) return a.localeCompare(b);
      if (pa === -1) return 1;
      if (pb === -1) return -1;
      return pa - pb;
    });
    return orderedExts.map((ext) => ({ ext, items: byExt.get(ext) }));
  };

  return {
    video: groupByExt(video, ["mp4", "webm"]),
    audio: groupByExt(audio, ["m4a", "webm", "opus"]),
  };
}

function resolutionArea(resolution) {
  const match = /^(\d+)x(\d+)$/.exec(resolution || "");
  return match ? parseInt(match[1], 10) * parseInt(match[2], 10) : 0;
}

// Highest-resolution entry in the highest-priority container group (i.e.
// `groups[0]`, since classifyFormats() already orders groups by priority).
function pickBestFormat(groups) {
  if (!groups.length) return null;
  return groups[0].items.reduce((best, item) =>
    resolutionArea(item.resolution) > resolutionArea(best.resolution) ? item : best
  );
}

fetchFormatsBtn.addEventListener("click", async () => {
  clearError();
  const url = urlInput.value.trim();
  if (!url) {
    showError("Enter a URL first.");
    return;
  }

  fetchFormatsBtn.disabled = true;
  const fetchFormatsLabel = fetchFormatsBtn.textContent;
  fetchFormatsBtn.textContent = "Searching…";
  // Format lookup is its own stage (can take a few seconds on a slow
  // connection or a big playlist) but previously had no visible progress at
  // all beyond this button's own label - show the same progress bar the
  // download flow uses so every in-progress stage actually looks active.
  // Skipped if a download job's progress is already on screen so this
  // doesn't steal or reset it.
  const showedSearchProgress = !currentJobId;
  if (showedSearchProgress) {
    progressCard.hidden = false;
    progressView.hidden = false;
    resultView.hidden = true;
    progressBar.classList.add("indeterminate");
    progressFill.style.removeProperty("width");
    progressText.textContent = "Searching for formats…";
    cancelBtn.hidden = true;
  }
  try {
    const isPlaylist = isPlaylistCheckbox.checked;
    const res = await fetch(
      `/api/formats?url=${encodeURIComponent(url)}${isPlaylist ? "&playlist=1" : ""}`
    );
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || "Failed to fetch formats");

    formatSelect.innerHTML = "";
    appendMp3Options(formatSelect);
    if (data.is_playlist) {
      videoTitle.textContent = `${data.title} (${data.entry_count} videos)`;
      const mp4Group = document.createElement("optgroup");
      mp4Group.label = "Video (MP4)";
      const mp4Opt = document.createElement("option");
      mp4Opt.value = "best_mp4";
      mp4Opt.textContent = "Best (video+audio, MP4)";
      mp4Group.appendChild(mp4Opt);
      formatSelect.appendChild(mp4Group);

      const presetGroup = document.createElement("optgroup");
      presetGroup.label = "Presets";
      for (const [id, label] of [
        ["best", "Best (video+audio, native container)"],
        ["bestvideo", "Best video only"],
        ["bestaudio", "Best audio only"],
        ["worst", "Worst (smallest size)"],
      ]) {
        const opt = document.createElement("option");
        opt.value = id;
        opt.textContent = label;
        presetGroup.appendChild(opt);
      }
      formatSelect.appendChild(presetGroup);

      formatSelect.value = data.is_audio_source ? "mp3:best" : "best_mp4";
    } else {
      videoTitle.textContent = data.title || "";
      const { video, audio } = classifyFormats(data.formats);
      for (const { ext, items } of video) {
        appendFormatGroup(formatSelect, `Video (${ext.toUpperCase()})`, items);
      }
      for (const { ext, items } of audio) {
        appendFormatGroup(formatSelect, `Audio (${ext.toUpperCase()})`, items);
      }

      const best = data.is_audio_source ? null : pickBestFormat(video);
      formatSelect.value = best ? formatOptionValue(best) : "mp3:best";
    }
    formatsCard.hidden = false;
    emptyState.hidden = true;
    switchTab("download");
  } catch (err) {
    showError(err.message);
  } finally {
    fetchFormatsBtn.disabled = false;
    fetchFormatsBtn.textContent = fetchFormatsLabel;
    if (showedSearchProgress) {
      progressCard.hidden = true;
      progressBar.classList.remove("indeterminate");
      cancelBtn.hidden = false;
    }
  }
});

// ---------- download + progress ----------

// Maps a job's backend `status` to what's shown in the progress card/tab
// badge — mainly so post-download ffmpeg steps (trimming a clip, extracting
// MP3, merging separate video+audio streams) read as their own action
// instead of leaving the UI stuck on "downloading — 100%".
const STATUS_LABELS = {
  starting: "Starting",
  downloading: "Downloading",
  clipping: "Clipping",
  converting: "Converting to MP3",
  merging: "Merging",
  finished: "Finished",
  error: "Error",
  cancelled: "Cancelled",
  not_found: "Not found",
};
const TERMINAL_STATUSES = ["finished", "error", "cancelled", "not_found"];

// A finished/failed/cancelled job used to just leave the progress bar frozen
// at 100% with a "Finished" label forever - this swaps the progress card
// over to a compact result view instead, with a reveal-in-folder icon for a
// successful download. Starting a new download (downloadBtn's click
// handler) swaps back to the progress view - there's always exactly one
// view showing in the card, never both stacked.
const RESULT_MESSAGES = {
  finished: "✅ Download finished.",
  cancelled: "⏹️ Download cancelled.",
  not_found: "This download is no longer tracked (the server may have restarted).",
};

function showDownloadResult(job, outputDir) {
  progressView.hidden = true;
  resultView.hidden = false;
  resultText.textContent =
    job.status === "error"
      ? `❌ ${job.error || "Download failed."}`
      : RESULT_MESSAGES[job.status] || STATUS_LABELS[job.status] || job.status;

  const revealTarget = job.status === "finished" && (job.filepath || outputDir);
  resultRevealBtn.hidden = !revealTarget;
  if (revealTarget) {
    resultRevealBtn.onclick = () => revealHistoryEntry({ filepath: job.filepath, outputDir });
  }
}

// Some qualities (confirmed: HLS-only 4K formats) make yt-dlp hand the
// transfer off to ffmpeg directly instead of its usual fragment-by-fragment
// downloader - that path never prints a "[download] NN%" line at all, so
// percent can sit unchanged for minutes even though it's status "downloading"
// the whole time. Rather than special-case that (or any other reason
// progress might stall - a slow network, YouTube throttling, etc.), just
// watch the wall-clock: if percent hasn't moved in a while, switch to the
// same indeterminate animation used for post-processing so it reads as
// "still working" instead of frozen.
const DOWNLOAD_STALL_MS = 4000;
let lastDownloadPercent = null;
let downloadPercentChangedAt = null;

downloadBtn.addEventListener("click", async () => {
  clearError();
  const url = urlInput.value.trim();
  const format_id = formatSelect.value;
  const is_playlist = isPlaylistCheckbox.checked;
  const output_dir = outputDirInput.value.trim();

  const clip_start = parseClipTime(clipStartInput.value);
  const clip_end = parseClipTime(clipEndInput.value);
  if (clip_start === undefined || clip_end === undefined) {
    showError("Clip start/end must look like a time, e.g. 90, 1:30, or 0:01:30.");
    return;
  }
  if (clip_start && clip_end && clipTimeToSeconds(clip_start) >= clipTimeToSeconds(clip_end)) {
    showError("Clip end must be after clip start.");
    return;
  }

  downloadBtn.disabled = true;
  progressCard.hidden = false;
  progressView.hidden = false;
  resultView.hidden = true;
  progressBar.classList.remove("indeterminate");
  progressFill.style.width = "0%";
  progressText.textContent = `${STATUS_LABELS.starting}…`;
  lastDownloadPercent = null;
  downloadPercentChangedAt = null;
  switchTab("download");
  downloadTabBadge.hidden = false;
  downloadTabBadge.textContent = "0%";

  const historyEntry = {
    jobId: null,
    url,
    title: videoTitle.textContent || url,
    status: "starting",
    timestamp: Date.now(),
    clip: clip_start || clip_end ? `${clip_start || "0:00"}–${clip_end || "end"}` : null,
  };

  try {
    const res = await fetch("/api/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, format_id, output_dir, is_playlist, clip_start, clip_end }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || "Failed to start download");

    currentJobId = data.job_id;
    historyEntry.jobId = currentJobId;
    historyEntry.outputDir = data.output_dir;
    addHistoryEntry(historyEntry);

    const source = new EventSource(`/api/progress/${data.job_id}`);
    currentEventSource = source;
    source.onmessage = (event) => {
      const job = JSON.parse(event.data);
      const percent = job.percent || 0;
      const label = STATUS_LABELS[job.status] || job.status;
      const isDownloading = job.status === "downloading";
      const isDone = TERMINAL_STATUSES.includes(job.status);

      // Some formats never emit a "[download] NN%" line at all (yt-dlp hands
      // the transfer to ffmpeg directly for them), so percent can sit
      // unchanged for minutes while still genuinely "downloading". Track how
      // long it's been since percent last moved so that case reads as
      // "working" too, not just frozen.
      let downloadStalled = false;
      if (isDownloading) {
        if (percent !== lastDownloadPercent || downloadPercentChangedAt === null) {
          lastDownloadPercent = percent;
          downloadPercentChangedAt = Date.now();
        }
        downloadStalled = Date.now() - downloadPercentChangedAt > DOWNLOAD_STALL_MS;
      } else {
        lastDownloadPercent = null;
        downloadPercentChangedAt = null;
      }

      // Post-download ffmpeg steps (clipping / converting to MP3 / merging)
      // never emit a "[download] NN%" line either, so holding the last
      // download percent would just sit frozen and then snap to 100% at the
      // very end - reads as stuck rather than working. Same indeterminate
      // sliding-bar animation covers both cases; the CSS animation (not a
      // stale inline width) drives the bar while it's showing.
      const showIndeterminate = (!isDownloading && !isDone) || downloadStalled;
      progressBar.classList.toggle("indeterminate", showIndeterminate);
      if (showIndeterminate) {
        progressFill.style.removeProperty("width");
      } else if (isDownloading || isDone) {
        progressFill.style.width = `${job.status === "finished" ? 100 : percent}%`;
      }

      if (isDownloading) {
        progressText.textContent =
          `${label} — ${percent}%` +
          (job.speed ? ` at ${job.speed}` : "") +
          (job.eta ? ` ETA ${job.eta}` : "") +
          (downloadStalled ? " (waiting for data…)" : "");
        downloadTabBadge.textContent = `${Math.round(percent)}%`;
      } else {
        progressText.textContent = isDone ? label : `${label}…`;
        downloadTabBadge.textContent = label;
      }

      if (job.filepath) {
        updateLastHistoryEntry(data.job_id, { filepath: job.filepath });
      }

      if (TERMINAL_STATUSES.includes(job.status)) {
        source.close();
        currentEventSource = null;
        currentJobId = null;
        downloadBtn.disabled = false;
        downloadTabBadge.hidden = true;
        updateLastHistoryEntry(data.job_id, { status: job.status });
        if (job.status === "error") showError(job.error || "Download failed");
        showDownloadResult(job, data.output_dir);
      }
    };
    source.onerror = () => {
      // EventSource fires "error" for ordinary transient connection drops
      // too (briefly losing the socket, a hiccup in the dev server's
      // polling generator, etc.) and silently retries the same URL on its
      // own - readyState stays CONNECTING for those. Previously this
      // handler treated every error as fatal and force-closed the stream,
      // wiping currentJobId even though the download was still running
      // server-side - Cancel's click handler no-ops on a null
      // currentJobId, so the job became silently un-cancellable (and kept
      // writing to disk) until it finished on its own. Only readyState
      // CLOSED means the browser itself gave up (per spec: a genuinely
      // fatal response - bad status/content-type - not a network blip).
      if (source.readyState === EventSource.CLOSED) {
        showError("Lost connection to the server while downloading. If it was still running, check History once the server is back.");
        currentEventSource = null;
        currentJobId = null;
        downloadBtn.disabled = false;
        downloadTabBadge.hidden = true;
      }
    };
  } catch (err) {
    showError(err.message);
    downloadBtn.disabled = false;
  }
});

cancelBtn.addEventListener("click", async () => {
  if (!currentJobId) return;
  clearError();
  cancelBtn.disabled = true;
  try {
    const res = await fetch(`/api/cancel/${currentJobId}`, { method: "POST" });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || "Failed to cancel");
  } catch (err) {
    showError(err.message);
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
