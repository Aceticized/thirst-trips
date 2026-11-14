const fs = require("fs");
const path = require("path");

// Serves index.html with ?v=<last-modified time> added to its local CSS/JS/image links.
// Cloudflare tells browsers to keep those files for 4 hours, so without this phones keep
// showing the old version after an edit. The HTML itself is never cached.
function versionedIndex(publicDir) {
  return (req, res, next) => {
    const urlPath = req.originalUrl.split("?")[0];
    const isIndex = (req.path === "/" && urlPath.endsWith("/")) || req.path === "/index.html";
    if (!isIndex) return next();

    fs.readFile(path.join(publicDir, "index.html"), "utf8", (err, html) => {
      if (err) return next();
      const versioned = html.replace(/(href|src)="([^":?#]+\.(?:css|js|png))"/g, (match, attr, file) => {
        try {
          const version = Math.floor(fs.statSync(path.join(publicDir, file)).mtimeMs);
          return `${attr}="${file}?v=${version}"`;
        } catch {
          return match; // not in this folder (e.g. the vendor libraries)
        }
      });
      res.set("Cache-Control", "no-cache").type("html").send(versioned);
    });
  };
}

module.exports = { versionedIndex };
