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

    async def _send_groq_request(self, system, user, task_type="generation", temperature=0.5):
        async def req(client):
            resp = await client.chat.completions.create(
                model=GROQ_MODEL, messages=[{"role":"system","content":system},{"role":"user","content":user}],
                temperature=temperature
            )
            return resp.choices[0].message.content
        return await self._make_groq_request(req)

    @staticmethod
    def _extract_json(text: str) -> str:
        text = text.replace("```json", "").replace("```", "")
        start = text.find('[') if text.find('[') != -1 else text.find('{')
        end = text.rfind(']') if text.rfind(']') != -1 else text.rfind('}')
        if start != -1 and end != -1: return text[start:end+1]
        return text

    # --- ИСПРАВЛЕННЫЙ МЕТОД ---
    async def analyze_categories(self, products: str) -> List[str]:
        """Определяет категории блюд (всегда возвращает список строк)"""
        # Промпт требует строго массив строк
        prompt = f"""Analyze products: {products}.
        Return a JSON ARRAY of strings with suitable meal categories from this list:
        ["breakfast", "soup", "main", "salad", "dessert", "drink", "snack"].
        Example: ["main", "salad"].
        Do NOT return objects, ONLY strings."""
        
        res = await self._send_groq_request(prompt, "Categorize", task_type="categorization")
        
        try:
            data = json.loads(self._extract_json(res))
            
            clean_categories = []
            if isinstance(data, list):
                for item in data:
                    # Если вернулась строка - берем её
                    if isinstance(item, str):
                        clean_categories.append(item.lower())
                    # Если вернулся словарь {"category": "soup"} - вытаскиваем значение
                    elif isinstance(item, dict):
                        # Берем первое значение из словаря
                        values = list(item.values())
                        if values and isinstance(values[0], str):
                            clean_categories.append(values[0].lower())
            
            # Если пусто или бред, возвращаем дефолт
            if not clean_categories:
                return ["main", "soup"]
                
            return clean_categories
            
        except Exception as e:
            logger.error(f"Category parsing error: {e}")
            return ["main", "soup"]

    async def generate_dishes_list(self, products: str, category: str) -> List[Dict[str, str]]:
        prompt = f"""Suggest 5 dishes for category '{category}' using: {products}.
        Return JSON ARRAY of objects: [{{"name": "Dish Name", "desc": "Short description"}}].
        Use Russian language for names and descriptions."""
        
        res = await self._send_groq_request(prompt, "Menu", task_type="generation")
        try:
            data = json.loads(self._extract_json(res))
            if isinstance(data, list): return data
            return []
        except: return []

    async def generate_recipe(self, dish_name: str, products: str) -> str:
        prompt = f"Write detailed recipe for '{dish_name}' using: {products}. Use Russian language. Use HTML tags for bold/italic."
        return await self._send_groq_request(prompt, "Recipe", task_type="recipe")

    async def generate_freestyle_recipe(self, dish_name: str) -> str:
        prompt = f"Write creative recipe for '{dish_name}'. Use Russian language. Use HTML tags."
        return await self._send_groq_request(prompt, "Recipe", task_type="freestyle")

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

    async def translate_to_english(self, text: str) -> str:
        prompt = f"Translate '{text}' to English for image prompt. Output ONLY translation."
        return await self._send_groq_request("Translator", prompt, temperature=0.3)

    async def parse_recipe_for_card(self, recipe_text: str) -> Dict:
        prompt = "Parse this recipe to JSON: title, ingredients(list of strings), time, portions, difficulty, chef_tip."
        res = await self._send_groq_request(prompt, recipe_text, task_type="validation")
        try:
            return json.loads(self._extract_json(res))
        except:
            return {}

groq_service = GroqService()
