// TCGplayer marketplace endpoints (same ones the Python version uses).
//
// The mpapi sales endpoint rejects requests without browser-shape headers, and
// the Python bot earned its cookies by hitting tcgplayer.com first. On
// Cloudflare's egress IPs we usually pass without the warmup — but the cookie
// dance is cheap, so we still do it once per worker isolate.

const SEARCH_URL = "https://mp-search-api.tcgplayer.com/v1/search/request?q=&isList=false";
const SALES_URL = "https://mpapi.tcgplayer.com/v2/product/{pid}/latestsales";
const PRODUCT_URL = "https://mp-search-api.tcgplayer.com/v2/product/{pid}/details";
export const IMAGE_URL = (pid: number) => `https://product-images.tcgplayer.com/fit-in/437x437/${pid}.jpg`;
export const TCGPLAYER_PRODUCT_URL = (pid: number) => `https://www.tcgplayer.com/product/${pid}`;
export const PRODUCT_LINE = "riftbound-league-of-legends-trading-card-game";

const COMMON_HEADERS: Record<string, string> = {
  "Origin": "https://www.tcgplayer.com",
  "Referer": "https://www.tcgplayer.com/",
  "Accept": "application/json",
  "Content-Type": "application/json",
  "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
};

let _warmed = false;
async function warmCookies(): Promise<void> {
  if (_warmed) return;
  try {
    await fetch("https://www.tcgplayer.com/", {
      headers: { "User-Agent": COMMON_HEADERS["User-Agent"] },
      cf: { cacheTtl: 0 },
    });
  } catch {
    // ignore
  }
  _warmed = true;
}

export interface SaleRecord {
  orderDate: string;
  quantity: number;
  purchasePrice: number;
  variant?: string;
  condition?: string;
}

export async function fetchLatestSales(productId: number, limit = 5): Promise<SaleRecord[]> {
  await warmCookies();
  const r = await fetch(SALES_URL.replace("{pid}", String(productId)), {
    method: "POST",
    headers: { ...COMMON_HEADERS, Referer: `https://www.tcgplayer.com/product/${productId}/` },
    body: JSON.stringify({ sortBy: "order", limit, offset: 0 }),
  });
  if (!r.ok) throw new Error(`latestsales HTTP ${r.status}`);
  const json = (await r.json()) as { data?: SaleRecord[] };
  return json.data || [];
}

export interface ProductDetail {
  setName?: string;
  rarityName?: string;
  marketPrice?: number;
  lowestPrice?: number;
  totalListings?: number;
}

export async function fetchProductDetail(productId: number): Promise<ProductDetail | null> {
  // Use the search API with a productLineProductId filter so we get the
  // current marketPrice/lowestPrice/totalListings without an auth-only call.
  await warmCookies();
  const body = {
    algorithm: "",
    from: 0,
    size: 1,
    filters: {
      term: {
        productLineName: [PRODUCT_LINE],
        productTypeName: ["Cards"],
        productId: [String(productId)],
      },
      range: {},
      match: {},
    },
    context: { cart: {}, shippingCountry: "US" },
    sort: {},
  };
  const r = await fetch(SEARCH_URL, {
    method: "POST",
    headers: COMMON_HEADERS,
    body: JSON.stringify(body),
  });
  if (!r.ok) return null;
  const j = (await r.json()) as { results?: { results?: ProductDetail[] }[] };
  const item = j.results?.[0]?.results?.[0];
  return item || null;
}

export async function* iterRiftboundCards(): AsyncGenerator<unknown, void, void> {
  await warmCookies();
  const pageSize = 50;
  let offset = 0;
  while (true) {
    const body = {
      algorithm: "",
      from: offset,
      size: pageSize,
      filters: {
        term: { productLineName: [PRODUCT_LINE], productTypeName: ["Cards"] },
        range: {},
        match: {},
      },
      context: { cart: {}, shippingCountry: "US" },
      sort: {},
    };
    const r = await fetch(SEARCH_URL, {
      method: "POST",
      headers: COMMON_HEADERS,
      body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error(`search HTTP ${r.status}`);
    const payload = ((await r.json()) as { results?: { results?: unknown[]; totalResults?: number }[] }).results?.[0];
    const results = (payload?.results || []) as unknown[];
    if (results.length === 0) return;
    for (const item of results) yield item;
    offset += pageSize;
    if (offset >= (payload?.totalResults || 0)) return;
    // Be polite — TCGplayer WAF kicks in around 100 sequential calls.
    await new Promise((r) => setTimeout(r, 300));
  }
}
