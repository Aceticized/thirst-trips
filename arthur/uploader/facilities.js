// Talks to the Django backend and works out which building a point is in.

// Load settings from .env (this folder or the parent "arthur" folder). Variables that are
// already set in the terminal take priority.
for (const dir of [__dirname, require("path").join(__dirname, "..")]) {
  const file = require("path").join(dir, ".env");
  if (require("fs").existsSync(file)) process.loadEnvFile(file);
}

// Same read endpoint the home app uses (override with DJANGO_API_URL).
const DJANGO_API_URL =
  process.env.DJANGO_API_URL || "http://127.0.0.1:8000/api/nearby/";

// Where new fountains are POSTed as JSON (override with DJANGO_UPLOAD_URL). This is the
// endpoint from django-patch/upload.py, which assigns the id itself.
const DJANGO_UPLOAD_URL =
  process.env.DJANGO_UPLOAD_URL || DJANGO_API_URL.replace(/nearby\/?$/, "facilities/create/");

// Shared secret that must match UPLOAD_TOKEN on the Django server.
const DJANGO_UPLOAD_TOKEN = process.env.DJANGO_UPLOAD_TOKEN || "";

const OVERPASS_URL = "https://overpass-api.de/api/interpreter";
const USER_AGENT = "fountain-finder-uploader/1.0";
const NEAR_METERS = 40;

const DJANGO_HEADERS = {
  Accept: "application/json",
  "ngrok-skip-browser-warning": "1", // skips ngrok's browser interstitial page
};

function distanceMeters(lat1, lon1, lat2, lon2) {
  const R = 6371000;
  const toRad = (d) => (d * Math.PI) / 180;
  const dp = toRad(lat2 - lat1);
  const dl = toRad(lon2 - lon1);
  const a = Math.sin(dp / 2) ** 2 + Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dl / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(a));
}

// fetch() that says which server it could not reach, and notices a down ngrok tunnel.
async function fetchDjango(url, options) {
  const origin = new URL(url).origin;
  let res;
  try {
    res = await fetch(url, options);
  } catch (err) {
    const reason = err.cause?.code || err.cause?.message || err.message;
    throw new Error(`Could not reach Django at ${origin} (${reason}).`);
  }
  if (res.headers.get("ngrok-error-code")) {
    throw new Error(`The ngrok tunnel for ${origin} is not running.`);
  }
  return res;
}

// Every entry in the database (of any type), sorted nearest-first from lat/lon.
async function listFacilities(lat, lon) {
  const url = new URL(DJANGO_API_URL);
  url.searchParams.set("lat", lat);
  url.searchParams.set("lon", lon);
  const res = await fetchDjango(url, { headers: DJANGO_HEADERS, signal: AbortSignal.timeout(10000) });
  if (!res.ok) throw new Error(`Django API responded with ${res.status}`);
  const body = await res.json();
  return Array.isArray(body) ? body : body.facilities || [];
}

async function overpass(query) {
  try {
    const res = await fetch(OVERPASS_URL, {
      method: "POST",
      headers: { "User-Agent": USER_AGENT },
      body: new URLSearchParams({ data: query }),
      signal: AbortSignal.timeout(15000),
    });
    if (!res.ok) return [];
    return (await res.json()).elements || [];
  } catch {
    return [];
  }
}

const buildingName = (tags = {}) => tags.short_name || tags.name || null;

async function detectBuilding(lat, lon) {
  // 1. A named building outline that contains the point (OpenStreetMap).
  const inside = await overpass(
    `[out:json][timeout:15];is_in(${lat},${lon})->.a;(way(pivot.a)[building];rel(pivot.a)[building];);out tags;`
  );
  for (const el of inside) {
    const name = buildingName(el.tags);
    if (name) return name;
  }

  // 2. A fountain already in the database right next to this spot.
  try {
    for (const f of await listFacilities(lat, lon)) {
      const d = distanceMeters(lat, lon, Number(f.latitude), Number(f.longitude));
      if (d <= NEAR_METERS && f.building) return f.building;
    }
  } catch {
    // fall through
  }

  // 3. The closest named building within a short distance.
  const around = await overpass(
    `[out:json][timeout:15];(way(around:${NEAR_METERS},${lat},${lon})[building][name];` +
      `rel(around:${NEAR_METERS},${lat},${lon})[building][name];);out tags center;`
  );
  let best = null;
  for (const el of around) {
    const c = el.center;
    const name = buildingName(el.tags);
    if (!c || !name) continue;
    const d = distanceMeters(lat, lon, c.lat, c.lon);
    if (!best || d < best.d) best = { name, d };
  }
  return best ? best.name : null;
}

// Sends a new fountain to Django. Django picks the id and returns the saved record.
async function sendToDjango(fountain) {
  const headers = { ...DJANGO_HEADERS, "Content-Type": "application/json" };
  if (DJANGO_UPLOAD_TOKEN) headers["X-Upload-Token"] = DJANGO_UPLOAD_TOKEN;

  const res = await fetchDjango(DJANGO_UPLOAD_URL, {
    method: "POST",
    headers,
    body: JSON.stringify(fountain),
    signal: AbortSignal.timeout(15000),
  });

  if (!res.ok) {
    let detail = "";
    try {
      detail = (await res.json()).error || "";
    } catch {
      // not JSON (e.g. a Django HTML error page)
    }
    if (res.status === 404) {
      throw new Error("The Django server has no upload endpoint yet - add django-patch/upload.py to it.");
    }
    if (res.status === 401 || res.status === 503) {
      throw new Error(detail || "Django refused the upload token - check DJANGO_UPLOAD_TOKEN and UPLOAD_TOKEN.");
    }
    throw new Error(detail || `Django rejected the upload (${res.status}).`);
  }
  return res.json();
}

module.exports = { detectBuilding, sendToDjango };
