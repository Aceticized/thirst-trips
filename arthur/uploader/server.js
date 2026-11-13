const express = require("express");
const https = require("https");
const os = require("os");
const path = require("path");
const selfsigned = require("selfsigned");

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

async function main() {
  const lan = getLanAddresses();

  // Tunnel mode: a tunnel service (e.g. cloudflared) provides the HTTPS, so
  // serve plain HTTP on localhost only.
  if (process.argv.includes("--tunnel")) {
    const app = express();
    app.use(express.static(path.join(__dirname, "public")));
    app.listen(PORT, "127.0.0.1", async () => {
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

  const app = express();
  app.use(express.static(path.join(__dirname, "public")));

  https.createServer({ key: pems.private, cert: pems.cert }, app).listen(PORT, "0.0.0.0", () => {
    console.log("Fountain Finder is running:\n");
    console.log(`  This PC:  https://localhost:${PORT}`);
    for (const ip of lan) console.log(`  Phone:    https://${ip}:${PORT}`);
    console.log("\nYour browser will warn about the certificate - that's expected, choose to proceed.");
  });
}

main();
