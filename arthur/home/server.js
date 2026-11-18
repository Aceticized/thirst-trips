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
const { versionedIndex } = require("./versioned-index");

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

  // Same-origin browser access to Django sessions, CSRF, and achievements.
  // Keep the upload secret out of this path: contributions use the user's session.
  app.use("/achievement-assets", express.static(path.join(__dirname, "..", "..", "rafay", "fountain-finder", "locations", "static", "locations", "achievements")));
  app.use("/static/locations", express.static(path.join(__dirname, "..", "..", "rafay", "fountain-finder", "locations", "static", "locations")));
  app.use(async (req, res, next) => {
    const apiRoute = /^\/api\/(auth\/|me\/|profile\/|checkin\/|achievements\/|facilities\/discover\/)/.test(req.path);
    const pageRoute = /^\/(account|accounts|login|signup|leaderboard|achievements|avatar|checkin)\//.test(req.path);
    if (!apiRoute && !pageRoute) return next();
    try {
      const base = new URL(process.env.DJANGO_API_URL || "http://localhost:8000/api/nearby/");
      const headers = { Accept: "application/json" };
      for (const name of ["cookie", "content-type", "x-csrftoken"]) {
        if (req.headers[name]) headers[name] = req.headers[name];
      }
      if (req.headers.origin) {
        // Validate browser origin before translating it to the backend origin.
        if (new URL(req.headers.origin).host !== req.headers.host) return res.sendStatus(403);
        headers.Origin = base.origin;
        headers.Referer = base.origin + "/";
      }
      const chunks = [];
      let size = 0;
      for await (const chunk of req) {
        size += chunk.length;
        if (size > 65536) return res.sendStatus(413);
        chunks.push(chunk);
      }
      const upstream = await fetch(new URL(req.originalUrl, base.origin), {
        method: req.method, headers, redirect: "manual",
        ...(["GET", "HEAD"].includes(req.method) ? {} : { body: Buffer.concat(chunks) }),
        signal: AbortSignal.timeout(15000),
      });
      res.set("Cache-Control", "no-store");
      for (const cookie of upstream.headers.getSetCookie()) res.append("Set-Cookie", cookie);
      const location = upstream.headers.get("location");
      if (location) {
        const target = new URL(location, base.origin);
        res.set("Location", target.origin === base.origin ? target.pathname + target.search + target.hash : location);
      }
      res.status(upstream.status).type(upstream.headers.get("content-type") || "application/json")
        .send(Buffer.from(await upstream.arrayBuffer()));
    } catch (err) {
      res.status(424).json({ error: "Cannot reach Django. Please try again." });
    }
  });

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

  app.use("/navigator", versionedIndex(path.join(__dirname, "..", "navigator", "public")), navigator.buildApp());
  app.use("/uploader", versionedIndex(path.join(__dirname, "..", "uploader", "public")), uploader.buildApp());
  app.use("/vendor/leaflet", express.static(path.join(__dirname, "node_modules", "leaflet", "dist")));
  app.use("/vendor/maplibre", express.static(path.join(__dirname, "node_modules", "maplibre-gl", "dist")));
  app.use("/vendor/maplibre-leaflet", express.static(path.join(__dirname, "node_modules", "@maplibre", "maplibre-gl-leaflet")));
  app.use(versionedIndex(path.join(__dirname, "public")));
  app.use(express.static(path.join(__dirname, "public")));
  return app;
}

async function main() {
  const lan = getLanAddresses();
  console.log(`Fountains: ${sourceDescription}`);

  if (process.argv.includes("--tunnel")) {
    const { Tunnel, bin, install } = require("cloudflared");
    const fs = require("fs");

    buildApp().listen(PORT, "localhost", async () => {
      console.log(`Home (tunnel mode) on http://localhost:${PORT}`);
      if (!fs.existsSync(bin)) {
        console.log("Downloading cloudflared (one-time)...");
        await install(bin);
      }
      const token = process.env.CLOUDFLARE_TUNNEL_TOKEN;
      let tunnel;
      if (token) {
        // Permanent tunnel: Cloudflare routes your own domain to this server.
        tunnel = Tunnel.withToken(token);
        tunnel.once("connected", () =>
          console.log(`\n  Live at:  ${process.env.PUBLIC_URL || "your Cloudflare domain"}\n`)
        );
      } else {
        // No token: a temporary random trycloudflare.com address.
        tunnel = Tunnel.quick(`http://localhost:${PORT}`);
        tunnel.once("url", (url) => console.log(`\n  Open this on your phone:  ${url}\n`));
      }
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
