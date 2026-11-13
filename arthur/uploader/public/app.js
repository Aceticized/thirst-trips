const uploadBtn = document.getElementById("upload-btn");
const cameraInput = document.getElementById("camera-input");
const statusEl = document.getElementById("status");
const preview = document.getElementById("preview");
const previewImg = document.getElementById("preview-img");
const previewCoords = document.getElementById("preview-coords");
const submitBtn = document.getElementById("submit-btn");
const results = document.getElementById("results");

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
        lat: pos.coords.latitude.toFixed(5),
        lon: pos.coords.longitude.toFixed(5),
      }),
      (err) => reject(new Error("Could not get location: " + err.message)),
      { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 }
    );
  });
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
  submitBtn.disabled = true;
  preview.hidden = false;

  try {
    const loc = await (locationPromise || getLocation());
    current.lat = loc.lat;
    current.lon = loc.lon;
    previewCoords.textContent = `Lat: ${loc.lat}  Lon: ${loc.lon}`;
    submitBtn.disabled = false;
  } catch (err) {
    previewCoords.textContent = "";
    statusEl.textContent = err.message + " Tap Upload Fountain to try again.";
    preview.hidden = true;
  }
});

submitBtn.addEventListener("click", () => {
  if (!current || current.lat === null) return;

  const card = document.createElement("div");
  card.className = "card";

  const img = document.createElement("img");
  img.src = current.url;
  img.alt = "Submitted fountain";

  const coords = document.createElement("p");
  coords.className = "coords";
  coords.textContent = `Lat: ${current.lat}  Lon: ${current.lon}`;

  card.append(img, coords);
  results.prepend(card);

  current = null;
  preview.hidden = true;
  previewImg.removeAttribute("src");
});
