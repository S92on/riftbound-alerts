export interface Env {
  DISCORD_PUBLIC_KEY: string;
  DISCORD_TOKEN: string;
  DISCORD_APPLICATION_ID: string;
  CARDS: KVNamespace;
  WATCHLISTS: KVNamespace;
  CONFIG: KVNamespace;
  MMCACHE: KVNamespace;
}

export interface Card {
  product_id: number;
  name: string;
  set_name?: string | null;
  rarity?: string | null;
  market_price?: number | null;
  lowest_price?: number | null;
  number?: string | null;
}

export interface Watch {
  product_id: number;
  name: string;
  baseline_price: number;
  threshold_pct: number;
  added_at: string;
  last_alert_at?: string;
}

export interface MMItem {
  product_id?: number | string;
  name?: string;
  set_name?: string;
  market_price?: number;
  is_foil_variant?: boolean;
  quantity_sold?: number;
  avg_daily_quantity_sold?: number;
  percent_change?: number;
  dollar_change?: number;
  previous_price?: number;
}

export interface MMSummary {
  last_updated?: string;
  total_cards?: number;
  trading_card_count?: number;
  market_summary?: {
    total_market_value?: number;
    total_cards_tracked?: number;
    total_sets_tracked?: number;
    total_quantity_sold?: number;
    total_transaction_count?: number;
    avg_daily_quantity_sold?: number;
    avg_daily_transaction_count?: number;
    set_breakdown?: Record<string, unknown>;
  };
  dashboard_aggregates?: {
    by_range?: Record<string, MMRange>;
  };
}

export interface MMRange {
  market_direction?: Record<string, number>;
  heat_count?: number;
  heat_by_tier?: Record<string, number>;
  top_movers?: { gainers?: MMItem[]; losers?: MMItem[] };
  top_sellers?: { items?: MMItem[] };
}

// Discord interaction enums (subset)
export const InteractionType = {
  PING: 1,
  APPLICATION_COMMAND: 2,
  MESSAGE_COMPONENT: 3,
  APPLICATION_COMMAND_AUTOCOMPLETE: 4,
  MODAL_SUBMIT: 5,
} as const;

export const InteractionResponseType = {
  PONG: 1,
  CHANNEL_MESSAGE_WITH_SOURCE: 4,
  DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE: 5,
  DEFERRED_UPDATE_MESSAGE: 6,
  UPDATE_MESSAGE: 7,
  APPLICATION_COMMAND_AUTOCOMPLETE_RESULT: 8,
  MODAL: 9,
} as const;

export const InteractionResponseFlags = {
  EPHEMERAL: 1 << 6, // 64
} as const;

export const RANGES = ["h24", "d7", "d30", "d60", "d90", "d180", "y1"] as const;
export const RANGE_LABEL: Record<string, string> = {
  h24: "24h", d7: "7d", d30: "30d", d60: "60d",
  d90: "90d", d180: "180d", y1: "1y",
};
