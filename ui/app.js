const urlInput = document.getElementById("url");
const fetchFormatsBtn = document.getElementById("fetch-formats");
const formatsCard = document.getElementById("formats-card");
const videoTitle = document.getElementById("video-title");
const formatSelect = document.getElementById("format");
const downloadBtn = document.getElementById("download");
const progressCard = document.getElementById("progress-card");
const progressFill = document.getElementById("progress-fill");
const progressText = document.getElementById("progress-text");
const updateBtn = document.getElementById("update");
const updateOutput = document.getElementById("update-output");
const errorEl = document.getElementById("error");

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

fetchFormatsBtn.addEventListener("click", async () => {
  clearError();
  const url = urlInput.value.trim();
  if (!url) {
    showError("Enter a URL first.");
    return;
  }

  fetchFormatsBtn.disabled = true;
  try {
    const res = await fetch(`/api/formats?url=${encodeURIComponent(url)}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Failed to fetch formats");

    videoTitle.textContent = data.title || "";
    formatSelect.innerHTML = "";
    for (const f of data.formats) {
      const opt = document.createElement("option");
      opt.value = f.format_id;
      opt.textContent = `${f.format_id} · ${f.ext} · ${f.resolution} · ${formatSize(f.filesize)}`;
      formatSelect.appendChild(opt);
    }
    formatsCard.hidden = false;
  } catch (err) {
    showError(err.message);
  } finally {
    fetchFormatsBtn.disabled = false;
  }
});

downloadBtn.addEventListener("click", async () => {
  clearError();
  const url = urlInput.value.trim();
  const format_id = formatSelect.value;

  downloadBtn.disabled = true;
  progressCard.hidden = false;
  progressFill.style.width = "0%";
  progressText.textContent = "Starting…";

  try {
    const res = await fetch("/api/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url, format_id }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Failed to start download");

    const source = new EventSource(`/api/progress/${data.job_id}`);
    source.onmessage = (event) => {
      const job = JSON.parse(event.data);
      const percent = job.percent || 0;
      progressFill.style.width = `${percent}%`;
      progressText.textContent =
        `${job.status} — ${percent}%` +
        (job.speed ? ` at ${job.speed}` : "") +
        (job.eta ? ` ETA ${job.eta}` : "");

      if (["finished", "error", "not_found"].includes(job.status)) {
        source.close();
        downloadBtn.disabled = false;
        if (job.status === "error") showError(job.error || "Download failed");
      }
    };
    source.onerror = () => {
      source.close();
      downloadBtn.disabled = false;
    };
  } catch (err) {
    showError(err.message);
    downloadBtn.disabled = false;
  }
});

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
