import { useEffect, useRef, useState } from "react";
import { Cite } from "./SourceViewer";
import { api } from "../lib/api";

type Msg = { role: "user" | "assistant"; text: string; citations?: any[]; offline?: boolean };

const SUGGEST = {
  attorney: ["What changed recently?", "When did we last talk to the client?", "What's the Medicaid lien?", "Why is liability a problem?"],
  provider: ["Is the case still active?", "What does the firm need from my office?", "What is my balance on file?", "When is the next visit?"],
};

/** Floating assistant, bottom-right. mode "attorney" = verified case facts with citations; "provider" = this link's shared items only. */
export default function ChatWidget({ mode, token, firm }: { mode: "attorney" | "provider"; token?: string; firm?: string }) {
  // ?chat=open in the URL opens the assistant on load (handy for demos)
  const [open, setOpen] = useState(() => /[?&]chat=open/.test(window.location.hash + window.location.search));
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [rec, setRec] = useState<"idle" | "recording" | "transcribing">("idle");
  const [secs, setSecs] = useState(0);
  const [speak, setSpeak] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);
  const timer = useRef<any>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const canTalk = typeof window !== "undefined" && !!navigator.mediaDevices?.getUserMedia && typeof MediaRecorder !== "undefined";
  const canSpeak = typeof window !== "undefined" && "speechSynthesis" in window;

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs, busy, open]);
  useEffect(() => () => { clearInterval(timer.current); window.speechSynthesis?.cancel(); }, []);

  const say = (text: string) => {
    if (!speak || !canSpeak) return;
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text.replace(/\[\d+\]/g, ""));
    u.rate = 1.02;
    window.speechSynthesis.speak(u);
  };

  const ask = async (q: string) => {
    const question = q.trim();
    if (!question || busy) return;
    setErr(null); setInput("");
    const history = msgs.map((m) => ({ role: m.role, text: m.text }));
    setMsgs((m) => [...m, { role: "user", text: question }]);
    setBusy(true);
    try {
      const r = mode === "provider" ? await api.providerChat(token!, question, history) : await api.chat(question, history);
      setMsgs((m) => [...m, { role: "assistant", text: r.answer, citations: r.citations, offline: r.offline }]);
      say(r.answer);
    } catch (e: any) {
      setMsgs((m) => [...m, { role: "assistant", text: `Sorry, that didn't work (${e.message}).`, offline: true }]);
    } finally { setBusy(false); }
  };

  const startRec = async () => {
    setErr(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const type = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg"].find((t) => MediaRecorder.isTypeSupported?.(t)) || "";
      const mr = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
      chunks.current = [];
      mr.ondataavailable = (e) => e.data.size && chunks.current.push(e.data);
      mr.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        clearInterval(timer.current);
        const blob = new Blob(chunks.current, { type: mr.mimeType || "audio/webm" });
        if (blob.size < 1200) { setRec("idle"); setErr("Didn't catch that. Hold the mic a little longer."); return; }
        setRec("transcribing");
        try {
          const r = await api.transcribe(blob, mode === "provider" ? token : undefined);
          setRec("idle");
          if (r.text) ask(r.text); else setErr("Didn't catch any words. Try again?");
        } catch (e: any) { setRec("idle"); setErr(`Voice failed: ${e.message}`); }
      };
      recorder.current = mr;
      mr.start();
      setRec("recording"); setSecs(0);
      timer.current = setInterval(() => setSecs((s) => { if (s >= 89) { mr.state === "recording" && mr.stop(); } return s + 1; }), 1000);
    } catch {
      setErr("Microphone blocked. Allow mic access in the browser to use voice.");
    }
  };
  const stopRec = () => recorder.current?.state === "recording" && recorder.current.stop();

  return (
    <>
      {!open && (
        <button onClick={() => setOpen(true)} aria-label="Open the case assistant"
          className="fixed bottom-5 right-5 z-[60] flex h-14 w-14 items-center justify-center rounded-full bg-indigo-600 text-white shadow-xl transition hover:scale-105 hover:bg-indigo-700">
          <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" /></svg>
        </button>
      )}
      {open && (
        <div className="fixed bottom-5 right-5 z-[60] flex h-[min(600px,calc(100vh-40px))] w-[min(400px,calc(100vw-24px))] flex-col overflow-hidden rounded-2xl border bg-white shadow-2xl" role="dialog" aria-label="Case assistant">
          <div className="flex items-start gap-2 border-b bg-slate-900 px-4 py-3 text-white">
            <div className="min-w-0 flex-1">
              <div className="font-semibold">{mode === "provider" ? "Ask about this case" : "Case assistant"}</div>
              <div className="text-[11px] text-slate-300">
                {mode === "provider" ? `Answers only from what ${firm || "the firm"} shared with you` : "Answers only from verified case facts, with sources"}
              </div>
            </div>
            {canSpeak && (
              <button onClick={() => { setSpeak(!speak); window.speechSynthesis.cancel(); }} aria-pressed={speak}
                title={speak ? "Stop reading answers aloud" : "Read answers aloud"}
                className={`rounded-lg px-2 py-1 text-xs ${speak ? "bg-white text-slate-900" : "text-slate-300 hover:bg-white/10"}`}>
                {speak ? "🔊 on" : "🔈 off"}
              </button>
            )}
            <button onClick={() => { setOpen(false); stopRec(); window.speechSynthesis?.cancel(); }} aria-label="Close" className="rounded-lg px-2 py-1 text-slate-300 hover:bg-white/10">✕</button>
          </div>

          <div className="flex-1 space-y-3 overflow-y-auto bg-slate-50 p-3">
            {msgs.length === 0 && (
              <div className="space-y-2">
                <div className="text-sm text-slate-600">Type a question or tap the mic and speak. Try:</div>
                {SUGGEST[mode].map((s) => (
                  <button key={s} onClick={() => ask(s)} className="block w-full rounded-lg border bg-white px-3 py-2 text-left text-sm hover:border-indigo-300">{s}</button>
                ))}
              </div>
            )}
            {msgs.map((m, i) => (
              <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
                <div className={`max-w-[85%] rounded-2xl px-3 py-2 text-sm ${m.role === "user" ? "bg-indigo-600 text-white" : m.offline ? "border border-amber-200 bg-amber-50 text-amber-900" : "border bg-white text-slate-800"}`}>
                  <div className="whitespace-pre-wrap">{m.text}</div>
                  {m.citations && m.citations.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1 border-t pt-2">
                      {mode === "attorney"
                        ? m.citations.map((c: any) => <Cite key={c.n} src={c} label={`[${c.n}] ${(c.text || "").slice(0, 28)}…`} />)
                        : m.citations.map((c: any) => <span key={c.n} title={c.text} className="chip bg-emerald-50 text-emerald-800">✓ shared item {c.n}</span>)}
                    </div>
                  )}
                  {m.role === "assistant" && canSpeak && !m.offline && (
                    <button onClick={() => { window.speechSynthesis.cancel(); window.speechSynthesis.speak(new SpeechSynthesisUtterance(m.text.replace(/\[\d+\]/g, ""))); }}
                      className="mt-1 text-[11px] text-slate-400 hover:text-indigo-600">🔈 read aloud</button>
                  )}
                </div>
              </div>
            ))}
            {busy && <div className="flex justify-start"><div className="rounded-2xl border bg-white px-3 py-2 text-sm text-slate-500"><span className="animate-pulse">Checking the file…</span></div></div>}
            <div ref={endRef} />
          </div>

          {err && <div className="border-t bg-rose-50 px-3 py-1.5 text-xs text-rose-700">{err}</div>}
          <form onSubmit={(e) => { e.preventDefault(); ask(input); }} className="flex items-center gap-2 border-t bg-white p-2">
            {canTalk && (
              <button type="button" onClick={rec === "recording" ? stopRec : startRec} disabled={rec === "transcribing" || busy}
                aria-label={rec === "recording" ? "Stop recording" : "Speak your question"} title={rec === "recording" ? "Stop and send" : "Speak your question"}
                className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full transition ${rec === "recording" ? "animate-pulse bg-rose-600 text-white" : "bg-slate-100 text-slate-700 hover:bg-slate-200"} disabled:opacity-50`}>
                {rec === "recording"
                  ? <span className="h-3 w-3 rounded-sm bg-white" />
                  : <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden><rect x="9" y="2" width="6" height="12" rx="3" /><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3" /></svg>}
              </button>
            )}
            <input value={rec === "recording" ? `Listening… ${secs}s (tap ■ to send)` : rec === "transcribing" ? "Transcribing…" : input}
              onChange={(e) => setInput(e.target.value)} disabled={rec !== "idle"} placeholder="Ask about this case…"
              className="min-w-0 flex-1 rounded-full border px-4 py-2 text-sm outline-none focus:border-indigo-400 disabled:bg-slate-50" />
            <button disabled={!input.trim() || busy || rec !== "idle"} className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-indigo-600 text-white disabled:opacity-40" aria-label="Send">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden><path d="M22 2 11 13M22 2l-7 20-4-9-9-4z" /></svg>
            </button>
          </form>
        </div>
      )}
    </>
  );
}
