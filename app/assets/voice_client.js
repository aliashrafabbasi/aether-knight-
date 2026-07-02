/**
 * Duplex voice with barge-in — mic stays open, interrupt to cut in.
 */
class NaturalVoiceClient {
  constructor(ws, { onLog, onStatus, onStop } = {}) {
    this.ws = ws;
    this.onLog = onLog || (() => {});
    this.onStatus = onStatus || (() => {});
    this.onStop = onStop || (() => {});

    this.state = "idle";
    this.phase = "idle";
    this.stream = null;
    this.mediaRecorder = null;
    this.audioContext = null;
    this.analyser = null;
    this.dataArray = null;
    this.monitorId = null;
    this.chunks = [];
    this.mimeType = "audio/webm";

    this.userRecording = false;
    this.silenceStart = null;
    this.speechStart = null;
    this.interruptHoldStart = null;
    this.noiseFloor = 0.004;
    this.calibrating = true;
    this.calibrationEnd = 0;

    this.currentAudio = null;
    this._speechResolve = null;
    this.staleGeneration = -1;

    this.SILENCE_MS = 1000;
    this.MIN_SPEECH_MS = 700;
    this.SPEECH_MULTIPLIER = 1.7;
    this.INTERRUPT_MULTIPLIER = 3.2;
    this.INTERRUPT_MS = 500;
    this.MAX_RECORD_MS = 22000;
    this.cooldownUntil = 0;
    this.endAfterSpeech = false;
  }

  _pickMimeType() {
    const types = [
      "audio/webm;codecs=opus",
      "audio/webm",
      "audio/ogg;codecs=opus",
    ];
    for (const t of types) {
      if (MediaRecorder.isTypeSupported(t)) return t;
    }
    return "audio/webm";
  }

  _extension() {
    if (this.mimeType.includes("ogg")) return "ogg";
    return "webm";
  }

  async start() {
    this.mimeType = this._pickMimeType();
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: false,
        autoGainControl: true,
        sampleRate: { ideal: 48000 },
        channelCount: 1,
      },
    });

    this.audioContext = new AudioContext({ sampleRate: 48000, latencyHint: "interactive" });
    await this.audioContext.resume();

    const source = this.audioContext.createMediaStreamSource(this.stream);
    this.analyser = this.audioContext.createAnalyser();
    this.analyser.fftSize = 2048;
    this.analyser.smoothingTimeConstant = 0.5;
    source.connect(this.analyser);
    this.dataArray = new Uint8Array(this.analyser.fftSize);

    this.calibrating = true;
    this.calibrationEnd = Date.now() + 1200;
    this.state = "live";
    this.phase = "calibrating";
    this.onStatus("listening", "Calibrating mic… stay quiet");
    this.onLog("Speak naturally — interrupt me while I talk", "sys");
    this._monitor();
  }

  stop() {
    this.state = "idle";
    this.phase = "idle";
    this.endAfterSpeech = false;
    this._stopAgentAudio();
    if (this.monitorId) cancelAnimationFrame(this.monitorId);
    if (this.mediaRecorder?.state === "recording") this.mediaRecorder.stop();
    this.stream?.getTracks().forEach((t) => t.stop());
    this.audioContext?.close();
  }

  endSession() {
    this.endAfterSpeech = true;
    if (!this.currentAudio) this._completeEnd();
  }

  _completeEnd() {
    const cb = this.onStop;
    this.stop();
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.close();
    }
    if (cb) cb();
  }

  requestEnd() {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: "end_session" }));
    }
  }

  onServerReady() {
    if (this.state !== "live") return;
    if (this.phase === "processing") {
      this.phase = "ready";
    }
    this.cooldownUntil = Date.now() + 400;
    this.onStatus("listening", "Your turn — speak or interrupt anytime");
  }

  _rms() {
    this.analyser.getByteTimeDomainData(this.dataArray);
    let sum = 0;
    for (let i = 0; i < this.dataArray.length; i++) {
      const v = (this.dataArray[i] - 128) / 128;
      sum += v * v;
    }
    return Math.sqrt(sum / this.dataArray.length);
  }

  _threshold(forInterrupt = false) {
    const mult = forInterrupt ? this.INTERRUPT_MULTIPLIER : this.SPEECH_MULTIPLIER;
    const floor = forInterrupt ? 0.008 : 0.004;
    return Math.max(this.noiseFloor * mult, floor);
  }

  _stopAgentAudio() {
    if (this.currentAudio) {
      this.currentAudio.pause();
      this.currentAudio.src = "";
      this.currentAudio = null;
    }
    if (this._speechResolve) {
      this._speechResolve("stopped");
      this._speechResolve = null;
    }
    if (this.phase === "agent_speaking") {
      this.phase = "ready";
      this.cooldownUntil = Date.now() + 300;
    }
  }

  _interruptAgent() {
    if (this.phase !== "agent_speaking" && this.phase !== "processing") return false;
    this._stopAgentAudio();
    if (this.phase === "processing") {
      this.staleGeneration += 1;
      if (this.ws?.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify({ type: "cancel" }));
      }
      this.onLog("Interrupted — listening…", "sys");
    } else {
      this.onLog("Interrupted — go ahead", "sys");
    }
    this.phase = "ready";
    return true;
  }

  _holdInterrupt(loud) {
    const now = Date.now();
    if (loud) {
      if (!this.interruptHoldStart) this.interruptHoldStart = now;
      else if (now - this.interruptHoldStart >= this.INTERRUPT_MS) {
        this.interruptHoldStart = null;
        return true;
      }
    } else {
      this.interruptHoldStart = null;
    }
    return false;
  }

  _beginRecording() {
    if (this.mediaRecorder?.state === "recording") return;
    this._stopAgentAudio();

    this.chunks = [];
    const opts = { mimeType: this.mimeType, audioBitsPerSecond: 256000 };
    this.mediaRecorder = new MediaRecorder(this.stream, opts);
    this.mediaRecorder.ondataavailable = (e) => {
      if (e.data.size > 0) this.chunks.push(e.data);
    };
    this.mediaRecorder.start(250);
    this.userRecording = true;
    this.phase = "recording";
    this.silenceStart = null;
    this.onStatus("recording", "Hearing you…");
    this.onLog("🎤 Recording", "sys");
  }

  _monitor() {
    if (this.state !== "live") return;

    const rms = this._rms();
    const now = Date.now();

    if (this.calibrating) {
      this.noiseFloor = this.noiseFloor * 0.85 + rms * 0.15;
      if (now >= this.calibrationEnd) {
        this.calibrating = false;
        this.phase = "ready";
        this.onStatus("listening", "Speak — pause 1 sec when done");
        this.onLog("Ready — interrupt me anytime while I speak", "sys");
      }
      this.monitorId = requestAnimationFrame(() => this._monitor());
      return;
    }

    // --- Finish recording on silence ---
    if (this.userRecording) {
      const loud = rms > this._threshold(false);
      if (loud) {
        this.silenceStart = null;
        if (now - this.speechStart > this.MAX_RECORD_MS) this._finishUtterance();
      } else if (!this.silenceStart) {
        this.silenceStart = now;
      } else if (now - this.silenceStart >= this.SILENCE_MS) {
        if (now - this.speechStart >= this.MIN_SPEECH_MS) {
          this._finishUtterance();
        } else {
          this._cancelUtterance();
        }
      }
      this.monitorId = requestAnimationFrame(() => this._monitor());
      return;
    }

    // --- Interrupt agent while speaking or thinking ---
    const agentBusy = this.phase === "agent_speaking" || this.phase === "processing";
    if (agentBusy) {
      const loud = rms > this._threshold(true);
      if (this._holdInterrupt(loud) && this._interruptAgent()) {
        this.speechStart = now;
        this._beginRecording();
      }
      this.monitorId = requestAnimationFrame(() => this._monitor());
      return;
    }

    // --- Start new utterance when idle ---
    if (this.phase === "ready" && now >= this.cooldownUntil) {
      const loud = rms > this._threshold(false);
      if (loud) {
        this.speechStart = now;
        this._beginRecording();
      }
    }

    this.monitorId = requestAnimationFrame(() => this._monitor());
  }

  async _sendRecording() {
    const blob = new Blob(this.chunks, { type: this.mimeType });
    const buffer = await blob.arrayBuffer();
    this.chunks = [];

    if (buffer.byteLength < 3000) {
      this.onLog("Too quiet — speak louder", "sys");
      this.phase = "ready";
      this.onStatus("listening", "Speak louder and try again");
      return;
    }

    if (this.ws.readyState !== WebSocket.OPEN) return;

    this.phase = "processing";
    this.onStatus("processing", "Thinking…");

    this.ws.send(JSON.stringify({ type: "start", format: this._extension() }));
    this.ws.send(buffer);
    this.ws.send(JSON.stringify({ type: "stop" }));
    this.onLog(`Sent ${(buffer.byteLength / 1024).toFixed(1)} KB`, "sys");
  }

  _finishUtterance() {
    if (!this.userRecording) return;
    this.silenceStart = null;
    this.onLog("Sending to agent…", "sys");

    const recorder = this.mediaRecorder;
    if (recorder?.state === "recording") {
      recorder.onstop = () => {
        this.userRecording = false;
        this._sendRecording();
      };
      if (typeof recorder.requestData === "function") recorder.requestData();
      recorder.stop();
    } else {
      this.userRecording = false;
      this._sendRecording();
    }
  }

  _cancelUtterance() {
    this.userRecording = false;
    this.silenceStart = null;
    this.chunks = [];
    if (this.mediaRecorder?.state === "recording") this.mediaRecorder.stop();
    this.phase = "ready";
    this.onStatus("listening", "Speak a bit longer");
    this.onLog("Too short — say a full phrase", "sys");
  }

  playSpeech(b64) {
    if (!b64) return Promise.resolve();

    this.phase = "agent_speaking";
    this.interruptHoldStart = null;
    this.onStatus("speaking", "Speaking — talk over me to interrupt");

    return new Promise((resolve) => {
      const audio = new Audio("data:audio/mp3;base64," + b64);
      this.currentAudio = audio;
      this._speechResolve = resolve;

      const finish = () => {
        if (this.currentAudio !== audio) return;
        this.currentAudio = null;
        this._speechResolve = null;
        if (this.phase === "agent_speaking") {
          this.phase = "ready";
          this.cooldownUntil = Date.now() + 500;
          if (!this.endAfterSpeech) {
            this.onStatus("listening", "Your turn");
          }
        }
        resolve("done");
        if (this.endAfterSpeech) this._completeEnd();
      };

      audio.onended = finish;
      audio.onerror = finish;
      audio.play().catch(finish);
    });
  }
}
