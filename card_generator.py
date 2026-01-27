import os
import textwrap
import logging
from io import BytesIO
import aiohttp
import aiofiles
from PIL import Image, ImageDraw, ImageFont

# --- КОНФИГУРАЦИЯ ---
FONTS_DIR = "fonts"
ASSETS_DIR = "assets"

# Цвета
BG_COLOR = "#F2E8D5"
TEXT_COLOR = "#3E2723"
ACCENT_COLOR = "#5D4037"
HIGHLIGHT_COLOR = "#2E7D32"

# Размеры
CARD_WIDTH = 1200
CARD_HEIGHT = 1600

logger = logging.getLogger(__name__)

class RecipeCardGenerator:
    FONTS_URLS = {
        "Title.ttf": "https://github.com/google/fonts/raw/main/ofl/playfairdisplay/PlayfairDisplay-Bold.ttf",
        "Body.ttf": "https://github.com/google/fonts/raw/main/ofl/lora/Lora-Regular.ttf",
        "BodyBold.ttf": "https://github.com/google/fonts/raw/main/ofl/lora/Lora-Bold.ttf",
        "Italic.ttf": "https://github.com/google/fonts/raw/main/ofl/lora/Lora-Italic.ttf"
    }

    def __init__(self):
        self.fonts_loaded = False
        self.fonts = {}
        self._ensure_dirs()

    def _ensure_dirs(self):
        if not os.path.exists(FONTS_DIR): 
            os.makedirs(FONTS_DIR)
        if not os.path.exists(ASSETS_DIR): 
            os.makedirs(ASSETS_DIR)

    def _get_font_path(self, name):
        return os.path.join(FONTS_DIR, name)

    async def ensure_fonts(self):
        """Скачивает винтажные шрифты"""
        async with aiohttp.ClientSession() as session:
            for filename, url in self.FONTS_URLS.items():
                path = self._get_font_path(filename)
                if not os.path.exists(path) or os.path.getsize(path) < 1000:
                    try:
                        logger.info(f"🔄 Скачиваю {filename}...")
                        async with session.get(url) as resp:
                            if resp.status == 200:
                                content = await resp.read()
                                async with aiofiles.open(path, mode='wb') as f:
                                    await f.write(content)
                                logger.info(f"✅ {filename} скачан")
                    except Exception as e:
                        logger.error(f"❌ Ошибка скачивания {filename}: {e}")
        self._load_fonts()

    def _load_fonts(self):
        """Загрузка шрифтов"""
        try:
            title_path = self._get_font_path("Title.ttf")
            body_path = self._get_font_path("Body.ttf")
            body_bold_path = self._get_font_path("BodyBold.ttf")
            italic_path = self._get_font_path("Italic.ttf")
            
            all_exist = all([
                os.path.exists(title_path) and os.path.getsize(title_path) > 1000,
                os.path.exists(body_path) and os.path.getsize(body_path) > 1000,
                os.path.exists(body_bold_path) and os.path.getsize(body_bold_path) > 1000,
                os.path.exists(italic_path) and os.path.getsize(italic_path) > 1000
            ])
            
            if not all_exist:
                logger.warning("⚠️ Шрифты не найдены, используем fallback")
                self._use_fallback_fonts()
                return
            
            self.fonts['header'] = ImageFont.truetype(title_path, 90)
            self.fonts['subheader'] = ImageFont.truetype(title_path, 50)
            self.fonts['body'] = ImageFont.truetype(body_path, 36)
            self.fonts['body_bold'] = ImageFont.truetype(body_bold_path, 36)
            self.fonts['italic'] = ImageFont.truetype(italic_path, 40)
            self.fonts['meta'] = ImageFont.truetype(body_path, 32)
            self.fonts['small'] = ImageFont.truetype(body_path, 28)
            
            self.fonts_loaded = True
            logger.info("✅ Шрифты загружены")
            
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки шрифтов: {e}")
            self._use_fallback_fonts()

    def _use_fallback_fonts(self):
        """Fallback шрифты"""
        logger.info("🔄 Используем системные шрифты...")
        system_fonts = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
        ]
        
        found_font = None
        for font_path in system_fonts:
            if os.path.exists(font_path):
                found_font = font_path
                break
        
        if found_font:
            try:
                self.fonts['header'] = ImageFont.truetype(found_font, 90)
                self.fonts['subheader'] = ImageFont.truetype(found_font, 50)
                self.fonts['body'] = ImageFont.truetype(found_font, 36)
                self.fonts['body_bold'] = ImageFont.truetype(found_font, 36)
                self.fonts['italic'] = ImageFont.truetype(found_font, 40)
                self.fonts['meta'] = ImageFont.truetype(found_font, 32)
                self.fonts['small'] = ImageFont.truetype(found_font, 28)
                self.fonts_loaded = True
                return
            except:
                pass
        
        default = ImageFont.load_default()
        self.fonts = {
            'header': default, 'subheader': default, 'body': default,
            'body_bold': default, 'italic': default, 'meta': default, 'small': default
        }
        self.fonts_loaded = True

    def _draw_divider(self, draw, center_x, y):
        """Декоративный разделитель"""
        width = 600
        start_x = center_x - width // 2
        draw.line([(start_x, y), (center_x + width // 2, y)], fill=ACCENT_COLOR, width=2)
        s = 8
        draw.polygon([(center_x, y-s), (center_x+s, y), (center_x, y+s), (center_x-s, y)], fill=ACCENT_COLOR)

    def generate_card(self, title, ingredients, time, portions, difficulty, chef_tip, steps=None, dish_image_data=None):
        """
        Генерирует карточку БЕЗ изображения, с фокусом на шаги приготовления
        
        Args:
            steps: Список шагов приготовления (новый параметр)
        """
        if not self.fonts_loaded: 
            self._load_fonts()

        img = Image.new('RGB', (CARD_WIDTH, CARD_HEIGHT), BG_COLOR)
        draw = ImageDraw.Draw(img)
        
        current_y = 80
        
        # --- ЗАГОЛОВОК ---
        clean_title = title.replace("<b>", "").replace("</b>", "").strip()
        clean_title = clean_title[0].upper() + clean_title[1:].lower() if clean_title else ""
        
        font_h = self.fonts['header']
        if len(clean_title) > 20:
            try:
                font_h = ImageFont.truetype(self._get_font_path("Title.ttf"), 70)
            except:
                pass

        wrapped_title = textwrap.wrap(clean_title, width=30)
        
        for line in wrapped_title:
            bbox = draw.textbbox((0, 0), line, font=font_h)
            w = bbox[2] - bbox[0]
            draw.text(((CARD_WIDTH - w) / 2, current_y), line, font=font_h, fill=TEXT_COLOR)
            current_y += (bbox[3] - bbox[1]) + 15

        self._draw_divider(draw, CARD_WIDTH // 2, current_y + 20)
        current_y += 60

        # --- МЕТА-ИНФОРМАЦИЯ С ЭМОДЗИ (В ОДНУ СТРОКУ) ---
        meta_info = f"⏱️ {time} мин  •  👥 {portions} порц  •  📊 {difficulty}"
        meta_bbox = draw.textbbox((0, 0), meta_info, font=self.fonts['meta'])
        meta_w = meta_bbox[2] - meta_bbox[0]
        draw.text(((CARD_WIDTH - meta_w) / 2, current_y), meta_info, font=self.fonts['meta'], fill=ACCENT_COLOR)
        current_y += 60

        # --- ИНГРЕДИЕНТЫ (КОМПАКТНО, 2 КОЛОНКИ) ---
        draw.text((80, current_y), "📦 ИНГРЕДИЕНТЫ:", font=self.fonts['subheader'], fill=TEXT_COLOR)
        current_y += 55
        
        clean_ings = [i.replace("<b>", "").replace("</b>", "").replace("🔸", "").strip("• ").strip() 
                      for i in ingredients[:12]]
        
        # Делим на 2 колонки
        col1_x, col2_x = 100, 650
        col_y = current_y
        
        for idx, ing in enumerate(clean_ings):
            x_pos = col1_x if idx % 2 == 0 else col2_x
            
            # Обрезаем длинные ингредиенты
            if len(ing) > 25:
                ing = ing[:22] + "..."
            
            draw.text((x_pos, col_y), f"• {ing}", font=self.fonts['small'], fill=TEXT_COLOR)
            
            if idx % 2 == 1:  # После каждой пары переходим на новую строку
                col_y += 38
        
        current_y = col_y + 50

        self._draw_divider(draw, CARD_WIDTH // 2, current_y)
        current_y += 50

        # --- ШАГИ ПРИГОТОВЛЕНИЯ (ОСНОВНОЙ КОНТЕНТ) ---
        draw.text((80, current_y), "👨‍🍳 ПРИГОТОВЛЕНИЕ:", font=self.fonts['subheader'], fill=TEXT_COLOR)
        current_y += 55
        
        # Извлекаем шаги из steps или парсим из текста
        if steps and isinstance(steps, list):
            step_lines = steps
        else:
            # Fallback - простой список
            step_lines = [
                "1. Подготовьте все ингредиенты",
                "2. Следуйте инструкциям рецепта",
                "3. Наслаждайтесь результатом!"
            ]
        
        for step in step_lines[:10]:  # Максимум 10 шагов
            # Переносим длинные шаги
            wrapped = textwrap.wrap(step, width=60)
            for line in wrapped:
                draw.text((100, current_y), line, font=self.fonts['body'], fill=TEXT_COLOR)
                current_y += 42
            current_y += 10  # Отступ между шагами

        # --- СОВЕТ ШЕФА ---
        if chef_tip and current_y < CARD_HEIGHT - 200:
            current_y += 30
            
            clean_tip = chef_tip.replace("<b>", "").replace("</b>", "").replace("СОВЕТ ШЕФ-ПОВАРА:", "").strip()
            
            header = "💡 СОВЕТ ШЕФА:"
            header_width = draw.textlength(header, font=self.fonts['subheader'])
            draw.text(((CARD_WIDTH - header_width)/2, current_y), 
                      header, font=self.fonts['subheader'], fill=ACCENT_COLOR)
            
            current_y += 60
            
            tip_lines = textwrap.wrap(clean_tip, width=55)
            for line in tip_lines[:3]:  # Максимум 3 строки
                lw = draw.textlength(line, font=self.fonts['italic'])
                draw.text(((CARD_WIDTH - lw)/2, current_y), line, font=self.fonts['italic'], fill=TEXT_COLOR)
                current_y += 45

        buffer = BytesIO()
        img.save(buffer, format='PNG', quality=95)
        return buffer.getvalue()

recipe_card_generator = RecipeCardGenerator()
