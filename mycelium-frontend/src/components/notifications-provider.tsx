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
import { usePathname } from "next/navigation";
import useSWR from "swr";
import { setStreamViewer, useNotificationStream, useNotificationsConnected } from "@/lib/stream-hub";
import { useCurrentUser } from "@/components/current-user";
import { audioReady, ping, playAudio, primeAudio } from "@/lib/audio-ping";
import { fetchMemories, fetchSpeech, fetchVoiceStatus } from "@/lib/api";
import { micOpen, onMicChange } from "@/lib/mic-activity";
import { mentionHref, OPEN_MENTION_EVENT } from "@/lib/notifications";
import { createReader, IDLE, type Reader, type ReaderState, type ReadItem } from "@/lib/read-aloud";
import { claimToSpeak } from "@/lib/speaking-tab";
import { speakable } from "@/lib/speakable";
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

interface NotificationsContextValue {
  notifications: StoredNotification[];
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

/** Reading mentions aloud, as the bell's popover and the settings page use it. */
export interface ReadAloud {
  /** The hub has a speech server, so it can be turned on. */
  available: boolean;
  state: ReaderState;
  stop: () => void;
  readAll: () => void;
  keepOpen: (open: boolean) => void;
  /** Say a sample line, from the settings page. */
  tryIt: () => void;
}

const NotificationsContext = createContext<NotificationsContextValue | null>(null);

/** Its own context, since it changes with every sentence: only the bell's
 *  popover and the settings page re-render as it reads. */
const ReadAloudContext = createContext<ReadAloud | null>(null);

const BASE_TITLE = "mycelium";

/** The longest a mention waits for its task's name before it's read with the room's. */
const TITLE_WAIT_MS = 1_500;

const SAMPLE =
  "This is how a mention sounds. First who sent it and where, then the start of the message, with each sentence lit as it's said.";

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
  /** The room another, focused window shows, from its "viewing" posts. */
  const viewedElsewhere = useRef<string | null>(null);
  const channelRef = useRef<ReturnType<typeof openCrossTabChannel> | null>(null);

  // Load from localStorage once the DOM is there to read it: on the server
  // there is none, and seeding at init would mismatch the SSR render.
  useEffect(() => {
    const stored = loadNotifications();
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setNotifications(stored);
    seenIds.current = new Set(stored.map((n) => n.id));
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

  // Mentions read aloud through the hub's speech server, when it has one.
  const { data: voice } = useSWR("voice-status", fetchVoiceStatus, { revalidateOnFocus: false });
  const speechAvailable = Boolean(voice?.speech);
  const speechRef = useRef(speechAvailable);
  useLayoutEffect(() => { speechRef.current = speechAvailable; }, [speechAvailable]);
  const [readerState, setReaderState] = useState<ReaderState>(IDLE);
  const readerRef = useRef<Reader | null>(null);
  useEffect(() => {
    const reader = createReader({
      fetch: fetchSpeech,
      play: playAudio,
      micOpen,
      onMicChange,
      onChange: setReaderState,
    });
    readerRef.current = reader;
    return () => {
      reader.dispose();
      readerRef.current = null;
    };
  }, []);
  // Turning it off, or Do not disturb on, stops what's being read.
  useEffect(() => {
    if (!settings.readAloud || settings.dnd) readerRef.current?.stop();
  }, [settings.readAloud, settings.dnd]);

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
        case "viewing":
          viewedElsewhere.current = msg.room;
          break;
      }
    });
    channelRef.current = channel;
    return () => channel.close();
  }, []);

  useEffect(() => {
    saveNotifications(notifications);
  }, [notifications]);

  // Tab-title unread badge — loud items only, matching the bell (badge-only room
  // activity stays in the sidebar, not the tab title).
  useEffect(() => {
    const unread = notifications.filter((n) => n.alert !== false && !n.read).length;
    document.title = unread > 0 ? `(${unread}) ${BASE_TITLE}` : BASE_TITLE;
  }, [notifications]);

  // Activity across every room the user participates in, independent of which
  // (if any) is open — one channel on the app's shared connection.
  // The feed is for whoever this browser is, so it carries their private rooms.
  useEffect(() => {
    setStreamViewer(principal);
  }, [principal]);

  // Task titles by thread, per room, read when a mention first comes from one
  // of the room's threads and again when an unknown thread shows up.
  const titles = useRef<Map<string, { at: number; byEpisode: Map<string, string> }>>(new Map());
  const taskTitle = useCallback(async (room: string, episode: string): Promise<string | null> => {
    let cached = titles.current.get(room);
    if (!cached || (!cached.byEpisode.has(episode) && Date.now() - cached.at > 30_000)) {
      // Every memory has a thread, not only the board's rows: a mention in a
      // `context/` note's discussion is named too.
      const memories = await fetchMemories(room);
      const byEpisode = new Map<string, string>();
      for (const row of memories) {
        if (!row.episode) continue;
        const text = typeof row.value === "string" ? row.value : ((row.value as { text?: string } | null)?.text ?? "");
        const first = text.split("\n").find((l) => l.trim());
        byEpisode.set(row.episode, first ? first.replace(/^#+\s*/, "").trim() : row.key);
      }
      cached = { at: Date.now(), byEpisode };
      titles.current.set(room, cached);
    }
    return cached.byEpisode.get(episode) ?? null;
  }, []);

  /** Read a mention aloud, if this is the tab that should: the one you can
   *  see, never a hidden one, and only one of several. */
  const readMention = useCallback(
    async (n: { id: string; room: string; sender: string; episode?: string | null; text: string }) => {
      // Shown in the window you're working in: you can read it there.
      if (!document.hasFocus() && viewedElsewhere.current === n.room) return;
      if (!(await claimToSpeak(n.id))) return;
      let where = n.room;
      if (n.episode) {
        const title = await Promise.race([
          taskTitle(n.room, n.episode).catch(() => null),
          new Promise<null>((resolve) => setTimeout(() => resolve(null), TITLE_WAIT_MS)),
        ]);
        if (title) where = title;
      }
      const item: ReadItem = { id: n.id, sender: n.sender, where, href: mentionHref(n), blocks: speakable(n.text) };
      readerRef.current?.enqueue(item);
    },
    [taskTitle],
  );

  useNotificationStream((raw) => {
    const classified = classify(raw as Record<string, unknown>, principalRef.current);
    if (!classified) return;
    // The whole message is kept only long enough to read it aloud.
    const { text, ...n } = classified;
    if (seenIds.current.has(n.id)) return;
    seenIds.current.add(n.id);
    // Muted rooms are dropped outright. Everything else is stored so it can
    // badge the room; `alert` records whether it's also "loud" (bell inbox
    // + sound/desktop) or badge-only.
    if (roomLevel(settingsRef.current, n.room) === "muted") return;
    const loud = isAlert(n, settingsRef.current);
    // Something said in the room you're looking at is read as it arrives: it
    // shouldn't badge the room you're in or count on the bell.
    const focused = document.hasFocus();
    const seeing = focused && roomOfPath(window.location.pathname) === n.room;
    setNotifications((prev) => [...prev, { ...n, read: seeing, alert: loud }]);
    // A mention of you plays a sound, unless you're looking at the room it was
    // said in. Only the leader tab plays it, so several open tabs ring once.
    // The system notification is for when the window isn't focused:
    // `hasFocus()` (not visibilityState) is false when you've switched tabs,
    // minimized, or alt-tabbed to another app.
    if (loud && !seeing && !settingsRef.current.dnd && isLeader.current) {
      if (settingsRef.current.soundEnabled) ping(settingsRef.current.soundVolume);
      if (
        !focused &&
        settingsRef.current.desktopEnabled &&
        "Notification" in window &&
        window.Notification.permission === "granted"
      ) {
        try {
          const note = new window.Notification(`${n.sender} mentioned you in ${n.room}`, { body: n.summary, tag: n.id });
          note.onclick = () => {
            window.focus();
            note.close();
            // The bell routes it, since it sits under the app's router.
            setNotifications((prev) => prev.map((x) => (x.id === n.id ? { ...x, read: true } : x)));
            channelRef.current?.post({ type: "read", id: n.id });
            window.dispatchEvent(new CustomEvent(OPEN_MENTION_EVENT, { detail: mentionHref(n) }));
          };
        } catch {
          // Best-effort — a blocked/unsupported Notification() must never break the feed.
        }
      }
    }
    // Read aloud whenever the bell rings for it, in the tab you can see, once
    // the page can play sound: a popover never opens pretending to read.
    if (loud && !seeing && !settingsRef.current.dnd && settingsRef.current.readAloud && speechRef.current && text && audioReady()) {
      void readMention({ ...n, text });
    }
    // A mention in a task's thread names the task in the bell.
    if (loud && n.episode) {
      const episode = n.episode;
      void taskTitle(n.room, episode).then((title) => {
        if (title) setNotifications((prev) => prev.map((x) => (x.id === n.id ? { ...x, title } : x)));
      });
    }
  });

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
    if (document.hasFocus()) channelRef.current?.post({ type: "viewing", room });
  }, []);

  // Coming back to the window reads the room it's showing: what arrived while
  // you were away is on screen now. Leaving it tells the other windows nothing
  // is on screen here any more.
  useEffect(() => {
    const onFocus = () => {
      const room = roomOfPath(window.location.pathname);
      if (room) markRoomRead(room);
      else channelRef.current?.post({ type: "viewing", room: null });
    };
    const onBlur = () => channelRef.current?.post({ type: "viewing", room: null });
    window.addEventListener("focus", onFocus);
    window.addEventListener("blur", onBlur);
    return () => {
      window.removeEventListener("focus", onFocus);
      window.removeEventListener("blur", onBlur);
    };
  }, [markRoomRead]);

  // Moving to another page without leaving the window: the room it showed is
  // off screen, so the other windows may read its mentions again.
  const pathname = usePathname();
  useEffect(() => {
    if (document.hasFocus()) channelRef.current?.post({ type: "viewing", room: roomOfPath(pathname ?? "") });
  }, [pathname]);

  const requestDesktopPermission = useCallback(() => {
    if (typeof window === "undefined" || !("Notification" in window)) return;
    window.Notification.requestPermission().then((perm) => setDesktopPermission(perm));
  }, []);

  const readAloud = useMemo<ReadAloud>(
    () => ({
      available: speechAvailable,
      state: readerState,
      stop: () => readerRef.current?.stop(),
      readAll: () => readerRef.current?.readAll(),
      keepOpen: (open) => readerRef.current?.keepOpen(open),
      tryIt: () => {
        primeAudio();
        readerRef.current?.enqueue({
          id: `try:${Date.now()}`,
          sender: "",
          where: "",
          href: null,
          blocks: speakable(SAMPLE),
        });
      },
    }),
    [speechAvailable, readerState],
  );

  // The bell's badge + tab title count only "loud" unread — mentions, directs,
  // and a negotiation you were in. Badge-only room activity lives in the sidebar.
  const unreadCount = useMemo(
    () => notifications.filter((n) => n.alert !== false && !n.read).length,
    [notifications],
  );

  const value = useMemo<NotificationsContextValue>(
    () => ({
      notifications,
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

  return (
    <NotificationsContext.Provider value={value}>
      <ReadAloudContext.Provider value={readAloud}>{children}</ReadAloudContext.Provider>
    </NotificationsContext.Provider>
  );
}

export function useReadAloud(): ReadAloud {
  const ctx = useContext(ReadAloudContext);
  if (!ctx) throw new Error("useReadAloud must be used within a NotificationsProvider");
  return ctx;
}

export function useNotifications(): NotificationsContextValue {
  const ctx = useContext(NotificationsContext);
  if (!ctx) throw new Error("useNotifications must be used within a NotificationsProvider");
  return ctx;
}

/** The same, or null outside a provider: for a control (the room's menu) that
 *  also renders where there are no notifications, like a test. */
export function useOptionalNotifications(): NotificationsContextValue | null {
  return useContext(NotificationsContext);
}
