"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

export function AlertGenerationButton() {
  const router = useRouter();
  const [pending, setPending] = useState(false);
  const [failed, setFailed] = useState(false);

  async function generate() {
    setPending(true);
    setFailed(false);
    const response = await fetch(`${API_BASE_URL}/alerts/generate`, { method: "POST" });
    if (response.ok) {
      router.refresh();
    } else {
      setFailed(true);
    }
    setPending(false);
  }

  return (
    <button className={failed ? "warn" : ""} disabled={pending} onClick={generate} type="button">
      {pending ? "Running" : failed ? "Retry rules" : "Run rules"}
    </button>
  );
}
