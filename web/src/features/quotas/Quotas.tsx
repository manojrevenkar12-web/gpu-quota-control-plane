import type { Split } from "../../shared/data/report";
import { hours, num, pct } from "../../shared/format";
import t from "../../shared/ui/table.module.css";

const DESIGNS = ["as_is", "manual_quotas", "auto_approve_all", "platform"];

export function Quotas({ split }: { split: Split }) {
  return (
    <div className={t.wrap}>
      <table className={t.table}>
        <thead>
          <tr>
            <th scope="col">Quota requests</th>
            <th scope="col">Decided without a person</th>
            <th scope="col">Time to decision, median</th>
            <th scope="col">Time to decision, p90</th>
            <th scope="col">Granted to abusive organisations</th>
            <th scope="col">Legitimate requests denied</th>
            <th scope="col">Node-hours nobody paid for</th>
          </tr>
        </thead>
        <tbody>
          {DESIGNS.map((n) => {
            const m = split.designs[n];
            if (!m) return null;
            return (
              <tr key={n} className={n === "platform" ? t.us : undefined}>
                <th scope="row">{split.labels[n]}</th>
                <td>{pct(m.auto_decision_rate, 0)}</td>
                <td>{hours(m.quota_decision_p50_h)}</td>
                <td>{hours(m.quota_decision_p90_h)}</td>
                <td className={m.abusive_approved > 1 ? t.fail : undefined}>{num(m.abusive_approved, 1)}</td>
                <td>{num(m.legit_denied, 1)}</td>
                <td>{num(m.unpaid_node_h)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
