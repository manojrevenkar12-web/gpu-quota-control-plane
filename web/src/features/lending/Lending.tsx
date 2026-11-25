import type { Split } from "../../shared/data/report";
import { num, pct } from "../../shared/format";
import t from "../../shared/ui/table.module.css";
import styles from "./lending.module.css";

const ROWS = [
  ["no_lending", "Lend nothing"],
  ["platform", "Lend above a forecast and a buffer"],
  ["lend_naive", "Lend every idle node"],
] as const;

export function Lending({ split }: { split: Split }) {
  const max = Math.max(...ROWS.map(([n]) => split.designs[n]?.lent_node_h ?? 0), 1);
  return (
    <div className={t.wrap}>
      <table className={t.table}>
        <thead>
          <tr>
            <th scope="col">Policy</th>
            <th scope="col" className={styles.barCol}>
              Idle reserved node-hours lent to preemptible jobs
            </th>
            <th scope="col">Reserved use there when needed</th>
            <th scope="col">Reservations ever short</th>
            <th scope="col">Preemptible node-hours taken back</th>
          </tr>
        </thead>
        <tbody>
          {ROWS.map(([n, label]) => {
            const m = split.designs[n];
            if (!m) return null;
            return (
              <tr key={n} className={n === "platform" ? t.us : undefined}>
                <th scope="row">{label}</th>
                <td className={styles.barCol}>
                  <div className={styles.barCell}>
                    <span className={styles.bar} style={{ width: `${(80 * m.lent_node_h) / max}%` }} aria-hidden="true" />
                    <span className={styles.barValue}>{num(m.lent_node_h)}</span>
                  </div>
                </td>
                <td className={m.sla_short_share > 0.001 ? t.fail : undefined}>{pct(1 - m.sla_short_share, 3)}</td>
                <td>{num(m.reservations_short, 1)}</td>
                <td>{num(m.preempted_node_h)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
