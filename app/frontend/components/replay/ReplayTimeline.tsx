"use client";

import { Pause, Play, RotateCcw, RotateCw } from "lucide-react";
import { useEffect, useState } from "react";
import { shortDate } from "@/components/common/format";
import { Panel } from "@/components/common/Panel";
import { useDashboardStore } from "@/stores/dashboard";

export function ReplayTimeline({ origins }: { origins: string[] }) {
  const { origin, set, reveal } = useDashboardStore();
  const ordered = [...origins].sort();
  const index = Math.max(0, ordered.indexOf(origin || ordered[ordered.length - 1] || ""));
  const [playing, setPlaying] = useState(false);
  useEffect(() => { if (!playing || ordered.length < 2) return; const timer = window.setInterval(() => { const current = ordered.indexOf(useDashboardStore.getState().origin || ordered[ordered.length - 1]); const next = current >= ordered.length - 1 ? 0 : current + 1; set({ origin: ordered[next], reveal: false }); }, 1500); return () => window.clearInterval(timer); }, [playing, ordered, set]);
  if (!ordered.length) return null;
  const change = (delta: number) => { const next = Math.max(0, Math.min(ordered.length - 1, index + delta)); set({ origin: ordered[next], reveal: false }); };
  return <Panel title="Replay timeline" eyebrow="Information available as of each forecast origin"><div className="px-4 py-4"><div className="flex items-center gap-3"><button onClick={() => change(-1)} className="rounded-lg border border-line p-2 text-slate-400 hover:text-white"><RotateCcw size={14} /></button><button onClick={() => setPlaying((value) => !value)} className="rounded-lg border border-cyanpulse/40 bg-cyanpulse/10 p-2 text-cyanpulse">{playing ? <Pause size={14} /> : <Play size={14} />}</button><button onClick={() => change(1)} className="rounded-lg border border-line p-2 text-slate-400 hover:text-white"><RotateCw size={14} /></button><div className="flex-1"><input aria-label="Forecast origin" type="range" min={0} max={ordered.length - 1} value={index} onChange={(event) => set({ origin: ordered[Number(event.target.value)], reveal: false })} className="w-full accent-cyanpulse" /><div className="mt-1 flex justify-between text-[10px] text-slate-500"><span>{shortDate(ordered[0])}</span><span className="font-semibold text-cyanpulse">Forecast origin {shortDate(ordered[index])}</span><span>{shortDate(ordered[ordered.length - 1])}</span></div></div><button onClick={() => set({ reveal: !reveal })} className={`rounded-lg border px-3 py-2 text-[10px] font-bold uppercase tracking-[.1em] ${reveal ? "border-orange-300/40 bg-orange-300/10 text-orange-200" : "border-line text-slate-400"}`}>Reveal future</button></div></div></Panel>;
}
