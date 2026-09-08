export type CaptureHandlers = {
  onFrame: (pcm: ArrayBuffer, rms: number, speech: boolean) => void;
  onSpeechStart: (rms: number) => void;
  onSpeechEnd: (rms: number) => void;
};

export class VoiceEngine {
  ctx: AudioContext | null = null;
  stream: MediaStream | null = null;
  capture: AudioWorkletNode | null = null;
  onPlaybackDone: (() => void) | null = null;

  private source: MediaStreamAudioSourceNode | null = null;
  private current: AudioBufferSourceNode | null = null;
  private queue: ArrayBuffer[] = [];
  private pumping = false;
  private cancelled = false;

  async start(handlers: CaptureHandlers): Promise<void> {
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
        channelCount: 1,
      },
    });
    const ctx = new AudioContext();
    this.ctx = ctx;
    await ctx.audioWorklet.addModule("/worklets/capture-processor.js");
    if (ctx.state === "suspended") await ctx.resume();

    this.capture = new AudioWorkletNode(ctx, "capture-processor");
    this.source = ctx.createMediaStreamSource(this.stream);
    this.source.connect(this.capture);
    const mute = ctx.createGain();
    mute.gain.value = 0;
    this.capture.connect(mute);
    mute.connect(ctx.destination);

    this.capture.port.onmessage = (ev: MessageEvent) => {
      const data = ev.data;
      if (data.type === "frame") handlers.onFrame(data.pcm, data.rms, data.speech);
      if (data.type === "speech_start") handlers.onSpeechStart(data.rms);
      if (data.type === "speech_end") handlers.onSpeechEnd(data.rms);
    };
  }

  enqueueMp3(data: ArrayBuffer) {
    if (!this.ctx) {
      this.ctx = new AudioContext();
    }
    if (this.ctx.state === "suspended") void this.ctx.resume();
    this.cancelled = false;
    this.queue.push(data);
    void this.pump();
  }

  flush() {
    this.cancelled = true;
    this.queue = [];
    if (this.current) {
      try {
        this.current.stop();
      } catch {
        /* already stopped */
      }
      this.current = null;
    }
    this.pumping = false;
  }

  async stop() {
    this.flush();
    const ctx = this.ctx;
    const stream = this.stream;
    try {
      this.capture?.disconnect();
    } catch {
      /* already gone */
    }
    try {
      this.source?.disconnect();
    } catch {
      /* already gone */
    }
    this.capture = null;
    this.source = null;
    this.stream = null;
    this.ctx = null;
    stream?.getTracks().forEach((t) => t.stop());
    if (ctx && ctx.state !== "closed") {
      try {
        await ctx.close();
      } catch {
        /* already closed */
      }
    }
  }

  private async pump() {
    if (this.pumping || !this.ctx) return;
    this.pumping = true;
    while (this.queue.length && this.ctx && !this.cancelled) {
      const raw = this.queue.shift();
      if (!raw) break;
      try {
        const buf = await this.ctx.decodeAudioData(raw.slice(0));
        if (this.cancelled) break;
        await this.playBuffer(buf);
      } catch (err) {
        console.warn("decode/play failed", err);
      }
    }
    this.pumping = false;
    if (!this.cancelled) this.onPlaybackDone?.();
  }

  private playBuffer(buf: AudioBuffer) {
    return new Promise<void>((resolve) => {
      if (!this.ctx) {
        resolve();
        return;
      }
      const src = this.ctx.createBufferSource();
      src.buffer = buf;
      src.connect(this.ctx.destination);
      this.current = src;
      src.onended = () => {
        if (this.current === src) this.current = null;
        resolve();
      };
      src.start();
    });
  }
}
