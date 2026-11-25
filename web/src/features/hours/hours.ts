import type { Metrics } from "../../shared/data/report";

export interface Segment {
  key: string;
  label: string;
  value: number;
  tone: "reserved" | "selfserve" | "abuse" | "idle" | "empty";
}

/** Every node-hour of the fleet, once: in use by a reservation, by a paying self-serve job, by a job nobody pays for,
 * held idle for a reservation, or empty. */
export function segments(m: Partial<Metrics>): Segment[] {
  const reserved = m.reserved_used_node_h ?? 0;
  const abuse = m.abusive_served_node_h ?? 0;
  const selfserve = Math.max(0, (m.ondemand_served_node_h ?? 0) - abuse);
  const idle = m.idle_reserved_node_h ?? 0;
  const empty = Math.max(0, (m.capacity_node_h ?? 0) - reserved - selfserve - abuse - idle);
  return [
    { key: "reserved", label: "Reservations in use", value: reserved, tone: "reserved" },
    { key: "selfserve", label: "Self-serve jobs that pay", value: selfserve, tone: "selfserve" },
    { key: "abuse", label: "Jobs nobody pays for", value: abuse, tone: "abuse" },
    { key: "idle", label: "Reserved, sitting idle", value: idle, tone: "idle" },
    { key: "empty", label: "Empty", value: empty, tone: "empty" },
  ];
}
