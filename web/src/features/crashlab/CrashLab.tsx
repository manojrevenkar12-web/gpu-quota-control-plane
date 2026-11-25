import type { Report, Split } from "../../shared/data/report";
import { num } from "../../shared/format";
import styles from "./crashlab.module.css";

const ORDER = ["platform", "no_cas", "no_idempotency", "no_outbox", "no_inbox"];

export function CrashLab({ split, report }: { split: Split; report: Report }) {
  const f = split.faults;
  const kinds = Array.from(new Set(Object.values(f.variants).flatMap((v) => Object.keys(v.by_kind)))).sort();
  if (!Object.keys(f.variants).length) return <p>No lab results in this report.</p>;
  return (
    <div className={styles.wrap}>
      <table className={styles.table}>
        <caption className={styles.caption}>{num(f.scenarios)} scenarios per variant; a cell counts the scenarios where that invariant broke.</caption>
        <thead>
          <tr>
            <th scope="col">Saga</th>
            <th scope="col">Broken</th>
            {kinds.map((k) => (
              <th scope="col" key={k} className={styles.kind}>
                {report.fault_kinds[k] ?? k}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {ORDER.filter((v) => f.variants[v]).map((v) => {
            const row = f.variants[v]!;
            return (
              <tr key={v} className={v === "platform" ? styles.us : undefined}>
                <th scope="row">{report.fault_labels[v] ?? v}</th>
                <td className={styles.total}>{num(row.scenarios_broken)}</td>
                {kinds.map((k) => {
                  const n = row.by_kind[k] ?? 0;
                  const share = n / f.scenarios;
                  return (
                    <td
                      key={k}
                      className={styles.cell}
                      style={{ ["--w" as string]: `${Math.min(100, Math.round(share * 160))}%` }}
                      title={`${n} of ${f.scenarios}`}
                    >
                      {n ? num(n) : <span className={styles.none}>0</span>}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
