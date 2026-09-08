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

export type MovieHold = {
  id: string;
  title: string;
  theater: string;
  time: string;
  date: string;
  seats: number;
  screen: string;
  price: number;
  code: string;
  confirmed: boolean;
};

export type TripHold = {
  id: string;
  kind: string;
  title: string;
  detail: string;
  date: string;
  travelers: number;
  price: number;
  code: string;
  confirmed: boolean;
};

export type Desk = {
  movies: MovieHold[];
  trips: TripHold[];
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
