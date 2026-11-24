import React, { useEffect, useRef } from 'react';
import { ColorType, CrosshairMode, LineStyle, UTCTimestamp, createChart } from 'lightweight-charts';
import { dateTimeET } from '../utils';

interface Props {
  nq: Array<{ t: number; c: number }>;
  es: Array<{ t: number; c: number }>;
  height?: number;
}

function normalize(points: Array<{ t: number; c: number }>) {
  if (!points.length) return [];
  const base = points[0].c || 1;
  return points.map((p) => ({ time: p.t as UTCTimestamp, value: ((p.c - base) / base) * 100 }));
}

export default function ComparisonChart({ nq, es, height = 150 }: Props) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = ref.current;
    if (!container) return;
    const chart = createChart(container, {
      width: container.clientWidth,
      height,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: '#8293a9',
        fontFamily: "'Inter', system-ui, sans-serif",
        fontSize: 9,
      },
      grid: {
        vertLines: { color: 'rgba(255,255,255,0.025)' },
        horzLines: { color: 'rgba(255,255,255,0.025)' },
      },
      rightPriceScale: { borderColor: '#19232f', scaleMargins: { top: 0.15, bottom: 0.1 } },
      timeScale: { borderColor: '#19232f', timeVisible: true, secondsVisible: true, rightOffset: 4, barSpacing: 4 },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: 'rgba(63,140,255,0.3)', style: LineStyle.Dashed, labelBackgroundColor: '#1d2a39' },
        horzLine: { color: 'rgba(63,140,255,0.3)', style: LineStyle.Dashed, labelBackgroundColor: '#1d2a39' },
      },
      localization: {
        timeFormatter: (t: any) => dateTimeET(Number(t)),
        priceFormatter: (p: number) => `${p.toFixed(2)}%`,
      },
    });
    const nqSeries = chart.addLineSeries({
      color: '#3f8cff',
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: true,
      crosshairMarkerRadius: 3,
      priceFormat: { type: 'custom', formatter: (p: number) => `${p.toFixed(2)}%` },
    });
    const esSeries = chart.addLineSeries({
      color: '#f3a83b',
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: true,
      crosshairMarkerRadius: 3,
      priceFormat: { type: 'custom', formatter: (p: number) => `${p.toFixed(2)}%` },
    });
    const nqData = normalize(nq);
    const esData = normalize(es);
    nqSeries.setData(nqData);
    esSeries.setData(esData);
    if (nqData.length && esData.length) chart.timeScale().fitContent();

    const observer = new ResizeObserver(() => chart.applyOptions({ width: container.clientWidth }));
    observer.observe(container);
    return () => {
      observer.disconnect();
      chart.remove();
    };
  }, [nq, es, height]);

  return <div ref={ref} style={{ width: '100%' }} />;
}
