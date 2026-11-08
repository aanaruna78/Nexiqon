/** Nexiqon mark: inline SVG (no request, scales crisply, follows the theme). */
export function BrandMark({ className = "size-8" }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden="true" focusable="false">
      <defs>
        <linearGradient id="nx-mark" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#2bb3a3" />
          <stop offset="1" stopColor="#0b6f66" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="9" fill="url(#nx-mark)" />
      <path d="M10 22V10l12 12V10" fill="none" stroke="#fff" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx="22" cy="10" r="2.2" fill="#f2c66d" />
    </svg>
  );
}
