// The promo's rhythm, as beats — not hand-typed seconds. The composition and
// the score both read their times from here, so a picture beat and its music
// land on the same grid. BEAT matches score.mjs (tempo ~69.6 BPM).
//
// A scene is a run of MOMENTS. The gap BEFORE each moment is a pause type:
//   switch  — a scene changes (medium breath)
//   short   — a beat inside a scene (a line, a row, a reply)
//   bigger  — a beat that lands harder (medium breath)
//   resolve — the scene settles before the next switch (long breath)
// # of short beats per scene is free; the rhythm stays constant because the
// pause vocabulary is fixed.

export const BEAT = 0.8625;

// Pause lengths, in beats.
export const PAUSE = { switch: 2, short: 1, bigger: 2, resolve: 3 };

// Each scene: an id and its moments as [pauseType, label].
// The label is what the composition/score hangs on that beat.
export const PLAN = [
  { id: 'hero', moments: [
    ['switch', 'in'], ['short', 'wordmark'], ['short', 'tagline'], ['resolve', 'hold'],
  ]},
  { id: 'cli', moments: [
    ['switch', 'term'], ['short', 'cmd'], ['short', 'ok1'], ['short', 'ok2'],
    ['short', 'ok3'], ['bigger', 'done'], ['resolve', 'hold'],
  ]},
  { id: 'install', moments: [
    ['switch', 'term'], ['short', 'cmd'], ['short', 'llm'], ['short', 'svc1'],
    ['short', 'svc2'], ['short', 'svc3'], ['bigger', 'ready'], ['resolve', 'hold'],
  ]},
  { id: 'board', moments: [
    ['switch', 'shell'], ['short', 'summary'], ['short', 'tabs'],
    ['short', 'decisions'], ['short', 'blocked'], ['short', 'review'],
    ['bigger', 'actions'], ['resolve', 'read'],
  ]},
  { id: 'drop', moments: [
    ['switch', 'focus'], ['short', 'type'], ['bigger', 'row'], ['resolve', 'hold'],
  ]},
  { id: 'decompose', moments: [
    ['switch', 'claim'], ['short', 'child1'], ['short', 'child2'],
    ['bigger', 'child3'], ['resolve', 'hold'],
  ]},
  { id: 'thread', moments: [
    ['switch', 'open'], ['short', 'body'], ['short', 'claim'],
    ['short', 'reply1'], ['bigger', 'reply2'], ['resolve', 'hold'],
  ]},
  { id: 'aligner', moments: [
    ['switch', 'summon'], ['short', 'issues'], ['short', 'round1'],
    ['short', 'round2'], ['bigger', 'round3'], ['short', 'round4'],
    ['bigger', 'converge'], ['resolve', 'consensus'],
  ]},
  { id: 'compile', moments: [
    ['switch', 'back'], ['short', 'row1'], ['bigger', 'row2'], ['resolve', 'hold'],
  ]},
];

// Roll the plan up into absolute times.
export function schedule() {
  let beat = 0;
  const scenes = [];
  for (const s of PLAN) {
    const events = [];
    let start = null;
    for (const [type, label] of s.moments) {
      beat += PAUSE[type];
      const t = +(beat * BEAT).toFixed(3);
      if (start === null) start = +((beat - PAUSE[type]) * BEAT).toFixed(3);
      events.push({ label, type, beat, t });
    }
    scenes.push({ id: s.id, start, events });
  }
  const totalBeats = beat;
  const scenesOut = scenes.map((s, i) => ({
    ...s,
    end: i + 1 < scenes.length ? scenes[i + 1].start : +(totalBeats * BEAT).toFixed(3),
  }));
  return { scenes: scenesOut, totalBeats, duration: +(totalBeats * BEAT).toFixed(3) };
}

// Print the schedule when run directly.
if (import.meta.url === `file://${process.argv[1]}`) {
  const { scenes, totalBeats, duration } = schedule();
  for (const s of scenes) {
    const dur = (s.end - s.start).toFixed(2);
    console.log(`\n${s.id.padEnd(10)} ${s.start.toFixed(2)}s → ${s.end.toFixed(2)}s  (${dur}s)`);
    for (const e of s.events) {
      console.log(`   ${e.t.toFixed(2).padStart(6)}s  ${e.type.padEnd(8)} ${e.label}`);
    }
  }
  console.log(`\nTOTAL ${totalBeats} beats · ${duration}s\n`);
}
