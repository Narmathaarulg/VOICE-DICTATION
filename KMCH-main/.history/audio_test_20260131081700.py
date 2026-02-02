import pyaudio, wave, time

p = pyaudio.PyAudio()
stream = p.open(format=pyaudio.paInt16, channels=1, rate=44100, input=True, frames_per_buffer=1024)

frames = []
print("Recording...")
for i in range(0, int(44100 / 1024 * 5)):
    data = stream.read(1024)
    frames.append(data)

print("Done")

stream.stop_stream()
stream.close()
p.terminate()

wf = wave.open("test.wav", 'wb')
wf.setnchannels(1)
wf.setsampwidth(p.get_sample_size(pyaudio.paInt16))
wf.setframerate(44100)
wf.writeframes(b''.join(frames))
wf.close()
