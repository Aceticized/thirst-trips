// Approximate field of view along the camera's long side, in degrees.
// Tweak this if the waypoint seems to move too fast/slow as you turn
// (a larger number makes the waypoint move less when you turn).
const CAMERA_LONG_SIDE_FOV = 70;
const AXES_SMOOTHING = 0.5;
const EDGE_MARGIN = 44;

// Calibration requirements
const CALIB_UPRIGHT_MS = 6000;   // time spent upright
const CALIB_MOTION_DEG = 150;    // total movement ("figure-8" waving)
const CALIB_MIN_SAMPLES = 20;    // compass readings collected

// After calibration, the compass is only allowed to correct the heading very
// slowly so the waypoint never visibly jumps or "resets".
const TRACK_GAIN = 0.004;
const TRACK_MAX_STEP = 0.02;     // degrees per sensor event

const video = document.getElementById("camera");
const startScreen = document.getElementById("start-screen");
const startBtn = document.getElementById("start-btn");
const statusEl = document.getElementById("status");
const calibEl = document.getElementById("calibration");
const calibFill = document.getElementById("calib-fill");
const calibMsg = document.getElementById("calib-msg");
const calibGps = document.getElementById("calib-gps");
const calibGo = document.getElementById("calib-go");
const arEl = document.getElementById("ar");
const waypointEl = document.getElementById("waypoint");
const wpName = document.getElementById("wp-name");
const wpDistance = document.getElementById("wp-distance");
const edgeArrow = document.getElementById("edge-arrow");
const hudInfo = document.getElementById("hud-info");
const calibValue = document.getElementById("calib-value");

const toRad = (d) => (d * Math.PI) / 180;
const toDeg = (r) => (r * 180) / Math.PI;
const norm360 = (d) => ((d % 360) + 360) % 360;
const wrap180 = (d) => ((d + 540) % 360) - 180;
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];

let waypoint = null;
let phase = "idle";        // idle -> calibrating -> navigating
let position = null;       // smoothed { lat, lon, accuracy }
let declination = 0;       // magnetic -> true north, degrees (east positive)
let manualOffset = Number(localStorage.getItem("compassOffset")) || 0;

let rel = null;            // latest gyro-based orientation { alpha, beta, gamma, t }
let absAlpha = null;       // latest compass-based alpha (Android)
let absTime = 0;
let yawOffset = null;      // slowly-updated: compass alpha minus gyro alpha
let sampleCount = 0;
let axes = null;           // smoothed camera { f, r, u }
let rawForward = null;
let motionDeg = 0;
let uprightMs = 0;
let calibStart = 0;
let rendering = false;

let geoWatchId = null;
let cameraStream = null;
let calibTimer = null;

const params = new URLSearchParams(location.search);

// The home page can pass a destination: ?lat=..&lon=..&name=..&return=<url>
function waypointFromUrl() {
  const lat = parseFloat(params.get("lat"));
  const lon = parseFloat(params.get("lon"));
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
  return { name: params.get("name") || "Fountain", lat, lon };
}

// ---------- Geo math ----------

function distanceAndBearing(lat1, lon1, lat2, lon2) {
  const R = 6371000;
  const p1 = toRad(lat1), p2 = toRad(lat2);
  const dp = p2 - p1, dl = toRad(lon2 - lon1);
  const a = Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
  const distance = 2 * R * Math.asin(Math.sqrt(a));
  const y = Math.sin(dl) * Math.cos(p2);
  const x = Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dl);
  return { distance, bearing: norm360(toDeg(Math.atan2(y, x))) };
}

function formatDistance(m) {
  return m < 1000 ? `${Math.round(m)} m` : `${(m / 1000).toFixed(2)} km`;
}

// ---------- Device orientation ----------

function screenAngle() {
  if (screen.orientation && typeof screen.orientation.angle === "number") return screen.orientation.angle;
  return norm360(window.orientation || 0);
}

// Builds the camera's forward/right/up vectors in a world frame (x=East, y=North, z=Up)
// from the W3C alpha/beta/gamma Euler angles.
function axesFromEuler(alphaDeg, betaDeg, gammaDeg) {
  const a = toRad(alphaDeg), b = toRad(betaDeg), g = toRad(gammaDeg);
  const cZ = Math.cos(a), sZ = Math.sin(a);
  const cX = Math.cos(b), sX = Math.sin(b);
  const cY = Math.cos(g), sY = Math.sin(g);

  const m11 = cY * cZ - sX * sY * sZ;
  const m12 = -cX * sZ;
  const m13 = sY * cZ + sX * cY * sZ;
  const m21 = cY * sZ + sX * sY * cZ;
  const m22 = cX * cZ;
  const m23 = sY * sZ - sX * cY * cZ;
  const m31 = -cX * sY;
  const m32 = sX;
  const m33 = cX * cY;

  // Device axes: x = right of screen, y = top of screen, z = out of screen.
  const x = [m11, m21, m31];
  const y = [m12, m22, m32];
  const f = [-m13, -m23, -m33]; // back camera looks along -z

  // Account for the screen being rotated (landscape).
  const th = toRad(screenAngle());
  const c = Math.cos(th), s = Math.sin(th);
  const r = x.map((v, i) => v * c - y[i] * s);
  const u = x.map((v, i) => v * s + y[i] * c);
  return { f, r, u };
}

function smoothAxes(next) {
  if (!axes) { axes = next; return; }
  const blend = (p, n) => {
    const v = p.map((pv, i) => pv + (n[i] - pv) * AXES_SMOOTHING);
    const len = Math.hypot(...v) || 1;
    return v.map((c) => c / len);
  };
  axes = { f: blend(axes.f, next.f), r: blend(axes.r, next.r), u: blend(axes.u, next.u) };
}

function isUpright() {
  return rel && performance.now() - rel.t < 500 && rel.beta > 45 && rel.beta < 135;
}

// Compass reading expressed as "how far the compass frame is rotated from the
// gyro frame". Returns null when no trustworthy reading is available.
function yawSample(e) {
  if (typeof e.webkitCompassHeading === "number" && e.webkitCompassHeading >= 0) {
    // iOS: only trustworthy when the phone is upright in portrait.
    if (screenAngle() === 0 && e.beta > 70 && e.beta < 110 && Math.abs(e.gamma) < 25) {
      return norm360(360 - e.webkitCompassHeading - e.alpha);
    }
    return null;
  }
  if (e.absolute) return 0; // browser already gives north-referenced angles
  if (absAlpha !== null && performance.now() - absTime < 300) return norm360(absAlpha - e.alpha);
  return null;
}

function updateYawOffset(sample) {
  sampleCount++;
  if (yawOffset === null) { yawOffset = sample; return; }
  const diff = wrap180(sample - yawOffset);
  if (phase === "calibrating") {
    // Fast averaging while the user calibrates.
    yawOffset = norm360(yawOffset + diff * Math.max(0.02, 1 / sampleCount));
  } else {
    // Afterwards: tiny, rate-limited steps so no visible drift or snapping.
    yawOffset = norm360(yawOffset + clamp(diff * TRACK_GAIN, -TRACK_MAX_STEP, TRACK_MAX_STEP));
  }
}

function handleOrientation(e) {
  if (e.alpha == null || e.beta == null || e.gamma == null) return;
  rel = { alpha: e.alpha, beta: e.beta, gamma: e.gamma, t: performance.now() };

  const next = axesFromEuler(e.alpha, e.beta, e.gamma);
  if (rawForward && isUpright()) {
    const step = toDeg(Math.acos(clamp(dot(rawForward, next.f), -1, 1)));
    if (step > 0.3) motionDeg += step;
  }
  rawForward = next.f;
  smoothAxes(next);

  const sample = yawSample(e);
  if (sample !== null) updateYawOffset(sample);
}

function handleAbsolute(e) {
  if (e.alpha == null) return;
  absAlpha = e.alpha;
  absTime = performance.now();
}

function startOrientation() {
  // The plain event is gyro-based (smooth). The absolute event is only used to
  // work out the north offset.
  window.addEventListener("deviceorientation", handleOrientation, true);
  if ("ondeviceorientationabsolute" in window) {
    window.addEventListener("deviceorientationabsolute", handleAbsolute, true);
  }
}

// ---------- Location ----------

function startLocation() {
  geoWatchId = navigator.geolocation.watchPosition(
    (pos) => {
      const fix = { lat: pos.coords.latitude, lon: pos.coords.longitude, accuracy: pos.coords.accuracy };
      if (!position) {
        position = fix;
      } else {
        // Ignore GPS jitter: small moves are blended in slowly, real moves quickly.
        const moved = distanceAndBearing(position.lat, position.lon, fix.lat, fix.lon).distance;
        const gain = moved > Math.max(fix.accuracy * 2, 15) ? 0.6 : 0.12;
        position = {
          lat: position.lat + (fix.lat - position.lat) * gain,
          lon: position.lon + (fix.lon - position.lon) * gain,
          accuracy: fix.accuracy,
        };
      }
      refreshMap();
      if (!startLocation.declinationLoaded) {
        startLocation.declinationLoaded = true;
        fetch(`api/declination?lat=${fix.lat}&lon=${fix.lon}`)
          .then((r) => r.json())
          .then((d) => { if (Number.isFinite(d.declination)) declination = d.declination; })
          .catch(() => { startLocation.declinationLoaded = false; });
      }
    },
    (err) => { calibGps.textContent = "GPS error: " + err.message; hudInfo.textContent = "GPS error: " + err.message; },
    { enableHighAccuracy: true, maximumAge: 0, timeout: 20000 }
  );
}

// ---------- Map ----------

const mapPanel = document.getElementById("map-panel");
const recenterBtn = document.getElementById("recenter");

let map = null;
let userMarker = null;
let wpMarker = null;
let routeLine = null;
let following = true;
let lastConeUpdate = 0;

// The picture used for the waypoint on the map. The drip at the bottom is the exact spot.
const waypointIcon = L.icon({
  iconUrl: "img/waypoint.png?v=1",
  iconSize: [38, 65],
  iconAnchor: [17, 65],
});

// Green-tinted colours for the map layers (everything else keeps the style's own colours).
const GREEN_TINT = {
  background: { "background-color": "#e2eed9" },
  park: { "fill-color": "#c9e3bb" },
  landcover_wood: { "fill-color": "#bcdcae" },
  landuse_residential: { "fill-color": "#dbead2" },
  water: { "fill-color": "#b7dcd6" },
  building: { "fill-color": "#b3d3a9" },
};

// Same map as the home page: OpenStreetMap-based, no labels, tinted green, with the building
// outlines drawn clearly. Falls back to a label-free raster map if it can't load.
async function addBasemap(targetMap) {
  let layer;
  try {
    const res = await fetch("https://tiles.openfreemap.org/styles/positron");
    const style = await res.json();
    style.layers = style.layers.filter((l) => l.type !== "symbol");
    for (const l of style.layers) {
      if (GREEN_TINT[l.id]) l.paint = { ...l.paint, ...GREEN_TINT[l.id] };
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
    layer = L.maplibreGL({ style });
  } catch {
    layer = L.tileLayer("https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png", {
      maxZoom: 19,
      subdomains: "abcd",
      className: "green-tiles",
    });
  }
  if (map === targetMap) layer.addTo(targetMap); // skip if the map was closed meanwhile
}

function initMap() {
  // No attribution control: the corner credits are hidden on purpose.
  map = L.map("map", { zoomControl: false, attributionControl: false, zoomSnap: 0.5 }).setView([waypoint.lat, waypoint.lon], 17);
  addBasemap(map);

  wpMarker = L.marker([waypoint.lat, waypoint.lon], { icon: waypointIcon, interactive: false }).addTo(map);

  userMarker = L.marker([waypoint.lat, waypoint.lon], {
    icon: L.divIcon({
      className: "you-marker",
      html: '<div class="cone"></div><img class="core" src="img/you.png?v=1" alt="" draggable="false">',
      iconSize: [0, 0],
    }),
    opacity: 0,
  }).addTo(map);

  routeLine = L.polyline([], { color: "#168a3c", weight: 4, dashArray: "8 8" }).addTo(map);

  // Stop auto-following as soon as the user moves the map themselves.
  map.getContainer().addEventListener("touchstart", () => {
    following = false;
    recenterBtn.hidden = false;
  }, { passive: true });
  map.getContainer().addEventListener("mousedown", () => {
    following = false;
    recenterBtn.hidden = false;
  });
  recenterBtn.addEventListener("click", () => {
    following = true;
    recenterBtn.hidden = true;
    refreshMap(true);
  });
}

function refreshMap(forceFit) {
  if (!map || !position) return;
  const here = [position.lat, position.lon];
  userMarker.setLatLng(here).setOpacity(1);
  routeLine.setLatLngs([here, [waypoint.lat, waypoint.lon]]);
  if (following || forceFit) {
    // The waypoint picture stands about 65px above its spot, so leave extra room at the top.
    map.fitBounds([here, [waypoint.lat, waypoint.lon]], {
      paddingTopLeft: [40, 80],
      paddingBottomRight: [40, 30],
      maxZoom: 19,
      animate: false,
    });
  }
}

function updateCone(headingDeg) {
  const now = performance.now();
  if (!userMarker || now - lastConeUpdate < 100) return;
  lastConeUpdate = now;
  const cone = userMarker.getElement() && userMarker.getElement().querySelector(".cone");
  if (cone) cone.style.transform = `rotate(${headingDeg}deg)`;
}

// ---------- Calibration ----------

function calibrationTick(dt) {
  if (phase !== "calibrating") return;

  const upright = isUpright();
  if (upright) uprightMs += dt;

  const timeFrac = Math.min(1, uprightMs / CALIB_UPRIGHT_MS);
  const motionFrac = Math.min(1, motionDeg / CALIB_MOTION_DEG);
  const sampleFrac = Math.min(1, sampleCount / CALIB_MIN_SAMPLES);
  const progress = Math.min(timeFrac, motionFrac, sampleFrac);
  calibFill.style.width = `${Math.round(progress * 100)}%`;

  const noCompass = performance.now() - calibStart > 20000 && sampleCount === 0;
  if (noCompass) {
    calibMsg.textContent = "No compass data from this browser. Try Safari (iPhone) or Chrome (Android).";
  } else if (!rel) {
    calibMsg.textContent = "Waiting for motion sensors...";
  } else if (!upright) {
    calibMsg.textContent = "Hold your phone upright, like you're taking a photo.";
  } else if (motionFrac < 1) {
    calibMsg.textContent = "Now wave it in a figure-8.";
  } else if (progress < 1) {
    calibMsg.textContent = "Keep going...";
  } else {
    calibMsg.textContent = "Compass calibrated!";
  }

  if (!position) {
    calibGps.textContent = "Waiting for GPS...";
  } else {
    calibGps.textContent = `GPS locked (\u00B1${Math.round(position.accuracy)} m)`;
  }

  calibGo.disabled = !(progress >= 1 && position && yawOffset !== null);
}

calibGo.addEventListener("click", () => {
  phase = "navigating";
  startSnapshots();
  updateShareUi();
  calibEl.hidden = true;
  document.body.classList.add("navigating");
  arEl.hidden = false;
  mapPanel.hidden = false;
  arriveBtn.hidden = false;
  if (!map) initMap();
  map.invalidateSize();
  refreshMap(true);
  if (!rendering) { rendering = true; render(); }
});

// ---------- Finish ----------

const arriveBtn = document.getElementById("arrive-btn");
const doneScreen = document.getElementById("done-screen");
const doneHome = document.getElementById("done-home");

// "I arrived!": shut everything down (camera, GPS, sensors, map) and show the end screen.
function finish() {
  phase = "done";

  window.removeEventListener("deviceorientation", handleOrientation, true);
  window.removeEventListener("deviceorientationabsolute", handleAbsolute, true);
  if (geoWatchId !== null) navigator.geolocation.clearWatch(geoWatchId);
  if (calibTimer !== null) clearInterval(calibTimer);
  stopSnapshots();
  shareChip.hidden = true;
  if (cameraStream) cameraStream.getTracks().forEach((t) => t.stop());
  video.srcObject = null;
  if (map) { map.remove(); map = null; }

  document.body.classList.remove("navigating");
  arEl.hidden = true;
  mapPanel.hidden = true;
  arriveBtn.hidden = true;
  video.hidden = true;

  const back = params.get("return");
  if (back && new URL(back, location.href).origin === location.origin) {
    doneHome.href = back;
    doneHome.hidden = false;
  }
  doneScreen.hidden = false;
}

// Grows while held, shrinks on release, and only then finishes.
const releaseArrive = () => arriveBtn.classList.remove("pressed");
arriveBtn.addEventListener("pointerdown", () => arriveBtn.classList.add("pressed"));
for (const type of ["pointerup", "pointercancel", "pointerleave", "lostpointercapture"]) {
  arriveBtn.addEventListener(type, releaseArrive);
}
arriveBtn.addEventListener("contextmenu", (e) => e.preventDefault());
arriveBtn.addEventListener("click", () => {
  releaseArrive();
  setTimeout(finish, 150); // let the shrink animation show first
});

// ---------- Rendering ----------

function rotateAzimuth(v, deg) {
  const d = toRad(deg), c = Math.cos(d), s = Math.sin(d);
  return [v[0] * c + v[1] * s, v[1] * c - v[0] * s, v[2]];
}

function render() {
  if (phase === "done") return;
  requestAnimationFrame(render);

  if (!position || !axes || yawOffset === null) {
    waypointEl.style.display = "none";
    edgeArrow.style.display = "none";
    hudInfo.textContent = "Waiting for sensors...";
    return;
  }

  const trueOffset = declination + manualOffset - yawOffset;
  const f = rotateAzimuth(axes.f, trueOffset);
  const r = rotateAzimuth(axes.r, trueOffset);
  const u = rotateAzimuth(axes.u, trueOffset);

  const { distance, bearing } = distanceAndBearing(position.lat, position.lon, waypoint.lat, waypoint.lon);
  const b = toRad(bearing);
  const t = [distance * Math.sin(b), distance * Math.cos(b), 0];

  const xc = dot(t, r);
  const yc = dot(t, u);
  const zc = dot(t, f);

  const W = arEl.clientWidth || window.innerWidth, H = arEl.clientHeight || window.innerHeight;
  const vw = video.videoWidth || W, vh = video.videoHeight || H;
  const scale = Math.max(W / vw, H / vh);
  const focal = (Math.max(vw, vh) / 2 / Math.tan(toRad(CAMERA_LONG_SIDE_FOV) / 2)) * scale;

  const sx = zc > 0 ? W / 2 + (xc / zc) * focal : NaN;
  const sy = zc > 0 ? H / 2 - (yc / zc) * focal : NaN;
  const onScreen = zc > 0 && sx > 0 && sx < W && sy > 0 && sy < H;

  if (onScreen) {
    waypointEl.style.display = "block";
    edgeArrow.style.display = "none";
    waypointEl.style.transform = `translate3d(${sx}px, ${sy}px, 0)`;
  } else {
    waypointEl.style.display = "none";
    let dx, dy;
    if (zc > 0) {
      dx = sx - W / 2;
      dy = sy - H / 2;
    } else {
      dx = Math.abs(xc) < 1e-3 ? 1 : xc;
      dy = 0;
    }
    const tScale = Math.min(
      (W / 2 - EDGE_MARGIN) / (Math.abs(dx) || 1e-6),
      (H / 2 - EDGE_MARGIN) / (Math.abs(dy) || 1e-6)
    );
    const ex = W / 2 + dx * tScale;
    const ey = H / 2 + dy * tScale;
    const rot = toDeg(Math.atan2(dx, -dy));
    edgeArrow.style.display = "block";
    edgeArrow.style.transform = `translate3d(${ex - 18}px, ${ey - 17}px, 0) rotate(${rot}deg)`;
  }

  wpDistance.textContent = formatDistance(distance);

  const heading = norm360(toDeg(Math.atan2(f[0], f[1])));
  latestHeading = heading;
  latestPose = { pitch: toDeg(Math.asin(clamp(f[2], -1, 1))), roll: toDeg(Math.atan2(r[2], u[2])) };
  updateCone(heading);
  hudInfo.innerHTML =
    `${waypoint.name}: ${formatDistance(distance)} @ ${Math.round(bearing)}&deg;<br>` +
    `Facing: ${Math.round(heading)}&deg; &middot; GPS &plusmn;${Math.round(position.accuracy)} m`;
}

// ---------- Sharing snapshots to help map building interiors ----------

// While navigating, and only if the person agreed, a photo from the camera is sent every couple of
// seconds with where and which way it was taken. The server saves each walk in its own folder under
// InteriorDevelopment/Pictures: "<number> <latitude> <longitude> <compass angle>.jpg" plus a .json
// file with the details (time, tilt, GPS accuracy...). InteriorDevelopment/Python reads those.
// 2 seconds keeps neighbouring photos overlapping at walking speed, which 3D reconstruction needs.
const SNAPSHOT_EVERY_MS = 2000;
const SNAPSHOT_MAX_WIDTH = 1280;
const SHARING_KEY = "interiorSharing"; // "yes" or "no"; missing means the person hasn't chosen yet

const shareYes = document.getElementById("share-yes");
const shareNo = document.getElementById("share-no");
const shareChip = document.getElementById("share-chip");
const snapshotCanvas = document.createElement("canvas");

let sharing = localStorage.getItem(SHARING_KEY) === "yes";
let latestHeading = null;   // camera direction in degrees from true north, set every frame
let latestPose = null;      // { pitch, roll } of the camera in degrees, set every frame
let snapshotSession = null; // one id per walk, e.g. "20261114-031542-k3x9"
let snapshotSeq = 0;        // photo number within the walk
let snapshotTimer = null;
let snapshotBusy = false;

function updateShareUi() {
  const choice = localStorage.getItem(SHARING_KEY);
  shareYes.classList.toggle("on", choice === "yes");
  shareNo.classList.toggle("on", choice === "no");
  shareChip.hidden = !(sharing && phase === "navigating");
}

function setSharing(on) {
  sharing = on;
  localStorage.setItem(SHARING_KEY, on ? "yes" : "no");
  if (!on) stopSnapshots();
  updateShareUi();
}

shareYes.addEventListener("click", () => setSharing(true));
shareNo.addEventListener("click", () => setSharing(false));
shareChip.addEventListener("click", () => setSharing(false));

// "20261114-031542-k3x9": the phone's date and time plus 4 random characters. It names the walk's folder.
function makeSessionId() {
  const now = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  const stamp = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
  return `${stamp}-${Math.random().toString(36).slice(2, 6).padEnd(4, "0")}`;
}

async function takeSnapshot() {
  if (!sharing || phase !== "navigating" || snapshotBusy || document.visibilityState !== "visible") return;
  if (!position || latestHeading === null || !latestPose || !video.videoWidth) return;
  snapshotBusy = true;
  try {
    // Remember where, which way and how the camera was held at the moment of the snapshot.
    const where = { lat: position.lat, lon: position.lon, accuracy: position.accuracy };
    const heading = latestHeading, pose = latestPose, takenAt = Date.now();

    const scale = Math.min(1, SNAPSHOT_MAX_WIDTH / video.videoWidth);
    snapshotCanvas.width = Math.round(video.videoWidth * scale);
    snapshotCanvas.height = Math.round(video.videoHeight * scale);
    snapshotCanvas.getContext("2d").drawImage(video, 0, 0, snapshotCanvas.width, snapshotCanvas.height);
    const blob = await new Promise((resolve) => snapshotCanvas.toBlob(resolve, "image/jpeg", 0.8));
    if (!blob) return;

    const query = new URLSearchParams({
      session: snapshotSession,
      seq: String(snapshotSeq++),
      t: String(takenAt),
      lat: where.lat.toFixed(7),
      lon: where.lon.toFixed(7),
      accuracy: where.accuracy.toFixed(1),
      heading: heading.toFixed(1),
      pitch: pose.pitch.toFixed(1),
      roll: pose.roll.toFixed(1),
      declination: declination.toFixed(2),
      offset: String(manualOffset),
      w: String(snapshotCanvas.width),
      h: String(snapshotCanvas.height),
      fov: String(CAMERA_LONG_SIDE_FOV),
    });
    await fetch(`api/snapshot?${query}`, { method: "POST", headers: { "Content-Type": "image/jpeg" }, body: blob });
  } catch {
    // A missed snapshot doesn't matter; the next one is only a couple of seconds away.
  } finally {
    snapshotBusy = false;
  }
}
function startSnapshots() {
  if (snapshotTimer !== null || !sharing) return;
  if (snapshotSession === null) { snapshotSession = makeSessionId(); snapshotSeq = 0; }
  snapshotTimer = setInterval(takeSnapshot, SNAPSHOT_EVERY_MS);
}

function stopSnapshots() {
  if (snapshotTimer !== null) clearInterval(snapshotTimer);
  snapshotTimer = null;
}

updateShareUi();
// ---------- Start-up ----------

function updateCalibLabel() {
  calibValue.textContent = `${manualOffset > 0 ? "+" : ""}${manualOffset}\u00B0`;
}

function nudge(delta) {
  manualOffset += delta;
  localStorage.setItem("compassOffset", String(manualOffset));
  updateCalibLabel();
}

document.getElementById("calib-left").addEventListener("click", () => nudge(-1));
document.getElementById("calib-right").addEventListener("click", () => nudge(1));
updateCalibLabel();

class NeedsTapError extends Error {}

// Starts everything: motion sensors, camera, GPS and the calibration screen. It runs by itself
// when the page opens. fromTap is true when the user pressed the start button, which is
// the only time an iPhone will agree to share its motion sensors.
async function begin(fromTap) {
  statusEl.textContent = "";
  startBtn.disabled = true;

  try {
    if (!window.isSecureContext) {
      throw new Error("This page must be opened over HTTPS for camera, GPS and compass access.");
    }
    if (!navigator.geolocation) throw new Error("Geolocation is not supported on this device.");

    if (typeof DeviceOrientationEvent !== "undefined" &&
        typeof DeviceOrientationEvent.requestPermission === "function") {
      let result;
      try {
        result = await DeviceOrientationEvent.requestPermission();
      } catch (err) {
        // iOS refuses to ask unless the request comes straight from a tap.
        if (!fromTap) throw new NeedsTapError("Tap the button to allow the motion sensors.");
        throw err;
      }
      if (result !== "granted") {
        if (!fromTap) throw new NeedsTapError("Tap the button to allow the motion sensors.");
        throw new Error("Motion & orientation access was denied.");
      }
    }

    const config = await (await fetch("api/config")).json();
    waypoint = waypointFromUrl() || config.waypoint;
    wpName.textContent = waypoint.name;

    const stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: "environment" } },
      audio: false,
    });
    cameraStream = stream;
    video.srcObject = stream;
    await video.play();

    phase = "calibrating";
    calibStart = performance.now();
    startOrientation();
    startLocation();

    startScreen.hidden = true;
    calibEl.hidden = false;

    let last = performance.now();
    calibTimer = setInterval(() => {
      const now = performance.now();
      calibrationTick(now - last);
      last = now;
    }, 100);
  } catch (err) {
    startScreen.hidden = false;
    statusEl.textContent = err.message || String(err);
    startBtn.disabled = false;
  }
}

startBtn.addEventListener("click", () => begin(true));
begin(false);
