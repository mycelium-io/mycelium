// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

// DESIGN MOCKUP (local branch, not for merge). Settings for a machine that
// belongs to several hubs, built from made-up data so the pages can be judged
// in the real app. Nothing here talks to a hub.

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Check, ChevronRight, Copy, Loader2, QrCode, X } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";
import { desktopMachine, isDesktop } from "@/lib/desktop";
import { useRooms } from "@/lib/room-data";

/** This machine as the title bar names it: "Mac" in the app on a Mac,
 *  "computer" anywhere else. */
function machineName(): string {
  return isDesktop() ? desktopMachine() : "computer";
}

/** A hub's colour is picked on this machine, never sent by the hub, and kept
 *  clear of the status hues. This machine's own hub has none. */
const HUB_COLOR = { work: "#7b93f0", studio: "#e38bc0", sam: "#b48ce6", acme: "#8a94a0" } as const;

function Swatch({ hub }: { hub: keyof typeof HUB_COLOR }) {
  return <span aria-hidden className="size-2.5 flex-shrink-0 rounded-[3px]" style={{ background: HUB_COLOR[hub] }} />;
}

/** A page that asks one question, in one roomy column. */
function QuestionPage({ crumb, question, lead, children }: { crumb?: ReactNode; question: string; lead: ReactNode; children: ReactNode }) {
  return (
    <div className="mx-auto max-w-[720px] px-6 pb-24 pt-10">
      {crumb && <div className="mb-3 text-micro text-faint">{crumb}</div>}
      <h1 className="text-[22px] font-semibold tracking-[-0.01em] text-text">{question}</h1>
      <p className="mt-2 max-w-[600px] text-body leading-relaxed text-[var(--prose)]">{lead}</p>
      <div className="mt-6 border-t border-border">{children}</div>
    </div>
  );
}

function Block({ children, className }: { children: ReactNode; className?: string }) {
  return <section className={cn("border-b border-border py-6", className)}>{children}</section>;
}

function Say({ children, quiet }: { children: ReactNode; quiet?: boolean }) {
  return <p className={cn("mt-1.5 text-body leading-relaxed", quiet ? "text-muted-foreground" : "text-[var(--prose)]")}>{children}</p>;
}

function When({ children }: { children: ReactNode }) {
  return <p className="mt-1.5 text-micro text-faint">{children}</p>;
}

/** Actions are words under what they act on. Leave is the quiet one. */
function Act({ children, onClick, tone = "accent" }: { children: ReactNode; onClick?: () => void; tone?: "accent" | "quiet" | "danger" }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "text-label hover:underline underline-offset-4",
        tone === "accent" && "text-accent",
        tone === "quiet" && "text-muted-foreground hover:text-text",
        tone === "danger" && "text-red",
      )}
    >
      {children}
    </button>
  );
}

function Acts({ children }: { children: ReactNode }) {
  return <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1">{children}</div>;
}

type Check = { ok: boolean; text: ReactNode };

/** A test that proves the connection, said in words, one line per check. */
function TestResult({ checks, after }: { checks: Check[]; after?: ReactNode }) {
  return (
    <div className="mt-3 space-y-1.5">
      {checks.map((c, i) => (
        <div key={i} className="flex items-baseline gap-2.5 text-body">
          {c.ok ? <Check className="size-3.5 flex-shrink-0 translate-y-0.5 text-green" /> : <X className="size-3.5 flex-shrink-0 translate-y-0.5 text-red" />}
          <span className="text-text">{c.text}</span>
        </div>
      ))}
      {after && <When>{after}</When>}
    </div>
  );
}

/** Runs a pretend test: a moment of "testing", then the result. */
function useTest(initial: boolean) {
  const [state, setState] = useState<"idle" | "running" | "done">(initial ? "done" : "idle");
  const run = () => {
    setState("running");
    window.setTimeout(() => setState("done"), 900);
  };
  return { state, run };
}

function Testing() {
  return (
    <div className="mt-3 flex items-center gap-2 text-body text-muted-foreground">
      <Loader2 className="size-3.5 animate-spin" /> Testing…
    </div>
  );
}

function Advanced({ children, open: initial = false }: { children: ReactNode; open?: boolean }) {
  const [open, setOpen] = useState(initial);
  return (
    <div className="mt-4">
      <button type="button" onClick={() => setOpen(!open)} className="flex items-center gap-1 text-label text-muted-foreground hover:text-text">
        <ChevronRight className={cn("size-3.5 transition-transform", open && "rotate-90")} /> Advanced
      </button>
      {open && <div className="mt-3 space-y-4 border-l border-border2 pl-4">{children}</div>}
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <div className="text-micro text-faint">{label}</div>
      <div className="mt-1 text-body text-text">{children}</div>
    </div>
  );
}

function LeaveConfirm({ hub, agents, onCancel }: { hub: string; agents: string[]; onCancel: () => void }) {
  return (
    <div role="alertdialog" className="mt-4 border-l-2 border-red/70 pl-4">
      <p className="text-body font-medium text-text">Leave {hub}?</p>
      <Say quiet>
        Its rooms leave your list, and your name, drafts and saved data for {hub} are removed from this {machineName()}. {hub} keeps
        what you posted.
      </Say>
      {agents.length > 0 && (
        <Say>
          {agents.join(" and ")} {agents.length === 1 ? "runs" : "run"} only for {hub}, so {agents.length === 1 ? "it stops" : "they stop"} too.
        </Say>
      )}
      <Acts>
        <Act tone="danger">Leave {hub}{agents.length ? ` and stop ${agents.length === 1 ? "it" : `${agents.length} agents`}` : ""}</Act>
        <Act tone="quiet" onClick={onCancel}>
          Cancel
        </Act>
      </Acts>
    </div>
  );
}

function HubTitle({ hub, address }: { hub: keyof typeof HUB_COLOR; address: string }) {
  return (
    <div className="flex items-center gap-2.5">
      <Swatch hub={hub} />
      <h2 className="text-[16px] font-semibold text-text">{hub}</h2>
      <span className="font-mono text-micro text-faint">{address}</span>
    </div>
  );
}

function WorkHub() {
  const test = useTest(true);
  const [leaving, setLeaving] = useState(false);
  return (
    <Block>
      <HubTitle hub="work" address="work.example.com" />
      <Say>
        You're <b className="font-medium text-text">@julia-v</b> here. Anyone who reaches work can post, because it doesn't ask people
        to sign in. Two of your agents, builder and reviewer, run on this {machineName()} for it.
      </Say>
      <Say>
        work may start agents on this {machineName()} only in <span className="font-mono text-label">~/code/checkout</span>, and it
        asks you each time.
      </Say>
      <Acts>
        <Act onClick={test.run}>Test the connection</Act>
        <Act>Rename or recolor</Act>
        <Act tone="quiet" onClick={() => setLeaving(true)}>
          Leave work…
        </Act>
      </Acts>
      {test.state === "running" && <Testing />}
      {test.state === "done" && (
        <TestResult
          checks={[
            { ok: true, text: "work answered in 120 ms." },
            { ok: true, text: "It's the same hub you joined. Its key matches the one it gave you then." },
            { ok: true, text: "@julia-v is still yours there." },
          ]}
          after="Tested just now."
        />
      )}
      {leaving && <LeaveConfirm hub="work" agents={["builder", "reviewer"]} onCancel={() => setLeaving(false)} />}
      <Advanced>
        <Field label="Folders work may start agents in">
          <div className="flex flex-wrap gap-1.5">
            <span className="flex items-center gap-1 rounded-md border border-border px-2 py-0.5 font-mono text-micro">
              ~/code/checkout <X className="size-3 text-faint" />
            </span>
            <button type="button" className="rounded-md border border-dashed border-border2 px-2 py-0.5 text-micro text-muted-foreground hover:text-text">
              Choose a folder…
            </button>
          </div>
          <When>A change applies to the next request. This {machineName()} still asks you each time.</When>
        </Field>
        <Field label="Hub key">
          <span className="font-mono text-label">7f3a 91c0 … 52d8 c21e</span>
        </Field>
        <Field label="Store id">
          <span className="font-mono text-label text-muted-foreground">st_8f2e41c7</span>
        </Field>
      </Advanced>
    </Block>
  );
}

function StudioHub() {
  const test = useTest(false);
  return (
    <Block>
      <HubTitle hub="studio" address="studio.example.org" />
      <Say>
        You're <b className="font-medium text-text">@julia</b> here. Only people studio invited can get in, and this {machineName()}{" "}
        holds your key for it. Your key is also on Studio iMac.
      </Say>
      <Say>studio can't start agents on this {machineName()}. You haven't allowed it any folders.</Say>
      <Acts>
        <Act onClick={test.run}>Test the connection</Act>
        <Link href="/settings/hub-devices" className="text-label text-accent underline-offset-4 hover:underline">
          Use studio on another device…
        </Link>
        <Act>Rename or recolor</Act>
        <Act tone="quiet">Leave studio…</Act>
      </Acts>
      {test.state === "running" && <Testing />}
      {test.state === "done" && (
        <TestResult
          checks={[
            { ok: true, text: "studio answered in 88 ms, and it's the same hub you joined." },
            { ok: true, text: "Your key for studio still works. Your sign-in renews by itself." },
          ]}
          after="Tested just now."
        />
      )}
    </Block>
  );
}

function SamHub() {
  const test = useTest(true);
  return (
    <Block>
      <HubTitle hub="sam" address="192.168.1.40:8000" />
      <Say>You're <b className="font-medium text-text">@julia</b> here. Last reached 2 hours ago.</Say>
      {test.state === "running" ? (
        <Testing />
      ) : (
        <TestResult
          checks={[
            {
              ok: false,
              text: "Couldn't reach sam at 192.168.1.40. Nothing answered on port 8000. The computer may be asleep or off this network.",
            },
          ]}
          after="Tested just now. Its rooms stay in your list, and the app tries again every minute."
        />
      )}
      <Acts>
        <Act onClick={test.run}>Test again</Act>
        <Act>Change its address…</Act>
        <Act tone="quiet">Leave sam…</Act>
      </Acts>
    </Block>
  );
}

function AcmeHub() {
  return (
    <Block>
      <HubTitle hub="acme" address="mycelium.acme.io" />
      <Say>You sign in to acme with your acme account, julia@acme.io.</Say>
      <TestResult
        checks={[
          { ok: true, text: "acme answered, and it's the same hub you joined." },
          { ok: false, text: "Your sign-in ran out yesterday, and acme refused to renew it. Sign in again to post there." },
        ]}
      />
      <Acts>
        <Act>Sign in again</Act>
        <Act tone="quiet">Leave acme…</Act>
      </Acts>
    </Block>
  );
}

/** Settings › Hubs: which hubs this machine is part of. */
export function HubsDesign() {
  const machine = machineName();
  return (
    <QuestionPage
      question={`Which hubs is this ${machine} part of?`}
      lead="Each hub has its own rooms, and your own name and sign-in there. Nothing you write on one reaches another."
    >
      <Block>
        <div className="flex items-center gap-2.5">
          <h2 className="text-[16px] font-semibold text-text">This {machine}</h2>
          <span className="text-micro text-faint">your own hub</span>
        </div>
        <Say>
          It runs here, and it's always part of this {machine}. Your rooms are only you. You share 3 rooms with people you invite, at{" "}
          <span className="font-mono text-label">julia-mbp.tail3e2c.ts.net</span>.
        </Say>
        <Acts>
          <Link href="/settings/hub-host" className="text-label text-accent underline-offset-4 hover:underline">
            Who else can get in…
          </Link>
        </Acts>
      </Block>
      <WorkHub />
      <StudioHub />
      <SamHub />
      <AcmeHub />
      <section className="py-6">
        <h2 className="text-[15px] font-semibold text-text">Join another hub</h2>
        <Say quiet>Open an invite link someone sent you. Mycelium checks the hub before you join.</Say>
        <Acts>
          <Act>Join with an invite link…</Act>
          <Act tone="quiet">I have a link code from my other device</Act>
        </Acts>
        <When>"Join with an invite link…" reads your clipboard once, to look for a link. Nothing reads it before you choose.</When>
      </section>
    </QuestionPage>
  );
}

/** A plain table: sentence-case headers, rows divided by hairlines, the
 *  row's one action at the right. */
function SimpleTable({ head, rows }: { head: string[]; rows: ReactNode[][] }) {
  return (
    <table className="mt-3 w-full text-left text-body">
      <thead>
        <tr className="border-b border-border">
          {head.map((h, i) => (
            <th key={i} className="py-2 pr-4 text-micro font-normal text-faint">
              {h}
            </th>
          ))}
        </tr>
      </thead>
      <tbody className="divide-y divide-border">
        {rows.map((r, i) => (
          <tr key={i}>
            {r.map((c, j) => (
              <td key={j} className={cn("py-2.5 pr-4 text-text", j === r.length - 1 && "pr-0 text-right")}>
                {c}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

const WHO = ["anyone with the link", "one person"];
const DAYS = ["1 day", "7 days", "30 days"];

/** The part of a sentence you can change: the words themselves, underlined
 *  with dots, opening a short menu of the other choices under them. */
function Inline({
  value,
  options,
  onChange,
  label,
  open: startOpen = false,
}: {
  value: string;
  options: string[];
  onChange: (v: string) => void;
  label: string;
  open?: boolean;
}) {
  const [open, setOpen] = useState(startOpen);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (!(e.target as HTMLElement).closest("[data-inline-pick]")) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);
  return (
    <span data-inline-pick className="relative inline-block">
      <button
        type="button"
        aria-label={label}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className={cn(
          "border-b border-dotted border-accent/70 leading-tight text-text outline-none transition-colors hover:text-accent focus-visible:text-accent",
          open && "text-accent",
        )}
      >
        {value}
      </button>
      {open && (
        <span role="listbox" aria-label={label} className="absolute left-0 top-full z-20 mt-1.5 flex min-w-[10rem] flex-col rounded-lg border border-border2 bg-elevated py-1 shadow-xl">
          {options.map((o) => (
            <button
              key={o}
              type="button"
              role="option"
              aria-selected={o === value}
              onClick={() => {
                onChange(o);
                setOpen(false);
              }}
              className="flex items-center gap-2 whitespace-nowrap px-3 py-1 text-left text-label leading-6 text-text hover:bg-hairline"
            >
              <Check className={cn("size-3.5 text-accent", o !== value && "invisible")} />
              {o}
            </button>
          ))}
        </span>
      )}
    </span>
  );
}

/** A number or a handle typed straight into the sentence, underlined like the choices. */
function InlineText({ value, onChange, label, width, placeholder }: { value: string; onChange: (v: string) => void; label: string; width: string; placeholder?: string }) {
  return (
    <input
      aria-label={label}
      value={value}
      placeholder={placeholder}
      onChange={(e) => onChange(e.target.value)}
      style={{ width }}
      className="border-0 border-b border-dotted border-accent/70 bg-transparent p-0 text-center leading-tight text-text outline-none placeholder:text-faint focus:border-solid"
    />
  );
}

/** Settings › This hub › Who can get in. The rooms are this hub's own. */
export function HubAccessDesign() {
  const { rooms } = useRooms();
  const shared = rooms.filter((r) => r.is_public !== false).map((r) => `#${r.name}`);
  const ROOMS = shared.length ? shared : ["#checkout"];
  const [who, setWho] = useState(WHO[0]);
  const [picked, setRoom] = useState<string | null>(null);
  const room = picked ?? ROOMS[0];
  const [r1, r2, r3] = [ROOMS[0], ROOMS[1] ?? ROOMS[0], ROOMS[2] ?? ROOMS[0]];
  const [days, setDays] = useState(DAYS[1]);
  const [uses, setUses] = useState("20");
  const [handle, setHandle] = useState("");
  // ?pick=room opens that menu, so a capture can show it.
  const pickOpen = useSearchParams().get("pick");
  const [made, setMade] = useState(true);
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const t = window.setTimeout(() => setCopied(false), 1500);
    return () => window.clearTimeout(t);
  }, [copied]);
  const one = who === "one person";
  return (
    <QuestionPage
      crumb="This hub"
      question="Who can get into this hub?"
      lead="Only people with an invite. 9 people are in, on 14 devices. You're one of this hub's admins, and this app holds your admin key, so you can invite people from here."
    >
      <Block>
        <h2 className="text-[15px] font-semibold text-text">Invite someone</h2>
        <p className="mt-3 text-[17px] leading-[2] text-[var(--prose)]">
          Let <Inline label="Who" value={who} options={WHO} onChange={setWho} />
          {one && (
            <>
              {" "}
              <InlineText label="Handle" value={handle} onChange={setHandle} width="6.5rem" placeholder="@handle" />
            </>
          )}{" "}
          join <Inline label="Room" value={room} options={ROOMS} onChange={setRoom} open={pickOpen === "room"} />, for the next{" "}
          <Inline label="How long" value={days} options={DAYS} onChange={setDays} />
          {!one && (
            <>
              , up to{" "}
              <InlineText label="People" value={uses} onChange={(v) => setUses(v.replace(/\D/g, ""))} width={`${Math.max(uses.length, 1) + 0.6}ch`} />{" "}
              people
            </>
          )}
          .
        </p>
        <Acts>
          <Act onClick={() => setMade(true)}>Make the link</Act>
        </Acts>
        {!one && <When>Uses can't be unlimited: a link that never runs out is open to anyone.</When>}
        {made && (
          <div className="mt-5 border-l-2 border-green/70 pl-4">
            <p className="text-body text-text">
              <Check className="mr-1.5 inline size-3.5 text-green" />
              <b className="font-medium">Here's the link.</b>{" "}
              <span className="text-muted-foreground">Copy it now. The hub keeps only a hash of the code, so the link can't be shown again.</span>
            </p>
            <p className="mt-2 break-all font-mono text-micro text-[var(--prose)]">
              https://mycelium-io.github.io/mycelium/join#hub=https://team.example.com&amp;key=c4e1…08ab&amp;code=K7QM4XHD9RWAC2LP
            </p>
            <Acts>
              <button type="button" onClick={() => setCopied(true)} className="flex items-center gap-1.5 text-label text-accent hover:underline underline-offset-4">
                {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />} {copied ? "Copied" : "Copy"}
              </button>
              <button type="button" className="flex items-center gap-1.5 text-label text-accent hover:underline underline-offset-4">
                <QrCode className="size-3.5" /> Show as a QR code
              </button>
            </Acts>
          </div>
        )}
      </Block>

      <section className="py-6">
        <h2 className="text-[15px] font-semibold text-text">Open invites</h2>
        <Say quiet>Each one works until it runs out or you revoke it. Revoking stops new people. Anyone who already joined stays.</Say>
        <SimpleTable
          head={["Room", "For", "Joined", "Ends", "Made by", ""]}
          rows={[
            [r1, "anyone with the link", "6 of 20", "Thursday", "you", <Act key="r" tone="danger">Revoke</Act>],
            [r2, "@dana", "not yet", "Saturday", "@mara", <Act key="r" tone="danger">Revoke</Act>],
            [<span key="g" className="text-faint">{r3}</span>, <span key="w" className="text-faint">anyone with the link</span>, <span key="j" className="text-faint">300 of 300</span>, <span key="e" className="text-faint">used up</span>, <span key="m" className="text-faint">you</span>, <span key="l" className="text-micro text-faint">gone tomorrow</span>],
          ]}
        />
        <When>Lost a link? Revoke it and make a new one.</When>
      </section>
    </QuestionPage>
  );
}

const SHARING = ["only me", "invited people"];

function Step({ n, title, children }: { n: number; title: string; children: ReactNode }) {
  return (
    <Block>
      <div className="flex items-baseline gap-3">
        {n > 0 && <span className="w-4 flex-shrink-0 text-label text-faint">{n}</span>}
        <div className="min-w-0 flex-1">
          <h2 className="text-[15px] font-semibold text-text">{title}</h2>
          {children}
        </div>
      </div>
    </Block>
  );
}

function Choice({ on, title, children, onPick }: { on: boolean; title: string; children: ReactNode; onPick: () => void }) {
  return (
    <button type="button" onClick={onPick} className="flex w-full items-start gap-3 py-2 text-left">
      <span className={cn("mt-1 size-3.5 flex-shrink-0 rounded-full border", on ? "border-[4px] border-accent" : "border-border2")} />
      <span>
        <span className="block text-body text-text">{title}</span>
        <span className="block text-label text-muted-foreground">{children}</span>
      </span>
    </button>
  );
}

/** Settings › This hub › Let people in: hosting from this computer. */
export function HubHostDesign() {
  const machine = machineName();
  const { rooms } = useRooms();
  // ?setup=1 shows the first time, before anyone can get in. Without it the
  // page shows this hub as it is in the mock: people can get in by invite.
  const setup = useSearchParams().get("setup") === "1";
  const [how, setHow] = useState<"invite" | "sign-in">("invite");
  const [sharing, setSharing] = useState<Record<string, string>>({});
  const seeOf = (r: (typeof rooms)[number]) => sharing[r.name] ?? (setup || r.is_public === false ? "only me" : "invited people");
  const [checked, setChecked] = useState<"no" | "running" | "ok">(setup ? "no" : "ok");
  const shared = rooms.filter((r) => seeOf(r) === "invited people").length;
  return (
    <QuestionPage
      crumb="This hub"
      question={setup ? `Let people into this ${machine}'s hub` : `Who else can get into this ${machine}'s hub?`}
      lead={
        setup
          ? "Right now only you and your agents use it. Letting people in makes it reachable at an address you give, and from then on nobody gets in without an invite or a sign-in."
          : "People you invite, at julia-mbp.tail3e2c.ts.net. Your rooms stay yours: only the rooms you share are open to them."
      }
    >
      <Step n={setup ? 1 : 0} title="Who can get in">
        <div className="mt-2">
          <Choice on={how === "invite"} onPick={() => setHow("invite")} title="People I invite">
            Each person gets a link from you. Their device keeps a key for this hub.
          </Choice>
          <Choice on={how === "sign-in"} onPick={() => setHow("sign-in")} title="People who sign in with our sign-in service">
            For a team that already has one, such as Okta or Google Workspace. You'll connect it next.
          </Choice>
        </div>
        <When>There's no &ldquo;anyone&rdquo;. A hub people can reach and that asks nobody who they are lets anyone post as anyone.</When>
      </Step>

      <Step n={setup ? 2 : 0} title="Which rooms they can see">
        <Say quiet>
          Every room starts as only you, so nothing private is shared by accident. Everyone you let in can see a room you share.
        </Say>
        <SimpleTable
          head={["Room", "Who can see it"]}
          rows={rooms.map((r) => [
            <span key="n">#{r.name}</span>,
            <Inline
              key="s"
              label={`Who can see #${r.name}`}
              value={seeOf(r)}
              options={SHARING}
              onChange={(v) => setSharing({ ...sharing, [r.name]: v })}
            />,
          ])}
        />
        <When>
          {shared === 0 ? "No rooms are shared yet. People you let in will see an empty hub." : `${shared} of ${rooms.length} rooms shared. A change takes effect right away.`}
        </When>
      </Step>

      <Step n={setup ? 3 : 0} title="The address people use">
        <Say quiet>How this {machine} gets an address is up to you: a server, a tunnel, or Tailscale.</Say>
        <div className="mt-3 flex items-center gap-3">
          <input
            aria-label="Address"
            defaultValue="https://julia-mbp.tail3e2c.ts.net"
            className="w-[340px] border-0 border-b border-dotted border-accent/70 bg-transparent p-0 pb-0.5 font-mono text-label text-text outline-none focus:border-solid"
          />
          <Act
            onClick={() => {
              setChecked("running");
              window.setTimeout(() => setChecked("ok"), 900);
            }}
          >
            Check it
          </Act>
        </div>
        {checked === "running" && <Testing />}
        {checked === "ok" && (
          <TestResult
            checks={[
              { ok: true, text: "That address reaches a hub." },
              { ok: true, text: `It's this ${machine}'s hub. Its key matches.` },
            ]}
          />
        )}
      </Step>

      {!setup && (
        <section className="py-6">
          <Say quiet>
            Your agents each have their own token for this hub. This hub doesn't trust a request just because it comes from this{" "}
            {machine}, since a tunnel makes outside requests look local.
          </Say>
          <Acts>
            <Act tone="quiet">Stop letting people in…</Act>
          </Acts>
          <When>Stopping closes the hub to everyone but you. The people you let in and their keys are kept, so starting again needs no new invites.</When>
        </section>
      )}
      {setup && (
      <Step n={4} title="Before it opens">
        <TestResult
          checks={[
            { ok: true, text: "You'll be this hub's first admin. This app sets that up, so there's no code to copy." },
            {
              ok: false,
              text: "builder and reviewer still rely on being on this computer. Letting people in gives each of them its own token first, and they keep working.",
            },
          ]}
        />
        <When>
          Once people can get in, this hub stops trusting requests just because they come from this {machine}. A tunnel makes outside requests look local.
        </When>
        <div className="mt-5 flex items-center gap-4">
          <button type="button" className="btn-accent rounded-md px-3.5 py-1.5 text-label font-medium">
            Let people in
          </button>
          <span className="text-micro text-faint">Takes effect right away. Then make invites under Who can get in.</span>
        </div>
      </Step>
      )}
    </QuestionPage>
  );
}

/** Hubs › studio › Use studio on another device. */
export function HubDevicesDesign() {
  const [left, setLeft] = useState(9 * 60 + 41);
  useEffect(() => {
    const t = window.setInterval(() => setLeft((s) => Math.max(0, s - 1)), 1000);
    return () => window.clearInterval(t);
  }, []);
  const mins = Math.ceil(left / 60);
  return (
    <QuestionPage
      crumb={
        <span className="flex items-center gap-1.5">
          <Link href="/settings/hubs" className="hover:text-text">
            Hubs
          </Link>
          <ChevronRight className="size-3" /> <Swatch hub="studio" /> studio
        </span>
      }
      question="Use studio on another device"
      lead={`studio knows you by a key on each of your devices. A new device gets its own key, and this ${machineName()} vouches for it. You don't need a new invite.`}
    >
      <Block>
        <h2 className="text-[15px] font-semibold text-text">Link a device</h2>
        <ol className="mt-3 list-decimal space-y-1 pl-5 text-body text-[var(--prose)]">
          <li>On the other device, open Mycelium.</li>
          <li>
            Choose <b className="font-medium text-text">Join another hub</b>, then{" "}
            <b className="font-medium text-text">I have a link code from my other device</b>.
          </li>
          <li>Enter this code:</li>
        </ol>
        <p className="mt-4 font-mono text-[30px] tracking-[0.16em] text-text">QW7-K3P</p>
        <div className="mt-2 flex items-center gap-2 text-body text-muted-foreground">
          <span className="size-1.5 animate-pulse rounded-full bg-accent" />
          Waiting for the other device. The code works once, for {mins} more minute{mins === 1 ? "" : "s"}.
        </div>
        <When>
          Both devices sign the link, so it can only add a key for @julia, and only from here. You'll see the device's name here before
          it's added.
        </When>
        <Acts>
          <Act tone="quiet">Cancel</Act>
        </Acts>
      </Block>
      <section className="py-6">
        <h2 className="text-[15px] font-semibold text-text">Your devices on studio</h2>
        <SimpleTable
          head={["Device", "Linked", "Last used", ""]}
          rows={[
            [<span key="d">This MacBook <span className="text-faint">(this one)</span></span>, "Aug 2", "now", ""],
            ["Studio iMac", "Oct 9", "yesterday", <Act key="r" tone="danger">Remove</Act>],
            ["Old laptop", "Aug 30", "7 weeks ago", <Act key="r" tone="danger">Remove</Act>],
          ]}
        />
        <When>
          Removing a device takes effect within the hour, when its sign-in next renews. Lost every device? Ask one of studio's admins to
          invite you again as @julia.
        </When>
      </section>
    </QuestionPage>
  );
}
