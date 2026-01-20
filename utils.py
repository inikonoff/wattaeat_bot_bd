import os
import asyncio
import speech_recognition as sr
from pydub import AudioSegment
from config import TEMP_DIR, SPEECH_LANGUAGE

class VoiceProcessor:
    def __init__(self):
        self.recognizer = sr.Recognizer()
    
    async def convert_ogg_to_wav(self, ogg_path: str) -> str:
        wav_path = ogg_path.replace('.ogg', '.wav')
        # Pydub использует FFmpeg, это блокирующая операция, выносим в тред
        await asyncio.to_thread(self._convert, ogg_path, wav_path)
        return wav_path

    def _convert(self, input_path, output_path):
        audio = AudioSegment.from_ogg(input_path)
        audio.export(output_path, format='wav')
    
    async def recognize_speech(self, wav_path: str) -> str:
        # Google API - синхронный запрос. Оборачиваем в to_thread
        return await asyncio.to_thread(self._recognize_sync, wav_path)

    def _recognize_sync(self, wav_path):
        try:
            with sr.AudioFile(wav_path) as source:
                audio_data = self.recognizer.record(source)
                return self.recognizer.recognize_google(audio_data, language=SPEECH_LANGUAGE)
        except sr.UnknownValueError:
            raise Exception("Речь не распознана")
        except sr.RequestError:
            raise Exception("Ошибка сервиса Google")

    async def process_voice(self, voice_file_path: str) -> str:
        ogg_path = None
        wav_path = None
        try:
            # Копируем файл в нужную структуру (если нужно) или используем как есть
            ogg_path = voice_file_path
            wav_path = await self.convert_ogg_to_wav(ogg_path)
            text = await self.recognize_speech(wav_path)
            return text
        finally:
            # Чистим
            for path in [ogg_path, wav_path]:
                if path and os.path.exists(path):
                    try:
                        os.remove(path)
                    except:
                        pass