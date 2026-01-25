import os
import asyncio
import aiohttp
import aiofiles
import textwrap
import logging
from io import BytesIO
from typing import List, Optional
from PIL import Image, ImageDraw, ImageFont

from config import (
    CARD_WIDTH, CARD_HEIGHT, CARD_BG_COLOR, CARD_ACCENT_COLOR,
    CARD_TEXT_COLOR, CARD_SECONDARY_COLOR,
    FONT_BOLD, FONT_MEDIUM, FONT_REGULAR,
    FONTS_DIR
)

logger = logging.getLogger(__name__)

class RecipeCardGenerator:
    """Генератор карточек с отложенной загрузкой шрифтов"""
    
    FONTS_URLS = {
        "Roboto-Bold.ttf": "https://github.com/google/fonts/raw/main/apache/roboto/Roboto-Bold.ttf",
        "Roboto-Medium.ttf": "https://github.com/google/fonts/raw/main/apache/roboto/Roboto-Medium.ttf",
        "Roboto-Regular.ttf": "https://github.com/google/fonts/raw/main/apache/roboto/Roboto-Regular.ttf"
    }
    
    def __init__(self):
        self.fonts_loaded = False
        # Инициализируем None, а не объектами шрифтов
        self.font_bold_large = None
        self.font_bold_medium = None
        self.font_medium = None
        self.font_regular = None
        self.font_small = None
        
    async def ensure_fonts(self):
        """Скачивает шрифты при старте"""
        logger.info("📦 Проверка наличия шрифтов...")
        if not os.path.exists(FONTS_DIR):
            os.makedirs(FONTS_DIR)

        async with aiohttp.ClientSession() as session:
            for filename, url in self.FONTS_URLS.items():
                file_path = os.path.join(FONTS_DIR, filename)
                if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
                    logger.info(f"📥 Скачиваю шрифт {filename}...")
                    try:
                        async with session.get(url) as resp:
                            if resp.status == 200:
                                f = await aiofiles.open(file_path, mode='wb')
                                await f.write(await resp.read())
                                await f.close()
                                logger.info(f"✅ Шрифт {filename} загружен")
                            else:
                                logger.error(f"❌ HTTP ошибка {resp.status} для {filename}")
                    except Exception as e:
                        logger.error(f"❌ Ошибка сети для {filename}: {e}")
        
        # После скачивания пробуем загрузить
        self._load_fonts()

    def _load_fonts(self):
        """Загрузка шрифтов в память Pillow"""
        if self.fonts_loaded: return

        try:
            # Используем абсолютные пути
            abs_font_bold = os.path.abspath(FONT_BOLD)
            abs_font_medium = os.path.abspath(FONT_MEDIUM)
            abs_font_regular = os.path.abspath(FONT_REGULAR)

            self.font_bold_large = ImageFont.truetype(abs_font_bold, 70)
            self.font_bold_medium = ImageFont.truetype(abs_font_bold, 50)
            self.font_medium = ImageFont.truetype(abs_font_medium, 40)
            self.font_regular = ImageFont.truetype(abs_font_regular, 36)
            self.font_small = ImageFont.truetype(abs_font_regular, 30)
            
            self.fonts_loaded = True
            logger.info("✅ Шрифты успешно подключены к Pillow")
        except Exception as e:
            logger.warning(f"⚠️ Ошибка загрузки TTF шрифтов: {e}. Использую дефолтные.")
            # Fallback на дефолтный шрифт
            default = ImageFont.load_default()
            self.font_bold_large = default
            self.font_bold_medium = default
            self.font_medium = default
            self.font_regular = default
            self.font_small = default
            self.fonts_loaded = True # Считаем загруженными, хоть и дефолтными

    def _draw_centered_text(self, draw, text, font, y, color):
        bbox = draw.textbbox((0, 0), text, font=font)
        width = bbox[2] - bbox[0]
        x = (CARD_WIDTH - width) // 2
        draw.text((x, y), text, font=font, fill=color)
        return y + (bbox[3] - bbox[1]) + 20

    def generate_card(self, title, ingredients, time, portions, difficulty, chef_tip, dish_image_data=None):
        if not self.fonts_loaded:
            self._load_fonts()

        image = Image.new('RGB', (CARD_WIDTH, CARD_HEIGHT), CARD_BG_COLOR)
        draw = ImageDraw.Draw(image)
        
        current_y = 0
        
        # 1. HEADER
        draw.rectangle([(0, 0), (CARD_WIDTH, 120)], fill=CARD_ACCENT_COLOR)
        self._draw_centered_text(draw, "🍽️ ЧЁПОЕСТЬ", self.font_bold_medium, 35, "#FFFFFF")
        current_y = 120

        # 2. IMAGE
        img_height = 800
        if dish_image_data:
            try:
                dish_img = Image.open(BytesIO(dish_image_data)).convert("RGBA")
                ratio = max(CARD_WIDTH / dish_img.width, img_height / dish_img.height)
                new_size = (int(dish_img.width * ratio), int(dish_img.height * ratio))
                dish_img = dish_img.resize(new_size, Image.Resampling.LANCZOS)
                
                left = (dish_img.width - CARD_WIDTH) // 2
                top = (dish_img.height - img_height) // 2
                dish_img = dish_img.crop((left, top, left + CARD_WIDTH, top + img_height))
                
                image.paste(dish_img, (0, current_y))
            except Exception as e:
                logger.error(f"Image error: {e}")
                draw.rectangle([(0, current_y), (CARD_WIDTH, current_y + img_height)], fill="#EEEEEE")
                self._draw_centered_text(draw, "Нет изображения", self.font_medium, current_y + 350, CARD_SECONDARY_COLOR)
        else:
            draw.rectangle([(0, current_y), (CARD_WIDTH, current_y + img_height)], fill="#EEEEEE")
            self._draw_centered_text(draw, "Нет изображения", self.font_medium, current_y + 350, CARD_SECONDARY_COLOR)
        
        current_y += img_height + 40

        # 3. TITLE
        lines = textwrap.wrap(title, width=25)
        for line in lines:
            current_y = self._draw_centered_text(draw, line, self.font_bold_large, current_y, CARD_TEXT_COLOR)
        
        current_y += 20
        draw.line([(300, current_y), (CARD_WIDTH - 300, current_y)], fill=CARD_ACCENT_COLOR, width=5)
        current_y += 50

        # 4. META
        meta_text = f"⏱ {time} мин   |   👥 {portions} порц.   |   📊 {difficulty}"
        current_y = self._draw_centered_text(draw, meta_text, self.font_medium, current_y, CARD_SECONDARY_COLOR)
        current_y += 50

        # 5. INGREDIENTS
        draw.text((80, current_y), "📦 Ингредиенты:", font=self.font_bold_medium, fill=CARD_ACCENT_COLOR)
        current_y += 70
        
        col_1_x = 100
        col_2_x = CARD_WIDTH // 2 + 50
        
        items = ingredients[:10]
        half = (len(items) + 1) // 2
        col1 = items[:half]
        col2 = items[half:]
        
        start_ingredients_y = current_y
        
        for ing in col1:
            draw.text((col_1_x, current_y), f"• {ing}", font=self.font_regular, fill=CARD_TEXT_COLOR)
            current_y += 50
            
        current_y = start_ingredients_y
        for ing in col2:
            draw.text((col_2_x, current_y), f"• {ing}", font=self.font_regular, fill=CARD_TEXT_COLOR)
            current_y += 50
            
        current_y = max(current_y, start_ingredients_y + (len(col1) * 50)) + 40

        # 6. TIP
        if chef_tip:
            tip_lines = textwrap.wrap(chef_tip, width=50)
            box_height = len(tip_lines) * 45 + 100
            
            draw.rounded_rectangle([(50, current_y), (CARD_WIDTH - 50, current_y + box_height)], radius=30, fill="#FFF3CD")
            draw.text((100, current_y + 30), "💡 Совет шефа:", font=self.font_bold_medium, fill="#856404")
            
            text_y = current_y + 90
            for line in tip_lines:
                draw.text((100, text_y), line, font=self.font_regular, fill="#856404")
                text_y += 45

        # FOOTER
        footer_y = CARD_HEIGHT - 80
        self._draw_centered_text(draw, "Сгенерировано ботом @chto_poest_bot", self.font_small, footer_y, CARD_SECONDARY_COLOR)

        buffer = BytesIO()
        image.save(buffer, format='PNG')
        return buffer.getvalue()

recipe_card_generator = RecipeCardGenerator()
