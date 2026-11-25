import "@testing-library/jest-dom/vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import fixture from "../test/report.fixture.json";
import { segments } from "../features/hours/hours";
import type { Metrics } from "../shared/data/report";
import { App } from "./App";

function serve(body: unknown, ok = true, status = 200) {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => Promise.resolve({ ok, status, json: () => Promise.resolve(body) })),
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("console", () => {
  it("shows a loading state, then the report", async () => {
    serve(fixture);
    render(<App />);
    expect(screen.getByRole("status", { name: "Loading the report" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent("Of every 100 GPU node-hours");
    expect(screen.getByRole("heading", { name: "Where the node-hours went" })).toBeInTheDocument();
  });

  it("shows an error with a retry when the report is missing", async () => {
    serve({}, false, 404);
    render(<App />);
    expect(await screen.findByRole("alert")).toHaveTextContent("HTTP 404");
    serve(fixture);
    await userEvent.click(screen.getByRole("button", { name: "Load again" }));
    expect(await screen.findByRole("heading", { level: 1 })).toBeInTheDocument();
  });

  it("rejects a report of the wrong shape", async () => {
    serve({ dev: {} });
    render(<App />);
    expect(await screen.findByRole("alert")).toHaveTextContent("not in the expected shape");
  });

  it("compares the plane with an ablation", async () => {
    serve(fixture);
    render(<App />);
    const group = await screen.findByRole("group", { name: "Compare the control plane with" });
    const naive = within(group).getByRole("button", { name: "Lend all idle" });
    await userEvent.click(naive);
    expect(naive).toHaveAttribute("aria-pressed", "true");
  });

  it("lists every gate and the lab rows", async () => {
    serve(fixture);
    render(<App />);
    expect(await screen.findByText(/gates pass/)).toBeInTheDocument();
    expect(screen.getByText("Without the outbox (commit, then send)")).toBeInTheDocument();
  });

  it("accounts for every node-hour once", () => {
    const m = fixture.dev.designs.platform as unknown as Metrics;
    const total = segments(m).reduce((a, s) => a + s.value, 0);
    expect(Math.abs(total - m.capacity_node_h)).toBeLessThan(1);
  });
});
