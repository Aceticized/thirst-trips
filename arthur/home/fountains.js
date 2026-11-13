const fs = require("fs");
const path = require("path");

// Django endpoint (override with the DJANGO_API_URL environment variable).
// It needs ?lat=&lon= and returns { facilities: [...] } sorted by distance.
const DJANGO_API_URL =
  process.env.DJANGO_API_URL || "https://partridge-stubble-even.ngrok-free.dev/api/nearby/";

// Set USE_SAMPLE_DATA=1 to use data/sample-fountains.json instead of Django.
const USE_SAMPLE_DATA = process.env.USE_SAMPLE_DATA === "1";

// Only this kind of facility is shown on the map and used by DRINK!.
const FACILITY_TYPE = "fountain";

// Used when the caller has no position (e.g. the desktop map).
const DEFAULT_CENTER = { lat: 53.52, lon: -113.53 };

function normalize(raw, index) {
  const lat = Number(raw.latitude ?? raw.lat);
  const lon = Number(raw.longitude ?? raw.lng ?? raw.lon);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
  if (raw.facility_type && raw.facility_type !== FACILITY_TYPE) return null;

  const id = raw.id ?? index;
  return {
    id,
    name: raw.name || `Fountain ${id}`,
    building: raw.building || "",
    floor: raw.floor != null ? String(raw.floor) : "",
    accessible: raw.accessible,
    lat,
    lon,
  };
}

async function loadFountains(lat = DEFAULT_CENTER.lat, lon = DEFAULT_CENTER.lon) {
  let rows;
  if (USE_SAMPLE_DATA) {
    rows = JSON.parse(fs.readFileSync(path.join(__dirname, "data", "sample-fountains.json"), "utf8"));
  } else {
    const url = new URL(DJANGO_API_URL);
    url.searchParams.set("lat", lat);
    url.searchParams.set("lon", lon);
    const res = await fetch(url, {
      headers: {
        Accept: "application/json",
        "ngrok-skip-browser-warning": "1", // skips ngrok's browser interstitial page
      },
      signal: AbortSignal.timeout(10000),
    });
    if (!res.ok) throw new Error(`Django API responded with ${res.status}`);
    const body = await res.json();
    rows = Array.isArray(body) ? body : body.facilities || [];
  }
  return rows.map(normalize).filter(Boolean);
}

function distanceMeters(lat1, lon1, lat2, lon2) {
  const R = 6371000;
  const toRad = (d) => (d * Math.PI) / 180;
  const dp = toRad(lat2 - lat1);
  const dl = toRad(lon2 - lon1);
  const a = Math.sin(dp / 2) ** 2 + Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dl / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(a));
}

function findNearest(fountains, lat, lon) {
  let best = null;
  for (const f of fountains) {
    const distance = distanceMeters(lat, lon, f.lat, f.lon);
    if (!best || distance < best.distance) best = { ...f, distance };
  }
  return best;
}

const sourceDescription = USE_SAMPLE_DATA ? "sample data (data/sample-fountains.json)" : `Django API ${DJANGO_API_URL}`;

module.exports = { loadFountains, findNearest, sourceDescription };
