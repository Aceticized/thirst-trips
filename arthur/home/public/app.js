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

// No attribution control: the corner credits (Leaflet, OpenFreeMap) are hidden on purpose.
const map = L.map("map", { zoomSnap: 0.5, attributionControl: false }).setView([53.5461, -113.4938], 12);

// The picture used for every fountain on the map. The drip at the bottom is the exact spot.
const waypointIcon = L.icon({
  iconUrl: "img/waypoint.png?v=1",
  iconSize: [38, 65],
  iconAnchor: [17, 65],
  popupAnchor: [2, -60],
});

// Your own location: the raccoon, whose red arrow tip is the exact spot.
const youIcon = L.icon({
  iconUrl: "img/you.png?v=1",
  iconSize: [56, 60],
  iconAnchor: [29, 59],
});

// The marker of the selected fountain is drawn a bit bigger.
const selectedIcon = L.icon({
  iconUrl: "img/waypoint.png?v=1",
  iconSize: [46, 78],
  iconAnchor: [21, 78],
  popupAnchor: [2, -72],
});

// Set by the mobile code below: called when a fountain is tapped, and when the map is tapped.
let onSelect = null;

// Green-tinted colours for the map layers (everything else keeps the style's own colours).
const GREEN_TINT = {
  background: { "background-color": "#e2eed9" },
  park: { "fill-color": "#c9e3bb" },
  landcover_wood: { "fill-color": "#bcdcae" },
  landuse_residential: { "fill-color": "#dbead2" },
  water: { "fill-color": "#b7dcd6" },
  building: { "fill-color": "#b3d3a9" },
};

// OpenStreetMap-based map without any labels (no names, numbers or icons), tinted green, with
// the building outlines drawn clearly. Falls back to a label-free raster map if it can't load.
async function addBasemap() {
  try {
    const res = await fetch("https://tiles.openfreemap.org/styles/positron");
    const style = await res.json();
    style.layers = style.layers.filter((layer) => layer.type !== "symbol");
    for (const layer of style.layers) {
      if (GREEN_TINT[layer.id]) layer.paint = { ...layer.paint, ...GREEN_TINT[layer.id] };
    }
    style.layers.push({
      id: "building-outline",
      type: "line",
      source: "openmaptiles",
      "source-layer": "building",
      minzoom: 13,
      paint: {
        "line-color": "#5b8a62",
        "line-width": ["interpolate", ["linear"], ["zoom"], 14, 0.4, 19, 1.6],
      },
    });
    L.maplibreGL({ style }).addTo(map);
  } catch {
    L.tileLayer("https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png", {
      maxZoom: 19,
      subdomains: "abcd",
      className: "green-tiles",
    }).addTo(map);
  }
}
addBasemap();

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
      const marker = L.marker([f.lat, f.lon], { icon: waypointIcon }).addTo(map).bindPopup(popup, { autoPan: false });
      marker.on("click", () => onSelect && onSelect(f, marker));
      bounds.push([f.lat, f.lon]);
    }
    countEl.textContent = `${fountains.length} fountain${fountains.length === 1 ? "" : "s"}`;
    if (bounds.length) map.fitBounds(bounds, { padding: [40, 40], maxZoom: 16 });
  } catch (err) {
    countEl.textContent = "Could not load fountains: " + err.message;
    showStatus("Could not load fountains: " + err.message);
  }
}

function showStatus(message, info = false) {
  if (!mobile) return;
  statusEl.textContent = message;
  statusEl.classList.toggle("info", info);
  statusEl.hidden = !message;
}

// Picture buttons: grow while held, shrink on release, and only then do the action.
function makePressable(button, action) {
  const release = () => button.classList.remove("pressed");
  button.addEventListener("pointerdown", () => button.classList.add("pressed"));
  for (const type of ["pointerup", "pointercancel", "pointerleave", "lostpointercapture"]) {
    button.addEventListener(type, release);
  }
  button.addEventListener("contextmenu", (e) => e.preventDefault());
  button.addEventListener("click", (e) => {
    e.preventDefault(); // links wait for the shrink animation too
    release();
    if (button.disabled) return;
    setTimeout(action, 150); // let the shrink animation show first
  });
}

loadFountains();

// ---------- Mobile-only: your location dot, the buttons and fountain selection ----------

if (mobile) {
  const drinkBtn = document.getElementById("drink-btn");
  const uploadBtn = document.getElementById("upload-btn");
  const trophyBtn = document.getElementById("trophy-btn");
  uploadBtn.hidden = false;
  trophyBtn.hidden = false;
  drinkBtn.hidden = false; // it waits below the screen until a fountain is selected

  const ROUTE_DRAW_MS = 700;

  let you = null; // [lat, lon] of the user, once GPS has a fix
  let gpsFailed = false;
  let selected = null; // { fountain, marker } of the fountain that was tapped
  let routeLine = null;
  let routeDone = false; // true once the line reaches the fountain
  let drawFrame = 0;
  let drawToken = 0; // bumped to cancel a line that is still being drawn

  const clearInfoStatus = () => {
    if (statusEl.classList.contains("info")) showStatus("");
  };

  function clearRoute() {
    drawToken++;
    cancelAnimationFrame(drawFrame);
    if (routeLine) routeLine.remove();
    routeLine = null;
    routeDone = false;
  }

  function deselect() {
    if (!selected) return;
    selected.marker.setIcon(waypointIcon);
    selected = null;
    clearRoute();
    drinkBtn.classList.remove("show");
    clearInfoStatus();
  }

  // Draws the dotted line from you to the fountain, then slides DRINK! in.
  function drawRoute() {
    clearRoute();
    drinkBtn.classList.remove("show");
    if (!selected) return;

    if (!you) {
      if (gpsFailed) drinkBtn.classList.add("show"); // no position, so no line: still allow DRINK!
      else showStatus("Finding your location...", true);
      return;
    }
    clearInfoStatus();

    const target = [selected.fountain.lat, selected.fountain.lon];
    routeLine = L.polyline([you, you], {
      className: "route-line",
      color: "#1a8cff",
      weight: 6,
      opacity: 0.95,
      dashArray: "0.1 14",
      lineCap: "round",
      interactive: false,
    }).addTo(map);

    map.fitBounds([you, target], { paddingTopLeft: [50, 180], paddingBottomRight: [50, 240], maxZoom: 18 });

    const token = drawToken;
    const started = performance.now();
    const step = (now) => {
      if (token !== drawToken) return;
      const t = Math.min(1, (now - started) / ROUTE_DRAW_MS);
      const eased = 1 - (1 - t) ** 3;
      const end = [you[0] + (target[0] - you[0]) * eased, you[1] + (target[1] - you[1]) * eased];
      routeLine.setLatLngs([you, end]);
      if (t < 1) {
        drawFrame = requestAnimationFrame(step);
      } else {
        routeDone = true;
        drinkBtn.classList.add("show");
      }
    };
    drawFrame = requestAnimationFrame(step);
  }

  onSelect = (fountain, marker) => {
    if (selected && selected.fountain === fountain) return;
    if (selected) selected.marker.setIcon(waypointIcon);
    selected = { fountain, marker };
    marker.setIcon(selectedIcon);
    drawRoute();
  };
  map.on("click", deselect);

  if (navigator.geolocation) {
    let youMarker = null;
    navigator.geolocation.watchPosition(
      (pos) => {
        you = [pos.coords.latitude, pos.coords.longitude];
        gpsFailed = false;
        if (!youMarker) {
          youMarker = L.marker(you, {
            icon: youIcon,
            interactive: false,
            zIndexOffset: 1000,
          }).addTo(map);
        } else {
          youMarker.setLatLng(you);
        }

        if (selected && !routeLine) drawRoute(); // the fountain was tapped before GPS was ready
        else if (routeDone) routeLine.setLatLngs([you, [selected.fountain.lat, selected.fountain.lon]]);
      },
      () => {
        gpsFailed = true;
        if (selected && !you) drawRoute();
      },
      { enableHighAccuracy: true, maximumAge: 5000 }
    );
  } else {
    gpsFailed = true;
  }

  makePressable(uploadBtn, async () => {
    if (uploadBtn.getAttribute("aria-busy") === "true") return;
    uploadBtn.setAttribute("aria-busy", "true");
    try {
      const response = await fetch("/api/me/", {
        credentials: "same-origin", cache: "no-store",
      });
      if (response.ok) {
        location.href = "/uploader/";
      } else if (response.status === 401) {
        location.href = "/login/?next=%2Fuploader%2F";
      } else {
        showStatus("Could not check your login. Please try again.");
      }
    } catch {
      showStatus("Could not connect. Please try again.");
    } finally {
      uploadBtn.removeAttribute("aria-busy");
    }
  });

  // The account page lives on the Django site. It shows the log-in page first if nobody is logged in.
  makePressable(trophyBtn, () => {
    location.href = trophyBtn.href;
  });

  makePressable(drinkBtn, () => {
    if (!selected) return;
    const { fountain } = selected;
    const target = new URLSearchParams({
      lat: fountain.lat,
      lon: fountain.lon,
      name: fountainLabel(fountain),
      return: "../",
    });
    location.href = `navigator/?${target}`;
  });
}
