export const pct = (x: number | null | undefined, d = 1) => (x == null ? "–" : `${(100 * x).toFixed(d)}%`);
export const num = (x: number | null | undefined, d = 0) =>
  x == null ? "–" : x.toLocaleString("en-GB", { minimumFractionDigits: d, maximumFractionDigits: d });
export const eurK = (x: number | null | undefined) => (x == null ? "–" : `€${Math.round(x / 1000).toLocaleString("en-GB")}k`);
export const hours = (x: number | null | undefined) => (x == null ? "–" : x < 1 ? `${Math.round(x * 60)} min` : `${x.toFixed(1)} h`);
