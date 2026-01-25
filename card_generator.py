import os
import textwrap
import logging
from io import BytesIO
import aiohttp
import aiofiles
from PIL import Image, ImageDraw, ImageFont

# --- КОНФИГУРАЦИЯ ---
FONTS_DIR = "fonts"
ASSETS_DIR = "assets"  # Папка для иконок и фонов

# Цвета из шаблона
BG_COLOR = "#F2E8D5"       # Цвет пергамента
TEXT_COLOR = "#3E2723"     # Темно-коричневый (вместо черного)
ACCENT_COLOR = "#5D4037"   # Светлее для линий
HIGHLIGHT_COLOR = "#2E7D32" # Оливковый (для зелени, если нужно)

# Размеры
CARD_WIDTH = 1200
CARD_HEIGHT = 1600

logger = logging.getLogger(__name__)

class RecipeCardGenerator:
    # Используем шрифты с засечками (Serif) для стиля "Старая книга"
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
        if not os.path.exists(FONTS_DIR): os.makedirs(FONTS_DIR)
        if not os.path.exists(ASSETS_DIR): os.makedirs(ASSETS_DIR)

    def _get_font_path(self, name):
        return os.path.join(FONTS_DIR, name)

    async def ensure_fonts(self):
        """Скачивает винтажные шрифты"""
        async with aiohttp.ClientSession() as session:
            for filename, url in self.FONTS_URLS.items():
                path = self._get_font_path(filename)
                if not os.path.exists(path) or os.path.getsize(path) < 1000:
                    try:
                        async with session.get(url) as resp:
                            if resp.status == 200:
                                content = await resp.read()
                                async with aiofiles.open(path, mode='wb') as f:
                                    await f.write(content)
                    except Exception as e:
                        logger.error(f"Error downloading {filename}: {e}")
        self._load_fonts()

    # Замените метод _load_fonts в card_generator.py:

def _load_fonts(self):
    """Загрузка шрифтов с fallback на дефолтные"""
    try:
        # Проверяем существование файлов
        title_path = self._get_font_path("Title.ttf")
        body_path = self._get_font_path("Body.ttf")
        body_bold_path = self._get_font_path("BodyBold.ttf")
        italic_path = self._get_font_path("Italic.ttf")
        
        # Проверяем, что все файлы существуют и не пусты
        all_exist = all([
            os.path.exists(title_path) and os.path.getsize(title_path) > 1000,
            os.path.exists(body_path) and os.path.getsize(body_path) > 1000,
            os.path.exists(body_bold_path) and os.path.getsize(body_bold_path) > 1000,
            os.path.exists(italic_path) and os.path.getsize(italic_path) > 1000
        ])
        
        if not all_exist:
            logger.warning("⚠️ Шрифты не найдены или повреждены, используем fallback")
            self._use_fallback_fonts()
            return
        
        # Пробуем загрузить
        self.fonts['header'] = ImageFont.truetype(title_path, 90)
        self.fonts['subheader'] = ImageFont.truetype(title_path, 50)
        self.fonts['body'] = ImageFont.truetype(body_path, 40)
        self.fonts['body_bold'] = ImageFont.truetype(body_bold_path, 40)
        self.fonts['italic'] = ImageFont.truetype(italic_path, 45)
        self.fonts['meta'] = ImageFont.truetype(body_path, 30)
        
        self.fonts_loaded = True
        logger.info("✅ Шрифты загружены успешно")
        
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки шрифтов: {e}")
        self._use_fallback_fonts()

def _use_fallback_fonts(self):
    """Использует системные шрифты как fallback"""
    logger.info("🔄 Попытка использовать системные шрифты...")
    
    # Список возможных системных шрифтов (по приоритету)
    system_fonts = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
        "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf",
        "C:\\Windows\\Fonts\\timesbd.ttf",  # Windows
    ]
    
    found_font = None
    for font_path in system_fonts:
        if os.path.exists(font_path):
            found_font = font_path
            logger.info(f"✅ Найден системный шрифт: {font_path}")
            break
    
    if found_font:
        try:
            self.fonts['header'] = ImageFont.truetype(found_font, 90)
            self.fonts['subheader'] = ImageFont.truetype(found_font, 50)
            self.fonts['body'] = ImageFont.truetype(found_font, 40)
            self.fonts['body_bold'] = ImageFont.truetype(found_font, 40)
            self.fonts['italic'] = ImageFont.truetype(found_font, 45)
            self.fonts['meta'] = ImageFont.truetype(found_font, 30)
            self.fonts_loaded = True
            logger.info("✅ Системные шрифты загружены")
            return
        except Exception as e:
            logger.error(f"❌ Не удалось загрузить системный шрифт: {e}")
    
    # Крайний fallback - PIL default
    logger.warning("⚠️ Используем PIL default шрифты")
    default = ImageFont.load_default()
    self.fonts = {
        'header': default,
        'subheader': default,
        'body': default,
        'body_bold': default,
        'italic': default,
        'meta': default
    }
    self.fonts_loaded = True

    def _draw_vintage_divider(self, draw, center_x, y):
        """Рисует декоративный разделитель, если нет картинки"""
        # Имитация узора ---x---x---
        width = 600
        start_x = center_x - width // 2
        draw.line([(start_x, y), (center_x + width // 2, y)], fill=ACCENT_COLOR, width=2)
        # Ромбик по центру
        s = 8
        draw.polygon([(center_x, y-s), (center_x+s, y), (center_x, y+s), (center_x-s, y)], fill=ACCENT_COLOR)
        # Точки по краям
        draw.ellipse([start_x-5, y-5, start_x+5, y+5], fill=ACCENT_COLOR)
        draw.ellipse([center_x + width//2 - 5, y-5, center_x + width//2 + 5, y+5], fill=ACCENT_COLOR)

    # Замените метод generate_card в классе RecipeCardGenerator:

    def generate_card(self, title, ingredients, time, portions, difficulty, chef_tip, dish_image_data=None):
        if not self.fonts_loaded: self._load_fonts()

        # 1. Фон
        bg_path = os.path.join(ASSETS_DIR, "paper_texture.jpg")
        if os.path.exists(bg_path):
            img = Image.open(bg_path).resize((CARD_WIDTH, CARD_HEIGHT)).convert("RGB")
        else:
            img = Image.new('RGB', (CARD_WIDTH, CARD_HEIGHT), BG_COLOR)
        
        draw = ImageDraw.Draw(img)
        
        # --- ЗАГОЛОВОК ---
        # Убираем HTML теги и приводим к Title Case
        clean_title = title.replace("<b>", "").replace("</b>", "").strip()
        # Приводим к нормальному виду: первая буква заглавная, остальные строчные
        clean_title = clean_title[0].upper() + clean_title[1:].lower() if clean_title else ""
        
        font_h = self.fonts['header']
        
        # Если заголовок длинный, уменьшаем шрифт
        if len(clean_title) > 20:
            font_h = ImageFont.truetype(self._get_font_path("Title.ttf"), 70)

        # Разбивка на строки
        wrapped_title = textwrap.wrap(clean_title, width=25)
        current_y = 120
        
        for line in wrapped_title:
            bbox = draw.textbbox((0, 0), line, font=font_h)
            w = bbox[2] - bbox[0]
            draw.text(((CARD_WIDTH - w) / 2, current_y), line, font=font_h, fill=TEXT_COLOR)
            current_y += (bbox[3] - bbox[1]) + 20

        # Декоративный разделитель
        self._draw_vintage_divider(draw, CARD_WIDTH // 2, current_y + 20)
        current_y += 80

        # --- ОСНОВНОЙ БЛОК (ФОТО + ИНГРЕДИЕНТЫ) ---
        col_left_x = 100
        col_right_x = 680
        photo_size = 520
        
        # 1. Фото блюда (Слева)
        if dish_image_data:
            try:
                dish = Image.open(BytesIO(dish_image_data)).convert("RGB")
                # Crop to square
                min_side = min(dish.size)
                left = (dish.width - min_side) / 2
                top = (dish.height - min_side) / 2
                dish = dish.crop((left, top, left + min_side, top + min_side))
                dish = dish.resize((photo_size, photo_size), Image.Resampling.LANCZOS)
                
                img.paste(dish, (col_left_x, current_y))
                
                # Двойная рамка вокруг фото
                draw.rectangle([col_left_x, current_y, col_left_x+photo_size, current_y+photo_size], outline=TEXT_COLOR, width=2)
                draw.rectangle([col_left_x-5, current_y-5, col_left_x+photo_size+5, current_y+photo_size+5], outline=ACCENT_COLOR, width=1)
                
            except Exception as e:
                logger.error(f"Image error: {e}")
                draw.rectangle([col_left_x, current_y, col_left_x+photo_size, current_y+photo_size], fill="#D7CCC8", outline=TEXT_COLOR)
                draw.text((col_left_x+180, current_y+240), "НЕТ ФОТО", font=self.fonts['subheader'], fill=ACCENT_COLOR)
        else:
            draw.rectangle([col_left_x, current_y, col_left_x+photo_size, current_y+photo_size], fill="#D7CCC8", outline=TEXT_COLOR)

        # 2. Ингредиенты (Справа)
        draw.text((col_right_x, current_y), "ИНГРЕДИЕНТЫ:", font=self.fonts['subheader'], fill=TEXT_COLOR)
        
        ing_y = current_y + 80
        clean_ings = [i.replace("<b>", "").replace("</b>", "").replace("🔸", "").strip("• ").strip() for i in ingredients[:10]]
        
        for ing in clean_ings:
            wrapped_ing = textwrap.wrap(f"• {ing}", width=22)
            for w_line in wrapped_ing:
                draw.text((col_right_x, ing_y), w_line, font=self.fonts['body'], fill=TEXT_COLOR)
                ing_y += 45
            ing_y += 15

        # --- ИНФО-ПАНЕЛЬ (ВРЕМЯ, ПОРЦИИ) ---
        meta_y = current_y + photo_size + 40
        
        icons_info = [
            ("clock.png", f"ВРЕМЯ: {time}"),
            ("chef.png", f"ПОРЦИИ: {portions}")
        ]
        
        icon_x_start = col_left_x
        for icon_file, text in icons_info:
            icon_path = os.path.join(ASSETS_DIR, icon_file)
            
            if os.path.exists(icon_path):
                try:
                    icn = Image.open(icon_path).convert("RGBA").resize((50, 50))
                    mask = icn.split()[3]
                    img.paste(icn, (icon_x_start, meta_y), mask)
                except:
                    draw.ellipse([icon_x_start, meta_y, icon_x_start+50, meta_y+50], outline=TEXT_COLOR, width=2)
            else:
                draw.ellipse([icon_x_start, meta_y, icon_x_start+50, meta_y+50], outline=TEXT_COLOR, width=2)
                
            draw.text((icon_x_start + 65, meta_y + 5), text, font=self.fonts['meta'], fill=TEXT_COLOR)
            icon_x_start += 300

        # --- СОВЕТ ШЕФА ---
        if chef_tip:
            tip_box_y = max(ing_y, meta_y + 100) + 40
            tip_margin = 100
            
            clean_tip = chef_tip.replace("<b>", "").replace("</b>", "").replace("СОВЕТ ШЕФ-ПОВАРА:", "").strip()
            
            header = "СОВЕТ ШЕФА:"
            header_width = draw.textlength(header, font=self.fonts['subheader'])
            draw.text(((CARD_WIDTH - header_width)/2, tip_box_y), 
                      header, font=self.fonts['subheader'], fill=ACCENT_COLOR)
            
            tip_lines = textwrap.wrap(clean_tip, width=50)
            text_start_y = tip_box_y + 70
            
            box_height = len(tip_lines) * 55 + 100
            
            rect_coords = [tip_margin, tip_box_y - 20, CARD_WIDTH - tip_margin, tip_box_y + box_height]
            draw.rectangle(rect_coords, outline=ACCENT_COLOR, width=3)
            draw.rectangle([r + 10 if i < 2 else r - 10 for i, r in enumerate(rect_coords)], outline=ACCENT_COLOR, width=1)

            ty = text_start_y
            for line in tip_lines:
                lw = draw.textlength(line, font=self.fonts['italic'])
                draw.text(((CARD_WIDTH - lw)/2, ty), line, font=self.fonts['italic'], fill=TEXT_COLOR)
                ty += 55

        buffer = BytesIO()
        img.save(buffer, format='PNG', quality=95)
        return buffer.getvalue()

recipe_card_generator = RecipeCardGenerator()
