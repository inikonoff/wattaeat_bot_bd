import json
import re
import logging
import asyncio
import random
from typing import Dict, List, Optional
from openai import AsyncOpenAI

from config import GROQ_API_KEYS, GROQ_MODEL

logger = logging.getLogger(__name__)

class GroqService:
    def __init__(self):
        self.clients = []
        self.current_client_index = 0
        self._init_clients()
    
    def _init_clients(self):
        if not GROQ_API_KEYS:
            logger.warning("GROQ_API_KEYS не настроены!")
            return
        
        for key in GROQ_API_KEYS:
            try:
                client = AsyncOpenAI(
                    api_key=key,
                    base_url="https://api.groq.com/openai/v1",
                    timeout=30.0,
                )
                self.clients.append(client)
            except Exception as e:
                logger.error(f"Error client: {e}")
    
    def _get_client(self):
        if not self.clients: return None
        client = self.clients[self.current_client_index]
        self.current_client_index = (self.current_client_index + 1) % len(self.clients)
        return client
    
    async def _make_groq_request(self, func, *args, **kwargs):
        if not self.clients: raise Exception("No Groq clients")
        errors = []
        for _ in range(len(self.clients) * 2):
            client = self._get_client()
            try:
                return await func(client, *args, **kwargs)
            except Exception as e:
                errors.append(str(e))
                await asyncio.sleep(0.5)
        raise Exception(f"All clients failed: {errors}")

    # --- ПЕРЕВОД ДЛЯ ГЕНЕРАЦИИ КАРТИНОК ---
    async def translate_to_english(self, text: str) -> str:
        """Переводит название блюда на английский для Hugging Face"""
        async def request(client):
            response = await client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {"role": "system", "content": "You are a professional translator. Translate the dish name to English for an image generator prompt. Output ONLY the translation. No explanations."},
                    {"role": "user", "content": text}
                ],
                max_tokens=50,
                temperature=0.3
            )
            return response.choices[0].message.content.strip()
        
        try:
            translation = await self._make_groq_request(request)
            # Очистка от кавычек если есть
            translation = translation.replace('"', '').replace("'", "")
            logger.info(f"🔤 Перевод: '{text}' -> '{translation}'")
            return translation
        except Exception as e:
            logger.error(f"Ошибка перевода: {e}")
            return text # Возвращаем оригинал если перевод сломался

    # ... (Остальные методы Whisper, validate, categories, generate_dishes, generate_recipe без изменений) ...
    # Вставь сюда остальные методы из старого groq_service.py:
    # transcribe_voice, _detect_input_language, _sanitize_input, _send_groq_request, _extract_json,
    # validate_ingredients, analyze_categories, generate_dishes_list, generate_recipe, 
    # generate_freestyle_recipe, parse_recipe_for_card, _is_refusal
    
    # Чтобы не раздувать ответ, я приведу только transcribe_voice для примера, остальное нужно сохранить:
    
    async def transcribe_voice(self, audio_bytes: bytes) -> str:
        async def transcribe(client):
            response = await client.audio.transcriptions.create(
                model="whisper-large-v3-turbo",
                file=("audio.ogg", audio_bytes, "audio/ogg"),
                language="ru",
                response_format="text",
            )
            return response
        try:
            return await self._make_groq_request(transcribe)
        except Exception as e:
            return f"❌ Ошибка: {str(e)[:100]}"
            
    async def validate_ingredients(self, text: str) -> bool:
        # ... код из старого файла ...
        return True # Заглушка, вставь код
        
    async def analyze_categories(self, products: str) -> List[str]:
        # ... код из старого файла ...
        prompt = f"Categorize these products into valid meal types for cooking: {products}. Return JSON array."
        res = await self._send_groq_request(prompt, "Categorize", task_type="categorization")
        try:
            return json.loads(self._extract_json(res))
        except:
            return ["main"]

    async def generate_dishes_list(self, products: str, category: str) -> List[Dict[str, str]]:
        # ... код из старого файла ...
        # Вставь реальную реализацию
        prompt = f"Suggest 5 dishes for category {category} using: {products}. Return JSON."
        res = await self._send_groq_request(prompt, "Menu", task_type="generation")
        try:
            return json.loads(self._extract_json(res))
        except:
            return []

    async def generate_recipe(self, dish_name: str, products: str) -> str:
        # ... код из старого файла ...
        # Вставь реальную реализацию
        prompt = f"Write recipe for {dish_name}. Use Russian."
        return await self._send_groq_request(prompt, "Recipe", task_type="recipe")

    async def generate_freestyle_recipe(self, dish_name: str) -> str:
        # ... код из старого файла ...
        prompt = f"Write creative recipe for {dish_name}. Use Russian."
        return await self._send_groq_request(prompt, "Recipe", task_type="freestyle")

    async def parse_recipe_for_card(self, recipe_text: str) -> Dict:
        # ... код из старого файла ...
        prompt = "Parse this recipe to JSON: title, ingredients(list), time, portions, difficulty, chef_tip."
        res = await self._send_groq_request(prompt, recipe_text, task_type="validation")
        try:
            return json.loads(self._extract_json(res))
        except:
            return {}
            
    # Вспомогательные методы
    @staticmethod
    def _extract_json(text: str) -> str:
        text = text.replace("```json", "").replace("```", "")
        start = text.find('[') if text.find('[') != -1 else text.find('{')
        end = text.rfind(']') if text.rfind(']') != -1 else text.rfind('}')
        if start != -1 and end != -1: return text[start:end+1]
        return text

    async def _send_groq_request(self, system, user, task_type="generation", temperature=0.5):
        async def req(client):
            resp = await client.chat.completions.create(
                model=GROQ_MODEL, messages=[{"role":"system","content":system},{"role":"user","content":user}],
                temperature=temperature
            )
            return resp.choices[0].message.content
        return await self._make_groq_request(req)

groq_service = GroqService()
