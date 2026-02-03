import os
import logging
from io import BytesIO

import aiohttp
import aiofiles
from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------------------
# КОНФИГУРАЦИЯ
# ---------------------------------------------------------------------------
FONTS_DIR  = "fonts"
ASSETS_DIR = "assets"

# Размеры карточки
CARD_WIDTH  = 1200
CARD_HEIGHT = 1700

# Палитра «Кондитерская»
COLOR_BG           = "#FAF6EF"   # фон карточки
COLOR_CREAM_DARK   = "#F0E6D3"   # тонкие разделители
COLOR_BROWN_DARK   = "#3B2316"   # основной текст
COLOR_BROWN_MID    = "#6B4226"   # акцент (полоса, бейдж номера, контур тэга)
COLOR_BROWN_LIGHT  = "#A0784A"   # орнамент, маркеры ингредиентов
COLOR_GREEN        = "#4A7C59"   # акцент «Средняя» и блок совета
COLOR_TAG_BG       = "#EDE4D3"   # фон мета-тэгов
COLOR_TIP_BG       = "#EBF5EE"   # фон блока совета шефа

logger = logging.getLogger(__name__)


# ===========================================================================
# РЕСУРС-МЕНЕДЖЕР ШРИФТОВ (не изменён по структуре)
# ===========================================================================
class RecipeCardGenerator:
    FONTS_URLS = {
        "Title.ttf":      "https://github.com/google/fonts/raw/main/ofl/playfairdisplay/PlayfairDisplay-Bold.ttf",
        "Body.ttf":       "https://github.com/google/fonts/raw/main/ofl/lora/Lora-Regular.ttf",
        "BodyBold.ttf":   "https://github.com/google/fonts/raw/main/ofl/lora/Lora-Bold.ttf",
        "Italic.ttf":     "https://github.com/google/fonts/raw/main/ofl/lora/Lora-Italic.ttf",
    }

    # размеры шрифтов под новый дизайн
    _FONT_SIZES = {
        "header":     88,
        "subheader":  42,
        "body":       30,
        "body_bold":  30,
        "italic":     28,
        "tag":        24,
        "step_num":   34,
    }

    def __init__(self):
        self.fonts_loaded = False
        self.fonts: dict[str, ImageFont.FreeTypeFont] = {}
        self._ensure_dirs()

    # ------------------------------------------------------------------
    # каталоги
    # ------------------------------------------------------------------
    def _ensure_dirs(self):
        os.makedirs(FONTS_DIR,  exist_ok=True)
        os.makedirs(ASSETS_DIR, exist_ok=True)

    def _get_font_path(self, name: str) -> str:
        return os.path.join(FONTS_DIR, name)

    # ------------------------------------------------------------------
    # async download
    # ------------------------------------------------------------------
    async def ensure_fonts(self):
        """Скачивает шрифты Google Fonts (если ещё нет на диске)."""
        async with aiohttp.ClientSession() as session:
            for filename, url in self.FONTS_URLS.items():
                path = self._get_font_path(filename)
                if not os.path.exists(path) or os.path.getsize(path) < 1000:
                    try:
                        logger.info("🔄 Скачиваю %s …", filename)
                        async with session.get(url) as resp:
                            if resp.status == 200:
                                content = await resp.read()
                                async with aiofiles.open(path, mode="wb") as f:
                                    await f.write(content)
                                logger.info("✅ %s скачан", filename)
                    except Exception as exc:
                        logger.error("❌ Ошибка скачивания %s: %s", filename, exc)
        self._load_fonts()

    # ------------------------------------------------------------------
    # загрузка шрифтов из файлов
    # ------------------------------------------------------------------
    def _load_fonts(self):
        title_path      = self._get_font_path("Title.ttf")
        body_path       = self._get_font_path("Body.ttf")
        body_bold_path  = self._get_font_path("BodyBold.ttf")
        italic_path     = self._get_font_path("Italic.ttf")

        paths = [title_path, body_path, body_bold_path, italic_path]
        if not all(os.path.exists(p) and os.path.getsize(p) > 1000 for p in paths):
            logger.warning("⚠️  Шрифты не найдены — используем fallback")
            self._use_fallback_fonts()
            return

        try:
            S = self._FONT_SIZES
            self.fonts["header"]     = ImageFont.truetype(title_path,     S["header"])
            self.fonts["subheader"]  = ImageFont.truetype(title_path,     S["subheader"])
            self.fonts["body"]       = ImageFont.truetype(body_path,      S["body"])
            self.fonts["body_bold"]  = ImageFont.truetype(body_bold_path, S["body_bold"])
            self.fonts["italic"]     = ImageFont.truetype(italic_path,    S["italic"])
            self.fonts["tag"]        = ImageFont.truetype(body_bold_path, S["tag"])
            self.fonts["step_num"]   = ImageFont.truetype(title_path,     S["step_num"])
            self.fonts_loaded = True
            logger.info("✅ Шрифты загружены")
        except Exception as exc:
            logger.error("❌ Ошибка загрузки шрифтов: %s", exc)
            self._use_fallback_fonts()

    # ------------------------------------------------------------------
    # fallback — системные шрифты
    # ------------------------------------------------------------------
    _FALLBACK_CANDIDATES = [
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    ]

    def _use_fallback_fonts(self):
        logger.info("🔄 Используем системные шрифты …")

        found = None
        for candidate in self._FALLBACK_CANDIDATES:
            if os.path.exists(candidate):
                found = candidate
                break

        if found:
            try:
                S = self._FONT_SIZES
                for key in ("header", "subheader", "body", "body_bold",
                            "italic", "tag", "step_num"):
                    self.fonts[key] = ImageFont.truetype(found, S[key])
                self.fonts_loaded = True
                return
            except Exception:
                pass

        # абсолютный fallback
        default = ImageFont.load_default()
        self.fonts = {k: default for k in self._FONT_SIZES}
        self.fonts_loaded = True

    # ==================================================================
    # ГЕНЕРАЦИЯ КАРТОЧКИ
    # ==================================================================
    def generate_card(
        self,
        title: str,
        ingredients: list[str],
        time: str | int,
        portions: str | int,
        difficulty: str,
        chef_tip: str,
        steps: list[str] | None = None,
        dish_image_data: bytes | None = None,   # зарезервирован, не используется
    ) -> bytes:
        """
        Генерирует PNG-карточку рецепта в стиле «Кондитерская».

        Args:
            title:          Название блюда.
            ingredients:    Список ингредиентов (до 12 штук).
            time:           Время приготовления в минутах.
            portions:       Количество порций.
            difficulty:     Уровень сложности (текст).
            chef_tip:       Совет шефа.
            steps:          Список шагов приготовления.  Если None — fallback.
            dish_image_data: зарезервирован для будущего использования.

        Returns:
            PNG-изображение в виде bytes.
        """
        if not self.fonts_loaded:
            self._load_fonts()

        img  = Image.new("RGB", (CARD_WIDTH, CARD_HEIGHT), COLOR_BG)
        draw = ImageDraw.Draw(img)

        y = self._draw_top_bar(draw)
        y = self._draw_title(draw, title, y)
        y = self._draw_ornament(draw, y)
        y = self._draw_meta_tags(draw, time, portions, difficulty, y)
        y = self._draw_section_divider(draw, y)
        y = self._draw_ingredients(draw, ingredients, y)
        y = self._draw_section_divider(draw, y)
        y = self._draw_steps(draw, steps, y)
        self._draw_chef_tip(draw, chef_tip, y)
        self._draw_bottom_bar(draw)

        buf = BytesIO()
        img.save(buf, format="PNG", quality=95)
        return buf.getvalue()

    # ==================================================================
    # ПРИВАТНЫЕ РЕНДЕР-БЛОКИ
    # ==================================================================

    # ------------------------------------------------------------------
    # утилита: перенос строки по пикселям
    # ------------------------------------------------------------------
    @staticmethod
    def _wrap_px(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> list[str]:
        """Разбивает текст на строки так, чтобы каждая укладывалась в max_w px."""
        words, lines, current = text.split(), [], ""
        for word in words:
            candidate = (current + " " + word).strip()
            bb = draw.textbbox((0, 0), candidate, font=font)
            if bb[2] - bb[0] <= max_w:
                current = candidate
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines or [""]

    # ------------------------------------------------------------------
    # утилита: очистка HTML-тегов из строки
    # ------------------------------------------------------------------
    @staticmethod
    def _clean(text: str) -> str:
        return text.replace("<b>", "").replace("</b>", "").replace("🔸", "").strip("• ").strip()

    # ------------------------------------------------------------------
    # верхняя полоса
    # ------------------------------------------------------------------
    @staticmethod
    def _draw_top_bar(draw: ImageDraw.ImageDraw) -> int:
        draw.rectangle([(0, 0), (CARD_WIDTH, 12)], fill=COLOR_BROWN_MID)
        return 70  # начальный y после полосы

    # ------------------------------------------------------------------
    # нижняя полоса
    # ------------------------------------------------------------------
    @staticmethod
    def _draw_bottom_bar(draw: ImageDraw.ImageDraw):
        draw.rectangle([(0, CARD_HEIGHT - 12), (CARD_WIDTH, CARD_HEIGHT)], fill=COLOR_BROWN_MID)

    # ------------------------------------------------------------------
    # заголовок
    # ------------------------------------------------------------------
    def _draw_title(self, draw: ImageDraw.ImageDraw, title: str, y: int) -> int:
        clean = self._clean(title)
        # первая буква заглавная, остальные как есть
        clean = (clean[0].upper() + clean[1:]) if clean else ""

        font = self.fonts["header"]
        # если длинный — чуть уменьшаем
        if len(clean) > 20:
            try:
                font = ImageFont.truetype(self._get_font_path("Title.ttf"), 70)
            except Exception:
                pass

        # перенос по пикселям
        lines = self._wrap_px(draw, clean, font, CARD_WIDTH - 160)
        for line in lines:
            bb = draw.textbbox((0, 0), line, font=font)
            lw = bb[2] - bb[0]
            draw.text(((CARD_WIDTH - lw) // 2, y), line, font=font, fill=COLOR_BROWN_DARK)
            y += (bb[3] - bb[1]) + 18

        return y

    # ------------------------------------------------------------------
    # орнамент  ─── ◆ ───
    # ------------------------------------------------------------------
    @staticmethod
    def _draw_ornament(draw: ImageDraw.ImageDraw, y: int) -> int:
        cx = CARD_WIDTH // 2
        draw.line([(cx - 180, y), (cx - 30, y)], fill=COLOR_BROWN_LIGHT, width=2)
        draw.line([(cx + 30,  y), (cx + 180, y)], fill=COLOR_BROWN_LIGHT, width=2)
        s = 7
        draw.polygon(
            [(cx, y - s), (cx + s, y), (cx, y + s), (cx - s, y)],
            fill=COLOR_BROWN_MID,
        )
        return y + 48

    # ------------------------------------------------------------------
    # мета-тэги (время / порции / сложность)
    # ------------------------------------------------------------------
    def _draw_meta_tags(self, draw: ImageDraw.ImageDraw,
                        time, portions, difficulty: str, y: int) -> int:
        font = self.fonts["tag"]

        tags = [
            (f"⏱  {time} мин",      COLOR_BROWN_MID),
            (f"👥 {portions} порции", COLOR_BROWN_MID),
            (f"📊 {difficulty}",      COLOR_GREEN),
        ]

        # предварительно считаем ширины для центрирования
        rects: list[tuple[int, int]] = []   # (ширина_блока, высота_блока)
        for txt, _ in tags:
            bb = draw.textbbox((0, 0), txt, font=font)
            rects.append((bb[2] - bb[0] + 36, bb[3] - bb[1] + 20))  # +padding

        gap      = 24
        total_w  = sum(r[0] for r in rects) + gap * (len(tags) - 1)
        x        = (CARD_WIDTH - total_w) // 2

        for (txt, color), (rw, rh) in zip(tags, rects):
            draw.rounded_rectangle(
                [(x, y), (x + rw, y + rh)],
                radius=12, fill=COLOR_TAG_BG, outline=color, width=1,
            )
            bb  = draw.textbbox((0, 0), txt, font=font)
            t_w = bb[2] - bb[0]
            t_h = bb[3] - bb[1]
            draw.text(
                (x + (rw - t_w) // 2, y + (rh - t_h) // 2),
                txt, font=font, fill=color,
            )
            x += rw + gap

        return y + rects[0][1] + 52

    # ------------------------------------------------------------------
    # тонкий горизонтальный разделитель
    # ------------------------------------------------------------------
    @staticmethod
    def _draw_section_divider(draw: ImageDraw.ImageDraw, y: int) -> int:
        draw.line([(80, y), (CARD_WIDTH - 80, y)], fill=COLOR_CREAM_DARK, width=1)
        return y + 40

    # ------------------------------------------------------------------
    # блок «Ингредиенты»
    # ------------------------------------------------------------------
    def _draw_ingredients(self, draw: ImageDraw.ImageDraw,
                          ingredients: list[str], y: int) -> int:
        draw.text((80, y), "ИНГРЕДИЕНТЫ", font=self.fonts["subheader"], fill=COLOR_BROWN_DARK)
        y += 58

        clean_ings = [self._clean(i) for i in ingredients[:12]]

        col_x = [100, 640]       # x-координата каждой колонки
        col_y = [y, y]           # текущий y в каждой колонке

        for idx, ing in enumerate(clean_ings):
            c = idx % 2          # 0 — левая, 1 — правая колонка

            # круглый маркер
            marker_x = col_x[c]
            marker_y = col_y[c] + 12
            draw.ellipse(
                [(marker_x, marker_y), (marker_x + 10, marker_y + 10)],
                fill=COLOR_BROWN_LIGHT,
            )
            draw.text((col_x[c] + 20, col_y[c]), ing, font=self.fonts["body"], fill=COLOR_BROWN_DARK)
            col_y[c] += 46       # увеличенный межстрочный интервал

        return max(col_y) + 44

    # ------------------------------------------------------------------
    # блок «Приготовление»
    # ------------------------------------------------------------------
    def _draw_steps(self, draw: ImageDraw.ImageDraw,
                    steps: list[str] | None, y: int) -> int:
        draw.text((80, y), "ПРИГОТОВЛЕНИЕ", font=self.fonts["subheader"], fill=COLOR_BROWN_DARK)
        y += 60

        if not steps or not isinstance(steps, list):
            steps = [
                "1. Подготовьте все ингредиенты.",
                "2. Следуйте инструкциям рецепта.",
                "3. Наслаждайтесь результатом!",
            ]

        badge_r   = 22                          # радиус круглого бейдж-номера
        text_x    = 80 + badge_r * 2 + 21       # текст правее бейдж
        max_text_w = CARD_WIDTH - text_x - 80

        for step in steps[:10]:                 # не более 10 шагов
            # разделяем номер и тело
            dot_pos = step.find(".")
            if dot_pos != -1 and step[:dot_pos].strip().isdigit():
                num  = step[:dot_pos].strip()
                rest = step[dot_pos + 1:].strip()
            else:
                num  = ""
                rest = step.strip()

            # ── круглый бейдж с номером ──
            if num:
                badge_cx = 80 + badge_r
                badge_cy = y  + badge_r
                draw.ellipse(
                    [(badge_cx - badge_r, badge_cy - badge_r),
                     (badge_cx + badge_r, badge_cy + badge_r)],
                    fill=COLOR_BROWN_MID,
                )
                bb   = draw.textbbox((0, 0), num, font=self.fonts["step_num"])
                nw   = bb[2] - bb[0]
                nh   = bb[3] - bb[1]
                draw.text(
                    (badge_cx - nw // 2, badge_cy - nh // 2 - 1),
                    num, font=self.fonts["step_num"], fill="white",
                )

            # ── текст шага (перенос по пикселям) ──
            lines = self._wrap_px(draw, rest, self.fonts["body"], max_text_w)
            line_h = 40                         # высота одной строки текста
            for i, line in enumerate(lines):
                draw.text((text_x, y + i * line_h), line, font=self.fonts["body"], fill=COLOR_BROWN_DARK)

            block_h = max(len(lines) * line_h, badge_r * 2)
            y += block_h + 24                   # отступ между шагами

        return y

    # ------------------------------------------------------------------
    # блок «Совет шефа»
    # ------------------------------------------------------------------
    def _draw_chef_tip(self, draw: ImageDraw.ImageDraw, chef_tip: str, y: int):
        if not chef_tip or y >= CARD_HEIGHT - 220:
            return

        clean_tip = (
            chef_tip
            .replace("<b>", "").replace("</b>", "")
            .replace("СОВЕТ ШЕФ-ПОВАРА:", "")
            .strip()
        )

        tip_pad   = 28
        max_tip_w = CARD_WIDTH - 160 - tip_pad * 2
        tip_lines = self._wrap_px(draw, clean_tip, self.fonts["italic"], max_tip_w)

        line_h       = 38
        block_h      = len(tip_lines) * line_h + 84
        block_left   = 60
        block_right  = CARD_WIDTH - 60

        # фон + контур
        draw.rounded_rectangle(
            [(block_left, y), (block_right, y + block_h)],
            radius=16, fill=COLOR_TIP_BG, outline=COLOR_GREEN, width=2,
        )

        # заголовок
        draw.text((80, y + 20), "💡 Совет шефа", font=self.fonts["subheader"], fill=COLOR_GREEN)

        # текст совета
        ty = y + 66
        for line in tip_lines:
            draw.text((80 + tip_pad, ty), line, font=self.fonts["italic"], fill=COLOR_BROWN_DARK)
            ty += line_h


# ---------------------------------------------------------------------------
# SINGLETON
# ---------------------------------------------------------------------------
recipe_card_generator = RecipeCardGenerator()
