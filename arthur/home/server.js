// Load settings from .env (this folder or the parent "arthur" folder) before anything reads
// them. Variables already set in the terminal take priority.
for (const dir of [__dirname, require("path").join(__dirname, "..")]) {
  const file = require("path").join(dir, ".env");
  if (require("fs").existsSync(file)) process.loadEnvFile(file);
}

const express = require("express");
const https = require("https");
const os = require("os");
const path = require("path");
const selfsigned = require("selfsigned");
const { loadFountains, findNearest, sourceDescription } = require("./fountains");

// The other two projects stay independent folders; the home server just mounts them.
const navigator = require("../navigator/server.js");
const uploader = require("../uploader/server.js");

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

function buildApp() {
  const app = express();

  app.get("/api/fountains", async (req, res) => {
    try {
      const lat = parseFloat(req.query.lat);
      const lon = parseFloat(req.query.lon);
      res.json(Number.isFinite(lat) && Number.isFinite(lon) ? await loadFountains(lat, lon) : await loadFountains());
    } catch (err) {
      // Not 502/504: the Cloudflare tunnel replaces those with its own HTML page and hides the message.
      res.status(424).json({ error: err.message });
    }
  });

  app.get("/api/nearest", async (req, res) => {
    const lat = parseFloat(req.query.lat);
    const lon = parseFloat(req.query.lon);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
      return res.status(400).json({ error: "lat and lon are required" });
    }
    try {
      const nearest = findNearest(await loadFountains(lat, lon), lat, lon);
      if (!nearest) return res.status(404).json({ error: "No fountains found" });
      res.json(nearest);
    } catch (err) {
      res.status(424).json({ error: err.message });
    }
  });

  app.use("/navigator", navigator.buildApp());
  app.use("/uploader", uploader.buildApp());
  app.use("/vendor/leaflet", express.static(path.join(__dirname, "node_modules", "leaflet", "dist")));
  app.use(express.static(path.join(__dirname, "public")));
  return app;
}

async function main() {
  const lan = getLanAddresses();
  console.log(`Fountains: ${sourceDescription}`);

  if (process.argv.includes("--tunnel")) {
    const { Tunnel, bin, install } = require("cloudflared");
    const fs = require("fs");

    buildApp().listen(PORT, "127.0.0.1", async () => {
      console.log(`Home (tunnel mode) on http://127.0.0.1:${PORT}`);
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
  const pems = await selfsigned.generate([{ name: "commonName", value: "fountain-finder-home" }], {
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
    console.log("Home is running:\n");
    console.log(`  This PC:  https://localhost:${PORT}`);
    for (const ip of lan) console.log(`  Phone:    https://${ip}:${PORT}`);
    console.log("\nYour browser will warn about the certificate - that's expected, choose to proceed.");
  });
}

main();
