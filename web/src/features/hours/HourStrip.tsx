import { motion, useReducedMotion } from "framer-motion";
import { useState } from "react";
import type { Split } from "../../shared/data/report";
import { num, pct } from "../../shared/format";
import styles from "./hours.module.css";
import { segments, type Segment } from "./hours";

function Strip({ name, label, split, delay }: { name: string; label: string; split: Split; delay: number }) {
  const m = split.designs[name];
  const reduce = useReducedMotion();
  const [tip, setTip] = useState<Segment | null>(null);
  if (!m) return null;
  const segs = segments(m);
  const total = segs.reduce((a, s) => a + s.value, 0) || 1;
  return (
    <figure className={styles.row} aria-label={`${label}: ${pct(m.gpu_utilisation)} of node-hours did work`}>
      <figcaption className={styles.rowHead}>
        <span className={styles.rowLabel}>{label}</span>
        <span className={styles.rowFigure}>{pct(m.gpu_utilisation)} did work</span>
      </figcaption>
      <div className={styles.track}>
        {segs.map((s, i) => (
          <motion.button
            type="button"
            key={s.key}
            className={`${styles.seg} ${styles[s.tone]}`}
            style={{ width: `${(100 * s.value) / total}%` }}
            initial={reduce ? false : { scaleX: 0 }}
            animate={{ scaleX: 1 }}
            transition={{ duration: 0.7, delay: delay + i * 0.08, ease: [0.2, 0.7, 0.2, 1] }}
            onMouseEnter={() => setTip(s)}
            onMouseLeave={() => setTip(null)}
            onFocus={() => setTip(s)}
            onBlur={() => setTip(null)}
            aria-label={`${s.label}: ${num(s.value)} node-hours, ${pct(s.value / total)}`}
          >
            {s.value / total > 0.09 && <span className={styles.segText}>{pct(s.value / total, 0)}</span>}
          </motion.button>
        ))}
      </div>
      <p className={styles.tip} aria-live="polite">
        {tip ? `${tip.label}: ${num(tip.value)} node-hours per site, ${pct(tip.value / total)} of the fleet` : " "}
      </p>
    </figure>
  );
}

export function HourStrip({ split }: { split: Split }) {
  const others = Object.keys(split.designs).filter((n) => n !== "platform" && n !== "as_is");
  const [against, setAgainst] = useState<string>("as_is");
  return (
    <div className={styles.wrap}>
      <ul className={styles.legend} aria-label="Legend">
        {segments(split.designs.platform ?? {}).map((s) => (
          <li key={s.key}>
            <span className={`${styles.swatch} ${styles[s.tone]}`} aria-hidden="true" />
            {s.label}
          </li>
        ))}
      </ul>
      <Strip key={against} name={against} label={split.labels[against] ?? against} split={split} delay={0} />
      <Strip name="platform" label={split.labels.platform ?? "Control plane"} split={split} delay={0.25} />
      <div className={styles.compare} role="group" aria-label="Compare the control plane with">
        <span>Compare with</span>
        {["as_is", ...others].map((n) => (
          <button key={n} type="button" aria-pressed={against === n} className={styles.chip} onClick={() => setAgainst(n)}>
            {split.labels[n] ?? n}
          </button>
        ))}
      </div>
    </div>
  );
}
