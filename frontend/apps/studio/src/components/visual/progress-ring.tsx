import type { CSSProperties } from "react";

/** Animated SVG ring; the value is also given as text for assistive technology. */
export function ProgressRing({ value, total, label, size = 88 }: { value: number; total: number; label: string; size?: number }) {
  const stroke = 8;
  const r = (size - stroke) / 2;
  const length = 2 * Math.PI * r;
  const ratio = total ? value / total : 0;
  return (
    <div className="relative inline-flex items-center justify-center" style={{ width: size, height: size }} role="img" aria-label={label}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="-rotate-90" aria-hidden="true">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--muted)" strokeWidth={stroke} />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="var(--primary)"
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={length}
          strokeDashoffset={length * (1 - ratio)}
          style={{ "--ring-length": `${length}px`, animation: "nx-ring 900ms cubic-bezier(0.2,0.8,0.2,1) both" } as CSSProperties}
        />
      </svg>
      <span className="absolute text-lg font-semibold tabular-nums" aria-hidden="true">
        {value}/{total}
      </span>
    </div>
  );
}
