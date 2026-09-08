class PlaybackProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.queue = [];
    this.offset = 0;
    this.fade = 0;
    this.fadeFrom = 0;
    this.last = 0;
    this.playing = false;
    this.port.onmessage = (e) => {
      if (e.data.type === "flush") {
        this.queue = [];
        this.offset = 0;
        this.fadeFrom = this.last;
        this.fade = Math.floor(sampleRate * 0.02);
      } else if (e.data.type === "audio") {
        this.queue.push(e.data.samples);
      }
    };
  }

  process(_inputs, outputs) {
    const out = outputs[0] && outputs[0][0];
    if (!out) return true;

    for (let i = 0; i < out.length; i++) {
      let sample = 0;
      if (this.fade > 0) {
        const steps = Math.max(1, Math.floor(sampleRate * 0.02));
        sample = this.fadeFrom * (this.fade / steps);
        this.fade -= 1;
      } else if (this.queue.length) {
        const cur = this.queue[0];
        sample = cur[this.offset] || 0;
        this.offset += 1;
        if (this.offset >= cur.length) {
          this.queue.shift();
          this.offset = 0;
        }
      }
      this.last = sample;
      out[i] = sample;
    }

    const active = this.queue.length > 0 || this.fade > 0;
    if (active !== this.playing) {
      this.playing = active;
      this.port.postMessage({ type: "playing", playing: active });
    }
    return true;
  }
}

registerProcessor("playback-processor", PlaybackProcessor);
