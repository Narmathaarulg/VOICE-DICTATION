import pyaudio

p = pyaudio.PyAudio()
stream = p.open(format=pyaudio.paInt16, channels=1, rate=44100,
                input=True, input_device_index=1, frames_per_buffer=1024)

print("Recording test...")
for i in range(50):
    data = stream.read(1024, exception_on_overflow=False)
    print("Frame:", len(data))

stream.stop_stream()
stream.close()
p.terminate()
print("Done")
