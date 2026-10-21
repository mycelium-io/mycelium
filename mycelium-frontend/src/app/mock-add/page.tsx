"use client";

// Scratch page for the Add agent mockups: opens the dialog on the kind asked for.

import { useSearchParams } from "next/navigation";
import { Suspense, useEffect } from "react";
import { AddMemberDialog, type MemberKind } from "@/components/add-member-dialog";

function Open() {
  const q = useSearchParams();
  // A still shouldn't show the dialog's first focus ring.
  useEffect(() => {
    const t = setTimeout(() => (document.activeElement as HTMLElement | null)?.blur(), 400);
    return () => clearTimeout(t);
  }, []);
  return (
    <AddMemberDialog
      open
      onOpenChange={() => {}}
      roomName="checkout"
      initialKind={(q.get("kind") as MemberKind) ?? "machine"}
      mock={q.get("mock") ?? undefined}
    />
  );
}

export default function Page() {
  return (
    <Suspense>
      <Open />
    </Suspense>
  );
}
