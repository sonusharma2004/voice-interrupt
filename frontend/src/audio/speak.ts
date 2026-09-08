export class BrowserVoice {
  warm() {
    if (typeof speechSynthesis === "undefined") return;
    speechSynthesis.getVoices();
  }

  speak(text: string) {
    const spoken = text.trim();
    if (!spoken || typeof speechSynthesis === "undefined") return;
    const utter = new SpeechSynthesisUtterance(spoken);
    const voice = this.pickVoice();
    if (voice) utter.voice = voice;
    utter.rate = 1.04;
    utter.pitch = 1.02;
    speechSynthesis.speak(utter);
  }

  cancel() {
    if (typeof speechSynthesis === "undefined") return;
    speechSynthesis.cancel();
  }

  private pickVoice(): SpeechSynthesisVoice | null {
    const voices = speechSynthesis.getVoices();
    const prefer = /samantha|ava neural|jenny|sara|google us english|female/i;
    return (
      voices.find((v) => prefer.test(v.name) && v.lang.startsWith("en")) ||
      voices.find((v) => v.lang === "en-US") ||
      voices.find((v) => v.lang.startsWith("en")) ||
      null
    );
  }
}
