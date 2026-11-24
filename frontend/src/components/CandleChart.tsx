import React, { useEffect, useRef } from 'react';
import {
  ColorType,
  CrosshairMode,
  IChartApi,
  IPriceLine,
  ISeriesApi,
  LineStyle,
  UTCTimestamp,
  createChart,
} from 'lightweight-charts';
import { Marker, OHLC, OpeningRange, Position } from '../types';
import { aggregate, atr, dateTimeET, vwap } from '../utils';

interface Props {
  bars: OHLC[];
  focusStart?: number | null;
  timeframe: number;
  openingRange: OpeningRange | null;
  markers: Marker[];
  position: Position | null;
  referenceLevel?: number | null;
  showVwap?: boolean;
  showAtr?: boolean;
  height?: number;
}

const BAR_SPACING = 4;
const PRICE_WIDTH_KEY = 'yed.priceScaleWidth';

function savedPriceWidth(): number {
  try {
    const value = Number(localStorage.getItem(PRICE_WIDTH_KEY));
    return Number.isFinite(value) && value > 0 ? Math.min(value, 240) : 0;
  } catch {
    return 0;
  }
}

const SHORT_LABEL: Record<string, string> = {
  breakout: 'Ruptura',
  false_breakout: 'Falso',
  smt: 'SMT',
  retest: 'Retest',
  entry: 'Entrada',
  trade_entry: 'Entrada',
  trade_exit: 'Salida',
};

export default function CandleChart({
  bars,
  focusStart = null,
  timeframe,
  openingRange,
  markers,
  position,
  referenceLevel = null,
  showVwap = false,
  showAtr = false,
  height = 420,
}: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const handleRef = useRef<HTMLDivElement>(null);
  const priceWidthRef = useRef(0);
  const barsCountRef = useRef(0);
  const candleRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volumeRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const vwapRef = useRef<ISeriesApi<'Line'> | null>(null);
  const atrRef = useRef<ISeriesApi<'Line'> | null>(null);
  const priceLinesRef = useRef<IPriceLine[]>([]);
  const drawRef = useRef<() => void>(() => {});
  const fittedRef = useRef(false);
  const tfRef = useRef(timeframe);

  const positionHandle = () => {
    const chart = chartRef.current;
    const handle = handleRef.current;
    if (!chart || !handle) return;
    const width = chart.priceScale('right').width();
    handle.style.right = `${Math.max(0, width - 3)}px`;
    handle.style.opacity = width > 0 ? '1' : '0';
  };

  const startPriceResize = (event: React.PointerEvent<HTMLDivElement>) => {
    const chart = chartRef.current;
    if (!chart) return;
    event.preventDefault();
    const startX = event.clientX;
    const startWidth = chart.priceScale('right').width();
    const onMove = (move: PointerEvent) => {
      const next = Math.max(0, Math.min(240, Math.round(startWidth + startX - move.clientX)));
      priceWidthRef.current = next;
      chart.priceScale('right').applyOptions({ minimumWidth: next });
      positionHandle();
    };
    const onUp = () => {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      document.body.style.cursor = '';
      try {
        if (priceWidthRef.current > 0) localStorage.setItem(PRICE_WIDTH_KEY, String(priceWidthRef.current));
        else localStorage.removeItem(PRICE_WIDTH_KEY);
      } catch {
        /* almacenamiento no disponible */
      }
    };
    document.body.style.cursor = 'col-resize';
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
  };

  const resetPriceWidth = () => {
    priceWidthRef.current = 0;
    chartRef.current?.priceScale('right').applyOptions({ minimumWidth: 0 });
    try {
      localStorage.removeItem(PRICE_WIDTH_KEY);
    } catch {
      /* almacenamiento no disponible */
    }
    requestAnimationFrame(positionHandle);
  };

  useEffect(() => {
    const container = chartContainerRef.current;
    const shell = wrapRef.current;
    if (!container || !shell) return;
    const chart = createChart(container, {
      width: container.clientWidth,
      height,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: '#8293a9',
        fontFamily: "'Inter', system-ui, sans-serif",
        fontSize: 10,
      },
      grid: {
        vertLines: { color: 'rgba(255,255,255,0.028)' },
        horzLines: { color: 'rgba(255,255,255,0.028)' },
      },
      rightPriceScale: {
        borderColor: '#19232f',
        scaleMargins: { top: 0.06, bottom: 0.24 },
        minimumWidth: savedPriceWidth(),
      },
      timeScale: {
        borderColor: '#19232f',
        timeVisible: true,
        secondsVisible: true,
        rightOffset: 4,
        barSpacing: BAR_SPACING,
        fixLeftEdge: false,
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: 'rgba(63,140,255,0.35)', width: 1, style: LineStyle.Dashed, labelBackgroundColor: '#1d2a39' },
        horzLine: { color: 'rgba(63,140,255,0.35)', width: 1, style: LineStyle.Dashed, labelBackgroundColor: '#1d2a39' },
      },
      localization: {
        timeFormatter: (time: any) => dateTimeET(Number(time)),
        priceFormatter: (p: number) => p.toFixed(2),
      },
      handleScroll: true,
      handleScale: true,
    });

    const candle = chart.addCandlestickSeries({
      upColor: '#18c37e',
      downColor: '#f6465d',
      wickUpColor: '#18c37e',
      wickDownColor: '#f6465d',
      borderVisible: false,
      priceLineVisible: false,
      lastValueVisible: true,
      priceFormat: { type: 'price', precision: 2, minMove: 0.25 },
    });

    const volume = chart.addHistogramSeries({
      priceFormat: { type: 'volume' },
      priceScaleId: '',
      lastValueVisible: false,
      priceLineVisible: false,
    });
    volume.priceScale().applyOptions({ scaleMargins: { top: 0.84, bottom: 0 } });

    const vwapLine = chart.addLineSeries({
      color: '#e0b64a',
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
      priceFormat: { type: 'price', precision: 2, minMove: 0.25 },
    });

    const atrLine = chart.addLineSeries({
      color: '#a78bfa',
      lineWidth: 1,
      priceScaleId: 'atr',
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    });
    chart.priceScale('atr').applyOptions({ scaleMargins: { top: 0.82, bottom: 0.02 }, visible: false });

    chartRef.current = chart;
    priceWidthRef.current = savedPriceWidth();
    candleRef.current = candle;
    volumeRef.current = volume;
    vwapRef.current = vwapLine;
    atrRef.current = atrLine;

    const observer = new ResizeObserver(() => {
      if (!wrapRef.current) return;
      chart.applyOptions({ width: wrapRef.current.clientWidth, height });
      requestAnimationFrame(positionHandle);
      drawRef.current();
    });
    observer.observe(shell);
    chart.timeScale().subscribeVisibleTimeRangeChange(() => drawRef.current());

    return () => {
      observer.disconnect();
      chart.remove();
      chartRef.current = null;
      candleRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const chart = chartRef.current;
    const candle = candleRef.current;
    const volume = volumeRef.current;
    if (!chart || !candle || !volume) return;

    const agg = aggregate(bars, timeframe);
    const previousRange = chart.timeScale().getVisibleRange();
    const previousCount = barsCountRef.current;
    candle.setData(
      agg.map((b) => ({
        time: b.t as UTCTimestamp,
        open: b.o,
        high: b.h,
        low: b.l,
        close: b.c,
      })),
    );
    volume.setData(
      agg.map((b) => ({
        time: b.t as UTCTimestamp,
        value: b.v,
        color: b.c >= b.o ? 'rgba(24,195,126,0.32)' : 'rgba(246,70,93,0.32)',
      })),
    );
    barsCountRef.current = agg.length;
    if (previousRange && agg.length - previousCount > 50) {
      // Al cargar el historial se anteponen velas: conserva el encuadre actual.
      chart.timeScale().setVisibleRange(previousRange);
    }

    if (vwapRef.current) {
      vwapRef.current.setData(showVwap ? vwap(agg).map((p) => ({ time: p.t as UTCTimestamp, value: p.value })) : []);
    }
    if (atrRef.current) {
      atrRef.current.setData(showAtr ? atr(agg, 14).map((p) => ({ time: p.t as UTCTimestamp, value: p.value })) : []);
    }

    priceLinesRef.current.forEach((line) => {
      try {
        candle.removePriceLine(line);
      } catch {
        /* ya eliminada */
      }
    });
    priceLinesRef.current = [];
    const addLine = (price: number, color: string, title: string, style: LineStyle = LineStyle.Dashed) => {
      const line = candle.createPriceLine({
        price,
        color,
        lineWidth: 1,
        lineStyle: style,
        axisLabelVisible: true,
        title,
      });
      priceLinesRef.current.push(line);
    };
    if (openingRange) {
      addLine(openingRange.high, 'rgba(63,140,255,0.85)', 'ORH');
      addLine(openingRange.low, 'rgba(63,140,255,0.55)', 'ORL');
      addLine(openingRange.mid, 'rgba(140,170,205,0.55)', '50%');
    }
    if (position) {
      addLine(position.entry_price, '#3f8cff', 'ENT', LineStyle.Solid);
      addLine(position.stop, '#f6465d', 'SL');
      addLine(position.target, '#18c37e', 'TP');
    }

    const colorFor = (m: Marker): string => {
      if (m.type === 'smt') return '#a78bfa';
      if (m.type === 'trade_exit') return m.label.includes('TP') ? '#18c37e' : '#f6465d';
      if (m.type === 'retest') return '#5aa9ff';
      if (m.type === 'false_breakout') return '#f3a83b';
      return m.direction === 'short' || m.direction === 'bearish' ? '#f6465d' : '#18c37e';
    };
    const sorted = [...markers].filter((m) => m.ts >= (agg[0]?.t ?? 0)).sort((a, b) => a.ts - b.ts);
    const unique: Marker[] = [];
    const seen = new Set<string>();
    for (const m of sorted) {
      const key = `${m.ts}-${m.type}-${m.label}`;
      if (seen.has(key)) continue;
      seen.add(key);
      unique.push(m);
    }
    try {
      candle.setMarkers(
        unique.map((m) => ({
          time: m.ts as UTCTimestamp,
          position: m.direction === 'short' || m.direction === 'bearish' ? ('aboveBar' as const) : ('belowBar' as const),
          color: colorFor(m),
          shape: m.type === 'smt' ? ('circle' as const) : m.type === 'trade_exit' ? ('square' as const) : ('arrowUp' as const),
          text: SHORT_LABEL[m.type] || m.label.slice(0, 14),
        })),
      );
    } catch {
      candle.setMarkers([]);
    }

    if (tfRef.current !== timeframe) {
      tfRef.current = timeframe;
      fittedRef.current = false;
    }
    if (!fittedRef.current && agg.length) {
      // El historial puede contener muchas sesiones: encuadra solo la sesión
      // actual para no convertir el gráfico en una línea ilegible.
      const focus = focusStart && focusStart > agg[0].t ? focusStart : null;
      if (focus) {
        chart.timeScale().setVisibleRange({
          from: focus as UTCTimestamp,
          to: (agg[agg.length - 1].t + timeframe * 60) as UTCTimestamp,
        });
      } else {
        chart.timeScale().fitContent();
      }
      chart.timeScale().applyOptions({ barSpacing: BAR_SPACING });
      fittedRef.current = true;
    }
    requestAnimationFrame(() => {
      positionHandle();
      drawRef.current();
    });
  }, [bars, focusStart, timeframe, openingRange, markers, position, showVwap, showAtr]);

  const draw = () => {
    const canvas = canvasRef.current;
    const chart = chartRef.current;
    const series = candleRef.current;
    const container = wrapRef.current;
    if (!canvas || !chart || !series || !container) return;
    const dpr = window.devicePixelRatio || 1;
    const width = container.clientWidth;
    const h = container.clientHeight;
    if (canvas.width !== Math.round(width * dpr) || canvas.height !== Math.round(h * dpr)) {
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(h * dpr);
    }
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, h);

    const xOf = (ts: number) => chart.timeScale().timeToCoordinate(ts as UTCTimestamp);
    const yOf = (price: number) => series.priceToCoordinate(price);
    const agg = aggregate(bars, timeframe);
    const last = agg[agg.length - 1];

    // Zona del Opening Range
    if (openingRange && last) {
      const x1 = xOf(openingRange.start_ts);
      const x2 = xOf(openingRange.end_ts);
      const yH = yOf(openingRange.high);
      const yL = yOf(openingRange.low);
      if (x1 !== null && x2 !== null && yH !== null && yL !== null) {
        const left = Math.min(x1, x2);
        const right = Math.max(x1, x2);
        ctx.fillStyle = 'rgba(63,140,255,0.07)';
        ctx.fillRect(left, yH, Math.max(right - left, 1), Math.max(yL - yH, 1));
        ctx.strokeStyle = 'rgba(63,140,255,0.32)';
        ctx.lineWidth = 1;
        ctx.setLineDash([4, 4]);
        ctx.strokeRect(left + 0.5, yH + 0.5, Math.max(right - left - 1, 1), Math.max(yL - yH - 1, 1));
        ctx.setLineDash([]);
        ctx.fillStyle = 'rgba(156,196,255,0.8)';
        ctx.font = '600 9px Inter, sans-serif';
        ctx.fillText('OPENING RANGE', left + 7, yH + 13);
      }
    }

    // Zona de retesteo alrededor de la referencia configurada
    if (referenceLevel && last) {
      const startTs = openingRange ? openingRange.end_ts : agg[0]?.t;
      const x1 = startTs ? xOf(startTs) : null;
      const x2 = xOf(last.t);
      const y = yOf(referenceLevel);
      if (x1 !== null && x2 !== null && y !== null) {
        const band = 4;
        ctx.fillStyle = 'rgba(167,139,250,0.10)';
        ctx.fillRect(Math.min(x1, x2), y - band, Math.max(Math.abs(x2 - x1), 1), band * 2);
        ctx.strokeStyle = 'rgba(167,139,250,0.35)';
        ctx.setLineDash([2, 5]);
        ctx.beginPath();
        ctx.moveTo(Math.min(x1, x2), y);
        ctx.lineTo(Math.max(x1, x2), y);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = 'rgba(196,181,253,0.85)';
        ctx.font = '600 9px Inter, sans-serif';
        ctx.fillText('ZONA DE RETESTEO', Math.min(x1, x2) + 7, y - 7);
      }
    }

    // Zonas de riesgo y beneficio de la posición abierta
    if (position && last) {
      const x1 = xOf(position.entry_ts);
      const x2 = xOf(last.t);
      const yEntry = yOf(position.entry_price);
      const yTp = yOf(position.target);
      const ySl = yOf(position.stop);
      if (x1 !== null && x2 !== null && yEntry !== null && yTp !== null && ySl !== null) {
        const start = Math.min(x1, x2);
        const right = Math.max(x1, x2) + 6;
        ctx.fillStyle = 'rgba(24,195,126,0.10)';
        ctx.fillRect(start, Math.min(yEntry, yTp), Math.max(right - start, 1), Math.abs(yTp - yEntry));
        ctx.fillStyle = 'rgba(246,70,93,0.10)';
        ctx.fillRect(start, Math.min(yEntry, ySl), Math.max(right - start, 1), Math.abs(ySl - yEntry));
        ctx.strokeStyle = 'rgba(63,140,255,0.5)';
        ctx.setLineDash([3, 3]);
        ctx.beginPath();
        ctx.moveTo(start, yEntry);
        ctx.lineTo(right, yEntry);
        ctx.stroke();
        ctx.setLineDash([]);
      }
    }
    positionHandle();
  };
  drawRef.current = draw;

  return (
    <div className="chart-shell" ref={wrapRef} style={{ height }}>
      <div ref={chartContainerRef} style={{ position: 'absolute', inset: 0 }} />
      <canvas ref={canvasRef} className="chart-overlay" style={{ width: '100%', height: '100%' }} />
      <div
        ref={handleRef}
        className="chart-price-handle"
        role="separator"
        aria-orientation="vertical"
        aria-label="Ancho de la columna de precios"
        title="Arrastra para expandir o contraer la columna de precios · doble clic para restablecer"
        onPointerDown={startPriceResize}
        onDoubleClick={resetPriceWidth}
      />
      {bars.length > 0 && (
        <div className="chart-time-stamp" title="Fecha y hora de la última vela mostrada">
          <span>Última vela</span>
          <strong>{dateTimeET(bars[bars.length - 1].t)}</strong>
        </div>
      )}
      {!bars.length && (
        <div className="chart-empty" style={{ position: 'absolute', inset: 0 }}>
          Esperando velas de la sesión…
          <br />
          <span style={{ fontSize: 10 }}>El motor entrega datos por WebSocket en tiempo real.</span>
        </div>
      )}
    </div>
  );
}
