import { useState } from "react";
import { CrashLab } from "../features/crashlab/CrashLab";
import { Fairness } from "../features/fairness/Fairness";
import { Gates } from "../features/gates/Gates";
import { HourStrip } from "../features/hours/HourStrip";
import { Lending } from "../features/lending/Lending";
import { Quotas } from "../features/quotas/Quotas";
import { Reservations } from "../features/reservations/Reservations";
import { useReport, type Report } from "../shared/data/report";
import { pct } from "../shared/format";
import { Section } from "../shared/ui/Section";
import { EmptyState, ErrorState, Skeleton } from "../shared/ui/States";
import styles from "./App.module.css";

function Body({ report }: { report: Report }) {
  const [which, setWhich] = useState<"dev" | "heldout">("dev");
  const split = which === "heldout" && report.heldout ? report.heldout : report.dev;
  const a = split.designs.as_is;
  const p = split.designs.platform;
  const site = split.sites[0];
  return (
    <>
      <header className={styles.hero}>
        <p className={styles.kicker}>GPU quota control plane</p>
        <h1 className={styles.title}>
          Of every 100 GPU node-hours, {a ? Math.round(100 * a.gpu_utilisation) : "–"} did work as found. With the control plane,{" "}
          {p ? Math.round(100 * p.gpu_utilisation) : "–"} did.
        </h1>
        <p className={styles.lede}>
          Reservations that sit idle are lent to preemptible jobs and taken back before the customer needs them, reservations nobody starts are released after a
          notice, flexible customers are placed in another region, and quota requests are scored instead of queued. Measured on simulated sites
          {site ? ` of ${site.nodes} nodes over ${split.days} days` : ""}; the numbers below come from <code>reports/{which}.json</code>.
        </p>
        <div className={styles.splits} role="group" aria-label="Which sites">
          <button type="button" aria-pressed={which === "dev"} onClick={() => setWhich("dev")}>
            Development sites
          </button>
          <button type="button" aria-pressed={which === "heldout"} disabled={!report.heldout} onClick={() => setWhich("heldout")}>
            Held-out sites, run once
          </button>
        </div>
      </header>
      <main>
        <Section
          id="hours"
          title="Where the node-hours went"
          intro="Each bar is the whole fleet for the whole run. Hover or tab to a segment for its node-hours."
        >
          <HourStrip split={split} />
        </Section>
        <Section
          id="lending"
          title="Lending idle reserved nodes, and taking them back"
          intro="A node lent to a preemptible job comes back within one 15-minute step. Lending above a forecast and a buffer keeps that step from leaving the customer short."
        >
          <Lending split={split} />
        </Section>
        <Section
          id="reservations"
          title="Reservations: placed, moved, released"
          intro="Moves only between regions with the same GPU type, and only for customers who said they accept it."
        >
          <Reservations split={split} />
        </Section>
        <Section
          id="quotas"
          title="Quota requests"
          intro="A score from account signals and metering approves modest, low-risk requests at once. Everything else waits for an analyst working office hours."
        >
          <Quotas split={split} />
        </Section>
        <Section
          id="fairness"
          title="Sharing contested capacity"
          intro={`Jain's index over the share of demand each legitimate organisation got when the pool ran out (1 = everyone the same). Weighted max-min fair share against first come, first served; ${pct(p?.legit_served_share, 0)} of demand served with the plane.`}
        >
          <Fairness split={split} />
        </Section>
        <Section
          id="crash"
          title="The saga under crashes, retries and duplicates"
          intro="Clients reserve one small cluster at once while steps interleave at random, workers die mid-step and messages arrive twice and out of order. Each row removes one safeguard."
        >
          <CrashLab split={split} report={report} />
        </Section>
        <Section id="gates" title="Release gates" intro="Set on the development sites before the held-out run, and not loosened after it.">
          <Gates split={split} />
        </Section>
      </main>
      <footer className={styles.footer}>
        Simulated: the customers, their usage, the abuse and the prices are generated. The saga, the store and the API are real code. See the README for the
        limits.
      </footer>
    </>
  );
}

export function App() {
  const { load, retry } = useReport();
  return (
    <div className={styles.page}>
      {load.state === "loading" && <Skeleton lines={5} label="Loading the report" />}
      {load.state === "error" && <ErrorState message={load.message} onRetry={retry} />}
      {load.state === "ready" &&
        (Object.keys(load.report.dev.designs).length ? (
          <Body report={load.report} />
        ) : (
          <EmptyState title="The report has no designs yet.">Run python -m gqc.cli dev to measure them.</EmptyState>
        ))}
    </div>
  );
}
