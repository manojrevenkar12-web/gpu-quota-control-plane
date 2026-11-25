import type { Split } from "../../shared/data/report";
import { num, pct } from "../../shared/format";
import styles from "./fairness.module.css";

const DESIGNS = ["as_is", "fifo_allocation", "platform"];

export function Fairness({ split }: { split: Split }) {
  return (
    <div className={styles.grid}>
      {DESIGNS.map((n) => {
        const m = split.designs[n];
        if (!m) return null;
        return (
          <div key={n} className={styles.row}>
            <span className={styles.label}>{split.labels[n]}</span>
            <span className={styles.track} aria-hidden="true">
              <span className={styles.fill} style={{ width: `${100 * m.jain_contested}%` }} />
            </span>
            <span className={styles.value}>
              {num(m.jain_contested, 2)} <span className={styles.sub}>({pct(m.legit_served_share, 0)} of demand served)</span>
            </span>
          </div>
        );
      })}
    </div>
  );
}
