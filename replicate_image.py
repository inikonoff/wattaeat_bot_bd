import os
import asyncio
import logging
from typing import Optional, Dict, Any, List
import replicate
from datetime import datetime
from config import REPLICATE_API_KEY, IMAGE_QUALITY

logger = logging.getLogger(__name__)

class ReplicateImageService:
    """Генерация изображений через Replicate с fallback по моделям"""
    
    # Приоритет моделей (от лучшей к запасным)
    MODEL_PRIORITY = [
        "flux-1.1-pro",
        "flux-kontext-pro",
        "sdxl",
        "realvisxl"
    ]
    
    # Доступные модели
    MODELS = {
        "flux-1.1-pro": "black-forest-labs/flux-1.1-pro",
        "flux-kontext-pro": "black-forest-labs/flux-kontext-pro",
        "sdxl": "stability-ai/sdxl",
        "realvisxl": "sgriebel/realvisxl-v4.0"
    }
    
    # Параметры по умолчанию для каждой модели
    MODEL_PARAMS = {
        "flux-1.1-pro": {
            "guidance_scale": 7.5,
            "num_inference_steps": 30,
            "aspect_ratio": "1:1",
            "negative_prompt": "text, watermark, logo, people, hands, blurry, cartoon, 3d render, drawing, bad quality, ugly"
        },
        "flux-kontext-pro": {
            "guidance_scale": 7.0,
            "num_inference_steps": 28,
            "aspect_ratio": "1:1",
            "negative_prompt": "text, watermark, logo, people, hands, blurry, cartoon, 3d render, drawing"
        },
        "sdxl": {
            "guidance_scale": 7.5,
            "num_inference_steps": 25,
            "negative_prompt": "text, watermark, logo, people, hands, blurry"
        },
        "realvisxl": {
            "guidance_scale": 7.0,
            "num_inference_steps": 30,
            "negative_prompt": "text, watermark, logo, people, hands, blurry"
        }
    }
    
    def __init__(self, model: str = "flux-1.1-pro"):
        """
        Инициализация Replicate сервиса
        
        Args:
            model: Идентификатор модели
        """
        self.api_key = REPLICATE_API_KEY
        self.model_name = model
        self.model_id = self.MODELS.get(model, self.MODELS["flux-1.1-pro"])
        self.model_params = self.MODEL_PARAMS.get(model, self.MODEL_PARAMS["flux-1.1-pro"])
        
        if not self.api_key:
            logger.error("REPLICATE_API_KEY не установлен в .env файле")
            raise ValueError("REPLICATE_API_KEY не найден")
        
        # Инициализируем клиент
        self.client = replicate.Client(api_token=self.api_key)
        logger.info(f"✅ Replicate инициализирован с моделью {model}")
    
    async def generate(
        self, 
        dish_name: str, 
        recipe_text: str = None,
        visual_desc: str = None
    ) -> Optional[bytes]:
        """
        Генерирует изображение блюда через Replicate
        
        Args:
            dish_name: Название блюда
            recipe_text: Полный текст рецепта
            visual_desc: Визуальное описание от LLM
            
        Returns:
            bytes: Изображение в формате JPEG/PNG или None при ошибке
        """
        start_time = datetime.now()
        
        try:
            # 1. Создаем промпт
            prompt = self._create_prompt(dish_name, recipe_text, visual_desc)
            logger.debug(f"Replicate промпт для {dish_name[:50]}...")
            
            # 2. Подготавливаем параметры
            params = self._prepare_parameters(prompt)
            
            # 3. Генерируем изображение
            logger.info(f"🎨 Запуск генерации через {self.model_name}: {dish_name}")
            image_url = await self._run_generation(params)
            
            if not image_url:
                logger.error(f"Replicate ({self.model_name}) не вернул URL изображения для {dish_name}")
                return None
            
            # 4. Скачиваем изображение
            image_data = await self._download_image(image_url)
            
            if not image_data:
                logger.error(f"Не удалось скачать изображение для {dish_name}")
                return None
            
            # 5. Оптимизируем изображение
            optimized_image = await self._optimize_image(image_data)
            
            # 6. Логируем успех
            duration = (datetime.now() - start_time).total_seconds()
            logger.info(f"✅ {self.model_name} сгенерировал {dish_name} за {duration:.1f}с, размер: {len(optimized_image) / 1024:.1f}KB")
            
            return optimized_image
            
        except replicate.exceptions.ModelError as e:
            logger.error(f"❌ Ошибка модели {self.model_name} для {dish_name}: {e}")
            return None
        except replicate.exceptions.ReplicateError as e:
            logger.error(f"❌ Ошибка Replicate API ({self.model_name}) для {dish_name}: {e}")
            return None
        except Exception as e:
            logger.error(f"❌ Критическая ошибка {self.model_name} для {dish_name}: {e}", exc_info=True)
            return None
    
    def _create_prompt(self, dish_name: str, recipe_text: str = None, visual_desc: str = None) -> str:
        """Создает промпт для Replicate модели"""
        # Извлекаем ключевые элементы
        elements = self._extract_key_elements(recipe_text, visual_desc)
        
        # Определяем стиль
        style = self._determine_replicate_style(dish_name, elements)
        
        # Собираем промпт частями
        prompt_parts = [
            # Основное описание
            f"Professional food photography of {dish_name}",
            
            # Детали
            elements if elements else "",
            
            # Качество и стиль
            style,
            "highly detailed, sharp focus",
            "appetizing, delicious looking",
            
            # Освещение и композиция
            "natural window lighting, soft shadows",
            "shallow depth of field, blurred background",
            "clean plate, food styling",
            
            # Технические требования
            "square aspect ratio 1:1",
            "1024x1024 resolution"
        ]
        
        # Фильтруем пустые части
        prompt = ", ".join(filter(None, prompt_parts))
        
        # Ограничиваем длину
        max_length = 500
        if len(prompt) > max_length:
            important_parts = [
                f"Professional food photography of {dish_name}",
                elements[:100] if elements else "",
                style,
                "appetizing, delicious looking"
            ]
            prompt = ", ".join(filter(None, important_parts))[:max_length]
        
        return prompt.strip()
    
    def _extract_key_elements(self, recipe_text: str = None, visual_desc: str = None) -> str:
        """Извлекает ключевые элементы для Replicate промпта"""
        elements = []
        
        # Из визуального описания
        if visual_desc:
            simple_desc = visual_desc.lower()
            for word in ["professional", "photography", "photo", "image", "picture"]:
                simple_desc = simple_desc.replace(word, "")
            elements.append(simple_desc.strip())
        
        # Из рецепта (первые упоминания ингредиентов)
        if recipe_text:
            lines = recipe_text.split('\n')
            for line in lines[:10]:
                line_lower = line.lower()
                if any(marker in line_lower for marker in ['-', '•', '*', '–', '🔸']) and len(line.strip()) > 5:
                    clean_line = line.strip().lstrip('-•*–🔸 ').strip()
                    words = clean_line.split()
                    if words and len(words) <= 5:
                        elements.append(clean_line)
                        if len(elements) >= 3:
                            break
        
        # Дедупликация
        if elements:
            unique_elements = []
            seen = set()
            for elem in elements:
                if elem not in seen and len(elem) > 2:
                    seen.add(elem)
                    unique_elements.append(elem)
            
            return ", ".join(unique_elements[:3])
        
        return "fresh ingredients, beautiful presentation"
    
    def _determine_replicate_style(self, dish_name: str, elements: str) -> str:
        """Определяет стиль для Replicate промпта"""
        dish_lower = dish_name.lower()
        elements_lower = elements.lower()
        
        if any(word in dish_lower or word in elements_lower 
               for word in ["cake", "pie", "cookie", "dessert", "sweet", "chocolate", "торт", "десерт"]):
            return "food photography, dessert styling, studio lighting"
        
        elif any(word in dish_lower or word in elements_lower 
                 for word in ["salad", "vegetable", "fresh", "зелень", "овощ", "салат"]):
            return "fresh, vibrant, natural light, healthy food"
        
        elif any(word in dish_lower or word in elements_lower 
                 for word in ["meat", "steak", "chicken", "beef", "pork", "мясо", "куриц", "говядин"]):
            return "restaurant quality, gourmet, dramatic lighting"
        
        elif any(word in dish_lower or word in elements_lower 
                 for word in ["soup", "stew", "broth", "суп", "бульон", "похлебка"]):
            return "comfort food, rustic, warm lighting"
        
        elif any(word in dish_lower or word in elements_lower 
                 for word in ["pasta", "pizza", "italian", "итальянск", "паста", "пицца"]):
            return "Italian cuisine, rustic, wood-fired"
        
        elif any(word in dish_lower or word in elements_lower 
                 for word in ["sushi", "asian", "japanese", "chinese", "суши", "азиатск"]):
            return "Japanese minimalism, clean presentation"
        
        else:
            return "restaurant quality, professional food styling"
    
    def _prepare_parameters(self, prompt: str) -> Dict[str, Any]:
        """Подготавливает параметры для Replicate API"""
        params = {
            "prompt": prompt,
            "num_outputs": 1,
            **self.model_params
        }
        
        # Для flux моделей добавляем дополнительные параметры
        if "flux" in self.model_id:
            params.update({
                "output_format": "jpg",
                "output_quality": 90,
                "seed": None,
            })
        
        return params
    
    async def _run_generation(self, params: Dict[str, Any]) -> Optional[str]:
        """Запускает генерацию через Replicate API"""
        try:
            output = await asyncio.to_thread(
                self.client.run,
                self.model_id,
                input=params
            )
            
            if isinstance(output, list) and len(output) > 0:
                return output[0]
            elif isinstance(output, str):
                return output
            
            return None
            
        except Exception as e:
            logger.error(f"❌ Ошибка запуска генерации Replicate ({self.model_name}): {e}")
            return None
    
    async def _download_image(self, image_url: str) -> Optional[bytes]:
        """Скачивает изображение по URL"""
        import aiohttp
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(image_url, timeout=30) as response:
                    if response.status == 200:
                        return await response.read()
                    else:
                        logger.error(f"❌ Ошибка скачивания изображения: {response.status}")
                        return None
                        
        except asyncio.TimeoutError:
            logger.error("❌ Timeout при скачивании изображения")
            return None
        except Exception as e:
            logger.error(f"❌ Ошибка скачивания изображения: {e}")
            return None
    
    async def _optimize_image(self, image_data: bytes) -> bytes:
        """Оптимизирует изображение для Telegram"""
        try:
            from PIL import Image
            import io
            
            img = Image.open(io.BytesIO(image_data))
            
            if img.mode in ('RGBA', 'LA', 'P'):
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                background.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
                img = background
            
            max_dimension = 2048
            if max(img.size) > max_dimension:
                ratio = max_dimension / max(img.size)
                new_size = tuple(int(dim * ratio) for dim in img.size)
                img = img.resize(new_size, Image.Resampling.LANCZOS)
            
            output = io.BytesIO()
            
            if "flux" in self.model_id:
                img.save(output, format='JPEG', quality=IMAGE_QUALITY, optimize=True)
            else:
                if img.mode == 'RGB':
                    img.save(output, format='JPEG', quality=IMAGE_QUALITY, optimize=True)
                else:
                    img.save(output, format='PNG', optimize=True)
            
            return output.getvalue()
            
        except ImportError:
            logger.warning("⚠️ PIL не установлен, пропускаем оптимизацию")
            return image_data
        except Exception as e:
            logger.error(f"❌ Ошибка оптимизации изображения: {e}")
            return image_data


# ==================== ФУНКЦИЯ С FALLBACK ====================

async def generate_with_fallback(dish_name: str, recipe_text: str) -> Optional[bytes]:
    """
    Генерирует изображение с автоматическим fallback по моделям
    
    Args:
        dish_name: Название блюда
        recipe_text: Текст рецепта
        
    Returns:
        bytes: Изображение или None если все модели упали
    """
    for model_name in ReplicateImageService.MODEL_PRIORITY:
        try:
            logger.info(f"🎨 Попытка генерации с моделью: {model_name}")
            service = ReplicateImageService(model=model_name)
            image = await service.generate(dish_name, recipe_text)
            
            if image:
                logger.info(f"✅ Успешная генерация с моделью: {model_name}")
                return image
            else:
                logger.warning(f"⚠️ Модель {model_name} вернула None")
                
        except ValueError as e:
            # API ключ не найден - прерываем сразу
            logger.error(f"❌ Критическая ошибка: {e}")
            return None
        except Exception as e:
            logger.warning(f"⚠️ Модель {model_name} недоступна: {e}")
            continue
    
    # Все модели упали
    logger.error("❌ Все модели Replicate недоступны!")
    return None


# Синглтон с основной моделью
replicate_service = ReplicateImageService(model="flux-1.1-pro")