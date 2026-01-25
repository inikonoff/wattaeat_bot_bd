
import aiohttp
import asyncio
import logging
from io import BytesIO
from PIL import Image
from config import IMAGE_MAX_SIZE, IMAGE_QUALITY, HUGGINGFACE_API_KEY

logger = logging.getLogger(__name__)

class ImageGeneratorService:
    """Сервис генерации изображений через Hugging Face Inference API"""
    
    # Модели в порядке приоритета
    # 1. FLUX.1-schnell (Быстрая, крутая)
    # 2. SDXL (Надежная классика)
    MODEL_FLUX = "black-forest-labs/FLUX.1-schnell"
    MODEL_SDXL = "stabilityai/stable-diffusion-xl-base-1.0"
    
    API_URL = "https://router.huggingface.co/hf-inference/models/"
    
    def __init__(self):
        self.headers = {
            "Authorization": f"Bearer {HUGGINGFACE_API_KEY}"
        }
    
    def _optimize_image(self, image_data: bytes) -> bytes:
        """Сжатие и ресайз изображения"""
        try:
            img = Image.open(BytesIO(image_data))
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            width, height = img.size
            if width > IMAGE_MAX_SIZE or height > IMAGE_MAX_SIZE:
                ratio = min(IMAGE_MAX_SIZE / width, IMAGE_MAX_SIZE / height)
                new_size = (int(width * ratio), int(height * ratio))
                img = img.resize(new_size, Image.Resampling.LANCZOS)
            
            buffer = BytesIO()
            img.save(buffer, format='JPEG', quality=IMAGE_QUALITY, optimize=True)
            return buffer.getvalue()
        except Exception as e:
            logger.error(f"Optimization error: {e}")
            return image_data

    async def _query(self, session, model, payload):
        """Отправка запроса к HF"""
        url = f"{self.API_URL}{model}"
        try:
            async with session.post(url, headers=self.headers, json=payload, timeout=60) as response:
                content_type = response.headers.get('Content-Type', '')
                
                # Успех
                if response.status == 200 and 'image' in content_type:
                    return await response.read()
                
                # Ошибка или ожидание
                try:
                    data = await response.json()
                except:
                    data = {}

                # Если модель грузится (стандартно для Free Tier)
                if 'error' in data and isinstance(data['error'], str) and 'loading' in data['error'].lower():
                    estimated_time = data.get('estimated_time', 20)
                    logger.info(f"⏳ Модель {model} загружается. Ждем {estimated_time}с...")
                    return {"wait": estimated_time}
                    
                logger.warning(f"Ошибка API HF {model}: {response.status} - {data}")
                return None
        except Exception as e:
            logger.error(f"Сетевая ошибка HF: {e}")
            return None

    async def generate_image(self, prompt_text: str) -> bytes:
        """Генерация с перебором моделей и повторными попытками"""
        
        # Улучшаем промпт для еды
        enhanced_prompt = f"Professional food photography of {prompt_text}, delicious, high quality, 4k, restaurant style, photorealistic"
        
        models_queue = [self.MODEL_FLUX, self.MODEL_SDXL]
        
        async with aiohttp.ClientSession() as session:
            for model in models_queue:
                logger.info(f"🎨 Пробуем модель: {model}")
                
                payload = {
                    "inputs": enhanced_prompt,
                    "parameters": {
                        # Flux любит меньше шагов, SDXL больше
                        "num_inference_steps": 4 if "FLUX" in model else 25,
                    }
                }
                
                # 3 попытки на модель
                for attempt in range(3):
                    result = await self._query(session, model, payload)
                    
                    if isinstance(result, bytes):
                        logger.info(f"✅ Успешно сгенерировано моделью {model}")
                        return self._optimize_image(result)
                    
                    elif isinstance(result, dict) and "wait" in result:
                        # Умное ожидание
                        wait_time = min(result["wait"], 30)
                        await asyncio.sleep(wait_time)
                        continue
                    
                    else:
                        # Быстрая пауза перед ретраем
                        await asyncio.sleep(1)
            
        logger.error("❌ Не удалось сгенерировать изображение ни одной моделью")
        return None

image_service = ImageGeneratorService()
