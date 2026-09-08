export type SessionState =
  | "idle"
  | "listening"
  | "transcribing"
  | "thinking"
  | "speaking"
  | "interrupted";

export type Line = {
  id: string;
  role: "user" | "assistant";
  text: string;
  interrupted?: boolean;
  partial?: boolean;
};

export type TicketLine = { item: string; qty: number; mods: string };
export type Booking = { name: string; party: number; date: string; time: string };

export type Ticket = {
  lines: TicketLine[];
  confirmed: boolean;
  bookings: Booking[];
};

export type CascadeStep = { step: string; ms: number };

export type InspectorEvent = {
  id: string;
  at: number;
  kind: string;
  detail: string;
};

export type Pipeline = {
  generationId: string;
  state: SessionState;
  micLive: boolean;
  inSpeech: boolean;
  rms: number;
  ttfaMs: number | null;
  lastCascade: CascadeStep[];
  events: InspectorEvent[];
};
