const el = (id) => document.getElementById(id);
console.log("✅ app.js loaded: AUTH + BILLING (NO TOP-UP) VERSION");

/* ----------------------------
   Elements
---------------------------- */
const videoEl = el("video");
const clipLenEl = el("clipLen");
const maxClipsEl = el("maxClips");
const goBtn = el("go");
const statusEl = el("status");
const clipsEl = el("clips");

const pv = el("pv");
const cap = el("cap");

const fontSizeEl = el("fontSize");
const wordWindowEl = el("wordWindow");
const colorEl = el("color");
const hiEl = el("hi");
const strokeEl = el("stroke");
const strokeWidthEl = el("strokeWidth");
const posXEl = el("posX");
const posYEl = el("posY");

const dlSrt = el("dlSrt");
const dlJson = el("dlJson");

/* SRT modal */
const srtModal = el("srtModal");
const srtBox = el("srtBox");
const srtStatus = el("srtStatus");
const closeSrtBtn = el("closeSrt");
const cancelSrtBtn = el("cancelSrt");
const saveSrtBtn = el("saveSrt");

/* Palettes */
const textPalette = el("textPalette");
const hiPalette = el("hiPalette");
const strokePalette = el("strokePalette");

/* Crop UI */
const outAspectEl = el("outAspect");
const outResEl = el("outRes");
const cropModeEl = el("cropMode");
const manualCropBox = el("manualCropBox");
const cropXEl = el("cropX");
const cropYEl = el("cropY");
const cropWEl = el("cropW");
const cropHEl = el("cropH");

/* Auth UI */
const authBtn = el("authBtn");
const creditBalanceEl = el("creditBalance");

const authModal = el("authModal");
const authCloseBtn = el("authCloseBtn");
const authTitle = el("authTitle");
const tabLogin = el("tabLogin");
const tabSignup = el("tabSignup");
const authError = el("authError");

const loginForm = el("loginForm");
const loginUsername = el("loginUsername");
const loginPassword = el("loginPassword");

const signupForm = el("signupForm");
const signupEmail = el("signupEmail");
const signupUsername = el("signupUsername");
const signupPassword = el("signupPassword");

const logoutBtn = el("logoutBtn");
const buyCreditsBtn = el("buyCreditsBtn"); // "Manage Plan"

/* Billing modal */
const billingModal = el("billingModal");
const billingCloseBtn = el("billingCloseBtn");
const billingStatus = el("billingStatus");
const billMonthlyBtn = el("billMonthlyBtn");
const billRecurringBtn = el("billRecurringBtn");
const planGrid = el("planGrid");
const planSaveBtn = el("planSaveBtn");

/* ----------------------------
   State
---------------------------- */
let currentJob = null;
let currentIdx = null;
let words = [];
let me = null; // {email, username, credits, plan, billing, next_reset_at}

let authWaitResolve = null;

/* Billing state */
let plansCache = null; // from /api/billing/plans
let billingMode = "monthly"; // "monthly" | "monthly_recurring"
let selectedPlan = null; // "free" | "basic" | "plus" | "pro"

/* ----------------------------
   Utils
---------------------------- */
function esc(s) {
  return String(s || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function setStatus(msg) {
  if (statusEl) statusEl.textContent = msg;
}

function clamp(n, a, b) {
  n = Number(n);
  if (Number.isNaN(n)) return a;
  return Math.max(a, Math.min(b, n));
}

function setCredits(n) {
  if (creditBalanceEl) creditBalanceEl.textContent = String(n ?? 0);
}

function setAuthLabel() {
  if (!authBtn) return;
  if (me?.username) authBtn.textContent = `@${me.username} (Account)`;
  else authBtn.textContent = "Login / Create";
}

function showAuthError(msg) {
  if (!authError) return;
  authError.style.display = "block";
  authError.textContent = msg || "Something went wrong.";
}

function hideAuthError() {
  if (!authError) return;
  authError.style.display = "none";
  authError.textContent = "";
}

function fmtPlanName(key) {
  const map = { free: "Free", basic: "Basic", plus: "Plus", pro: "Pro" };
  return map[key] || key;
}

/* ----------------------------
   API: Auth
---------------------------- */
async function apiMe() {
  const r = await fetch("/api/auth/me");
  if (!r.ok) return null;
  return await r.json();
}

async function apiLogin(username, password) {
  const form = new FormData();
  form.append("username", username);
  form.append("password", password);
  const r = await fetch("/api/auth/login", { method: "POST", body: form });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || "Login failed");
  return data;
}

async function apiSignup(email, username, password) {
  const form = new FormData();
  form.append("email", email);
  form.append("username", username);
  form.append("password", password);
  const r = await fetch("/api/auth/signup", { method: "POST", body: form });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || "Signup failed");
  return data;
}

async function apiLogout() {
  const r = await fetch("/api/auth/logout", { method: "POST" });
  if (!r.ok) return null;
  return await r.json().catch(() => ({}));
}

/* Billing endpoints */
async function apiBillingPlans() {
  const r = await fetch("/api/billing/plans");
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || "Failed to load plans");
  return data;
}

async function apiSetPlan(plan, billing) {
  const form = new FormData();
  form.append("plan", plan);
  form.append("billing", billing);
  const r = await fetch("/api/billing/set_plan", { method: "POST", body: form });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || "Failed to set plan");
  return data; // {ok, plan, billing, credits, next_reset_at}
}

/* ----------------------------
   Auth Modal behavior
---------------------------- */
function openAuthModal(mode = "login") {
  if (!authModal) return;
  hideAuthError();

  authModal.style.display = "grid";

  if (mode === "signup") {
    setTab("signup");
    signupEmail?.focus();
  } else {
    setTab("login");
    loginUsername?.focus();
  }

  // show account actions if logged in
  if (me?.username) {
    logoutBtn.style.display = "inline-flex";
    buyCreditsBtn.style.display = "inline-flex";
  } else {
    logoutBtn.style.display = "none";
    buyCreditsBtn.style.display = "none";
  }
}

function closeAuthModal() {
  if (!authModal) return;
  authModal.style.display = "none";
  hideAuthError();
}

function setTab(which) {
  if (!tabLogin || !tabSignup || !loginForm || !signupForm || !authTitle) return;
  hideAuthError();

  const isLogin = which === "login";
  tabLogin.classList.toggle("active", isLogin);
  tabSignup.classList.toggle("active", !isLogin);

  loginForm.style.display = isLogin ? "flex" : "none";
  signupForm.style.display = isLogin ? "none" : "flex";
  authTitle.textContent = isLogin ? "Login" : "Create Account";
}

tabLogin?.addEventListener("click", () => setTab("login"));
tabSignup?.addEventListener("click", () => setTab("signup"));
authCloseBtn?.addEventListener("click", closeAuthModal);

// click outside card closes
authModal?.addEventListener("mousedown", (e) => {
  if (e.target === authModal) closeAuthModal();
});

/* Top-right button */
authBtn?.addEventListener("click", async () => {
  me = await apiMe();
  if (me?.username) {
    setCredits(me.credits);
    setAuthLabel();
    openAuthModal("login");
  } else {
    openAuthModal("login");
  }
});

logoutBtn?.addEventListener("click", async () => {
  await apiLogout();
  me = null;
  setCredits(0);
  setAuthLabel();
  closeAuthModal();
  setStatus("Logged out.");
});

/* Handle login submit */
loginForm?.addEventListener("submit", async (e) => {
  e.preventDefault();
  hideAuthError();

  const u = (loginUsername?.value || "").trim();
  const p = (loginPassword?.value || "").trim();

  if (!u || !p) return showAuthError("Enter username/email and password.");

  try {
    const data = await apiLogin(u, p);
    me = data;
    setCredits(me.credits);
    setAuthLabel();
    closeAuthModal();
    setStatus("Logged in ✅");

    if (typeof authWaitResolve === "function") {
      authWaitResolve(true);
      authWaitResolve = null;
    }
  } catch (err) {
    showAuthError(err.message || String(err));
  }
});

/* Handle signup submit */
signupForm?.addEventListener("submit", async (e) => {
  e.preventDefault();
  hideAuthError();

  const email = (signupEmail?.value || "").trim();
  const username = (signupUsername?.value || "").trim();
  const password = (signupPassword?.value || "").trim();

  if (!email || !username || !password) return showAuthError("Fill out all fields.");
  if (password.length < 8) return showAuthError("Password must be at least 8 characters.");

  try {
    const data = await apiSignup(email, username, password);
    me = data;
    setCredits(me.credits);
    setAuthLabel();
    closeAuthModal();
    setStatus("Account created ✅");

    if (typeof authWaitResolve === "function") {
      authWaitResolve(true);
      authWaitResolve = null;
    }
  } catch (err) {
    showAuthError(err.message || String(err));
  }
});

/* Used by Generate button */
async function ensureLoggedIn() {
  me = await apiMe();
  if (me?.username) return true;

  openAuthModal("login");
  return await new Promise((resolve) => {
    authWaitResolve = resolve;
  });
}

/* ----------------------------
   Billing modal
---------------------------- */
function openBillingModal() {
  if (!billingModal) return;
  billingModal.style.display = "grid";
  if (billingStatus) billingStatus.textContent = "Loading plans...";
  planSaveBtn.disabled = true;

  // default selections
  billingMode = "monthly";
  selectedPlan = me?.plan || "free";
  updateBillingTabs();
  loadAndRenderPlans().catch((e) => {
    if (billingStatus) billingStatus.textContent = `Failed: ${e.message || e}`;
  });
}

function closeBillingModal() {
  if (!billingModal) return;
  billingModal.style.display = "none";
  if (billingStatus) billingStatus.textContent = "";
}

billingCloseBtn?.addEventListener("click", closeBillingModal);
billingModal?.addEventListener("mousedown", (e) => {
  if (e.target === billingModal) closeBillingModal();
});

function updateBillingTabs() {
  billMonthlyBtn?.classList.toggle("active", billingMode === "monthly");
  billRecurringBtn?.classList.toggle("active", billingMode === "monthly_recurring");
}

billMonthlyBtn?.addEventListener("click", () => {
  billingMode = "monthly";
  updateBillingTabs();
  renderPlans();
});

billRecurringBtn?.addEventListener("click", () => {
  billingMode = "monthly_recurring";
  updateBillingTabs();
  renderPlans();
});

async function loadAndRenderPlans() {
  plansCache = await apiBillingPlans();
  renderPlans();
}

function planCardHtml(planKey, planObj, discountPct) {
  const credits = planObj.monthly_credits;
  const priceMonthly = planObj.price_monthly;
  const priceRecurring = planObj.price_monthly_recurring;

  const price = billingMode === "monthly_recurring" ? priceRecurring : priceMonthly;
  const priceLabel = price === 0 ? "Free" : `$${price}/mo`;

  const subline =
    billingMode === "monthly_recurring" && priceMonthly > 0
      ? `Discounted (−${discountPct}%)`
      : "Standard billing";

  const isActive = selectedPlan === planKey;

  return `
    <button type="button"
      class="tab ${isActive ? "active" : ""}"
      data-plan="${planKey}"
      style="text-align:left;padding:14px;border-radius:16px;display:block;width:100%;">
      <div style="display:flex;justify-content:space-between;align-items:baseline;gap:10px;">
        <div style="font-weight:900;font-size:16px;">${fmtPlanName(planKey)}</div>
        <div style="font-weight:900;">${priceLabel}</div>
      </div>
      <div style="opacity:.8;margin-top:6px;">
        ${credits} credits / month
        <span style="opacity:.7;">• ${subline}</span>
      </div>
      <div style="opacity:.65;font-size:12px;margin-top:6px;">
        1 credit = 1 job. Credits reset monthly to your tier amount.
      </div>
    </button>
  `;
}

function renderPlans() {
  if (!planGrid || !plansCache?.plans) return;

  const discountPct = plansCache.recurring_discount_pct ?? 0;
  const plans = plansCache.plans;

  planGrid.innerHTML = Object.keys(plans)
    .map((k) => planCardHtml(k, plans[k], discountPct))
    .join("");

  [...planGrid.querySelectorAll("[data-plan]")].forEach((btn) => {
    btn.addEventListener("click", () => {
      selectedPlan = btn.dataset.plan;
      renderPlans();
      planSaveBtn.disabled = !selectedPlan;
    });
  });

  if (billingStatus) billingStatus.textContent = "";
  planSaveBtn.disabled = !selectedPlan;
}

planSaveBtn?.addEventListener("click", async () => {
  if (!selectedPlan) return;

  planSaveBtn.disabled = true;
  const old = planSaveBtn.textContent;
  planSaveBtn.textContent = "Saving...";

  try {
    const data = await apiSetPlan(selectedPlan, billingMode);

    // Keep consistent user object for UI
    me = me ? { ...me, ...data } : data;
    if (typeof data.credits !== "undefined") setCredits(data.credits);

    if (billingStatus) billingStatus.textContent = "Saved ✅";
    setStatus(`Plan updated to ${fmtPlanName(data.plan)}.`);
    setTimeout(() => closeBillingModal(), 500);
  } catch (e) {
    if (billingStatus) billingStatus.textContent = `Save failed: ${e.message || e}`;
  } finally {
    planSaveBtn.textContent = old || "Save Plan";
    planSaveBtn.disabled = false;
  }
});

/* Hook Manage Plan button */
buyCreditsBtn?.addEventListener("click", async () => {
  const session = await apiMe();
  if (!session?.ok) {
    alert("Please log in first.");
    return;
  }
  me = session;
  closeAuthModal();
  openBillingModal();
});

/* ----------------------------
   Caption style + karaoke
---------------------------- */
function applyStyle() {
  if (!cap) return;

  cap.style.fontSize = `${clamp(fontSizeEl?.value ?? 35, 18, 120)}px`;
  cap.style.left = `${clamp(posXEl?.value ?? 50, 0, 100)}%`;
  cap.style.top = `${clamp(posYEl?.value ?? 78, 0, 100)}%`;
  cap.style.color = (colorEl?.value || "#ffffff");

  const sw = Math.max(0, Number(strokeWidthEl?.value ?? 2));
  const stroke = strokeEl?.value || "#000000";
  const shadow = [];
  for (let x = -1; x <= 1; x++) {
    for (let y = -1; y <= 1; y++) {
      if (x === 0 && y === 0) continue;
      shadow.push(`${x * sw}px ${y * sw}px 0 ${stroke}`);
    }
  }
  cap.style.textShadow = shadow.join(",");
}

function renderKaraoke(t) {
  if (!cap) return;
  if (!words.length) {
    cap.textContent = "";
    return;
  }

  let idx = words.findIndex(w => t >= w.start && t <= w.end);
  if (idx < 0) {
    for (let i = words.length - 1; i >= 0; i--) {
      if (t >= words[i].end) { idx = i; break; }
    }
  }
  if (idx < 0) idx = 0;

  const windowSize = clamp(wordWindowEl?.value ?? 3, 1, 5);
  const before = Math.floor((windowSize - 1) / 2);
  const after = windowSize - 1 - before;

  let s = Math.max(0, idx - before);
  let e = Math.min(words.length, idx + after + 1);

  const have = e - s;
  if (have < windowSize) {
    const miss = windowSize - have;
    s = Math.max(0, s - miss);
    e = Math.min(words.length, s + windowSize);
  }

  const slice = words.slice(s, e);
  const hi = hiEl?.value || "#ff2a2a";

  cap.innerHTML = slice.map((w, i) => {
    const gi = s + i;
    const safe = esc(w.word);
    if (gi === idx) {
      return `<span style="background:${hi}55;padding:2px 10px;border-radius:10px;">${safe}</span>`;
    }
    return `<span style="opacity:.9">${safe}</span>`;
  }).join(" ");
}

async function loadWords(jobId, idx) {
  const r = await fetch(`/api/jobs/${jobId}/clips/${idx}/words`);
  if (!r.ok) throw new Error("Failed to load words");
  const data = await r.json();
  words = (data.words || []).map(w => ({
    word: w.word,
    start: Number(w.start || 0),
    end: Number(w.end || 0)
  }));
}

/* ----------------------------
   Clip list
---------------------------- */
function clipRow(jobId, c) {
  const thumbSrc = c.thumb ? `/api/jobs/${jobId}/files/${c.thumb}` : "";
  const thumbTag = thumbSrc
    ? `<img class="clipThumb" src="${thumbSrc}" alt="thumb">`
    : `<div class="clipThumb" style="display:grid;place-items:center;opacity:.7;">No thumb</div>`;

  return `
    <div class="clip">
      ${thumbTag}
      <div class="clipMeta">
        <div class="title">Clip #${c.index}</div>
        <div class="sub">${Math.round((c.end - c.start))}s</div>
      </div>
      <div class="clipBtns">
        <button class="pvBtn" data-idx="${c.index}">Preview</button>
        <button class="editBtn" data-idx="${c.index}">Edit</button>
      </div>
    </div>
  `;
}

async function refreshClips(jobId) {
  const r = await fetch(`/api/jobs/${jobId}/clips`);
  if (!r.ok) {
    const d = await r.json().catch(() => ({}));
    setStatus(d.detail || "Failed to load clips.");
    return;
  }
  const data = await r.json();
  const clips = data.clips || [];

  clipsEl.innerHTML = clips.map(c => clipRow(jobId, c)).join("");

  [...clipsEl.querySelectorAll(".pvBtn")].forEach(btn => {
    btn.addEventListener("click", async () => {
      const idx = Number(btn.dataset.idx);
      await previewClip(jobId, idx);
    });
  });

  [...clipsEl.querySelectorAll(".editBtn")].forEach(btn => {
    btn.addEventListener("click", async () => {
      const idx = Number(btn.dataset.idx);
      await openSrtEditor(jobId, idx);
    });
  });
}

/* ----------------------------
   Preview behavior
---------------------------- */
async function previewClip(jobId, idx) {
  currentIdx = idx;

  pv.src = `/api/jobs/${jobId}/clips/${idx}/video`;
  pv.currentTime = 0;
  pv.load();

  dlSrt.href = `/api/jobs/${jobId}/clips/${idx}/captions.srt`;
  dlJson.href = `/api/jobs/${jobId}/clips/${idx}/captions.json`;

  setStatus(`Loading word timings for clip ${idx}...`);
  try {
    await loadWords(jobId, idx);
    applyStyle();
    renderKaraoke(0);
    setStatus(`Previewing clip ${idx}.`);
  } catch (e) {
    console.error(e);
    setStatus(`Previewing clip ${idx} (but word timings failed).`);
    words = [];
    cap.textContent = "";
  }
}

/* ----------------------------
   Captions (SRT) modal
---------------------------- */
function showSrtModal() {
  if (!srtModal) return;
  srtModal.style.display = "grid";
}
function hideSrtModal() {
  if (!srtModal) return;
  srtModal.style.display = "none";
  if (srtStatus) srtStatus.textContent = "";
}

async function fetchSrt(jobId, idx) {
  let r = await fetch(`/api/jobs/${jobId}/clips/${idx}/captions`);
  if (r.ok) return await r.text();
  r = await fetch(`/api/jobs/${jobId}/clips/${idx}/captions.srt`);
  if (r.ok) return await r.text();
  throw new Error("Could not load SRT");
}

async function saveSrt(jobId, idx, srtText) {
  const form = new FormData();
  form.append("srt_text", srtText || "");
  const r = await fetch(`/api/jobs/${jobId}/clips/${idx}/captions`, {
    method: "POST",
    body: form
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    throw new Error(err.detail || "Failed to save captions");
  }
}

async function openSrtEditor(jobId, idx) {
  if (!srtModal || !srtBox) return;
  currentIdx = idx;

  showSrtModal();
  if (srtStatus) srtStatus.textContent = `Loading captions for clip ${idx}...`;
  srtBox.value = "";

  try {
    const srt = await fetchSrt(jobId, idx);
    srtBox.value = srt;
    if (srtStatus) srtStatus.textContent = `Editing captions for clip ${idx}.`;
  } catch (e) {
    console.error(e);
    if (srtStatus) srtStatus.textContent = "Failed to load captions.";
  }
}

closeSrtBtn?.addEventListener("click", hideSrtModal);
cancelSrtBtn?.addEventListener("click", hideSrtModal);

document.addEventListener("mousedown", (e) => {
  if (!srtModal) return;
  if (srtModal.style.display === "grid" && e.target === srtModal) hideSrtModal();
});

saveSrtBtn?.addEventListener("click", async () => {
  if (!currentJob || currentIdx === null || !srtBox) return;
  if (srtStatus) srtStatus.textContent = "Saving captions...";

  saveSrtBtn.disabled = true;
  const oldText = saveSrtBtn.textContent;
  saveSrtBtn.textContent = "Saving...";

  try {
    await saveSrt(currentJob, currentIdx, srtBox.value);
    if (srtStatus) srtStatus.textContent = "Saved ✅";
    try { await loadWords(currentJob, currentIdx); } catch {}
    renderKaraoke(pv.currentTime || 0);
  } catch (e) {
    console.error(e);
    if (srtStatus) srtStatus.textContent = `Save failed: ${e.message || e}`;
  } finally {
    saveSrtBtn.disabled = false;
    saveSrtBtn.textContent = oldText || "Save";
  }
});

/* ----------------------------
   Palettes
---------------------------- */
const DEFAULT_SWATCHES = [
  "#ffffff", "#000000", "#ff2a2a", "#ffd400", "#00e5ff", "#7c4dff",
  "#00ff7a", "#ff6d00", "#ff2bd6", "#bdbdbd"
];

function buildPalette(container, hiddenInput, initial) {
  if (!container || !hiddenInput) return;

  const swatches = DEFAULT_SWATCHES.slice();
  if (initial && !swatches.includes(initial)) swatches.unshift(initial);

  function setActive(hex) {
    hiddenInput.value = hex;
    [...container.querySelectorAll(".swatch")].forEach(s => {
      s.classList.toggle("active", s.dataset.hex === hex);
    });
    applyStyle();
    renderKaraoke(pv.currentTime || 0);
  }

  container.innerHTML = swatches.map(hex =>
    `<div class="swatch" data-hex="${hex}" title="${hex}" style="background:${hex};"></div>`
  ).join("");

  container.addEventListener("click", (e) => {
    const sw = e.target.closest(".swatch");
    if (!sw) return;
    setActive(sw.dataset.hex);
  });

  setActive(initial || hiddenInput.value || swatches[0]);
}

function initPalettes() {
  buildPalette(textPalette, colorEl, colorEl?.value || "#ffffff");
  buildPalette(hiPalette, hiEl, hiEl?.value || "#ff2a2a");
  buildPalette(strokePalette, strokeEl, strokeEl?.value || "#000000");
}

/* ----------------------------
   Crop UI helpers
---------------------------- */
const RES_BY_ASPECT = {
  "9:16": ["1080x1920", "720x1280", "1440x2560"],
  "1:1": ["1080x1080", "720x720"],
  "16:9": ["1920x1080", "1280x720"]
};

function fillResOptions(aspect) {
  if (!outResEl) return;
  const opts = RES_BY_ASPECT[aspect] || RES_BY_ASPECT["9:16"];
  outResEl.innerHTML = opts.map(x => `<option value="${x}">${x}</option>`).join("");
}

function updateManualVisibility() {
  if (!manualCropBox || !cropModeEl) return;
  manualCropBox.style.display = (cropModeEl.value === "manual") ? "block" : "none";
}

outAspectEl?.addEventListener("change", () => fillResOptions(outAspectEl.value));
cropModeEl?.addEventListener("change", updateManualVisibility);

/* ----------------------------
   Job creation
---------------------------- */
goBtn?.addEventListener("click", async () => {
  const ok = await ensureLoggedIn();
  if (!ok) return;

  const f = videoEl.files?.[0];
  if (!f) { alert("Pick an mp4 first."); return; }

  goBtn.disabled = true;
  const old = goBtn.textContent;
  goBtn.textContent = "Generating...";

  setStatus("Uploading...");

  const form = new FormData();
  form.append("video", f);
  form.append("clip_len", clipLenEl.value || "25");
  form.append("max_clips", maxClipsEl.value || "8");

  // crop + output
  const aspect = outAspectEl?.value || "9:16";
  const res = outResEl?.value || "1080x1920";
  const mode = cropModeEl?.value || "center";
  const [wStr, hStr] = res.split("x");

  form.append("out_aspect", aspect);
  form.append("out_w", String(parseInt(wStr, 10) || 0));
  form.append("out_h", String(parseInt(hStr, 10) || 0));
  form.append("crop_mode", mode);
  form.append("crop_x", String(cropXEl?.value ?? 50));
  form.append("crop_y", String(cropYEl?.value ?? 50));
  form.append("crop_w", String(cropWEl?.value ?? 56));
  form.append("crop_h", String(cropHEl?.value ?? 100));

  const r = await fetch("/api/jobs", { method: "POST", body: form });
  const data = await r.json().catch(() => ({}));

  if (!r.ok) {
    alert(data.detail || "Failed");
    goBtn.disabled = false;
    goBtn.textContent = old;
    return;
  }

  currentJob = data.job_id;
  if (typeof data.credits !== "undefined") {
    setCredits(data.credits);
    if (me) me.credits = data.credits;
  }

  setStatus(`Job done. Job ID: ${currentJob}`);
  await refreshClips(currentJob);

  const firstBtn = clipsEl?.querySelector(".pvBtn");
  if (firstBtn) {
    const idx = Number(firstBtn.dataset.idx);
    await previewClip(currentJob, idx);
  }

  goBtn.disabled = false;
  goBtn.textContent = old;
});

/* ----------------------------
   Listeners
---------------------------- */
pv?.addEventListener("timeupdate", () => renderKaraoke(pv.currentTime));

[fontSizeEl, wordWindowEl, strokeWidthEl, posXEl, posYEl].forEach(x => {
  if (!x) return;
  x.addEventListener("input", () => {
    applyStyle();
    renderKaraoke(pv.currentTime || 0);
  });
});

/* ----------------------------
   Init
---------------------------- */
(async function init() {
  applyStyle();
  initPalettes();
  fillResOptions(outAspectEl?.value || "9:16");
  updateManualVisibility();

  me = await apiMe();
  if (me?.username) {
    setCredits(me.credits);
  } else {
    setCredits(0);
  }
  setAuthLabel();
})();
