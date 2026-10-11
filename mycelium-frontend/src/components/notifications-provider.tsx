// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { setStreamViewer, useNotificationStream, useNotificationsConnected } from "@/lib/stream-hub";
import { useCurrentUser } from "@/components/current-user";
import { ping, primeAudio } from "@/lib/audio-ping";
import {
  classify,
  DEFAULT_SETTINGS,
  electLeader,
  isAlert,
  loadNotifications,
  loadSettings,
  openCrossTabChannel,
  roomLevel,
  roomOfPath,
  saveNotifications,
  saveSettings,
  type NotificationSettings,
  type RoomLevel,
  type StoredNotification,
} from "@/lib/notifications";
import { fetchMemories, fetchRoomAgents } from "@/lib/api";
import {
  applyEvent,
  applyRow,
  entryHref,
  entryTitle,
  isInvolved,
  lastAsk,
  loadEntries,
  MOVE_LABEL,
  rowFactsOf,
  saveEntries,
  sortEntries,
  taskEventOf,
  taskIdOf,
  yourMove,
  type Me,
  type RowFacts,
  type TaskEntry,
  type YourMove,
} from "@/lib/task-inbox";

/** The one toast on screen: which task, and why it needs you. */
export interface TaskToast {
  id: string;
  move: YourMove;
  /** When it was raised (or last folded into), for the one-minute merge. */
  at: number;
}

/** Raised on `window` when a system notification is clicked, with the task
 *  and where it opens as its detail; `TaskToast` routes it. */
export const OPEN_TASK_EVENT = "mycelium:open-task";
export interface OpenTaskDetail {
  id: string;
  href: string;
}

/** Several changes to one task inside this window make one toast. */
const TOAST_MERGE_MS = 60_000;
/** How long the room's agents and rows are trusted before they're read again. */
const AGENTS_TTL_MS = 5 * 60_000;
const ROWS_TTL_MS = 30_000;

interface NotificationsContextValue {
  notifications: StoredNotification[];
  /** Tasks you're involved in, one entry each, as the bell shows them. */
  tasks: TaskEntry[];
  /** How many tasks wait on you: the bell's badge. */
  needsYouCount: number;
  toast: TaskToast | null;
  dismissToast: () => void;
  /** Mark a task seen (opened from the bell or a toast). */
  markTaskSeen: (id: string) => void;
  markAllTasksSeen: () => void;
  dismissTask: (id: string) => void;
  muteTask: (id: string) => void;
  unmuteTask: (id: string) => void;
  /** Kept for the sidebar's room badges: unread room activity, per event. */
  unreadCount: number;
  connected: boolean;
  settings: NotificationSettings;
  setSettings: (settings: NotificationSettings) => void;
  markRead: (id: string) => void;
  markAllRead: () => void;
  markRoomRead: (room: string) => void;
  dismiss: (id: string) => void;
  clearAll: () => void;
  muteRoom: (room: string) => void;
  unmuteRoom: (room: string) => void;
  setRoomLevel: (room: string, level: RoomLevel) => void;
  desktopPermission: NotificationPermission | "unsupported";
  requestDesktopPermission: () => void;
}

const NotificationsContext = createContext<NotificationsContextValue | null>(null);

const BASE_TITLE = "mycelium";

export function NotificationsProvider({ children }: { children: ReactNode }) {
  const { principal } = useCurrentUser();
  const [notifications, setNotifications] = useState<StoredNotification[]>([]);
  const [settings, setSettingsState] = useState<NotificationSettings>(DEFAULT_SETTINGS);
  const connected = useNotificationsConnected();
  const [desktopPermission, setDesktopPermission] = useState<NotificationPermission | "unsupported">(
    "unsupported",
  );

  const settingsRef = useRef(settings);
  const principalRef = useRef(principal);
  useLayoutEffect(() => { settingsRef.current = settings; }, [settings]);
  useLayoutEffect(() => { principalRef.current = principal; }, [principal]);
  const seenIds = useRef<Set<string>>(new Set());
  const isLeader = useRef(false);
  const channelRef = useRef<ReturnType<typeof openCrossTabChannel> | null>(null);

  // The task inbox: entries keyed by task id. The ref is what an arriving
  // event folds into (so two events for one task in quick succession see each
  // other); the state is what renders.
  const tasksRef = useRef<Record<string, TaskEntry>>({});
  const [tasks, setTasks] = useState<TaskEntry[]>([]);
  const [toast, setToast] = useState<TaskToast | null>(null);
  const toastRef = useRef<TaskToast | null>(null);
  useLayoutEffect(() => { toastRef.current = toast; }, [toast]);
  // Per room: the agents you own there, and its rows by thread, each read
  // when first needed and again once stale.
  const agentsCache = useRef<Map<string, { at: number; mine: string[] }>>(new Map());
  const rowsCache = useRef<Map<string, { at: number; byEpisode: Map<string, RowFacts> }>>(new Map());

  const commitTasks = useCallback((next: Record<string, TaskEntry>) => {
    tasksRef.current = next;
    setTasks(Object.values(next));
    saveEntries(Object.values(next));
  }, []);

  const updateTask = useCallback(
    (id: string, change: (entry: TaskEntry) => TaskEntry | null) => {
      const entry = tasksRef.current[id];
      if (!entry) return;
      const next = { ...tasksRef.current };
      const changed = change(entry);
      if (changed) next[id] = changed;
      else delete next[id];
      commitTasks(next);
    },
    [commitTasks],
  );

  // Load from localStorage once the DOM is there to read it: on the server
  // there is none, and seeding at init would mismatch the SSR render.
  useEffect(() => {
    const stored = loadNotifications();
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setNotifications(stored);
    seenIds.current = new Set(stored.map((n) => n.id));
    const entries = loadEntries();
    tasksRef.current = Object.fromEntries(entries.map((e) => [e.id, e]));
    setTasks(entries);
    setSettingsState(loadSettings());
    if (typeof window !== "undefined" && "Notification" in window) {
      setDesktopPermission(window.Notification.permission);
    }
  }, []);

  // Unlock the audio chime on the first user gesture (autoplay policies block
  // sound before one).
  useEffect(() => {
    const unlock = () => primeAudio();
    window.addEventListener("pointerdown", unlock, { once: true });
    window.addEventListener("keydown", unlock, { once: true });
    return () => {
      window.removeEventListener("pointerdown", unlock);
      window.removeEventListener("keydown", unlock);
    };
  }, []);

  // Exactly one open tab is "leader" — the only one that plays the audio ping
  // or raises a desktop Notification for a new item. Every tab still keeps its
  // own full notification list (each holds its own SSE connection).
  useEffect(() => {
    electLeader((leader) => {
      isLeader.current = leader;
    });
  }, []);

  // Cross-tab sync: read/dismiss/clear/settings apply everywhere immediately.
  useEffect(() => {
    const channel = openCrossTabChannel((msg) => {
      switch (msg.type) {
        case "read":
          setNotifications((prev) => prev.map((n) => (n.id === msg.id ? { ...n, read: true } : n)));
          break;
        case "read-all":
          setNotifications((prev) => prev.map((n) => ({ ...n, read: true })));
          break;
        case "room-read":
          setNotifications((prev) =>
            prev.map((n) => (n.room === msg.room ? { ...n, read: true } : n)),
          );
          break;
        case "dismiss":
          setNotifications((prev) => prev.filter((n) => n.id !== msg.id));
          break;
        case "clear":
          setNotifications([]);
          break;
        case "settings":
          setSettingsState(msg.settings);
          break;
        case "task-seen":
          updateTask(msg.id, (e) => ({ ...e, seenAt: msg.at }));
          break;
        case "tasks-seen":
          commitTasks(
            Object.fromEntries(Object.entries(tasksRef.current).map(([id, e]) => [id, { ...e, seenAt: msg.at }])),
          );
          break;
        case "task-dismiss":
          updateTask(msg.id, () => null);
          break;
      }
    });
    channelRef.current = channel;
    return () => channel.close();
  }, [commitTasks, updateTask]);

  useEffect(() => {
    saveNotifications(notifications);
  }, [notifications]);

  // What the bell counts: tasks waiting on you, muted ones left out.
  const needsYouCount = useMemo(
    () => sortEntries(tasks.filter((t) => !settings.mutedTasks?.includes(t.id))).needsYou.length,
    [tasks, settings.mutedTasks],
  );

  // The tab title carries the bell's count, so a tab in the background still
  // says something is waiting on you.
  useEffect(() => {
    document.title = needsYouCount > 0 ? `(${needsYouCount}) ${BASE_TITLE}` : BASE_TITLE;
  }, [needsYouCount]);

  // Activity across every room the user participates in, independent of which
  // (if any) is open — one channel on the app's shared connection.
  // The feed is for whoever this browser is, so it carries their private rooms.
  useEffect(() => {
    setStreamViewer(principal);
  }, [principal]);

  // The agents you own in a room, read once and then every few minutes: an
  // agent you own filing or working a task makes the task yours.
  const myAgentsIn = useCallback(async (room: string): Promise<string[]> => {
    const cached = agentsCache.current.get(room);
    if (cached && Date.now() - cached.at < AGENTS_TTL_MS) return cached.mine;
    const me = principalRef.current.trim().replace(/^@/, "").toLowerCase();
    const agents = me ? await fetchRoomAgents(room) : [];
    const mine = agents
      .filter((a) => (a.owner ?? "").replace(/^@/, "").toLowerCase() === me)
      .map((a) => a.handle.toLowerCase());
    agentsCache.current.set(room, { at: Date.now(), mine });
    return mine;
  }, []);

  // A row's facts by its thread, for a message from a thread the bell hasn't
  // met yet: its title, and whether it's yours.
  const rowOf = useCallback(async (room: string, episode: string): Promise<RowFacts | null> => {
    let cached = rowsCache.current.get(room);
    if (!cached || (!cached.byEpisode.has(episode) && Date.now() - cached.at > ROWS_TTL_MS)) {
      const rows = await fetchMemories(room, "work/");
      const byEpisode = new Map<string, RowFacts>();
      for (const row of rows) if (row.episode) byEpisode.set(row.episode, rowFactsOf(row));
      cached = { at: Date.now(), byEpisode };
      rowsCache.current.set(room, cached);
    }
    return cached.byEpisode.get(episode) ?? null;
  }, []);

  // Tell you a task now needs you: a toast in the window you're looking
  // at, or a system notification (and the chime) when you're elsewhere.
  const announce = useCallback(
    (entry: TaskEntry, move: YourMove) => {
      const s = settingsRef.current;
      if (s.dnd || s.toasts === "off" || s.mutedTasks?.includes(entry.id)) return;
      const now = Date.now();
      const current = toastRef.current;
      const merged = current && current.id === entry.id && now - current.at < TOAST_MERGE_MS;
      // One toast at a time: a newer one replaces the older, and a change to
      // the same task within the minute updates it in place.
      setToast({ id: entry.id, move, at: merged ? current.at : now });
      if (document.hasFocus() || !isLeader.current) return;
      if (s.soundEnabled) ping(s.soundVolume);
      if (s.desktopEnabled && "Notification" in window && window.Notification.permission === "granted") {
        const ask = move === "asks" ? lastAsk(entry) : null;
        try {
          const note = new window.Notification(`${MOVE_LABEL[move]} · ${entryTitle(entry)}`, {
            body: ask?.text ? `${ask.actor}: ${ask.text}` : entry.room,
            // The same task replaces its own notification rather than stacking.
            tag: entry.id,
          });
          note.onclick = () => {
            window.focus();
            // The toast host routes it: it lives under the app's router.
            window.dispatchEvent(
              new CustomEvent<OpenTaskDetail>(OPEN_TASK_EVENT, { detail: { id: entry.id, href: entryHref(entry) } }),
            );
            note.close();
          };
        } catch {
          // Best-effort — a blocked/unsupported Notification() must never break the feed.
        }
      }
    },
    [],
  );

  const ingest = useCallback(
    async (raw: Record<string, unknown>) => {
      const ev = taskEventOf(raw, principalRef.current);
      if (!ev || roomLevel(settingsRef.current, ev.room) === "muted") return;
      const id = taskIdOf(ev.room, ev.episode, ev.key);
      const mine = await myAgentsIn(ev.room);
      const known = tasksRef.current[id];
      const row = ev.episode && !known?.key ? await rowOf(ev.room, ev.episode) : null;
      // Read again after the awaits: another event may have folded in meanwhile.
      const before = tasksRef.current[id];
      const me: Me = { handle: principalRef.current.trim().replace(/^@/, "").toLowerCase(), agents: new Set(mine) };
      let next = applyEvent(before, ev, me);
      if (row) next = applyRow(next, row, me);
      if (next === before) return;
      commitTasks({ ...tasksRef.current, [id]: next });
      const was = before && isInvolved(before) ? yourMove(before) : null;
      const now = isInvolved(next) ? yourMove(next) : null;
      if (now && now !== was) announce(next, now);
    },
    [announce, commitTasks, myAgentsIn, rowOf],
  );

  useNotificationStream((raw) => {
    void ingest(raw as Record<string, unknown>);
    // The per-event list below only badges rooms in the sidebar now; the bell
    // and its toasts come from the task inbox above.
    const n = classify(raw as Record<string, unknown>, principalRef.current);
    if (!n) return;
    if (seenIds.current.has(n.id)) return;
    seenIds.current.add(n.id);
    // Muted rooms are dropped outright. Everything else is stored so it can
    // badge the room.
    if (roomLevel(settingsRef.current, n.room) === "muted") return;
    const loud = isAlert(n, settingsRef.current);
    // Something said in the room you're looking at is read as it arrives: it
    // shouldn't badge the room you're in.
    const seeing = document.hasFocus() && roomOfPath(window.location.pathname) === n.room;
    setNotifications((prev) => [...prev, { ...n, read: seeing, alert: loud }]);
  });

  const dismissToast = useCallback(() => setToast(null), []);

  const markTaskSeen = useCallback(
    (id: string) => {
      const at = new Date().toISOString();
      updateTask(id, (e) => ({ ...e, seenAt: at }));
      channelRef.current?.post({ type: "task-seen", id, at });
      if (toastRef.current?.id === id) setToast(null);
    },
    [updateTask],
  );

  const markAllTasksSeen = useCallback(() => {
    const at = new Date().toISOString();
    commitTasks(Object.fromEntries(Object.entries(tasksRef.current).map(([id, e]) => [id, { ...e, seenAt: at }])));
    channelRef.current?.post({ type: "tasks-seen", at });
  }, [commitTasks]);

  const dismissTask = useCallback(
    (id: string) => {
      updateTask(id, () => null);
      channelRef.current?.post({ type: "task-dismiss", id });
    },
    [updateTask],
  );

  const setSettings = useCallback((next: NotificationSettings) => {
    setSettingsState(next);
    saveSettings(next);
    channelRef.current?.post({ type: "settings", settings: next });
  }, []);

  const markRead = useCallback((id: string) => {
    setNotifications((prev) => prev.map((n) => (n.id === id ? { ...n, read: true } : n)));
    channelRef.current?.post({ type: "read", id });
  }, []);

  const markAllRead = useCallback(() => {
    setNotifications((prev) => prev.map((n) => ({ ...n, read: true })));
    channelRef.current?.post({ type: "read-all" });
  }, []);

  const dismiss = useCallback((id: string) => {
    setNotifications((prev) => prev.filter((n) => n.id !== id));
    channelRef.current?.post({ type: "dismiss", id });
  }, []);

  const clearAll = useCallback(() => {
    setNotifications([]);
    channelRef.current?.post({ type: "clear" });
  }, []);

  // Set a room's Discord-style level. `mutedRooms` is kept in sync with the
  // override so the settings panel's muted-rooms list keeps working unchanged.
  const setRoomLevel = useCallback(
    (room: string, level: RoomLevel) => {
      const s = settingsRef.current;
      const roomLevels = { ...s.roomLevels, [room]: level };
      const mutedRooms =
        level === "muted"
          ? [...new Set([...s.mutedRooms, room])]
          : s.mutedRooms.filter((r) => r !== room);
      setSettings({ ...s, roomLevels, mutedRooms });
    },
    [setSettings],
  );

  const muteRoom = useCallback((room: string) => setRoomLevel(room, "muted"), [setRoomLevel]);

  const muteTask = useCallback(
    (id: string) => {
      const s = settingsRef.current;
      setSettings({ ...s, mutedTasks: [...new Set([...(s.mutedTasks ?? []), id])] });
      if (toastRef.current?.id === id) setToast(null);
    },
    [setSettings],
  );

  const unmuteTask = useCallback(
    (id: string) => {
      const s = settingsRef.current;
      setSettings({ ...s, mutedTasks: (s.mutedTasks ?? []).filter((t) => t !== id) });
    },
    [setSettings],
  );

  // Unmute clears the override entirely, restoring the global default.
  const unmuteRoom = useCallback(
    (room: string) => {
      const s = settingsRef.current;
      const roomLevels = { ...s.roomLevels };
      delete roomLevels[room];
      setSettings({ ...s, roomLevels, mutedRooms: s.mutedRooms.filter((r) => r !== room) });
    },
    [setSettings],
  );

  // Opening a room reads it: clears its unread badge and marks its bell entries
  // read, on every tab.
  const markRoomRead = useCallback((room: string) => {
    setNotifications((prev) =>
      prev.map((n) => (n.room === room && !n.read ? { ...n, read: true } : n)),
    );
    channelRef.current?.post({ type: "room-read", room });
  }, []);

  // Coming back to the window reads the room it's showing: what arrived while
  // you were away is on screen now.
  useEffect(() => {
    const onFocus = () => {
      const room = roomOfPath(window.location.pathname);
      if (room) markRoomRead(room);
    };
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [markRoomRead]);

  const requestDesktopPermission = useCallback(() => {
    if (typeof window === "undefined" || !("Notification" in window)) return;
    window.Notification.requestPermission().then((perm) => setDesktopPermission(perm));
  }, []);

  // The bell's badge + tab title count only "loud" unread — mentions, directs,
  // and a negotiation you were in. Badge-only room activity lives in the sidebar.
  const unreadCount = useMemo(
    () => notifications.filter((n) => n.alert !== false && !n.read).length,
    [notifications],
  );

  const value = useMemo<NotificationsContextValue>(
    () => ({
      notifications,
      tasks,
      needsYouCount,
      toast,
      dismissToast,
      markTaskSeen,
      markAllTasksSeen,
      dismissTask,
      muteTask,
      unmuteTask,
      unreadCount,
      connected,
      settings,
      setSettings,
      markRead,
      markAllRead,
      markRoomRead,
      dismiss,
      clearAll,
      muteRoom,
      unmuteRoom,
      setRoomLevel,
      desktopPermission,
      requestDesktopPermission,
    }),
    [
      notifications,
      tasks,
      needsYouCount,
      toast,
      dismissToast,
      markTaskSeen,
      markAllTasksSeen,
      dismissTask,
      muteTask,
      unmuteTask,
      unreadCount,
      connected,
      settings,
      setSettings,
      markRead,
      markAllRead,
      markRoomRead,
      dismiss,
      clearAll,
      muteRoom,
      unmuteRoom,
      setRoomLevel,
      desktopPermission,
      requestDesktopPermission,
    ],
  );

  return <NotificationsContext.Provider value={value}>{children}</NotificationsContext.Provider>;
}

export function useNotifications(): NotificationsContextValue {
  const ctx = useContext(NotificationsContext);
  if (!ctx) throw new Error("useNotifications must be used within a NotificationsProvider");
  return ctx;
}

/** The same, or null outside a provider: for a control (a row's menu) that
 *  also renders where there are no notifications, like a test. */
export function useOptionalNotifications(): NotificationsContextValue | null {
  return useContext(NotificationsContext);
}
