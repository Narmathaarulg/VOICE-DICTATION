"""
Deepgram Service - FINAL WORKING VERSION
Fixed variable scope issues
"""

import os
import asyncio
from deepgram import (
    DeepgramClient,
    DeepgramClientOptions,
    LiveTranscriptionEvents,
    LiveOptions,
)

class DeepgramService:
    """Real-time medical transcription service"""
    
    def __init__(self):
        api_key = os.getenv("DEEPGRAM_API_KEY")
        if not api_key:
            raise RuntimeError("❌ DEEPGRAM_API_KEY missing")

        config = DeepgramClientOptions(options={"keepalive": "true"})
        self.client = DeepgramClient(api_key, config)
        
        self.connection = None
        self.final_transcript = ""
        self.last_interim = ""
        self.active = False
        self.callback = None
        
        print("✅ Deepgram Service initialized")

    async def start_transcription(self, send_to_client):
        """Start live transcription"""
        try:
            self.callback = send_to_client
            self.final_transcript = ""
            self.last_interim = ""
            
            self.connection = self.client.listen.asynclive.v("1")
            print("🎤 Creating Deepgram live connection...")
            
            # Store reference to service instance for use in callbacks
            service = self
            
            # Event handlers - use 'service' variable instead of 'self'
            async def on_open(_, open_response, **kwargs):
                print(f"✅ Deepgram opened")
            
            async def on_message(_, result, **kwargs):
                """Handle transcription results"""
                print(f"🔔 MESSAGE RECEIVED")
                
                try:
                    if not result.channel or not result.channel.alternatives:
                        return
                    
                    sentence = result.channel.alternatives[0].transcript
                    if not sentence:
                        return
                    
                    is_final = result.is_final
                    
                    if is_final:
                        print(f"✅ Final: {sentence}")
                        # ✅ Use 'service' variable
                        service.final_transcript += sentence + " "
                        service.last_interim = ""
                        if service.callback:
                            await service.callback(sentence, True)
                    else:
                        print(f"⏳ Interim: {sentence[:50]}...")
                        
                        # ✅ FIXED: Do NOT append interim results to final_transcript
                        # Only update last_interim for reference if needed
                        service.last_interim = sentence
                        
                        if service.callback:
                            await service.callback(sentence, False)
                            
                except Exception as e:
                    print(f"❌ Error in on_message: {e}")
                    import traceback
                    traceback.print_exc()
            
            async def on_metadata(_, metadata, **kwargs):
                print(f"📊 Metadata received")
            
            async def on_speech_started(_, speech_started, **kwargs):
                print(f"🗣️ Speech started")
            
            async def on_utterance_end(_, utterance_end, **kwargs):
                print(f"🔚 Utterance ended")
            
            async def on_error(_, error, **kwargs):
                print(f"❌ Deepgram error: {error}")
            
            async def on_close(_, **kwargs):
                print(f"🔌 Connection closed")
            
            # Register handlers
            self.connection.on(LiveTranscriptionEvents.Open, on_open)
            self.connection.on(LiveTranscriptionEvents.Transcript, on_message)
            self.connection.on(LiveTranscriptionEvents.Metadata, on_metadata)
            self.connection.on(LiveTranscriptionEvents.SpeechStarted, on_speech_started)
            self.connection.on(LiveTranscriptionEvents.UtteranceEnd, on_utterance_end)
            self.connection.on(LiveTranscriptionEvents.Error, on_error)
            self.connection.on(LiveTranscriptionEvents.Close, on_close)
            
            # Configure
            options = LiveOptions(
                model="nova-2-medical",
                language="en",
                encoding="linear16",
                sample_rate=16000,
                channels=1,
                interim_results=True,
                smart_format=True,
                punctuate=True,
                endpointing=300,
            )
            
            # Start
            result = await self.connection.start(options)
            if result:
                print("✅ Deepgram started successfully")
                self.active = True
                return True
            else:
                print("❌ Failed to start")
                return False
                
        except Exception as e:
            print(f"❌ Start error: {e}")
            import traceback
            traceback.print_exc()
            return False

    async def send_audio(self, audio_data: bytes) -> bool:
        """Send audio to Deepgram"""
        try:
            if self.connection and self.active:
                await self.connection.send(audio_data)
                return True
            return False
        except Exception as e:
            print(f"❌ Send error: {e}")
            return False

    async def finish(self) -> str:
        """Close and return transcript"""
        try:
            self.active = False
            
            if self.connection:
                await self.connection.finish()
                print("✅ Connection closed")
            
            final = self.final_transcript.strip()
            print(f"📝 Final transcript ({len(final)} chars)")
            if final:
                print(f"   Preview: {final[:100]}...")
            
            return final
            
        except Exception as e:
            print(f"❌ Finish error: {e}")
            return self.final_transcript.strip()

    def is_active(self) -> bool:
        return self.active

    def reset(self):
        self.final_transcript = ""
        self.last_interim = ""
        self.active = False
        self.connection = None
        self.callback = None
        print("🔄 Reset complete")