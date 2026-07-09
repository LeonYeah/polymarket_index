"use client";

import { FormEvent, useState } from "react";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

type Props = {
  kind: "wallet" | "market";
  targetId: string;
};

export function WatchlistForm({ kind, targetId }: Props) {
  const [label, setLabel] = useState("");
  const [reason, setReason] = useState("");
  const [status, setStatus] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setStatus("saving");
    const path = kind === "wallet" ? "/watchlist/wallets" : "/watchlist/markets";
    const body =
      kind === "wallet"
        ? { wallet_address: targetId, label, reason, operator: "dashboard" }
        : { condition_id: targetId, label, reason, operator: "dashboard" };
    const response = await fetch(`${API_BASE_URL}${path}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    });
    setStatus(response.ok ? "saved" : "failed");
  }

  return (
    <form className="form-row" onSubmit={submit}>
      <input
        aria-label="Label"
        maxLength={200}
        onChange={(event) => setLabel(event.target.value)}
        placeholder="Label"
        value={label}
      />
      <input
        aria-label="Reason"
        maxLength={500}
        onChange={(event) => setReason(event.target.value)}
        placeholder="Reason"
        value={reason}
      />
      <button className="primary" type="submit">
        {status === "saving" ? "Saving" : status === "saved" ? "Saved" : "Watch"}
      </button>
    </form>
  );
}
