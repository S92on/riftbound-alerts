// Upload the local data/cards.json (produced by the Python refresh_cards.py)
// into the Workers CARDS KV namespace under the key "all".
//
// Usage:  npm run upload-cards
// Requires that wrangler.toml has the CARDS KV binding configured with an id.

import { execSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

const repoRoot = path.resolve(process.cwd(), "..");
const cardsPath = path.join(repoRoot, "data", "cards.json");
if (!fs.existsSync(cardsPath)) {
  console.error(`No file at ${cardsPath}. Run the Python refresh_cards.py first.`);
  process.exit(1);
}
const raw = fs.readFileSync(cardsPath, "utf8");
const parsed = JSON.parse(raw);
console.log(`Loaded ${parsed.length} cards from ${cardsPath} (${raw.length} bytes)`);

// Write a temp file then point wrangler at it — wrangler kv key put can take a
// --path arg and stream from disk, which avoids stuffing a 1MB blob through
// the command line.
const tmp = path.join(repoRoot, "cf-worker", ".cards-upload.json");
fs.writeFileSync(tmp, raw, "utf8");
try {
  execSync(
    `npx wrangler kv key put --binding=CARDS "all" --path="${tmp}"`,
    { stdio: "inherit" },
  );
  console.log("Upload complete.");
} finally {
  fs.unlinkSync(tmp);
}
