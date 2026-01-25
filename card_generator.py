import os
import asyncio
import aiohttp
import aiofiles
import textwrap
import logging
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
from config import FONTS_DIR

# Константы дизайна
CARD_WIDTH = 1200
CARD_HEIGHT = 1600
BG_COLOR = "#FDFBF7"       
TEXT_COLOR = "#2C2C2C"     
ACCENT_COLOR = "#8B7355"   

logger = logging.getLogger(__name__)

class RecipeCardGenerator:
    # Используем Roboto для надежности с кириллицей
    FONTS_URLS = {
        "Bold.ttf": "https://github.com/google/fonts/raw/main/apache/roboto/Roboto-Bold.ttf",
        "Regular.ttf": "https://github.com/google/fonts/raw/main/apache/roboto/Roboto-Regular.ttf",
        "Italic.ttf": "https://github.com/google/fonts/raw/main/apache/roboto/Roboto-Italic.ttf",
        "Medium.ttf": "https://github.com/google/fonts/raw/main/apache/roboto/Roboto-Medium.ttf"
    }
    
    def __init__(self):
        self.fonts_loaded = False
        self.fonts = {}
        
    def _get_font_path(self, name):
        return os.path.join(FONTS_DIR, name)

    async def ensure_fonts(self):
        """Скачивает шрифты при старте бота"""
        if not os.path.exists(FONTS_DIR):
            os.makedirs(FONTS_DIR)

        logger.info("📦 Скачивание шрифтов для карточек...")
        async with aiohttp.ClientSession() as session:
            for filename, url in self.FONTS_URLS.items():
                path = self._get_font_path(filename)
                
                # Если файла нет или он пустой (< 1KB)
                if not os.path.exists(path) or os.path.getsize(path) < 1000:
                    logger.info(f"📥 Скачиваю {filename}...")
                    try:
                        async with session.get(url) as resp:
                            if resp.status == 200:
                                content = await resp.read()
                                async with aiofiles.open(path, mode='wb') as f:
                                    await f.write(content)
                            else:
                                logger.error(f"❌ Ошибка HTTP {resp.status} для {filename}")
                    except Exception as e:
                        logger.error(f"❌ Ошибка сети для {filename}: {e}")
        
        self._load_fonts()

    def _load_fonts(self):
        """Загрузка шрифтов в память"""
        try:
            self.fonts['title'] = ImageFont.truetype(self._get_font_path("Bold.ttf"), 80)
            self.fonts['section'] = ImageFont.truetype(self._get_font_path("Bold.ttf"), 45)
            self.fonts['main'] = ImageFont.truetype(self._get_font_path("Regular.ttf"), 38)
            self.fonts['italic'] = ImageFont.truetype(self._get_font_path("Italic.ttf"), 38)
            self.fonts['meta'] = ImageFont.truetype(self._get_font_path("Medium.ttf"), 32)
            self.fonts_loaded = True
            logger.info("✅ Шрифты успешно загружены")
        except Exception as e:
            logger.error(f"❌ Критическая ошибка шрифтов: {e}")
            # Fallback на дефолт (будут квадратики, но код не упадет)
            default = ImageFont.load_default()
            self.fonts = {k: default for k in ['title', 'section', 'main', 'italic', 'meta']}
            self.fonts_loaded = True

    def generate_card(self, title, ingredients, time, portions, difficulty, chef_tip, dish_image_data=None):
        if not self.fonts_loaded: 
            self._load_fonts()

        img = Image.new('RGB', (CARD_WIDTH, CARD_HEIGHT), BG_COLOR)
        draw = ImageDraw.Draw(img)
        margin = 80

        # --- 1. ЗАГОЛОВОК ---
        # Удаляем HTML теги из заголовка если есть
        clean_title = title.replace("<b>", "").replace("</b>", "").upper()
        
        # Подбор размера шрифта
        font_title = self.fonts['title']
        if len(clean_title) > 30:
            font_title = self.fonts['section'] # Поменьше

        wrapped_title = textwrap.wrap(clean_title, width=20)
        current_y = 100
        
        for line in wrapped_title:
            bbox = draw.textbbox((0, 0), line, font=font_title)
            text_w = bbox[2] - bbox[0]
            draw.text(((CARD_WIDTH - text_w)//2, current_y), line, font=font_title, fill=TEXT_COLOR)
            current_y += (bbox[3] - bbox[1]) + 20

        # Линия
        draw.line([(margin, current_y + 20), (CARD_WIDTH - margin, current_y + 20)], fill=ACCENT_COLOR, width=3)
        current_y += 80

        # --- 2. ФОТО И ИНГРЕДИЕНТЫ ---
        photo_width = 500
        photo_height = 650
        
        # Фото (Слева)
        if dish_image_data:
            try:
                dish_img = Image.open(BytesIO(dish_image_data)).convert("RGB")
                
                # Smart Crop
                aspect = dish_img.width / dish_img.height
                target_aspect = photo_width / photo_height
                
                if aspect > target_aspect:
                    new_w = int(dish_img.height * target_aspect)
                    offset = (dish_img.width - new_w) // 2
                    dish_img = dish_img.crop((offset, 0, offset + new_w, dish_img.height))
                else:
                    new_h = int(dish_img.width / target_aspect)
                    offset = (dish_img.height - new_h) // 2
                    dish_img = dish_img.crop((0, offset, dish_img.width, offset + new_h))
                
                dish_img = dish_img.resize((photo_width, photo_height), Image.Resampling.LANCZOS)
                img.paste(dish_img, (margin, current_y))
                draw.rectangle([margin, current_y, margin + photo_width, current_y + photo_height], outline=ACCENT_COLOR, width=3)
            except Exception as e:
                logger.error(f"Ошибка фото: {e}")
                self._draw_placeholder(draw, margin, current_y, photo_width, photo_height)
        else:
            self._draw_placeholder(draw, margin, current_y, photo_width, photo_height)

        # Ингредиенты (Справа)
        ing_x = margin + photo_width + 60
        draw.text((ing_x, current_y), "ИНГРЕДИЕНТЫ:", font=self.fonts['section'], fill=ACCENT_COLOR)
        
        ing_y = current_y + 70
        # Чистим ингредиенты от HTML и маркеров
        clean_ingredients = []
        for ing in ingredients[:12]:
            clean = ing.replace("<b>", "").replace("</b>", "").replace("🔸", "").replace("•", "").strip()
            if clean: clean_ingredients.append(clean)

        for ing in clean_ingredients:
            line = f"• {ing}"
            wrapped_ing = textwrap.wrap(line, width=25)
            for w_line in wrapped_ing:
                draw.text((ing_x, ing_y), w_line, font=self.fonts['main'], fill=TEXT_COLOR)
                ing_y += 45
            ing_y += 10

        current_y += max(photo_height, (ing_y - current_y)) + 60

        # --- 3. МЕТА ---
        meta_y = current_y
        meta_items = [f"ВРЕМЯ: {time}", f"ПОРЦИИ: {portions}", f"УРОВЕНЬ: {difficulty}"]
        col_width = (CARD_WIDTH - 2 * margin) // 3
        
        for i, item in enumerate(meta_items):
            x_pos = margin + (i * col_width)
            bbox = draw.textbbox((0, 0), item, font=self.fonts['meta'])
            text_w = bbox[2] - bbox[0]
            draw.text((x_pos + (col_width - text_w)//2, meta_y), item, font=self.fonts['meta'], fill=ACCENT_COLOR)

        current_y += 100

        # --- 4. СОВЕТ ---
        if chef_tip:
            # Чистим текст совета
            clean_tip = chef_tip.replace("<b>", "").replace("</b>", "").replace("💡", "").replace("СОВЕТ ШЕФ-ПОВАРА:", "").strip()
            
            tip_margin = margin
            tip_y_start = current_y
            
            tip_text = textwrap.wrap(f"«{clean_tip}»", width=50)
            box_h = len(tip_text) * 50 + 130
            
            # Проверка выхода за границы
            if tip_y_start + box_h > CARD_HEIGHT - 80:
                tip_text = tip_text[:3] + ["..."]
                box_h = len(tip_text) * 50 + 130

            draw.rectangle([tip_margin, tip_y_start, CARD_WIDTH - tip_margin, tip_y_start + box_h], outline=ACCENT_COLOR, width=2)
            
            header = "СОВЕТ ШЕФА"
            bbox = draw.textbbox((0, 0), header, font=self.fonts['section'])
            header_w = bbox[2] - bbox[0]
            draw.rectangle([((CARD_WIDTH - header_w)//2 - 20, tip_y_start - 25), ((CARD_WIDTH + header_w)//2 + 20, tip_y_start + 25)], fill=BG_COLOR)
            draw.text(((CARD_WIDTH - header_w)//2, tip_y_start - 25), header, font=self.fonts['section'], fill=ACCENT_COLOR)
            
            ty = tip_y_start + 70
            for t_line in tip_text:
                bbox = draw.textbbox((0, 0), t_line, font=self.fonts['italic'])
                draw.text(((CARD_WIDTH - (bbox[2]-bbox[0]))//2, ty), t_line, font=self.fonts['italic'], fill=TEXT_COLOR)
                ty += 50

        # --- 5. ФУТЕР ---
        footer = "Сгенерировано ботом @chto_poest_bot"
        bbox = draw.textbbox((0, 0), footer, font=self.fonts['meta'])
        draw.text(((CARD_WIDTH - (bbox[2]-bbox[0]))//2, CARD_HEIGHT - 60), footer, font=self.fonts['meta'], fill="#AAAAAA")

        buffer = BytesIO()
        img.save(buffer, format='PNG', quality=95)
        return buffer.getvalue()

    def _draw_placeholder(self, draw, x, y, w, h):
        draw.rectangle([x, y, x + w, y + h], fill="#E0E0E0", outline=ACCENT_COLOR)
        draw.text((x + w//2 - 60, y + h//2), "Нет фото", font=self.fonts['section'], fill=ACCENT_COLOR)

recipe_card_generator = RecipeCardGenerator()