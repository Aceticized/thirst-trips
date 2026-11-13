const params = new URLSearchParams(location.search);

function isMobile() {
  const view = params.get("view");
  if (view === "mobile") return true;
  if (view === "desktop") return false;
  const ua = navigator.userAgent;
  // iPadOS pretends to be a Mac, so also check for touch support.
  return /Android|iPhone|iPad|iPod|Mobile/i.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1);
}

const mobile = isMobile();
document.body.classList.add(mobile ? "mobile" : "desktop");

const fmt = (n) => n.toFixed(7);
const fountainLabel = (f) => (f.building ? `${f.name} - ${f.building}` : f.name);
const countEl = document.getElementById("count");
const statusEl = document.getElementById("status");

// ---------- Map with every fountain (desktop and mobile) ----------

const map = L.map("map").setView([53.5461, -113.4938], 12);
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
}).addTo(map);

async function loadFountains() {
  try {
    const res = await fetch("api/fountains");
    const fountains = await res.json();
    if (!res.ok) throw new Error(fountains.error || "Failed to load fountains");

    const bounds = [];
    for (const f of fountains) {
      const popup = document.createElement("div");
      const title = document.createElement("strong");
      title.textContent = fountainLabel(f);
      popup.append(title);
      const details = [];
      if (f.floor) details.push(`Floor ${f.floor}`);
      if (f.accessible === true) details.push("Accessible");
      if (details.length) popup.append(document.createElement("br"), details.join(" \u00B7 "));
      popup.append(document.createElement("br"), `${fmt(f.lat)}, ${fmt(f.lon)}`);
      L.marker([f.lat, f.lon]).addTo(map).bindPopup(popup);
      bounds.push([f.lat, f.lon]);
    }
    countEl.textContent = `${fountains.length} fountain${fountains.length === 1 ? "" : "s"}`;
    if (bounds.length) map.fitBounds(bounds, { padding: [40, 40], maxZoom: 16 });
  } catch (err) {
    countEl.textContent = "Could not load fountains: " + err.message;
    showStatus("Could not load fountains: " + err.message);
  }
}

function showStatus(message) {
  if (!mobile) return;
  statusEl.textContent = message;
  statusEl.hidden = !message;
}

loadFountains();

// ---------- Mobile-only: your location dot and the buttons ----------

if (mobile) {
  const drinkBtn = document.getElementById("drink-btn");
  document.getElementById("upload-btn").hidden = false;
  drinkBtn.hidden = false;

  if (navigator.geolocation) {
    let youMarker = null;
    navigator.geolocation.watchPosition(
      (pos) => {
        const here = [pos.coords.latitude, pos.coords.longitude];
        if (!youMarker) {
          youMarker = L.marker(here, {
            icon: L.divIcon({ className: "", html: '<div class="you-dot"></div>', iconSize: [16, 16], iconAnchor: [8, 8] }),
            interactive: false,
            zIndexOffset: 1000,
          }).addTo(map);
        } else {
          youMarker.setLatLng(here);
        }
      },
      () => {},
      { enableHighAccuracy: true, maximumAge: 5000 }
    );
  }

  drinkBtn.addEventListener("click", () => {
    showStatus("");
    drinkBtn.disabled = true;
    drinkBtn.textContent = "Finding...";

    const reset = (message) => {
      showStatus(message);
      drinkBtn.disabled = false;
      drinkBtn.textContent = "DRINK!";
    };

    if (!navigator.geolocation) return reset("Geolocation is not supported on this device.");

    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        try {
          const { latitude, longitude } = pos.coords;
          const res = await fetch(`api/nearest?lat=${latitude}&lon=${longitude}`);
          const fountain = await res.json();
          if (!res.ok) throw new Error(fountain.error || "Could not find a fountain.");

          const target = new URLSearchParams({
            lat: fountain.lat,
            lon: fountain.lon,
            name: fountainLabel(fountain),
            return: "../",
          });
          location.href = `navigator/?${target}`;
        } catch (err) {
          reset(err.message);
        }
      },
      (err) => reset("Could not get your location: " + err.message),
      { enableHighAccuracy: true, timeout: 20000, maximumAge: 0 }
    );
  });
}
