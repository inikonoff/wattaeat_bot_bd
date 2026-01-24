import aiohttp
import asyncio
import logging
import json
from io import BytesIO
from PIL import Image
from typing import Optional
from config import IMAGE_MAX_SIZE, IMAGE_QUALITY, POLLINATIONS_API_KEY

logger = logging.getLogger(__name__)

class PollinationsService:
    """Сервис для генерации изображений через Pollinations.ai API"""
    
    API_BASE_URL = "https://api.pollinations.ai"
    MODELS = ["flux", "flux-schnell", "stable-diffusion", "dall-e-3"]
    
    def __init__(self):
        self.headers = {
            "Authorization": f"Bearer {POLLINATIONS_API_KEY}",
            "Content-Type": "application/json"
        }
    
    @staticmethod
    def _create_prompt(dish_name: str, recipe_desc: str = "") -> str:
        """Создаёт промпт для генерации изображения"""
        # Очищаем текст
        clean_name = dish_name.split('(')[0].strip()  # Убираем перевод в скобках
        clean_desc = recipe_desc[:100] if recipe_desc else ""
        
        # Собираем промпт
        prompt_parts = [
            f"Professional food photography of {clean_name}",
            "appetizing, delicious, restaurant quality",
            "natural lighting, sharp focus, high resolution",
            "food styling, beautiful presentation",
            "on a clean plate, white background",
            "high detail, photorealistic, 8k"
        ]
        
        if clean_desc:
            prompt_parts.append(f"Description: {clean_desc}")
        
        prompt = ", ".join(prompt_parts)
        
        # Ограничиваем длину промпта
        if len(prompt) > 400:
            prompt = prompt[:400] + "..."
        
        return prompt
    
    async def generate_image(self, dish_name: str, recipe_desc: str = "") -> Optional[bytes]:
        """
        Генерирует изображение блюда через Pollinations.ai API
        
        Args:
            dish_name: Название блюда
            recipe_desc: Описание блюда (опционально)
            
        Returns:
            bytes: Данные изображения или None при ошибке
        """
        try:
            # Создаём промпт
            prompt = self._create_prompt(dish_name, recipe_desc)
            logger.info(f"Генерирую изображение для: {dish_name}")
            
            # Параметры запроса
            payload = {
                "prompt": prompt,
                "model": "flux",  # Можно менять на другие модели
                "width": 1024,
                "height": 1024,
                "steps": 20,
                "seed": hash(dish_name) % 1000000,  # Детерминированный seed
                "negative": "text, watermark, logo, signature, ugly, blurry"
            }
            
            # Отправляем запрос к API
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.API_BASE_URL}/image",
                    headers=self.headers,
                    json=payload,
                    timeout=60  # Увеличиваем таймаут для генерации
                ) as response:
                    
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"Pollinations API error {response.status}: {error_text}")
                        return None
                    
                    # Получаем изображение
                    image_data = await response.read()
                    
                    if not image_data or len(image_data) < 100:
                        logger.error("Получены пустые данные изображения")
                        return None
            
            # Оптимизируем изображение
            optimized_data = self._optimize_image(image_data)
            
            logger.info(f"✅ Изображение сгенерировано: {len(optimized_data)} bytes")
            return optimized_data
            
        except asyncio.TimeoutError:
            logger.error("Таймаут при генерации изображения")
            return None
        except Exception as e:
            logger.error(f"Критическая ошибка генерации изображения: {e}")
            return None
    
    @staticmethod
    def _optimize_image(image_data: bytes) -> bytes:
        """Оптимизирует изображение с помощью Pillow"""
        try:
            # Открываем изображение
            img = Image.open(BytesIO(image_data))
            
            # Конвертируем в RGB если нужно
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            # Масштабируем если слишком большое
            width, height = img.size
            if width > IMAGE_MAX_SIZE or height > IMAGE_MAX_SIZE:
                ratio = min(IMAGE_MAX_SIZE / width, IMAGE_MAX_SIZE / height)
                new_width = int(width * ratio)
                new_height = int(height * ratio)
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            
            # Сохраняем в JPEG с оптимизацией
            output_buffer = BytesIO()
            img.save(
                output_buffer,
                format='JPEG',
                quality=IMAGE_QUALITY,
                optimize=True
            )
            
            return output_buffer.getvalue()
            
        except Exception as e:
            logger.error(f"Ошибка оптимизации изображения: {e}")
            return image_data  # Возвращаем оригинал если ошибка
    
    async def generate_image_with_retry(
        self, 
        dish_name: str, 
        recipe_desc: str = "", 
        max_retries: int = 2,
        model: str = "flux"
    ) -> Optional[bytes]:
        """Генерация с повторными попытками и сменой модели"""
        models_to_try = [model, "flux-schnell", "stable-diffusion"]
        
        for attempt in range(max_retries):
            for current_model in models_to_try:
                try:
                    logger.info(f"Попытка {attempt+1}, модель: {current_model}")
                    
                    prompt = self._create_prompt(dish_name, recipe_desc)
                    
                    payload = {
                        "prompt": prompt,
                        "model": current_model,
                        "width": 1024,
                        "height": 1024,
                        "steps": 15 if current_model == "flux-schnell" else 20,
                        "seed": hash(dish_name + str(attempt)) % 1000000,
                        "negative": "text, watermark, logo, signature"
                    }
                    
                    async with aiohttp.ClientSession() as session:
                        async with session.post(
                            f"{self.API_BASE_URL}/image",
                            headers=self.headers,
                            json=payload,
                            timeout=45
                        ) as response:
                            
                            if response.status == 200:
                                image_data = await response.read()
                                if image_data and len(image_data) > 100:
                                    optimized = self._optimize_image(image_data)
                                    logger.info(f"✅ Успешно сгенерировано моделью {current_model}")
                                    return optimized
                    
                    await asyncio.sleep(1)  # Задержка между попытками
                    
                except Exception as e:
                    logger.warning(f"Ошибка с моделью {current_model}: {e}")
                    continue
        
        logger.error(f"Все {max_retries} попыток не удались")
        return None
    
    async def get_account_info(self) -> Optional[dict]:
        """Получает информацию об аккаунте Pollinations"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.API_BASE_URL}/account",
                    headers=self.headers,
                    timeout=10
                ) as response:
                    
                    if response.status == 200:
                        return await response.json()
                    else:
                        logger.error(f"Ошибка получения информации об аккаунте: {response.status}")
                        return None
                        
        except Exception as e:
            logger.error(f"Ошибка получения информации об аккаунте: {e}")
            return None

# Глобальный экземпляр
pollinations_service = PollinationsService()
