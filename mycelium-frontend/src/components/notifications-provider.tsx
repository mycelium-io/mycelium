// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { getNotificationsSSEUrl } from "@/lib/api";
import { useCurrentUser } from "@/components/current-user";
import { ping, primeAudio } from "@/lib/audio-ping";
import {
  classify,
  DEFAULT_SETTINGS,
  electLeader,
  isAdmitted,
  loadNotifications,
  loadSettings,
  openCrossTabChannel,
  saveNotifications,
  saveSettings,
  type NotificationSettings,
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
  dismiss: (id: string) => void;
  clearAll: () => void;
  muteRoom: (room: string) => void;
  unmuteRoom: (room: string) => void;
  desktopPermission: NotificationPermission | "unsupported";
  requestDesktopPermission: () => void;
}

const NotificationsContext = createContext<NotificationsContextValue | null>(null);

const BASE_TITLE = "mycelium";

export function NotificationsProvider({ children }: { children: ReactNode }) {
  const { principal } = useCurrentUser();
  const [notifications, setNotifications] = useState<StoredNotification[]>([]);
  const [settings, setSettingsState] = useState<NotificationSettings>(DEFAULT_SETTINGS);
  const [connected, setConnected] = useState(false);
  const [desktopPermission, setDesktopPermission] = useState<NotificationPermission | "unsupported">(
    "unsupported",
  );

  const settingsRef = useRef(settings);
  settingsRef.current = settings;
  const principalRef = useRef(principal);
  principalRef.current = principal;
  const seenIds = useRef<Set<string>>(new Set());
  const isLeader = useRef(false);
  const channelRef = useRef<ReturnType<typeof openCrossTabChannel> | null>(null);

  // Hydrate from localStorage once the DOM is available (SSR has none).
  useEffect(() => {
    const stored = loadNotifications();
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
        case "dismiss":
          setNotifications((prev) => prev.filter((n) => n.id !== msg.id));
          break;
        case "clear":
          setNotifications([]);
          break;
        case "settings":
          setSettingsState(msg.settings);
          break;
      }
    });
    channelRef.current = channel;
    return () => channel.close();
  }, []);

  // Persist to localStorage whenever the list changes.
  useEffect(() => {
    saveNotifications(notifications);
  }, [notifications]);

  // Tab-title unread badge.
  useEffect(() => {
    const unread = notifications.filter((n) => !n.read).length;
    document.title = unread > 0 ? `(${unread}) ${BASE_TITLE}` : BASE_TITLE;
  }, [notifications]);

  // The single global SSE subscription — one connection for every room the
  // user participates in, independent of which (if any) is open.
  useEffect(() => {
    const url = getNotificationsSSEUrl();
    let es: EventSource;
    let retryTimeout: ReturnType<typeof setTimeout>;

    function connect() {
      es = new EventSource(url);
      es.onopen = () => setConnected(true);
      es.onmessage = (e) => {
        try {
          const raw = JSON.parse(e.data);
          const n = classify(raw, principalRef.current);
          if (!n) return;
          if (seenIds.current.has(n.id)) return;
          seenIds.current.add(n.id);
          if (!isAdmitted(n, settingsRef.current)) return;
          setNotifications((prev) => [...prev, { ...n, read: false }]);
          if (isLeader.current && document.visibilityState !== "visible") {
            if (settingsRef.current.soundEnabled) ping(settingsRef.current.soundVolume);
            if (settingsRef.current.desktopEnabled && "Notification" in window && window.Notification.permission === "granted") {
              try {
                new window.Notification(`${n.room} · ${n.kind}`, { body: n.summary || n.sender });
              } catch {
                // Best-effort — a blocked/unsupported Notification() must never break the feed.
              }
            }
          }
        } catch {
          // A malformed frame is dropped, not fatal to the connection.
        }
      };
      es.onerror = () => {
        setConnected(false);
        es.close();
        retryTimeout = setTimeout(connect, 5000);
      };
    }

    connect();
    return () => {
      es?.close();
      clearTimeout(retryTimeout);
    };
  }, []);

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

  const muteRoom = useCallback(
    (room: string) => {
      if (settingsRef.current.mutedRooms.includes(room)) return;
      setSettings({ ...settingsRef.current, mutedRooms: [...settingsRef.current.mutedRooms, room] });
    },
    [setSettings],
  );

  const unmuteRoom = useCallback(
    (room: string) => {
      setSettings({ ...settingsRef.current, mutedRooms: settingsRef.current.mutedRooms.filter((r) => r !== room) });
    },
    [setSettings],
  );

  const requestDesktopPermission = useCallback(() => {
    if (typeof window === "undefined" || !("Notification" in window)) return;
    window.Notification.requestPermission().then((perm) => setDesktopPermission(perm));
  }, []);

  const unreadCount = useMemo(() => notifications.filter((n) => !n.read).length, [notifications]);

  const value = useMemo<NotificationsContextValue>(
    () => ({
      notifications,
      unreadCount,
      connected,
      settings,
      setSettings,
      markRead,
      markAllRead,
      dismiss,
      clearAll,
      muteRoom,
      unmuteRoom,
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
      dismiss,
      clearAll,
      muteRoom,
      unmuteRoom,
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
