const uploadBtn = document.getElementById("upload-btn");
const cameraInput = document.getElementById("camera-input");
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
const results = document.getElementById("results");

const FLOOR_PATTERN = /^[A-Za-z]?\d+$/; // a number, or a letter then a number (e.g. 2, M2)

let locationPromise = null;
let current = null;

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
    current &&
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

uploadBtn.addEventListener("click", () => {
  statusEl.textContent = "";
  // Start the location request now (inside the tap) so the permission prompt
  // appears and the fix is ready by the time the photo is taken.
  locationPromise = getLocation();
  locationPromise.catch(() => {});
  cameraInput.value = "";
  cameraInput.click();
});

cameraInput.addEventListener("change", async () => {
  const file = cameraInput.files[0];
  if (!file) return;

  if (current) URL.revokeObjectURL(current.url);
  current = { url: URL.createObjectURL(file), lat: null, lon: null };

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
    statusEl.textContent = err.message + " Tap Upload Fountain to try again.";
    preview.hidden = true;
    return;
  }

  await lookUpBuilding(current.lat, current.lon);
  updateSubmitState();
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
  submitBtn.textContent = "Submitting...";

  try {
    const { record } = await fetchJson("api/upload", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        latitude: Number(current.lat),
        longitude: Number(current.lon),
        building: buildingInput.value.trim(),
        floor: floorInput.value.trim(),
        accessible: accessibleInput.checked,
      }),
    });

    addResultCard(current, record);
    current = null;
    preview.hidden = true;
    previewImg.removeAttribute("src");
  } catch (err) {
    formError.textContent = err.message;
    updateSubmitState();
  } finally {
    submitBtn.textContent = "Submit";
  }
});
