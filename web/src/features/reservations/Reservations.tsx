import type { Split } from "../../shared/data/report";
import { num } from "../../shared/format";
import t from "../../shared/ui/table.module.css";

const DESIGNS = ["as_is", "no_rebalance", "no_reclaim", "platform"];

export function Reservations({ split }: { split: Split }) {
  return (
    <div className={t.wrap}>
      <table className={t.table}>
        <thead>
          <tr>
            <th scope="col">Per site, {split.days} days</th>
            <th scope="col">Requests</th>
            <th scope="col">Turned away</th>
            <th scope="col">Placed in another region, same GPU</th>
            <th scope="col">Unused, released after a notice</th>
            <th scope="col">Customers who came back to nothing</th>
          </tr>
        </thead>
        <tbody>
          {DESIGNS.map((n) => {
            const m = split.designs[n];
            if (!m) return null;
            return (
              <tr key={n} className={n === "platform" ? t.us : undefined}>
                <th scope="row">{split.labels[n]}</th>
                <td>{num(m.reservations_requested, 1)}</td>
                <td>{num(m.reservations_rejected, 1)}</td>
                <td>{num(m.moved_to_other_region, 1)}</td>
                <td>{num(m.reclaimed, 1)}</td>
                <td className={m.wrongful_reclaims > 0 ? t.fail : t.zero}>{num(m.wrongful_reclaims, 1)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
