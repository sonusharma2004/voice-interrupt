const EXACT = new Set([
  "stop",
  "stop it",
  "stop now",
  "stop talking",
  "stop listening",
  "stop speaking",
  "please stop",
  "please stop talking",
  "please stop listening",
  "thats enough",
  "that is enough",
  "never mind",
  "nevermind",
  "cancel",
  "quiet",
  "be quiet",
  "shut up",
  "hang up",
  "goodbye",
  "good bye",
  "bye",
  "bye bye",
  "were done",
  "we are done",
  "thats it",
  "enough",
  "end",
  "end voice",
  "mute",
  "you stop",
  "you stop now",
  "can you stop",
  "could you stop",
  "cut stop",
  "ok stop",
  "okay stop",
  "im going to go",
  "i am going to go",
  "im gonna go",
  "i am gonna go",
  "i gotta go",
  "i have to go",
  "i need to go",
  "gotta go",
  "got to go",
  "talk later",
  "see you",
  "see ya",
  "im done",
  "i am done",
]);

const LEAVE = [
  "going to go",
  "gonna go",
  "gotta go",
  "got to go",
  "have to go",
  "need to go",
  "gotta run",
];

const FRAGMENTS = new Set(["so", "sto", "sop", "stahp", "stap", "stoped", "staap"]);

export function isStopCommand(text: string, afterInterrupt = false): boolean {
  const a = text
    .toLowerCase()
    .replace(/[^a-z0-9\s]+/g, "")
    .trim();
  if (!a) return false;
  if (EXACT.has(a)) return true;
  const words = a.split(/\s+/);
  if (afterInterrupt && FRAGMENTS.has(a)) return true;
  if (words.some((w) => w === "stop" || w === "stopped" || w === "stopping")) {
    if (["dont", "never", "cant", "cannot"].includes(words[0])) return false;
    if (words.includes("sign") || a === "bus stop" || a === "stop sign") return false;
    return words.length <= 8;
  }
  if (words.length <= 6 && LEAVE.some((p) => a.includes(p))) return true;
  return false;
}
