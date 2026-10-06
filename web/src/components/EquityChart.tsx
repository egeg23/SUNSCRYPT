"use client";

import {
  AreaSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useRef } from "react";

export type Fill = { ts: number; sym: string; side: string; qty: number; price: number };

function css(name: string) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/** Кривая баланса (одна линия — без легенды) с отметками сделок. */
export function EquityChart({ equity, fills }: { equity: [number, number][]; fills: Fill[] }) {
  const box = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const series = useRef<ISeriesApi<"Area"> | null>(null);
  const markers = useRef<ISeriesMarkersPluginApi<Time> | null>(null);

  useEffect(() => {
    if (!box.current) return;
    const c = createChart(box.current, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: css("--muted"), fontFamily: "JetBrains Mono Variable, monospace", attributionLogo: false },
      grid: { vertLines: { visible: false }, horzLines: { color: css("--line") } },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false, timeVisible: true },
      localization: { locale: "ru-RU" },
    });
    const s = c.addSeries(AreaSeries, { lineWidth: 2, priceLineVisible: false });
    chart.current = c;
    series.current = s;
    markers.current = createSeriesMarkers(s, []);
    const paint = () => {
      const accent = css("--accent");
      s.applyOptions({ lineColor: accent, topColor: `color-mix(in srgb, ${accent} 18%, transparent)`, bottomColor: "transparent" });
      c.applyOptions({ layout: { textColor: css("--muted") }, grid: { horzLines: { color: css("--line") } } });
    };
    paint();
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    mq.addEventListener("change", paint);
    return () => {
      mq.removeEventListener("change", paint);
      c.remove();
    };
  }, []);

  useEffect(() => {
    if (!series.current) return;
    const seen = new Set<number>();
    const data = equity
      .map(([ms, v]) => ({ time: Math.floor(ms / 1000) as UTCTimestamp, value: v }))
      .filter((p) => (seen.has(p.time) ? false : (seen.add(p.time), true)));
    series.current.setData(data);
    const first = data[0]?.time ?? 0;
    const m: SeriesMarker<Time>[] = fills
      .filter((f) => f.ts / 1000 >= first)
      .sort((a, b) => a.ts - b.ts)
      .map((f) => ({
        time: Math.floor(f.ts / 1000) as UTCTimestamp,
        position: f.side === "buy" ? "belowBar" : "aboveBar",
        shape: f.side === "buy" ? "arrowUp" : "arrowDown",
        color: f.side === "buy" ? css("--gain") : css("--loss"),
        text: `${f.side === "buy" ? "+" : "−"}${f.sym.replace("USDT", "")}`,
      }));
    markers.current?.setMarkers(m);
    chart.current?.timeScale().fitContent();
  }, [equity, fills]);

  return <div ref={box} style={{ height: 300, width: "100%" }} role="img" aria-label="График баланса счёта со сделками" />;
}
