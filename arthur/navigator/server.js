const express = require("express");
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

function buildApp() {
  const app = express();

  app.get("/api/config", (req, res) => res.json({ waypoint: WAYPOINT }));

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

    buildApp().listen(PORT, "127.0.0.1", async () => {
      console.log(`Navigator (tunnel mode) on http://127.0.0.1:${PORT}`);
      if (!fs.existsSync(bin)) {
        console.log("Downloading cloudflared (one-time)...");
        await install(bin);
      }
      const tunnel = Tunnel.quick(`http://127.0.0.1:${PORT}`);
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
