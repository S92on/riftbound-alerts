// Discord requires Ed25519 signature verification on every incoming interaction.
// Cloudflare Workers' WebCrypto supports Ed25519 directly — no external library
// needed (no tweetnacl).

function hexToBytes(hex: string): Uint8Array {
  const out = new Uint8Array(hex.length / 2);
  for (let i = 0; i < out.length; i++) {
    out[i] = parseInt(hex.substr(i * 2, 2), 16);
  }
  return out;
}

let _keyCache: { hex: string; key: CryptoKey } | null = null;

async function importPublicKey(hexKey: string): Promise<CryptoKey> {
  if (_keyCache && _keyCache.hex === hexKey) return _keyCache.key;
  const key = await crypto.subtle.importKey(
    "raw",
    hexToBytes(hexKey),
    { name: "Ed25519" },
    false,
    ["verify"],
  );
  _keyCache = { hex: hexKey, key };
  return key;
}

export async function verifyDiscordRequest(
  request: Request,
  publicKey: string,
): Promise<{ valid: boolean; body: string }> {
  const signature = request.headers.get("X-Signature-Ed25519");
  const timestamp = request.headers.get("X-Signature-Timestamp");
  const body = await request.text();
  if (!signature || !timestamp) {
    return { valid: false, body };
  }
  try {
    const key = await importPublicKey(publicKey);
    const valid = await crypto.subtle.verify(
      { name: "Ed25519" },
      key,
      hexToBytes(signature),
      new TextEncoder().encode(timestamp + body),
    );
    return { valid, body };
  } catch {
    return { valid: false, body };
  }
}
