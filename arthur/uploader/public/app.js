const uploadBtn = document.getElementById("upload-btn"); // only used when the live camera can't open
const cameraInput = document.getElementById("camera-input");
const cameraBox = document.getElementById("camera");
const viewfinder = document.getElementById("viewfinder");
const shutter = document.getElementById("shutter");
const statusEl = document.getElementById("status");
const preview = document.getElementById("preview");
const previewImg = document.getElementById("preview-img");
const previewCoords = document.getElementById("preview-coords");
const form = document.getElementById("upload-form");
const buildingInput = document.getElementById("building");
const buildingNote = document.getElementById("building-note");
const floorInput = document.getElementById("floor");
const accessibleInput = document.getElementById("accessible");
const formError = document.getElementById("form-error");
const submitBtn = document.getElementById("submit-btn");
const retakeBtn = document.getElementById("retake-btn");
const results = document.getElementById("results");

const FLOOR_PATTERN = /^[A-Za-z]?\d+$/; // a number, or a letter then a number (e.g. 2, M2)

let contributor = null;
let csrfToken = null;
async function sessionRequest(path, data) {
  csrfToken = (await fetchJson("/api/auth/csrf/")).csrfToken;
  return fetchJson(path, {
    method: "POST", credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken },
    body: JSON.stringify(data),
  });
}
const contributorStatus = document.getElementById("contributor-status");
function setContributor(user) {
  contributor = user;
  contributorStatus.textContent = `Contributing as ${user.username}`;
  document.querySelectorAll("#contributor-login label, #contributor-login button").forEach(el => el.hidden = true);
  updateSubmitState();
}
fetchJson("/api/me/").then(setContributor).catch(() => {});
document.getElementById("contributor-login").addEventListener("submit", async event => {
  event.preventDefault();
  try {
    setContributor(await sessionRequest("/api/auth/login/", {
      username: document.getElementById("contributor-username").value,
      password: document.getElementById("contributor-password").value,
    }));
    document.getElementById("contributor-password").value = "";
    window.dispatchEvent(new Event("achievements:check"));
  } catch (err) { contributorStatus.textContent = err.message; }
});

let locationPromise = null;
let current = null;
let stream = null;

// Picture buttons: grow while held, shrink on release.
function addPressEffect(button) {
  const release = () => button.classList.remove("pressed");
  button.addEventListener("pointerdown", () => button.classList.add("pressed"));
  for (const type of ["pointerup", "pointercancel", "pointerleave", "lostpointercapture"]) {
    button.addEventListener(type, release);
  }
  button.addEventListener("contextmenu", (e) => e.preventDefault());
  return release;
}

function getLocation() {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) {
      reject(new Error("Geolocation is not supported on this device."));
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => resolve({
        lat: pos.coords.latitude.toFixed(7),
        lon: pos.coords.longitude.toFixed(7),
      }),
      (err) => reject(new Error("Could not get location: " + err.message)),
      { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 }
    );
  });
}

function updateSubmitState() {
  const ready =
    contributor && current &&
    current.lat !== null &&
    buildingInput.value.trim() !== "" &&
    FLOOR_PATTERN.test(floorInput.value.trim());
  submitBtn.disabled = !ready;
}

async function fetchJson(url, options) {
  const res = await fetch(url, options);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error || `Request failed (${res.status})`);
  return body;
}

async function lookUpBuilding(lat, lon) {
  buildingInput.value = "";
  buildingInput.readOnly = true;
  buildingNote.textContent = "Detecting building from your location...";
  try {
    const { building } = await fetchJson(`api/building?lat=${lat}&lon=${lon}`);
    if (building) {
      buildingInput.value = building;
      buildingNote.textContent = "Detected from your location.";
      return;
    }
  } catch {
    // fall through to manual entry
  }
  buildingInput.readOnly = false;
  buildingNote.textContent = "Couldn't detect the building - please type it.";
}

// ---------- Camera: opens as soon as the page does ----------

function stopCamera() {
  if (stream) stream.getTracks().forEach((track) => track.stop());
  stream = null;
  viewfinder.srcObject = null;
}

// Browsers only open the system camera app after a tap, so this shows the live camera inside
// the page instead. If that isn't possible, the "Take a photo" button is shown as a fallback.
async function startCamera() {
  stopCamera();
  uploadBtn.hidden = true;
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return useFilePicker();
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: "environment" }, width: { ideal: 1280 }, height: { ideal: 960 } },
      audio: false,
    });
    viewfinder.srcObject = stream;
    cameraBox.hidden = false;
  } catch {
    useFilePicker();
  }
}

function useFilePicker() {
  cameraBox.hidden = true;
  uploadBtn.hidden = false;
  if (!statusEl.textContent) statusEl.textContent = "Couldn't open the camera here. Tap the button to take a photo instead.";
}

async function handlePhoto(blob) {
  stopCamera();
  cameraBox.hidden = true;
  uploadBtn.hidden = true;
  statusEl.textContent = "";

  if (current) URL.revokeObjectURL(current.url);
  current = { url: URL.createObjectURL(blob), lat: null, lon: null };

  previewImg.src = current.url;
  previewCoords.textContent = "Getting location...";
  form.reset();
  formError.textContent = "";
  buildingNote.textContent = "";
  buildingInput.readOnly = true;
  submitBtn.disabled = true;
  preview.hidden = false;

  try {
    const loc = await (locationPromise || getLocation());
    current.lat = loc.lat;
    current.lon = loc.lon;
    previewCoords.textContent = `Lat: ${loc.lat}  Lon: ${loc.lon}`;
  } catch (err) {
    previewCoords.textContent = "";
    statusEl.textContent = err.message + " Try taking the photo again.";
    preview.hidden = true;
    startCamera();
    return;
  }

  await lookUpBuilding(current.lat, current.lon);
  updateSubmitState();
}

shutter.addEventListener("click", () => {
  const width = viewfinder.videoWidth;
  const height = viewfinder.videoHeight;
  if (!width || !height) return; // the camera isn't ready yet

  // Start the location request with the tap so the fix is ready as the photo is processed.
  locationPromise = getLocation();
  locationPromise.catch(() => {});

  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  canvas.getContext("2d").drawImage(viewfinder, 0, 0, width, height);
  canvas.toBlob((blob) => blob && handlePhoto(blob), "image/jpeg", 0.85);
});

uploadBtn.addEventListener("click", () => {
  statusEl.textContent = "";
  locationPromise = getLocation();
  locationPromise.catch(() => {});
  cameraInput.value = "";
  cameraInput.click();
});

cameraInput.addEventListener("change", () => {
  const file = cameraInput.files[0];
  if (file) handlePhoto(file);
});

retakeBtn.addEventListener("click", () => {
  if (current) URL.revokeObjectURL(current.url);
  current = null;
  preview.hidden = true;
  previewImg.removeAttribute("src");
  statusEl.textContent = "";
  startCamera();
});

buildingInput.addEventListener("input", updateSubmitState);
floorInput.addEventListener("input", updateSubmitState);

function addResultCard(item, record) {
  const card = document.createElement("div");
  card.className = "card";

  const img = document.createElement("img");
  img.src = item.url;
  img.alt = "Submitted fountain";

  const title = document.createElement("h3");
  title.textContent = `Fountain #${record.id}`;

  const lines = [
    `Building: ${record.building}`,
    `Floor: ${record.floor}`,
    `Accessible: ${record.accessible ? "Yes" : "No"}`,
  ].map((text) => {
    const p = document.createElement("p");
    p.className = "meta";
    p.textContent = text;
    return p;
  });

  const coords = document.createElement("p");
  coords.className = "coords";
  coords.textContent = `Lat: ${item.lat}  Lon: ${item.lon}`;

  const badge = document.createElement("span");
  badge.className = "badge saved";
  badge.textContent = "Saved to database";

  card.append(img, title, ...lines, coords, badge);
  results.prepend(card);
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!current || current.lat === null || submitBtn.disabled) return;

  formError.textContent = "";
  submitBtn.disabled = true;
  submitBtn.classList.add("busy");

  try {
    const record = await sessionRequest("/api/facilities/discover/", {
        name: "Community fountain", facility_type: "fountain",
        latitude: Number(current.lat),
        longitude: Number(current.lon),
        building: buildingInput.value.trim(),
        floor: floorInput.value.trim(),
        accessible: accessibleInput.checked,
    });

    window.dispatchEvent(new Event("achievements:check"));

    addResultCard(current, record);
    current = null;
    preview.hidden = true;
    previewImg.removeAttribute("src");
    startCamera(); // ready for the next fountain
  } catch (err) {
    formError.textContent = err.message;
    updateSubmitState();
  } finally {
    submitBtn.classList.remove("busy");
  }
});

addPressEffect(shutter);
addPressEffect(submitBtn);

// Back button: shown only when this page is served under the home app (e.g. /uploader/), not on its own at "/".
const backLink = document.getElementById("back-link");
if (location.pathname !== "/") backLink.hidden = false;
const releaseBack = addPressEffect(backLink);
backLink.addEventListener("click", (e) => {
  e.preventDefault();
  releaseBack();
  setTimeout(() => { location.href = backLink.getAttribute("href"); }, 150); // let the shrink show first
});

// Straight to the camera. Asking for location now makes the permission prompt appear right away.
getLocation().catch(() => {});
startCamera();
