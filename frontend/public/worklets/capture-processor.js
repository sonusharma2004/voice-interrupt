class CaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._acc = [];
    this.ratio = sampleRate / 16000;
    this._frac = 0;
    this.speech = false;
    this.speechMs = 0;
    this.silenceMs = 0;
    this.noise = 0.01;
  }

  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (!channel) return true;

    const down = [];
    let i = this._frac;
    while (i < channel.length) {
      const i0 = Math.floor(i);
      const i1 = Math.min(i0 + 1, channel.length - 1);
      const f = i - i0;
      down.push(channel[i0] * (1 - f) + channel[i1] * f);
      i += this.ratio;
    }
    this._frac = i - channel.length;

    for (const s of down) this._acc.push(s);
    while (this._acc.length >= 320) {
      const frame = this._acc.splice(0, 320);
      this._emit(frame);
    }
    return true;
  }

  _emit(frame) {
    let sum = 0;
    const pcm = new Int16Array(frame.length);
    for (let i = 0; i < frame.length; i++) {
      const x = Math.max(-1, Math.min(1, frame[i]));
      pcm[i] = x < 0 ? x * 32768 : x * 32767;
      sum += x * x;
    }
    const rms = Math.sqrt(sum / frame.length);
    if (rms < this.noise * 1.6) {
      this.noise = this.noise * 0.96 + rms * 0.04;
    }
    const thresh = Math.max(0.018, this.noise * 3.2);
    const voiced = rms > thresh;
    const ms = (frame.length / 16000) * 1000;

    if (voiced) {
      this.speechMs += ms;
      this.silenceMs = 0;
      if (!this.speech && this.speechMs > 90) {
        this.speech = true;
        this.port.postMessage({ type: "speech_start", rms });
      }
    } else {
      this.silenceMs += ms;
      if (this.speech && this.silenceMs > 240) {
        this.speech = false;
        this.speechMs = 0;
        this.port.postMessage({ type: "speech_end", rms });
      }
    }

    this.port.postMessage(
      { type: "frame", pcm: pcm.buffer, rms, speech: this.speech },
      [pcm.buffer]
    );
  }
}

registerProcessor("capture-processor", CaptureProcessor);
