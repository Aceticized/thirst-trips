const express = require("express");
const https = require("https");
const os = require("os");
const path = require("path");
const selfsigned = require("selfsigned");
const { detectBuilding, sendToDjango } = require("./facilities");

const PORT = process.env.PORT || 3000;

function getLanAddresses() {
  const addresses = [];
  for (const list of Object.values(os.networkInterfaces())) {
    for (const iface of list) {
      if (iface.family === "IPv4" && !iface.internal) addresses.push(iface.address);
    }
  }
  return addresses;
}

// The Express app on its own, so the home project can mount it under /uploader.
const FLOOR_PATTERN = /^[A-Za-z]?\d+$/; // a number, or a letter then a number (e.g. 2, M2)

function buildApp() {
  const app = express();
  app.use(express.json());

  app.get("/api/building", async (req, res) => {
    const lat = parseFloat(req.query.lat);
    const lon = parseFloat(req.query.lon);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
      return res.status(400).json({ error: "lat and lon are required" });
    }
    res.json({ building: await detectBuilding(lat, lon) });
  });

  app.post("/api/upload", async (req, res) => {
    const { latitude, longitude, building, floor, accessible } = req.body || {};
    const lat = Number(latitude);
    const lon = Number(longitude);
    const cleanBuilding = typeof building === "string" ? building.trim() : "";
    const cleanFloor = typeof floor === "string" ? floor.trim().toUpperCase() : "";

    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return res.status(400).json({ error: "Valid latitude and longitude are required." });
    if (!cleanBuilding || cleanBuilding.length > 100) return res.status(400).json({ error: "A building is required." });
    if (!FLOOR_PATTERN.test(cleanFloor)) return res.status(400).json({ error: "Floor must be a number or a letter and a number, like 2 or M2." });

    try {
      // Django assigns the id (and name) so simultaneous uploads can't clash.
      const record = await sendToDjango({
        latitude: lat,
        longitude: lon,
        building: cleanBuilding,
        floor: cleanFloor,
        accessible: Boolean(accessible),
      });
      res.json({ record });
    } catch (err) {
      // Not 502/504: the Cloudflare tunnel replaces those with its own HTML page and hides the message.
      res.status(424).json({ error: err.message });
    }
  });

  app.use(express.static(path.join(__dirname, "public")));
  return app;
}

async function main() {
  const lan = getLanAddresses();

  // Tunnel mode: a tunnel service (e.g. cloudflared) provides the HTTPS, so
  // serve plain HTTP on localhost only.
  if (process.argv.includes("--tunnel")) {
    buildApp().listen(PORT, "localhost", async () => {
      console.log(`Fountain Finder (tunnel mode) on http://localhost:${PORT}`);
      const localtunnel = require("localtunnel");
      const tunnel = await localtunnel({ port: Number(PORT) });
      console.log(`\n  Open this on your phone:  ${tunnel.url}\n`);
      tunnel.on("close", () => console.log("Tunnel closed."));
    });
    return;
  }

  // Phones only allow camera/location on HTTPS, so generate a throwaway
  // self-signed certificate that also covers this PC's LAN IP addresses.
  const pems = await selfsigned.generate([{ name: "commonName", value: "fountain-finder" }], {
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
    console.log("Fountain Finder is running:\n");
    console.log(`  This PC:  https://localhost:${PORT}`);
    for (const ip of lan) console.log(`  Phone:    https://${ip}:${PORT}`);
    console.log("\nYour browser will warn about the certificate - that's expected, choose to proceed.");
  });
}

module.exports = { buildApp };

if (require.main === module) main();
