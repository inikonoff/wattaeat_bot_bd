import aiohttp
import asyncio
import logging
from io import BytesIO
from PIL import Image
from typing import Optional, Tuple

from config import IMAGE_MAX_SIZE, IMAGE_QUALITY

logger = logging.getLogger(__name__)

class PollinationsService:
    """Сервис для генерации изображений через Pollinations.ai"""
    
    BASE_URL = "https://image.pollinations.ai/prompt"
    
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
            "on a clean plate, white background"
        ]
        
        if clean_desc:
            prompt_parts.append(f"Description: {clean_desc}")
        
        prompt = ", ".join(prompt_parts)
        
        # Ограничиваем длину промпта
        if len(prompt) > 400:
            prompt = prompt[:400] + "..."
        
        return prompt
    
    @staticmethod
    async def _download_image(url: str) -> Optional[bytes]:
        """Скачивает изображение по URL"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=30) as response:
                    if response.status == 200:
                        return await response.read()
                    else:
                        logger.error(f"Ошибка загрузки: {response.status}")
                        return None
        except Exception as e:
            logger.error(f"Ошибка скачивания изображения: {e}")
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
    
    async def generate_image(self, dish_name: str, recipe_desc: str = "") -> Optional[bytes]:
        """
        Генерирует изображение блюда через Pollinations.ai
        
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
            
            # Кодируем промпт для URL
            import urllib.parse
            encoded_prompt = urllib.parse.quote(prompt)
            
            # Параметры для Pollinations
            params = {
                "width": "1024",
                "height": "1024",
                "model": "flux",
                "seed": str(hash(dish_name) % 1000000),  # Детерминированный seed
                "nologo": "true"
            }
            
            # Формируем URL
            query_string = "&".join([f"{k}={v}" for k, v in params.items()])
            url = f"{self.BASE_URL}/{encoded_prompt}?{query_string}"
            
            logger.debug(f"Pollinations URL: {url}")
            
            # Скачиваем изображение
            image_data = await self._download_image(url)
            
            if not image_data:
                logger.error("Не удалось скачать изображение")
                return None
            
            # Проверяем что это действительно изображение
            if len(image_data) < 100:  # Слишком маленький файл
                logger.error("Скачанный файл слишком мал")
                return None
            
            # Оптимизируем
            optimized_data = self._optimize_image(image_data)
            
            logger.info(f"✅ Изображение сгенерировано: {len(optimized_data)} bytes")
            return optimized_data
            
        except Exception as e:
            logger.error(f"Критическая ошибка генерации изображения: {e}")
            return None
    
    async def generate_image_with_retry(
        self, 
        dish_name: str, 
        recipe_desc: str = "", 
        max_retries: int = 3
    ) -> Optional[bytes]:
        """Генерация с повторными попытками"""
        for attempt in range(max_retries):
            try:
                result = await self.generate_image(dish_name, recipe_desc)
                if result:
                    return result
                
                logger.warning(f"Попытка {attempt + 1} не удалась, повтор...")
                await asyncio.sleep(1)  # Задержка между попытками
                
            except Exception as e:
                logger.error(f"Ошибка в попытке {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2)
        
        logger.error(f"Все {max_retries} попыток не удались")
        return None

# Глобальный экземпляр
pollinations_service = PollinationsService()
