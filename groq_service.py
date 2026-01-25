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

    async def analyze_categories(self, products: str) -> List[str]:
        prompt = f"""Analyze products: {products}.
        Return a JSON ARRAY of strings with suitable meal categories from this list:
        ["breakfast", "soup", "main", "salad", "dessert", "drink", "snack"].
        Example: ["main", "salad"]."""
        res = await self._send_groq_request(prompt, "Categorize", task_type="categorization")
        try:
            data = json.loads(self._extract_json(res))
            if isinstance(data, list): return [str(i).lower() for i in data]
            return ["main", "soup"]
        except: return ["main", "soup"]

    async def generate_dishes_list(self, products: str, category: str) -> List[Dict[str, str]]:
        prompt = f"""Suggest 5 dishes for category '{category}' using: {products}.
        Return JSON ARRAY of objects: [{{"name": "Dish Name", "desc": "Short description"}}].
        Use Russian language."""
        res = await self._send_groq_request(prompt, "Menu", task_type="generation")
        try:
            return json.loads(self._extract_json(res))
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
        try: return await self._make_groq_request(transcribe)
        except Exception as e: return f"❌ Ошибка: {str(e)[:100]}"

    async def create_visual_prompt(self, recipe_text: str) -> str:
        """Создает детальный английский промпт на основе текста рецепта"""
        system_prompt = (
            "You are a professional food stylist and photographer. "
            "Analyze the provided recipe and create a short, vivid visual prompt in English (up to 40 words) for image generation. "
            "Describe only the finished dish: colors, textures, garnishes, and plating. "
            "Focus on the main ingredients mentioned in the text. Do not describe the cooking process, taste, or smell. "
            "Output ONLY the prompt text."
        )
        return await self._send_groq_request(system_prompt, recipe_text, temperature=0.3)

    async def parse_recipe_for_card(self, recipe_text: str) -> Dict:
        prompt = """Parse this recipe to JSON: title, ingredients(list of strings), time, portions, difficulty, chef_tip.
        Return ONLY valid JSON object."""
        res = await self._send_groq_request(prompt, recipe_text, task_type="validation")
        try:
            data = json.loads(self._extract_json(res))
            return data[0] if isinstance(data, list) else data
        except: return {}

groq_service = GroqService()
