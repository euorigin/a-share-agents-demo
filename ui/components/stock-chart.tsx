"use client";

import { useEffect, useMemo, useState } from "react";
import { Loader2 } from "lucide-react";

/**
 * A股走势图（日K / 周K / 分时）。
 *
 * 数据来自后端 GET /stock/chart?symbol=&period=
 * 颜色遵循 A股习惯：涨=红，跌=绿。
 */

type Candle = {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};

type IntradayPoint = {
  time: string;
  price: number;
  avg: number;
  volume: number;
};

type ChartData = {
  symbol: string;
  name: string;
  kind?: string;
  period: "day" | "week" | "min" | string;
  period_label?: string;
  prev_close: number;
  price: number;
  change_pct: number;
  open?: number;
  candles?: Candle[];
  points?: IntradayPoint[];
  as_of?: string;
  market_status?: string;
  error?: string;
};

export type StockChartProps = {
  symbol: string;
  period?: string;
};

// A股配色：涨红跌绿
const UP = "#e5484d";
const DOWN = "#12a150";
const GRID = "#eef0f2";
const AXIS_TEXT = "#8a8f98";
const MA5 = "#f59e0b";
const MA10 = "#3b82f6";

const VIEW_W = 660;
const PAD_L = 8;
const PAD_R = 52; // 右侧留给价格刻度
const PLOT_W = VIEW_W - PAD_L - PAD_R;

function formatSignedPct(value: number) {
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

function movingAverage(values: number[], window: number): (number | null)[] {
  const out: (number | null)[] = [];
  let sum = 0;
  for (let i = 0; i < values.length; i += 1) {
    sum += values[i];
    if (i >= window) sum -= values[i - window];
    out.push(i >= window - 1 ? sum / window : null);
  }
  return out;
}

function niceTicks(min: number, max: number, count = 4): number[] {
  const span = max - min || 1;
  return Array.from({ length: count + 1 }, (_, i) => min + (span * i) / count);
}

export function StockChart({ symbol, period = "day" }: StockChartProps) {
  const [data, setData] = useState<ChartData | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setFailed(null);
    setData(null);

    const url = `/stock/chart?symbol=${encodeURIComponent(symbol)}&period=${encodeURIComponent(period)}`;
    fetch(url)
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return (await res.json()) as ChartData;
      })
      .then((json) => {
        if (cancelled) return;
        if (json.error) {
          setFailed(json.error);
        } else {
          setData(json);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) setFailed(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [symbol, period]);

  if (loading) {
    return (
      <div className="my-2 flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-3 py-4 text-xs text-zinc-500">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        正在加载 {symbol} 走势图…
      </div>
    );
  }

  if (failed || !data) {
    return (
      <div className="my-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
        走势图加载失败：{failed ?? "无数据"}
      </div>
    );
  }

  const isIntraday = data.period === "min";
  const up = data.change_pct >= 0;
  const color = up ? UP : DOWN;

  return (
    <div className="my-2 overflow-hidden rounded-lg border border-gray-200 bg-white">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 border-b border-gray-100 px-3 py-2">
        <div className="flex items-baseline gap-2">
          <span className="text-sm font-semibold text-zinc-800">{data.name}</span>
          <span className="text-[11px] text-zinc-500">{data.symbol}</span>
          <span className="rounded bg-gray-100 px-1.5 py-0.5 text-[10px] text-zinc-600">
            {data.period_label ?? (isIntraday ? "分时" : "日K")}
          </span>
        </div>
        <div className="flex items-baseline gap-2">
          <span className="text-sm font-semibold" style={{ color }}>
            {data.price.toFixed(2)}
          </span>
          <span className="text-[11px] tabular-nums" style={{ color }}>
            {formatSignedPct(data.change_pct)}
          </span>
        </div>
      </div>

      {isIntraday ? (
        <IntradayChart data={data} color={color} />
      ) : (
        <CandleChart data={data} />
      )}

      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-gray-100 px-3 py-1.5 text-[10px] text-zinc-400">
        <span>
          {isIntraday
            ? `昨收 ${data.prev_close.toFixed(2)}　今开 ${(data.open ?? data.prev_close).toFixed(2)}`
            : `${data.candles?.[0]?.date ?? ""} ~ ${data.candles?.[data.candles.length - 1]?.date ?? ""}`}
        </span>
        <span>{data.market_status ?? "演示数据"}</span>
      </div>
    </div>
  );
}

function CandleChart({ data }: { data: ChartData }) {
  const candles = data.candles ?? [];

  const { lo, hi, ticks } = useMemo(() => {
    const lows = candles.map((c) => c.low);
    const highs = candles.map((c) => c.high);
    const min = Math.min(...lows);
    const max = Math.max(...highs);
    const pad = (max - min) * 0.06 || max * 0.02;
    const loV = min - pad;
    const hiV = max + pad;
    return { lo: loV, hi: hiV, ticks: niceTicks(loV, hiV, 4) };
  }, [candles]);

  const ma5 = useMemo(() => movingAverage(candles.map((c) => c.close), 5), [candles]);
  const ma10 = useMemo(() => movingAverage(candles.map((c) => c.close), 10), [candles]);

  if (!candles.length) return null;

  const priceH = 190;
  const volH = 54;
  const priceTop = 12;
  const volTop = priceTop + priceH + 16;
  const height = volTop + volH + 18;

  const maxVol = Math.max(...candles.map((c) => c.volume), 1);
  const slot = PLOT_W / candles.length;
  const bodyW = Math.max(1.5, Math.min(slot * 0.62, 9));

  const xOf = (i: number) => PAD_L + slot * (i + 0.5);
  const yOf = (v: number) => priceTop + ((hi - v) / (hi - lo || 1)) * priceH;
  const yVol = (v: number) => volTop + volH - (v / maxVol) * volH;

  const linePath = (series: (number | null)[]) => {
    let d = "";
    let started = false;
    series.forEach((v, i) => {
      if (v === null) return;
      const cmd = started ? "L" : "M";
      d += `${cmd}${xOf(i).toFixed(1)},${yOf(v).toFixed(1)} `;
      started = true;
    });
    return d.trim();
  };

  const labelEvery = Math.max(1, Math.ceil(candles.length / 6));

  return (
    <svg viewBox={`0 0 ${VIEW_W} ${height}`} className="w-full" role="img" aria-label="K线图">
      {ticks.map((t) => (
        <g key={`t-${t}`}>
          <line
            x1={PAD_L}
            x2={PAD_L + PLOT_W}
            y1={yOf(t)}
            y2={yOf(t)}
            stroke={GRID}
            strokeWidth={1}
          />
          <text x={PAD_L + PLOT_W + 6} y={yOf(t) + 3.5} fontSize={10} fill={AXIS_TEXT}>
            {t.toFixed(2)}
          </text>
        </g>
      ))}

      {candles.map((c, i) => {
        const rising = c.close >= c.open;
        const stroke = rising ? UP : DOWN;
        const top = yOf(Math.max(c.open, c.close));
        const bottom = yOf(Math.min(c.open, c.close));
        return (
          <g key={c.date}>
            <line
              x1={xOf(i)}
              x2={xOf(i)}
              y1={yOf(c.high)}
              y2={yOf(c.low)}
              stroke={stroke}
              strokeWidth={1}
            />
            <rect
              x={xOf(i) - bodyW / 2}
              y={top}
              width={bodyW}
              height={Math.max(1, bottom - top)}
              fill={rising ? UP : stroke}
              stroke={stroke}
              strokeWidth={0.5}
            />
            <rect
              x={xOf(i) - bodyW / 2}
              y={yVol(c.volume)}
              width={bodyW}
              height={Math.max(0.5, volTop + volH - yVol(c.volume))}
              fill={stroke}
              opacity={0.35}
            />
          </g>
        );
      })}

      <path d={linePath(ma5)} fill="none" stroke={MA5} strokeWidth={1.2} />
      <path d={linePath(ma10)} fill="none" stroke={MA10} strokeWidth={1.2} />

      <line
        x1={PAD_L}
        x2={PAD_L + PLOT_W}
        y1={yVol(0)}
        y2={yVol(0)}
        stroke={GRID}
        strokeWidth={1}
      />

      {candles.map((c, i) =>
        i % labelEvery === 0 ? (
          <text
            key={`x-${c.date}`}
            x={xOf(i)}
            y={height - 4}
            fontSize={9.5}
            fill={AXIS_TEXT}
            textAnchor="middle"
          >
            {c.date.slice(5)}
          </text>
        ) : null
      )}

      <g transform={`translate(${PAD_L + 4}, ${volTop + 10})`}>
        <rect x={0} y={-7} width={8} height={2} fill={MA5} />
        <text x={12} y={-3} fontSize={9.5} fill={AXIS_TEXT}>
          MA5
        </text>
        <rect x={42} y={-7} width={8} height={2} fill={MA10} />
        <text x={54} y={-3} fontSize={9.5} fill={AXIS_TEXT}>
          MA10
        </text>
      </g>
    </svg>
  );
}

function IntradayChart({ data, color }: { data: ChartData; color: string }) {
  const points = data.points ?? [];

  const { lo, hi, ticks } = useMemo(() => {
    const prices = points.map((p) => p.price);
    const min = Math.min(...prices, data.prev_close);
    const max = Math.max(...prices, data.prev_close);
    // 分时图以昨收为中心对称，涨跌幅度看起来更直观
    const span = Math.max(max - data.prev_close, data.prev_close - min) * 1.08 || data.prev_close * 0.01;
    const loV = data.prev_close - span;
    const hiV = data.prev_close + span;
    return { lo: loV, hi: hiV, ticks: niceTicks(loV, hiV, 4) };
  }, [points, data.prev_close]);

  if (!points.length) return null;

  const priceH = 200;
  const volH = 46;
  const priceTop = 12;
  const volTop = priceTop + priceH + 14;
  const height = volTop + volH + 18;

  const maxVol = Math.max(...points.map((p) => p.volume), 1);
  const xOf = (i: number) => PAD_L + (PLOT_W * i) / Math.max(1, points.length - 1);
  const yOf = (v: number) => priceTop + ((hi - v) / (hi - lo || 1)) * priceH;
  const yVol = (v: number) => volTop + volH - (v / maxVol) * volH;

  const priceLine = points
    .map((p, i) => `${i === 0 ? "M" : "L"}${xOf(i).toFixed(1)},${yOf(p.price).toFixed(1)}`)
    .join(" ");
  const avgLine = points
    .map((p, i) => `${i === 0 ? "M" : "L"}${xOf(i).toFixed(1)},${yOf(p.avg).toFixed(1)}`)
    .join(" ");
  const area = `${priceLine} L${xOf(points.length - 1).toFixed(1)},${yOf(lo).toFixed(1)} L${xOf(0).toFixed(1)},${yOf(lo).toFixed(1)} Z`;

  const barW = Math.max(0.8, PLOT_W / points.length - 0.5);

  return (
    <svg viewBox={`0 0 ${VIEW_W} ${height}`} className="w-full" role="img" aria-label="分时图">
      <defs>
        <linearGradient id="intraday-fill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity={0.22} />
          <stop offset="100%" stopColor={color} stopOpacity={0.02} />
        </linearGradient>
      </defs>

      {ticks.map((t) => (
        <g key={`t-${t}`}>
          <line x1={PAD_L} x2={PAD_L + PLOT_W} y1={yOf(t)} y2={yOf(t)} stroke={GRID} strokeWidth={1} />
          <text x={PAD_L + PLOT_W + 6} y={yOf(t) + 3.5} fontSize={10} fill={AXIS_TEXT}>
            {t.toFixed(2)}
          </text>
        </g>
      ))}

      {/* 午休分隔线 */}
      <line
        x1={xOf(119.5)}
        x2={xOf(119.5)}
        y1={priceTop}
        y2={volTop + volH}
        stroke={GRID}
        strokeWidth={1}
      />

      <path d={area} fill="url(#intraday-fill)" />
      <path d={priceLine} fill="none" stroke={color} strokeWidth={1.4} />
      <path d={avgLine} fill="none" stroke={MA5} strokeWidth={1.1} />

      {points.map((p, i) => (
        <rect
          key={p.time}
          x={xOf(i) - barW / 2}
          y={yVol(p.volume)}
          width={barW}
          height={Math.max(0.5, volTop + volH - yVol(p.volume))}
          fill={p.price >= data.prev_close ? UP : DOWN}
          opacity={0.32}
        />
      ))}

      <line x1={PAD_L} x2={PAD_L + PLOT_W} y1={yVol(0)} y2={yVol(0)} stroke={GRID} strokeWidth={1} />

      {[0, 60, 120, 180, 239].map((i) => (
        <text
          key={`x-${i}`}
          x={xOf(i)}
          y={height - 4}
          fontSize={9.5}
          fill={AXIS_TEXT}
          textAnchor={i === 0 ? "start" : i === 239 ? "end" : "middle"}
        >
          {points[i]?.time ?? ""}
        </text>
      ))}

      <g transform={`translate(${PAD_L + 4}, ${volTop + 10})`}>
        <rect x={0} y={-7} width={8} height={2} fill={color} />
        <text x={12} y={-3} fontSize={9.5} fill={AXIS_TEXT}>
          价格
        </text>
        <rect x={42} y={-7} width={8} height={2} fill={MA5} />
        <text x={54} y={-3} fontSize={9.5} fill={AXIS_TEXT}>
          均价
        </text>
      </g>
    </svg>
  );
}

export default StockChart;
