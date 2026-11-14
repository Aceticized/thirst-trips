const express = require("express");
const fs = require("fs");
const https = require("https");
const os = require("os");
const path = require("path");
const selfsigned = require("selfsigned");
const geomagnetism = require("geomagnetism");

const PORT = process.env.PORT || 3000;

const WAYPOINT = {
  name: "Fountain",
  lat: 53.5260874,
  lon: -113.5203733,
};

function getLanAddresses() {
  const addresses = [];
  for (const list of Object.values(os.networkInterfaces())) {
    for (const iface of list) {
      if (iface.family === "IPv4" && !iface.internal) addresses.push(iface.address);
    }
  }
  return addresses;
}

// ---------- Interior snapshots ----------
// Photos sent from the navigator (only by people who agreed) are saved here. Every walk gets its own
// folder, and every photo gets a description file next to it:
//   <Pictures>/<session>/0007 <latitude> <longitude> <compass angle>.jpg
//   <Pictures>/<session>/0007 <latitude> <longitude> <compass angle>.json
// The description file is what InteriorDevelopment/Python reads. Override the folder with INTERIOR_PICTURES_DIR.
const PICTURES_DIR = process.env.INTERIOR_PICTURES_DIR || path.join(__dirname, "..", "..", "InteriorDevelopment", "Pictures");
const MAX_SNAPSHOT_BYTES = 2 * 1024 * 1024;
const MAX_FOLDER_BYTES = (Number(process.env.INTERIOR_MAX_MB) || 2000) * 1024 * 1024; // stop saving past this
const SNAPSHOTS_PER_MINUTE = 45;                   // one every 2 seconds is 30, so this leaves room
const SESSION_PATTERN = /^\d{8}-\d{6}-[a-z0-9]{4}$/; // e.g. 20261114-031542-k3x9, made by the phone
const snapshotTimes = new Map();                    // visitor address -> times of their recent snapshots
let folderBytes = null;                             // counted once, then kept up to date

function allowSnapshot(visitor) {
  const now = Date.now();
  const recent = (snapshotTimes.get(visitor) || []).filter((time) => now - time < 60000);
  if (recent.length >= SNAPSHOTS_PER_MINUTE) { snapshotTimes.set(visitor, recent); return false; }
  recent.push(now);
  snapshotTimes.set(visitor, recent);
  if (snapshotTimes.size > 5000) {
    for (const [key, times] of snapshotTimes) if (!times.some((time) => now - time < 60000)) snapshotTimes.delete(key);
  }
  return true;
}

// Adds up the size of every file under the pictures folder (once; after that it is kept up to date).
async function currentFolderBytes() {
  if (folderBytes === null) {
    folderBytes = 0;
    const walk = async (dir) => {
      for (const entry of await fs.promises.readdir(dir, { withFileTypes: true })) {
        const full = path.join(dir, entry.name);
        if (entry.isDirectory()) await walk(full);
        else try { folderBytes += (await fs.promises.stat(full)).size; } catch { /* removed meanwhile */ }
      }
    };
    await walk(PICTURES_DIR);
  }
  return folderBytes;
}

// Reads the numbers sent with a snapshot. Returns null if anything is missing or out of range.
// Everything saved is rebuilt from these numbers; nothing the visitor typed is used in a file name.
function readSnapshotInfo(query) {
  const number = (key) => (query[key] === undefined || query[key] === "" ? NaN : Number(query[key]));
  const info = {
    session: String(query.session || ""),
    seq: number("seq"),
    epochMs: number("t"),
    latitude: number("lat"),
    longitude: number("lon"),
    headingDeg: number("heading"),
    pitchDeg: number("pitch"),
    rollDeg: number("roll"),
    gpsAccuracyM: number("accuracy"),
    declinationDeg: number("declination"),
    compassOffsetDeg: number("offset"),
    imageWidth: number("w"),
    imageHeight: number("h"),
    assumedFovLongSideDeg: number("fov"),
  };
  const within = (value, low, high) => Number.isFinite(value) && value >= low && value <= high;
  const ok =
    SESSION_PATTERN.test(info.session) &&
    Number.isInteger(info.seq) && within(info.seq, 0, 999999) &&
    within(info.epochMs, 1e12, 4e12) &&
    within(info.latitude, -90, 90) && within(info.longitude, -180, 180) &&
    within(info.headingDeg, 0, 360) && within(info.pitchDeg, -90, 90) && within(info.rollDeg, -180, 180) &&
    within(info.gpsAccuracyM, 0, 100000) && within(info.declinationDeg, -180, 180) && within(info.compassOffsetDeg, -360, 360) &&
    within(info.imageWidth, 16, 8192) && within(info.imageHeight, 16, 8192) && within(info.assumedFovLongSideDeg, 10, 170);
  return ok ? info : null;
}

async function saveSnapshot(info, jpeg) {
  const folder = path.join(PICTURES_DIR, info.session);
  await fs.promises.mkdir(folder, { recursive: true });
  const heading = Math.round(info.headingDeg) % 360;
  const stem = `${String(info.seq).padStart(4, "0")} ${info.latitude.toFixed(7)} ${info.longitude.toFixed(7)} ${heading}`;
  const description = {
    version: 1,
    session: info.session,
    seq: info.seq,
    takenAt: new Date(info.epochMs).toISOString(),
    latitude: info.latitude,
    longitude: info.longitude,
    gpsAccuracyM: info.gpsAccuracyM,
    headingDeg: info.headingDeg,            // direction the camera faces, degrees clockwise from true north
    pitchDeg: info.pitchDeg,                // camera tilt: positive looks up, negative looks down
    rollDeg: info.rollDeg,                  // camera roll around its own axis
    magneticDeclinationDeg: info.declinationDeg,
    manualCompassOffsetDeg: info.compassOffsetDeg,
    imageWidth: info.imageWidth,
    imageHeight: info.imageHeight,
    assumedFovLongSideDeg: info.assumedFovLongSideDeg, // a guess, not measured for each phone
  };
  for (let attempt = 1; attempt <= 20; attempt++) {
    const name = attempt === 1 ? stem : `${stem} (${attempt})`;
    try {
      await fs.promises.writeFile(path.join(folder, `${name}.jpg`), jpeg, { flag: "wx" });
      await fs.promises.writeFile(path.join(folder, `${name}.json`), JSON.stringify(description, null, 2), { flag: "wx" });
      folderBytes = (await currentFolderBytes()) + jpeg.length;
      return name;
    } catch (err) {
      if (err.code !== "EEXIST") throw err;
    }
  }
  throw new Error("Too many snapshots with the same name");
}

function buildApp() {
  const app = express();

  app.get("/api/config", (req, res) => res.json({ waypoint: WAYPOINT }));

  app.post("/api/snapshot", express.raw({ type: "image/jpeg", limit: MAX_SNAPSHOT_BYTES }), async (req, res) => {
    const info = readSnapshotInfo(req.query);
    if (!info) return res.status(400).json({ error: "Missing or invalid snapshot details" });
    const jpeg = req.body;
    const looksLikeJpeg = Buffer.isBuffer(jpeg) && jpeg.length > 1000 && jpeg[0] === 0xff && jpeg[1] === 0xd8 && jpeg[2] === 0xff;
    if (!looksLikeJpeg) return res.status(415).json({ error: "A JPEG image is required" });

    const visitor = req.headers["cf-connecting-ip"] || req.ip || "unknown";
    if (!allowSnapshot(String(visitor))) return res.status(429).json({ error: "Too many snapshots" });

    try {
      await fs.promises.mkdir(PICTURES_DIR, { recursive: true });
      if ((await currentFolderBytes()) + jpeg.length > MAX_FOLDER_BYTES) {
        return res.status(507).json({ error: "The snapshot folder is full" });
      }
      await saveSnapshot(info, jpeg);
      res.status(201).json({ saved: true });
    } catch (err) {
      res.status(500).json({ error: "Could not save the snapshot" });
    }
  });

  // Phone compasses report magnetic north; this gives the correction to true north.
  app.get("/api/declination", (req, res) => {
    const lat = parseFloat(req.query.lat);
    const lon = parseFloat(req.query.lon);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
      return res.status(400).json({ error: "lat and lon are required" });
    }
    const info = geomagnetism.model().point([lat, lon]);
    res.json({ declination: info.decl });
  });

  app.use("/vendor/leaflet", express.static(path.join(__dirname, "node_modules", "leaflet", "dist")));
  app.use("/vendor/maplibre", express.static(path.join(__dirname, "node_modules", "maplibre-gl", "dist")));
  app.use("/vendor/maplibre-leaflet", express.static(path.join(__dirname, "node_modules", "@maplibre", "maplibre-gl-leaflet")));
  app.use(express.static(path.join(__dirname, "public")));
  return app;
}

async function main() {
  const lan = getLanAddresses();

  if (process.argv.includes("--tunnel")) {
    const { Tunnel, bin, install } = require("cloudflared");
    const fs = require("fs");

    buildApp().listen(PORT, "localhost", async () => {
      console.log(`Navigator (tunnel mode) on http://localhost:${PORT}`);
      if (!fs.existsSync(bin)) {
        console.log("Downloading cloudflared (one-time)...");
        await install(bin);
      }
      const tunnel = Tunnel.quick(`http://localhost:${PORT}`);
      tunnel.once("url", (url) => console.log(`\n  Open this on your phone:  ${url}\n`));
      tunnel.on("error", (err) => console.error("Tunnel error:", err.message));
      tunnel.on("exit", (code) => {
        console.error(`Tunnel stopped (code ${code}).`);
        process.exit(1);
      });
      process.on("exit", () => tunnel.stop());
    });
    return;
  }

  // Phones only allow camera, GPS and motion sensors on HTTPS.
  const pems = await selfsigned.generate([{ name: "commonName", value: "navigator" }], {
    extensions: [
      {
        name: "subjectAltName",
        altNames: [
          { type: 2, value: "localhost" },
          { type: 7, ip: "127.0.0.1" },
          ...lan.map((ip) => ({ type: 7, ip })),
        ],
      },
    ],
  });

  https.createServer({ key: pems.private, cert: pems.cert }, buildApp()).listen(PORT, "0.0.0.0", () => {
    console.log("Navigator is running:\n");
    console.log(`  This PC:  https://localhost:${PORT}`);
    for (const ip of lan) console.log(`  Phone:    https://${ip}:${PORT}`);
    console.log("\nYour browser will warn about the certificate - that's expected, choose to proceed.");
  });
}

module.exports = { buildApp };

if (require.main === module) main();
