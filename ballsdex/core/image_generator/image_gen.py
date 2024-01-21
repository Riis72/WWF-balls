import os
import textwrap
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image, ImageDraw, ImageFont, ImageOps
import logging
log = logging.getLogger("ballsdex")

if TYPE_CHECKING:
    from ballsdex.core.models import BallInstance





SOURCES_PATH = Path(os.path.dirname(os.path.abspath(__file__)), "./src")
WIDTH = 1500
HEIGHT = 2000

RECTANGLE_WIDTH = WIDTH - 40
RECTANGLE_HEIGHT = (HEIGHT // 5) * 2

CORNERS = ((34, 261), (1393, 992))
artwork_size = [b - a for a, b in zip(*CORNERS)]

title_font = ImageFont.truetype(str(SOURCES_PATH / "ArsenicaTrial-Extrabold.ttf"), 170)
capacity_name_font = ImageFont.truetype(str(SOURCES_PATH / "Bobby Jones Soft.otf"), 110)
capacity_description_font = ImageFont.truetype(str(SOURCES_PATH / "OpenSans-Semibold.ttf"), 75)
stats_font = ImageFont.truetype(str(SOURCES_PATH / "Bobby Jones Soft.otf"), 130)
credits_font = ImageFont.truetype(str(SOURCES_PATH / "arial.ttf"), 40)


def draw_card(ball_instance: "BallInstance"):
    ball = ball_instance.countryball
    ball_health = (237, 115, 101, 255)

    if ball_instance.shiny:
        image = Image.open(str(SOURCES_PATH / "shiny.png"))
        ball_health = (255, 255, 255, 255)
    elif special_image := ball_instance.special_card:
        image = Image.open("." + special_image)
    else:
        image = Image.open("." + ball.cached_regime.background)
        log.info(ball.cached_regime.background)
    icon = Image.open("." + ball.cached_economy.icon) if ball.cached_economy else None

    artwork = Image.open("." + ball.collection_card)
    artwork = artwork.resize((1359, 731), Image.Resampling.LANCZOS)
    blendedImage = Image.blend(image, artwork, 0.2)

    draw = ImageDraw.Draw(blendedImage)

    if ball.cached_regime.background == '/static/uploads/hyvikset(1).png':
        if ball_instance.shiny:
            draw.text((50, 20), ball.short_name or ball.country, font=title_font, fill=(255, 255, 255, 255))
        else:
            draw.text((50, 20), ball.short_name or ball.country, font=title_font, fill=(0, 0, 128, 255))
    else:
        draw.text((50, 20), ball.short_name or ball.country, font=title_font, fill=(255, 255, 255, 255))
    if ball.cached_regime.background == '/static/uploads/pahikset(1).png':
        ball_health = (255, 255, 255, 255)


    for i, line in enumerate(textwrap.wrap(f"Kyky: {ball.capacity_name}", width=26)):
        draw.text(
            (100, 1050 + 100 * i),
            line,
            font=capacity_name_font,
            fill=(230, 230, 230, 255),
            stroke_width=2,
            stroke_fill=(0, 0, 0, 255),
        )
    for i, line in enumerate(textwrap.wrap(ball.capacity_description, width=32)):
        draw.text(
            (60, 1300 + 80 * i),
            line,
            font=capacity_description_font,
            stroke_width=1,
            stroke_fill=(0, 0, 0, 255),
        )
    draw.text(
        (320, 1670),
        str(ball_instance.health),
        font=stats_font,
        fill=ball_health,
        stroke_width=1,
        stroke_fill=(0, 0, 0, 255),
    )
    draw.text(
        (1120, 1670),
        str(ball_instance.attack),
        font=stats_font,
        fill=(252, 194, 76, 255),
        stroke_width=1,
        stroke_fill=(0, 0, 0, 255),
        anchor="ra",
    )
    draw.text(
        (30, 1870),
        # Modifying the line below is breaking the licence as you are removing credits
        # If you don't want to receive a DMCA, just don't
        "Created by El Laggron\n" f"Artwork author: {ball.credits}",
        font=credits_font,
        fill=(0, 0, 0, 255),
        stroke_width=0,
        stroke_fill=(255, 255, 255, 255),
    )

    artwork1 = Image.open("." + ball.collection_card)
    image.paste(ImageOps.fit(artwork1, artwork_size), CORNERS[0])  # type: ignore

    if icon:
        icon = ImageOps.fit(icon, (192, 192))
        image.paste(icon, (1200, 30), mask=icon)
        icon.close()
    artwork.close()

    return image
