// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { Check } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { versionLink } from "@/lib/desktop";
import { cn } from "@/lib/utils";

/** A settings page: a title that stays put while the page scrolls, the one
 *  line saying where these settings are kept, and the page's own actions. */
export function SettingsPage({
  title,
  scope,
  actions,
  children,
}: {
  title: ReactNode;
  scope: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="min-w-0 flex-1">
      <div className="sticky top-0 z-10 flex items-start gap-3 border-b border-border bg-bg/95 px-4 py-4 backdrop-blur sm:px-8">
        <div className="min-w-0">
          <h1 className="text-body font-medium text-text">{title}</h1>
          <p className="mt-0.5 text-micro text-muted-foreground">{scope}</p>
        </div>
        {actions && <div className="ml-auto flex flex-shrink-0 items-center gap-2">{actions}</div>}
      </div>
      <div className="max-w-3xl px-4 pb-16 sm:px-8">{children}</div>
    </div>
  );
}

export function Section({ title, children, note }: { title: string; children: ReactNode; note?: ReactNode }) {
  return (
    <section className="mt-7">
      <h2 className="mb-1 text-micro font-semibold uppercase tracking-wide text-faint">{title}</h2>
      {note && <p className="mb-2 text-micro text-muted-foreground">{note}</p>}
      <div className="divide-y divide-border rounded-xl border border-border">{children}</div>
    </section>
  );
}

/** One setting. `id` is its anchor, so `settingHref` can land on it; a row the
 *  person changed shows a dot and a way back to the default. */
export function Row({
  id,
  label,
  help,
  children,
  changed = false,
  onReset,
  defaultLabel,
  tag,
  below,
}: {
  id?: string;
  label: ReactNode;
  help?: ReactNode;
  children?: ReactNode;
  changed?: boolean;
  onReset?: () => void;
  /** The default, said in the reset link: "Reset to default (Enter)". */
  defaultLabel?: string;
  /** A short tag for a row that differs from its page, like "from the hub". */
  tag?: string;
  /** Anything that belongs under the row across its full width (a confirm). */
  below?: ReactNode;
}) {
  const lit = useLitAnchor(id);
  return (
    <div
      id={id}
      className={cn(
        "scroll-mt-24 px-4 py-3 transition-colors duration-700",
        lit && "bg-accent-soft",
      )}
    >
      <div className="flex flex-wrap items-start gap-x-6 gap-y-2">
        <div className="min-w-0 flex-1 basis-64">
          <div className="flex items-center gap-2 text-label text-text">
            {changed && <span aria-label="Changed" className="size-1.5 flex-shrink-0 rounded-full bg-accent" />}
            {label}
            {tag && (
              <span className="rounded border border-border px-1.5 text-[11px] leading-4 text-muted-foreground">
                {tag}
              </span>
            )}
          </div>
          {help && <p className="mt-0.5 text-micro leading-relaxed text-muted-foreground">{help}</p>}
          {changed && onReset && (
            <button type="button" onClick={onReset} className="mt-1 text-micro text-accent hover:underline">
              Reset to default{defaultLabel ? ` (${defaultLabel})` : ""}
            </button>
          )}
        </div>
        {children && <div className="flex flex-shrink-0 items-center gap-2">{children}</div>}
      </div>
      {below}
    </div>
  );
}

/** Whether the page was opened at this row's anchor, for a moment. */
function useLitAnchor(id: string | undefined): boolean {
  const [lit, setLit] = useState(false);
  useEffect(() => {
    if (!id) return;
    const check = () => {
      if (window.location.hash.slice(1) !== id) return;
      document.getElementById(id)?.scrollIntoView({ block: "center" });
      setLit(true);
      window.setTimeout(() => setLit(false), 1800);
    };
    check();
    window.addEventListener("hashchange", check);
    return () => window.removeEventListener("hashchange", check);
  }, [id]);
  return lit;
}

export function Toggle({
  checked,
  onChange,
  label,
  disabled,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  label: string;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        "relative h-5 w-9 flex-shrink-0 rounded-full border transition-colors outline-none focus-visible:ring-2 focus-visible:ring-accent/40 disabled:opacity-40",
        checked ? "border-accent bg-accent" : "border-border2 bg-surface",
      )}
    >
      <span
        className={cn(
          "absolute top-0.5 size-3.5 rounded-full transition-all",
          checked ? "left-[18px] bg-bg" : "left-0.5 bg-muted-foreground",
        )}
      />
    </button>
  );
}

/** One choice from a few, side by side. */
export function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: readonly { value: T; label: ReactNode }[];
  onChange: (next: T) => void;
  label: string;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="flex rounded-md border border-border p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={o.value === value}
          onClick={() => onChange(o.value)}
          className={cn(
            "rounded px-2.5 py-1 text-label transition-colors",
            o.value === value ? "bg-surface text-text" : "text-muted-foreground hover:text-text",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** Several choices that can all be on: a check mark says each one is. */
export function CheckChips({
  value,
  options,
  onChange,
  label,
}: {
  value: readonly string[];
  options: readonly { value: string; label: string }[];
  onChange: (next: string[]) => void;
  label: string;
}) {
  return (
    <div role="group" aria-label={label} className="flex flex-wrap gap-1.5">
      {options.map((o) => {
        const on = value.includes(o.value);
        return (
          <button
            key={o.value}
            type="button"
            aria-pressed={on}
            onClick={() => onChange(on ? value.filter((v) => v !== o.value) : [...value, o.value])}
            className={cn(
              "flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-label transition-colors",
              on ? "border-accent/40 bg-accent-soft text-accent" : "border-border text-muted-foreground hover:bg-surface",
            )}
          >
            {on && <Check className="size-3" />}
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

/** A change that asks first, said under the row it belongs to. */
export function Confirm({
  title,
  children,
  confirmLabel,
  onConfirm,
  onCancel,
  busy,
}: {
  title: string;
  children: ReactNode;
  confirmLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
  busy?: boolean;
}) {
  return (
    <div role="alertdialog" aria-label={title} className="mt-3 rounded-lg border border-yellow/40 bg-yellow/5 px-3 py-2.5">
      <p className="text-label font-medium text-text">{title}</p>
      <div className="mt-0.5 text-micro leading-relaxed text-muted-foreground">{children}</div>
      <div className="mt-2 flex gap-2">
        <button
          type="button"
          onClick={onConfirm}
          disabled={busy}
          className="rounded-md bg-accent px-2.5 py-1 text-label font-medium text-accent-fg disabled:opacity-50"
        >
          {confirmLabel}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded-md border border-border px-2.5 py-1 text-label text-text hover:bg-surface"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

/** Beside the app's own hub's version: opens the app's Settings at Version,
 *  where it switches to another release or a release candidate. */
export function ChangeVersion() {
  return (
    <a href={versionLink()} className="ml-3 text-label text-accent hover:underline">
      Change version…
    </a>
  );
}

/** A read-only value; amber only when it is a real risk. */
export function Value({ children, risk = false, mono = false }: { children: ReactNode; risk?: boolean; mono?: boolean }) {
  return (
    <span className={cn("text-label", mono && "font-mono text-micro", risk ? "text-yellow" : "text-text")}>
      {children}
    </span>
  );
}

export function Note({ children, tone = "info" }: { children: ReactNode; tone?: "info" | "error" }) {
  return (
    <p
      role={tone === "error" ? "alert" : undefined}
      className={cn("mt-2 text-micro", tone === "error" ? "text-red" : "text-muted-foreground")}
    >
      {children}
    </p>
  );
}
