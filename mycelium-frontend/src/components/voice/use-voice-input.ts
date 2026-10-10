// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import useSWR from "swr";
import { ApiError, closeVoiceSession, fetchVoiceStatus, sendVoiceChunk } from "@/lib/api";
import { isDesktop } from "@/lib/desktop";
import {
  appRefusesMic,
  CAPTURE_WORKLET,
  CHUNK_MS,
  concatPcm,
  downsample,
  micErrorMessage,
  newVoiceSessionId,
  toPcm16,
} from "@/lib/voice";

export type MicState = "off" | "starting" | "listening";

/** Audio held while the hub is busy (fetching its model the first time),
 *  past which the oldest is dropped so a chunk stays under the hub's cap. */
const MAX_BUFFERED_S = 45;

function remoteInApp(): boolean {
  return typeof window !== "undefined" && appRefusesMic(window.location.hostname, isDesktop());
}

/** Drop the oldest audio past `MAX_BUFFERED_S`, keeping the latest. */
function trim(r: Rig) {
  while (r.buffered > MAX_BUFFERED_S * r.rate && r.buffer.length > 1) {
    r.buffered -= r.buffer.shift()!.length;
  }
}

interface Rig {
  sid: string;
  rate: number;
  ctx: AudioContext;
  stream: MediaStream;
  node: AudioWorkletNode;
  workletUrl: string;
  timer: ReturnType<typeof setInterval>;
  buffer: Int16Array[];
  buffered: number;
  inflight: Promise<void> | null;
  /** Until the hub says its model is ready, it's only asked (an empty chunk)
   *  while the audio waits here, so a slow first load isn't re-sent each tick. */
  loading: boolean;
}

/**
 * The composer's mic: on until it's turned off, never by a pause.
 *
 * While it's on, what the mic records goes to the hub every `CHUNK_MS`, one
 * request at a time (the hub reads a mic's chunks in order), and each piece of
 * speech the hub finishes comes back to `onText`. Turning it off sends what's
 * left with `final`, so the last thing said still lands. Nothing sends a
 * message: what's heard is only ever draft text.
 */
export function useVoiceInput(onText: (text: string) => void, onError: (message: string) => void) {
  const { data: status } = useSWR("voice-status", fetchVoiceStatus, { revalidateOnFocus: false });
  const [state, setState] = useState<MicState>("off");
  const [speaking, setSpeaking] = useState(false);
  // The first chunk can wait on the hub fetching its model; say so meanwhile.
  const [warming, setWarming] = useState(false);
  const rig = useRef<Rig | null>(null);
  const handlers = useRef({ onText, onError });
  useEffect(() => {
    handlers.current = { onText, onError };
  });

  const release = useCallback((r: Rig) => {
    clearInterval(r.timer);
    r.node.port.onmessage = null;
    r.node.disconnect();
    r.stream.getTracks().forEach((t) => t.stop());
    void r.ctx.close();
    URL.revokeObjectURL(r.workletUrl);
  }, []);

  const fail = useCallback(
    (r: Rig, err: unknown) => {
      if (rig.current === r) rig.current = null;
      release(r);
      void closeVoiceSession(r.sid);
      setState("off");
      setSpeaking(false);
      setWarming(false);
      const message = err instanceof ApiError ? err.message : micErrorMessage(err);
      handlers.current.onError(message);
    },
    [release],
  );

  /** Send what's buffered, or only ask whether the hub is ready while it loads. */
  const send = useCallback(
    (r: Rig, final: boolean): Promise<void> => {
      const probing = r.loading && !final;
      const pcm = probing ? new Int16Array(0) : concatPcm(r.buffer);
      if (!probing) {
        r.buffer = [];
        r.buffered = 0;
      }
      const out = sendVoiceChunk(r.sid, pcm, final)
        .then((heard) => {
          if (heard.ready === false) {
            // Still loading, and this chunk wasn't read: keep any audio it
            // carried, ahead of what's been recorded since.
            if (!final && rig.current === r && pcm.length) {
              r.buffer.unshift(pcm);
              r.buffered += pcm.length;
              trim(r);
            }
            r.loading = true;
            setWarming(true);
            return;
          }
          r.loading = false;
          for (const text of heard.texts) handlers.current.onText(text);
          if (rig.current === r) setSpeaking(heard.speaking);
          setWarming(false);
        })
        .catch((err: unknown) => {
          if (!final) fail(r, err);
          else handlers.current.onError(err instanceof Error ? err.message : String(err));
        })
        .finally(() => {
          if (r.inflight === out) r.inflight = null;
        });
      r.inflight = out;
      return out;
    },
    [fail],
  );

  const start = useCallback(async () => {
    if (rig.current || state !== "off") return;
    setState("starting");
    let stream: MediaStream | null = null;
    let ctx: AudioContext | null = null;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      ctx = new AudioContext();
      const workletUrl = URL.createObjectURL(new Blob([CAPTURE_WORKLET], { type: "text/javascript" }));
      await ctx.audioWorklet.addModule(workletUrl);
      const node = new AudioWorkletNode(ctx, "mycelium-capture");
      ctx.createMediaStreamSource(stream).connect(node);
      // The worklet writes nothing to its output; connecting it is what keeps it running.
      node.connect(ctx.destination);
      const rate = status?.sample_rate ?? 16000;
      const r: Rig = {
        sid: newVoiceSessionId(),
        rate,
        ctx,
        stream,
        node,
        workletUrl,
        buffer: [],
        buffered: 0,
        inflight: null,
        loading: true,
        timer: setInterval(() => {
          if (rig.current === r && !r.inflight && (r.loading || r.buffered > 0)) void send(r, false);
        }, CHUNK_MS),
      };
      const sourceRate = ctx.sampleRate;
      node.port.onmessage = (e: MessageEvent<Float32Array>) => {
        const pcm = toPcm16(downsample(e.data, sourceRate, rate));
        r.buffer.push(pcm);
        r.buffered += pcm.length;
        trim(r);
      };
      rig.current = r;
      setState("listening");
      if (status?.state === "not_downloaded") setWarming(true);
      // An empty first chunk asks at once, so a hub that has to load (or
      // fetch) its model starts on it while the person is still talking.
      void send(r, false);
    } catch (err) {
      stream?.getTracks().forEach((t) => t.stop());
      void ctx?.close();
      setState("off");
      handlers.current.onError(micErrorMessage(err));
    }
  }, [send, state, status]);

  const stop = useCallback(async () => {
    const r = rig.current;
    if (!r) return;
    rig.current = null;
    release(r);
    setState("off");
    setSpeaking(false);
    setWarming(false);
    if (r.inflight) await r.inflight;
    await send(r, true);
  }, [release, send]);

  // Leaving the composer closes the mic without transcribing the rest.
  useEffect(
    () => () => {
      const r = rig.current;
      if (!r) return;
      rig.current = null;
      release(r);
      void closeVoiceSession(r.sid);
    },
    [release],
  );

  return {
    /** Whether the mic is offered: the hub can transcribe, and nothing will refuse the microphone. */
    available: Boolean(status && status.state !== "unavailable") && !remoteInApp(),
    state,
    speaking,
    warming,
    toggle: () => (rig.current ? stop() : start()),
  };
}
