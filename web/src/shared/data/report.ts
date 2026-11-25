import { useCallback, useEffect, useState } from "react";

export interface Metrics {
  [key: string]: number;
  gpu_utilisation: number;
  idle_reserved_node_h: number;
  lent_node_h: number;
  reservations_rejected: number;
  moved_to_other_region: number;
  sla_short_share: number;
  reservations_short: number;
  reclaimed: number;
  wrongful_reclaims: number;
  preempted_node_h: number;
  legit_served_share: number;
  jain_contested: number;
  quota_decision_p90_h: number;
  quota_decision_p50_h: number;
  auto_decision_rate: number;
  abusive_approved: number;
  legit_denied: number;
  unpaid_node_h: number;
  revenue: number;
  reserved_used_node_h: number;
  ondemand_served_node_h: number;
  abusive_served_node_h: number;
  capacity_node_h: number;
  reservations_requested: number;
  sla_short_node_h: number;
}

export interface Gate {
  gate: string;
  value: number;
  limit: number;
  kind: "max" | "min";
  pass: boolean;
}

export interface FaultVariant {
  scenarios_broken: number;
  share_broken: number;
  by_kind: Record<string, number>;
}

export interface Split {
  designs: Record<string, Metrics>;
  labels: Record<string, string>;
  descriptions: Record<string, string>;
  faults: { scenarios: number; variants: Record<string, FaultVariant> };
  gates: { platform: Gate[]; platform_pass: boolean };
  per_seed: Array<{ seed: number } & Record<string, Metrics | number>>;
  sites: Array<{ seed: number; reservations: number; requests: number; orgs: number; nodes: number }>;
  days: number;
}

export interface Report {
  dev: Split;
  heldout: Split | null;
  fault_labels: Record<string, string>;
  fault_kinds: Record<string, string>;
}

export type Load = { state: "loading" } | { state: "error"; message: string } | { state: "ready"; report: Report };

export function isReport(x: unknown): x is Report {
  const r = x as Report;
  return !!r && typeof r === "object" && !!r.dev && typeof r.dev.designs === "object" && !!r.dev.designs.platform && !!r.dev.faults;
}

export function useReport(url = "data/report.json"): { load: Load; retry: () => void } {
  const [load, setLoad] = useState<Load>({ state: "loading" });
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let live = true;
    setLoad({ state: "loading" });
    fetch(url)
      .then((r) => {
        if (!r.ok) throw new Error(`The report could not be loaded (HTTP ${r.status}).`);
        return r.json();
      })
      .then((j: unknown) => {
        if (!live) return;
        if (!isReport(j)) throw new Error("The report file is not in the expected shape. Regenerate it with python -m gqc.cli report.");
        setLoad({ state: "ready", report: j });
      })
      .catch((e: Error) => live && setLoad({ state: "error", message: e.message }));
    return () => {
      live = false;
    };
  }, [url, attempt]);
  const retry = useCallback(() => setAttempt((a) => a + 1), []);
  return { load, retry };
}
