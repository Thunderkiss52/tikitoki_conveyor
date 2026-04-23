const API_PREFIX = "/api/v1";

const state = {
  options: null,
  jobs: [],
  selectedJobId: null,
  selectedJob: null,
  currentPlan: null,
  chatMessages: [],
  selectedImages: [],
  selectedReferenceVideo: null,
  selectedLogo: null,
  pollHandle: null,
  sceneTuningOpen: false,
};

const ids = {
  apiStatusChip: document.getElementById("apiStatusChip"),
  assistantStatusChip: document.getElementById("assistantStatusChip"),
  runtimeStatusChip: document.getElementById("runtimeStatusChip"),
  messageBar: document.getElementById("messageBar"),
  refreshButton: document.getElementById("refreshButton"),
  generateNowButton: document.getElementById("generateNowButton"),
  queueJobButton: document.getElementById("queueJobButton"),
  clearImagesButton: document.getElementById("clearImagesButton"),
  clearReferenceButton: document.getElementById("clearReferenceButton"),
  clearLogoButton: document.getElementById("clearLogoButton"),
  imagesUploadInput: document.getElementById("imagesUploadInput"),
  referenceUploadInput: document.getElementById("referenceUploadInput"),
  logoUploadInput: document.getElementById("logoUploadInput"),
  imagesGrid: document.getElementById("imagesGrid"),
  referenceSlot: document.getElementById("referenceSlot"),
  logoSlot: document.getElementById("logoSlot"),
  topicInput: document.getElementById("topicInput"),
  durationInput: document.getElementById("durationInput"),
  aspectInput: document.getElementById("aspectInput"),
  languageInput: document.getElementById("languageInput"),
  platformInput: document.getElementById("platformInput"),
  ctaInput: document.getElementById("ctaInput"),
  resolutionInput: document.getElementById("resolutionInput"),
  titleInput: document.getElementById("titleInput"),
  subtitlesToggle: document.getElementById("subtitlesToggle"),
  voiceoverToggle: document.getElementById("voiceoverToggle"),
  brandOverlayToggle: document.getElementById("brandOverlayToggle"),
  planPromptButton: document.getElementById("planPromptButton"),
  clearChatButton: document.getElementById("clearChatButton"),
  sendPromptButton: document.getElementById("sendPromptButton"),
  chatGenerateButton: document.getElementById("chatGenerateButton"),
  chatLog: document.getElementById("chatLog"),
  chatInput: document.getElementById("chatInput"),
  planSummary: document.getElementById("planSummary"),
  planNotes: document.getElementById("planNotes"),
  jobList: document.getElementById("jobList"),
  selectedJobSummary: document.getElementById("selectedJobSummary"),
  resultVideo: document.getElementById("resultVideo"),
  resultPreview: document.getElementById("resultPreview"),
  resultVoice: document.getElementById("resultVoice"),
  resultMusic: document.getElementById("resultMusic"),
  artifactLinks: document.getElementById("artifactLinks"),
  toggleSceneTuningButton: document.getElementById("toggleSceneTuningButton"),
  sceneTuningPanel: document.getElementById("sceneTuningPanel"),
  sceneTuningList: document.getElementById("sceneTuningList"),
  reviseNowButton: document.getElementById("reviseNowButton"),
  queueRevisionButton: document.getElementById("queueRevisionButton"),
  hideSceneTuningButton: document.getElementById("hideSceneTuningButton"),
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function showMessage(text, tone = "") {
  ids.messageBar.textContent = text;
  ids.messageBar.className = "message-bar";
  if (tone) {
    ids.messageBar.classList.add(`is-${tone}`);
  }
}

async function fetchJson(path, options = {}) {
  const response = await fetch(path, {
    headers: options.body instanceof FormData ? undefined : { "Content-Type": "application/json" },
    ...options,
  });
  const text = await response.text();
  let payload = null;
  try {
    payload = text ? JSON.parse(text) : null;
  } catch (_error) {
    payload = text;
  }
  if (!response.ok) {
    const detail = payload && typeof payload === "object" && payload.detail ? payload.detail : response.statusText;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return payload;
}

function createStorageUrl(path) {
  if (!path) return null;
  if (path.startsWith("/storage/")) return path;
  if (path.startsWith("storage/")) return `/${path}`;
  return null;
}

function setMediaSource(element, path) {
  const url = createStorageUrl(path);
  if (!url) {
    element.classList.add("is-hidden");
    element.removeAttribute("src");
    element.load?.();
    return;
  }
  element.classList.remove("is-hidden");
  element.src = url;
  element.load?.();
}

function jobLabel(status) {
  return String(status || "").replaceAll("_", " ");
}

function formatDate(value) {
  if (!value) return "n/a";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("ru-RU");
}

function setDefaults() {
  if (!state.options) return;
  const defaults = state.options.defaults?.job || {};
  if (!ids.durationInput.value) ids.durationInput.value = String(defaults.duration_sec || 8);
  if (!ids.aspectInput.value) ids.aspectInput.value = defaults.aspect || "9:16";
  if (!ids.languageInput.value) ids.languageInput.value = defaults.language || "ru";
  if (!ids.platformInput.value) ids.platformInput.value = defaults.target_platform || "tiktok";
  ids.subtitlesToggle.checked = Boolean(defaults.subtitles ?? true);
  ids.voiceoverToggle.checked = Boolean(defaults.voiceover ?? true);
  ids.brandOverlayToggle.checked = Boolean(defaults.brand_overlay ?? true);
}

function collectDraftPayload() {
  return {
    topic: ids.topicInput.value.trim() || null,
    cta: ids.ctaInput.value.trim() || null,
    duration_sec: ids.durationInput.value ? Number(ids.durationInput.value) : null,
    language: ids.languageInput.value.trim() || null,
    target_platform: ids.platformInput.value.trim() || null,
    aspect: ids.aspectInput.value || null,
    export_resolution: ids.resolutionInput.value.trim() || null,
    title_override: ids.titleInput.value.trim() || null,
    subtitles: ids.subtitlesToggle.checked,
    voiceover: ids.voiceoverToggle.checked,
    brand_overlay: ids.brandOverlayToggle.checked,
  };
}

function collectCurrentAssetsPayload() {
  return {
    images: state.selectedImages.map((item) => item.path),
    reference_video_path: state.selectedReferenceVideo?.path || null,
    logo_path: state.selectedLogo?.path || null,
  };
}

function collectRevisionAssetsPayload() {
  const promptInputs = state.selectedJob?.config_json?.prompt_inputs || {};
  if (promptInputs.images || promptInputs.reference_video_path || promptInputs.logo_path) {
    return {
      images: Array.isArray(promptInputs.images) ? promptInputs.images : [],
      reference_video_path: promptInputs.reference_video_path || null,
      logo_path: promptInputs.logo_path || null,
    };
  }
  return collectCurrentAssetsPayload();
}

function planForRevision() {
  if (state.selectedJob?.config_json?.prompt_plan) {
    return state.selectedJob.config_json.prompt_plan;
  }
  if (state.currentPlan) return state.currentPlan;
  return null;
}

function applyPlanToForm(plan) {
  if (!plan) return;
  ids.topicInput.value = plan.topic || ids.topicInput.value;
  ids.durationInput.value = String(plan.duration_sec || ids.durationInput.value || 8);
  ids.aspectInput.value = plan.aspect || ids.aspectInput.value || "9:16";
  ids.languageInput.value = plan.language || ids.languageInput.value || "ru";
  ids.platformInput.value = plan.target_platform || ids.platformInput.value || "tiktok";
  ids.ctaInput.value = plan.cta || ids.ctaInput.value;
  ids.resolutionInput.value = plan.export_resolution || ids.resolutionInput.value;
  ids.titleInput.value = plan.title_override || ids.titleInput.value;
  ids.subtitlesToggle.checked = Boolean(plan.subtitles);
  ids.voiceoverToggle.checked = Boolean(plan.voiceover);
  ids.brandOverlayToggle.checked = Boolean(plan.brand_overlay);
}

function renderChat() {
  if (!state.chatMessages.length) {
    ids.chatLog.innerHTML = '<div class="empty-state">Введи промпт обычным языком. Chat разберет его на параметры и подстроит генерацию.</div>';
    return;
  }
  ids.chatLog.innerHTML = state.chatMessages
    .map(
      (message) => `
        <article class="chat-message ${message.role === "assistant" ? "is-assistant" : "is-user"}">
          <div class="chat-role">${escapeHtml(message.role)}</div>
          <div class="chat-body">${escapeHtml(message.content)}</div>
        </article>
      `
    )
    .join("");
  ids.chatLog.scrollTop = ids.chatLog.scrollHeight;
}

function renderSelectedImages() {
  if (!state.selectedImages.length) {
    ids.imagesGrid.innerHTML = '<div class="empty-state">Картинки не загружены.</div>';
    return;
  }
  ids.imagesGrid.innerHTML = state.selectedImages
    .map(
      (item, index) => `
        <article class="asset-card">
          <img class="asset-thumb" src="${escapeHtml(item.url)}" alt="${escapeHtml(item.filename || item.path)}">
          <div class="asset-meta">
            <div class="asset-name">${escapeHtml(item.filename || item.path)}</div>
            <div class="asset-actions">
              <button class="action-button mini-button" type="button" data-remove-image="${index}">
                <span class="button-icon">x</span><span>Remove</span>
              </button>
            </div>
          </div>
        </article>
      `
    )
    .join("");
}

function renderSingleAsset(slot, asset, kind) {
  if (!asset) {
    slot.innerHTML = `<div class="empty-state">${kind === "video" ? "Референс-видео не выбрано." : "Логотип не выбран."}</div>`;
    return;
  }
  const media = kind === "video"
    ? `<video class="single-asset-media" src="${escapeHtml(asset.url)}" muted loop autoplay playsinline></video>`
    : `<img class="single-asset-media" src="${escapeHtml(asset.url)}" alt="${escapeHtml(asset.filename || asset.path)}">`;
  slot.innerHTML = `
    <article class="single-asset-card">
      ${media}
      <div class="single-asset-body">
        <div class="asset-name">${escapeHtml(asset.filename || asset.path)}</div>
      </div>
    </article>
  `;
}

function renderAssets() {
  renderSelectedImages();
  renderSingleAsset(ids.referenceSlot, state.selectedReferenceVideo, "video");
  renderSingleAsset(ids.logoSlot, state.selectedLogo, "logo");
}

function renderPlanSummary() {
  if (!state.currentPlan) {
    ids.planSummary.innerHTML = '<div class="empty-state">Сначала проанализируй промпт. Здесь появятся параметры, которые chat вывел из запроса.</div>';
    ids.planNotes.innerHTML = "";
    return;
  }
  const plan = state.currentPlan;
  const rows = [
    ["Source Mode", plan.source_mode],
    ["Project", plan.project_name],
    ["Template", plan.template],
    ["Visual Style", plan.visual_style],
    ["Voice Style", plan.voice_style],
    ["Music Style", plan.music_style],
    ["Timeline", `${plan.duration_sec}s / ${plan.scene_count} scenes / ${plan.aspect}`],
    ["Parser", plan.parser],
    ["Topic", plan.topic],
    ["Overlay Lines", Array.isArray(plan.overlay_lines) ? plan.overlay_lines.join(" | ") : ""],
    ["Voiceover Lines", Array.isArray(plan.voiceover_lines) ? plan.voiceover_lines.join(" | ") : ""],
  ];
  ids.planSummary.innerHTML = rows
    .map(
      ([label, value]) => `
        <div class="summary-row">
          <div class="summary-label">${escapeHtml(label)}</div>
          <div class="summary-value">${escapeHtml(value || "n/a")}</div>
        </div>
      `
    )
    .join("");
  ids.planNotes.innerHTML = (plan.notes || [])
    .map((note) => `<div class="note-chip">${escapeHtml(note)}</div>`)
    .join("");
}

function renderJobs() {
  if (!state.jobs.length) {
    ids.jobList.innerHTML = '<div class="empty-state">Job list is empty.</div>';
    return;
  }
  ids.jobList.innerHTML = state.jobs
    .map((job) => `
      <button class="job-card ${job.id === state.selectedJobId ? "is-active" : ""}" type="button" data-job-id="${job.id}">
        <div class="job-line"><strong>${escapeHtml(job.topic)}</strong><span>${escapeHtml(jobLabel(job.status))}</span></div>
        <div class="job-line"><span>${escapeHtml(job.mode)}</span><span>${escapeHtml(formatDate(job.created_at))}</span></div>
      </button>
    `)
    .join("");
}

function renderArtifacts(result) {
  const links = [
    ["Final Video", result?.final_video],
    ["Preview", result?.preview_image],
    ["Metadata", result?.metadata_json],
    ["Subtitles", result?.subtitles],
    ["Voice", result?.voiceover_track],
    ["Music", result?.music_track],
  ].filter(([, path]) => createStorageUrl(path));
  if (!links.length) {
    ids.artifactLinks.innerHTML = "";
    return;
  }
  ids.artifactLinks.innerHTML = links
    .map(([label, path]) => `<a class="artifact-link" href="${escapeHtml(createStorageUrl(path))}" target="_blank" rel="noreferrer">${escapeHtml(label)}</a>`)
    .join("");
}

function renderSelectedJob() {
  const job = state.selectedJob;
  if (!job) {
    ids.selectedJobSummary.textContent = "Выбери job, чтобы посмотреть детали.";
    ids.toggleSceneTuningButton.classList.add("is-hidden");
    ids.sceneTuningPanel.classList.add("is-hidden");
    setMediaSource(ids.resultVideo, null);
    setMediaSource(ids.resultPreview, null);
    setMediaSource(ids.resultVoice, null);
    setMediaSource(ids.resultMusic, null);
    ids.artifactLinks.innerHTML = "";
    return;
  }

  ids.selectedJobSummary.innerHTML = `
    <div><strong>${escapeHtml(job.topic)}</strong></div>
    <div class="job-line"><span>Status</span><span>${escapeHtml(jobLabel(job.status))}</span></div>
    <div class="job-line"><span>Mode</span><span>${escapeHtml(job.mode)}</span></div>
    <div class="job-line"><span>Created</span><span>${escapeHtml(formatDate(job.created_at))}</span></div>
  `;

  const result = job.result_json || {};
  setMediaSource(ids.resultVideo, result.final_video);
  setMediaSource(ids.resultPreview, result.preview_image);
  setMediaSource(ids.resultVoice, result.voiceover_track);
  setMediaSource(ids.resultMusic, result.music_track);
  renderArtifacts(result);

  if (job.shots?.length && job.config_json?.prompt_plan) {
    ids.toggleSceneTuningButton.classList.remove("is-hidden");
  } else {
    ids.toggleSceneTuningButton.classList.add("is-hidden");
    ids.sceneTuningPanel.classList.add("is-hidden");
    state.sceneTuningOpen = false;
  }
}

function renderSceneTuning() {
  const job = state.selectedJob;
  if (!state.sceneTuningOpen || !job?.shots?.length) {
    ids.sceneTuningPanel.classList.add("is-hidden");
    return;
  }

  ids.sceneTuningPanel.classList.remove("is-hidden");
  ids.sceneTuningList.innerHTML = job.shots
    .map((shot, index) => {
      const provider = shot.metadata_json?.provider_settings || {};
      const sourceKind = provider.source_kind || (provider.reference_video_path || provider.source_path ? "video" : "generated");
      return `
        <article class="scene-card" data-scene-index="${index}">
          <h3 class="scene-title">Scene ${index + 1}</h3>
          <div class="scene-fields">
            <label class="field">
              <span>Prompt</span>
              <textarea data-field="prompt" rows="4">${escapeHtml(shot.prompt || "")}</textarea>
            </label>
            <label class="field">
              <span>Overlay</span>
              <input data-field="overlay" type="text" value="${escapeHtml(shot.overlay_text || "")}">
            </label>
            <label class="field">
              <span>Duration</span>
              <input data-field="duration_sec" type="number" min="0.5" step="0.1" value="${escapeHtml(shot.duration_sec || 0)}">
            </label>
            <label class="field">
              <span>Source Kind</span>
              <select data-field="source_kind">
                <option value="generated" ${sourceKind === "generated" ? "selected" : ""}>generated</option>
                <option value="video" ${sourceKind === "video" ? "selected" : ""}>video</option>
                <option value="image_to_video" ${sourceKind === "image_to_video" ? "selected" : ""}>image_to_video</option>
                <option value="image" ${sourceKind === "image" ? "selected" : ""}>image</option>
                <option value="brand" ${sourceKind === "brand" ? "selected" : ""}>brand</option>
              </select>
            </label>
            <label class="field">
              <span>Source Path</span>
              <input data-field="source_path" type="text" value="${escapeHtml(provider.source_path || provider.reference_image_path || provider.reference_video_path || "")}">
            </label>
            <label class="field">
              <span>Source Start</span>
              <input data-field="source_start_sec" type="number" min="0" step="0.1" value="${escapeHtml(provider.source_start_sec ?? "")}">
            </label>
            <label class="field">
              <span>Source Duration</span>
              <input data-field="source_duration_sec" type="number" min="0.1" step="0.1" value="${escapeHtml(provider.source_duration_sec ?? "")}">
            </label>
            <label class="field">
              <span>Speed</span>
              <input data-field="speed" type="number" min="0.1" step="0.05" value="${escapeHtml(provider.speed ?? "")}">
            </label>
          </div>
        </article>
      `;
    })
    .join("");
}

function renderStatus() {
  ids.apiStatusChip.textContent = "API: online";
  const assistant = state.options?.prompt_assistant;
  if (!assistant) {
    ids.assistantStatusChip.textContent = "Assistant: ...";
  } else {
    ids.assistantStatusChip.textContent = assistant.configured
      ? `Assistant: OpenAI (${assistant.model})`
      : "Assistant: fallback";
  }
  const runtime = state.options?.runtime;
  ids.runtimeStatusChip.textContent = runtime
    ? `Runtime: text-only -> ${runtime.text_only_video_provider}`
    : "Runtime: ...";
}

async function uploadAsset(file, kind, logoMode = null) {
  const formData = new FormData();
  formData.append("file", file);
  formData.append("kind", kind);
  if (logoMode) formData.append("logo_mode", logoMode);
  return fetchJson(`${API_PREFIX}/ui/assets/upload`, {
    method: "POST",
    body: formData,
  });
}

async function handleImagesUpload(fileList) {
  const files = Array.from(fileList || []);
  if (!files.length) return;
  showMessage("Uploading pictures...");
  for (const file of files) {
    const asset = await uploadAsset(file, "reference");
    state.selectedImages.push(asset);
  }
  renderAssets();
  showMessage("Pictures uploaded.", "success");
}

async function handleReferenceUpload(file) {
  if (!file) return;
  showMessage("Uploading reference video...");
  state.selectedReferenceVideo = await uploadAsset(file, "reference");
  renderAssets();
  showMessage("Reference video uploaded.", "success");
}

async function handleLogoUpload(file) {
  if (!file) return;
  showMessage("Uploading logo...");
  state.selectedLogo = await uploadAsset(file, "logo", "auto_emblem");
  renderAssets();
  showMessage("Logo uploaded.", "success");
}

async function analyzePrompt() {
  const promptText = ids.chatInput.value.trim();
  if (promptText) {
    state.chatMessages.push({ role: "user", content: promptText });
    ids.chatInput.value = "";
  }
  if (!state.chatMessages.length) {
    const fallbackPrompt = ids.topicInput.value.trim();
    if (fallbackPrompt) {
      state.chatMessages.push({ role: "user", content: fallbackPrompt });
    }
  }
  if (!state.chatMessages.length) {
    throw new Error("Добавь prompt в чат или хотя бы Topic.");
  }

  renderChat();
  showMessage("Analyzing prompt...");
  const response = await fetchJson(`${API_PREFIX}/ui/assistant/plan`, {
    method: "POST",
    body: JSON.stringify({
      messages: state.chatMessages,
      assets: collectCurrentAssetsPayload(),
      draft: collectDraftPayload(),
    }),
  });

  state.currentPlan = response.plan;
  applyPlanToForm(response.plan);
  state.chatMessages.push({ role: "assistant", content: response.plan.assistant_reply });
  renderChat();
  renderPlanSummary();
  renderStatus();
  showMessage("Prompt analyzed. Plan updated.", "success");
  return response.plan;
}

async function ensureCurrentPlan() {
  if (ids.chatInput.value.trim() || !state.currentPlan) {
    return analyzePrompt();
  }
  return state.currentPlan;
}

async function generateJob({ enqueue = false, revision = false } = {}) {
  const plan = revision ? planForRevision() : await ensureCurrentPlan();
  if (!plan) {
    throw new Error("Нет активного prompt plan.");
  }

  const payload = {
    plan,
    assets: revision ? collectRevisionAssetsPayload() : collectCurrentAssetsPayload(),
    draft: collectDraftPayload(),
    shot_overrides: revision ? collectSceneOverrides() : [],
    enqueue,
    run_now: !enqueue,
  };

  showMessage(revision ? "Creating revision..." : "Creating job...");
  const response = await fetchJson(`${API_PREFIX}/ui/assistant/generate`, {
    method: "POST",
    body: JSON.stringify(payload),
  });

  state.currentPlan = response.plan;
  await refreshJobs(response.job.id);
  state.selectedJob = response.job;
  state.selectedJobId = response.job.id;
  renderJobs();
  renderSelectedJob();
  renderSceneTuning();
  showMessage(
    revision
      ? `Revision ${enqueue ? "queued" : "completed"}: ${response.job.id}`
      : `Job ${enqueue ? "queued" : "created"}: ${response.job.id}`,
    "success"
  );
}

function collectSceneOverrides() {
  return Array.from(ids.sceneTuningList.querySelectorAll(".scene-card")).map((card, index) => {
    const field = (name) => card.querySelector(`[data-field="${name}"]`);
    const sourceKind = field("source_kind").value || null;
    const sourcePath = field("source_path").value.trim() || null;
    const sourceStart = field("source_start_sec").value.trim();
    const sourceDuration = field("source_duration_sec").value.trim();
    const speed = field("speed").value.trim();
    const isImage = sourceKind === "image_to_video" || sourceKind === "image" || sourceKind === "brand";
    const isVideo = sourceKind === "video";

    return {
      order: index + 1,
      duration_sec: Number(field("duration_sec").value || "0"),
      prompt: field("prompt").value.trim(),
      overlay: field("overlay").value.trim(),
      source_kind: sourceKind,
      source_path: sourcePath,
      reference_image_path: isImage ? sourcePath : null,
      reference_video_path: isVideo ? sourcePath : null,
      source_start_sec: sourceStart ? Number(sourceStart) : null,
      source_duration_sec: sourceDuration ? Number(sourceDuration) : null,
      speed: speed ? Number(speed) : null,
    };
  });
}

async function refreshJobs(preselectId = state.selectedJobId) {
  state.jobs = await fetchJson(`${API_PREFIX}/jobs`);
  renderJobs();
  if (preselectId) {
    await selectJob(preselectId, true);
  } else if (state.jobs[0]) {
    await selectJob(state.jobs[0].id, true);
  } else {
    state.selectedJob = null;
    state.selectedJobId = null;
    renderSelectedJob();
  }
}

async function selectJob(jobId, quiet = false) {
  state.selectedJobId = jobId;
  renderJobs();
  state.selectedJob = await fetchJson(`${API_PREFIX}/jobs/${jobId}`);
  renderSelectedJob();
  renderSceneTuning();
  if (!quiet) {
    showMessage(`Loaded job ${jobId}.`);
  }
}

function startPolling() {
  if (state.pollHandle) window.clearInterval(state.pollHandle);
  state.pollHandle = window.setInterval(async () => {
    const activeStatuses = new Set(["queued", "ingesting", "analyzing", "scripting", "planning", "generating_video", "generating_voice", "generating_music", "composing", "exporting"]);
    if (state.jobs.some((job) => activeStatuses.has(job.status)) || (state.selectedJob && activeStatuses.has(state.selectedJob.status))) {
      try {
        await refreshJobs(state.selectedJobId);
      } catch (_error) {
        // Ignore transient polling failures.
      }
    }
  }, 7000);
}

function bindEvents() {
  ids.refreshButton.addEventListener("click", async () => {
    try {
      showMessage("Refreshing...");
      await bootstrap();
      showMessage("Refreshed.", "success");
    } catch (error) {
      showMessage(error.message, "error");
    }
  });

  ids.imagesUploadInput.addEventListener("change", async (event) => {
    try {
      await handleImagesUpload(event.target.files);
    } catch (error) {
      showMessage(error.message, "error");
    } finally {
      event.target.value = "";
    }
  });

  ids.referenceUploadInput.addEventListener("change", async (event) => {
    try {
      await handleReferenceUpload(event.target.files?.[0]);
    } catch (error) {
      showMessage(error.message, "error");
    } finally {
      event.target.value = "";
    }
  });

  ids.logoUploadInput.addEventListener("change", async (event) => {
    try {
      await handleLogoUpload(event.target.files?.[0]);
    } catch (error) {
      showMessage(error.message, "error");
    } finally {
      event.target.value = "";
    }
  });

  ids.clearImagesButton.addEventListener("click", () => {
    state.selectedImages = [];
    renderAssets();
    showMessage("Pictures cleared.");
  });

  ids.clearReferenceButton.addEventListener("click", () => {
    state.selectedReferenceVideo = null;
    renderAssets();
    showMessage("Reference video cleared.");
  });

  ids.clearLogoButton.addEventListener("click", () => {
    state.selectedLogo = null;
    renderAssets();
    showMessage("Logo cleared.");
  });

  ids.imagesGrid.addEventListener("click", (event) => {
    const button = event.target.closest("[data-remove-image]");
    if (!button) return;
    const index = Number(button.dataset.removeImage);
    if (Number.isFinite(index)) {
      state.selectedImages.splice(index, 1);
      renderAssets();
    }
  });

  ids.planPromptButton.addEventListener("click", async () => {
    try {
      await analyzePrompt();
    } catch (error) {
      showMessage(error.message, "error");
    }
  });

  ids.sendPromptButton.addEventListener("click", async () => {
    try {
      await analyzePrompt();
    } catch (error) {
      showMessage(error.message, "error");
    }
  });

  ids.chatGenerateButton.addEventListener("click", async () => {
    try {
      await generateJob({ enqueue: false, revision: false });
    } catch (error) {
      showMessage(error.message, "error");
    }
  });

  ids.generateNowButton.addEventListener("click", async () => {
    try {
      await generateJob({ enqueue: false, revision: false });
    } catch (error) {
      showMessage(error.message, "error");
    }
  });

  ids.queueJobButton.addEventListener("click", async () => {
    try {
      await generateJob({ enqueue: true, revision: false });
    } catch (error) {
      showMessage(error.message, "error");
    }
  });

  ids.clearChatButton.addEventListener("click", () => {
    state.chatMessages = [];
    state.currentPlan = null;
    renderChat();
    renderPlanSummary();
    showMessage("Chat cleared.");
  });

  ids.jobList.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-job-id]");
    if (!button) return;
    try {
      await selectJob(button.dataset.jobId);
    } catch (error) {
      showMessage(error.message, "error");
    }
  });

  ids.toggleSceneTuningButton.addEventListener("click", () => {
    state.sceneTuningOpen = !state.sceneTuningOpen;
    renderSceneTuning();
  });

  ids.hideSceneTuningButton.addEventListener("click", () => {
    state.sceneTuningOpen = false;
    renderSceneTuning();
  });

  ids.reviseNowButton.addEventListener("click", async () => {
    try {
      await generateJob({ enqueue: false, revision: true });
    } catch (error) {
      showMessage(error.message, "error");
    }
  });

  ids.queueRevisionButton.addEventListener("click", async () => {
    try {
      await generateJob({ enqueue: true, revision: true });
    } catch (error) {
      showMessage(error.message, "error");
    }
  });
}

async function bootstrap() {
  state.options = await fetchJson(`${API_PREFIX}/ui/options`);
  setDefaults();
  renderStatus();
  renderChat();
  renderAssets();
  renderPlanSummary();
  await refreshJobs();
}

async function init() {
  bindEvents();
  try {
    await bootstrap();
    startPolling();
    showMessage("Prompt Studio is ready.", "success");
  } catch (error) {
    showMessage(error.message, "error");
  }
}

init();
