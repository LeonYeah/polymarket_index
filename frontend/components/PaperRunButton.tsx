"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

export function PaperRunButton() {
  const router = useRouter();
  const [state, setState] = useState<"idle" | "running" | "failed">("idle");

  async function runCycle() {
    setState("running");
    try {
      const response = await fetch(`${API_BASE_URL}/paper/run`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ order_type: "FAK", lookback_minutes: 60 }),
      });
      if (!response.ok) {
        setState("failed");
        return;
      }
      setState("idle");
      router.refresh();
    } catch {
      setState("failed");
    }
  }

  return (
    <button className="primary" disabled={state === "running"} onClick={runCycle} type="button">
      {state === "running" ? "Running paper cycle" : state === "failed" ? "Retry cycle" : "Run paper cycle"}
    </button>
  );
}
