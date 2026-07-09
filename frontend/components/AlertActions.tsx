"use client";

import { useState } from "react";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

type Props = {
  alertId: string;
  initialStatus: string;
};

export function AlertActions({ alertId, initialStatus }: Props) {
  const [status, setStatus] = useState(initialStatus);
  const [pending, setPending] = useState<string | null>(null);

  async function update(nextStatus: "ack" | "resolved" | "open") {
    setPending(nextStatus);
    const response = await fetch(`${API_BASE_URL}/alerts/${alertId}`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ status: nextStatus, operator: "dashboard" }),
    });
    if (response.ok) {
      setStatus(nextStatus);
    }
    setPending(null);
  }

  return (
    <div className="button-row" aria-label={`Alert status ${status}`}>
      <button disabled={pending !== null || status === "ack"} onClick={() => update("ack")}>
        Ack
      </button>
      <button
        className="primary"
        disabled={pending !== null || status === "resolved"}
        onClick={() => update("resolved")}
      >
        Close
      </button>
    </div>
  );
}
