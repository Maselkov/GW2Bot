"""Build templates: chat codes from a build and the build image (used by
/character gear and chat link previews)."""
import asyncio
import base64
import collections
import functools
import io
import itertools
import struct

import aiohttp
import discord
from PIL import Image, ImageDraw, ImageFont

from .utils.wiki import profession_icon_url

Profession = collections.namedtuple("Profession", ["name", "icon", "color"])


def profession_info(gamedata, profession, specializations):
    """Name, icon and colour for a profession, as its elite specialization
    when the last of `specializations` (spec documents, or None) is one."""
    def get_elite_spec():
        try:
            spec = specializations[-1]
        except IndexError:
            return None
        if spec:
            if not spec["elite"]:
                return None
            return spec["name"]
        return None

    color = discord.Color(
        int(gamedata["professions"][profession.lower()]["color"], 0))
    name = get_elite_spec() or profession
    icon = profession_icon_url(name)
    return Profession(name.title(), icon, color)


@functools.cache
def font():
    """The font for specialization names on build images."""
    try:
        return ImageFont.truetype("GWTwoFont1p1.ttf", size=30)
    except IOError:
        return ImageFont.load_default()


# Concurrent downloads per build image
IMAGE_DOWNLOADS = 10


async def download_images(session, urls):
    """Fetch image URLs concurrently. Returns {url: bytes}."""
    semaphore = asyncio.Semaphore(IMAGE_DOWNLOADS)
    timeout = aiohttp.ClientTimeout(total=30)

    async def fetch(url):
        async with semaphore, session.get(url, timeout=timeout) as response:
            response.raise_for_status()
            return url, await response.read()

    return dict(await asyncio.gather(*(fetch(url) for url in set(urls))))


class Build:
    def __init__(self, cog, profession, specializations, skills, code):
        self.cog = cog
        self.specializations = specializations
        self.skills = skills
        self.profession = profession
        self.code = code

    @classmethod
    async def from_code(cls, cog, chatcode):
        code = chatcode[2:-1]
        code = base64.b64decode(code)
        fields = struct.unpack("8B10H4B6H", code[:44])
        profession_doc = await cog.db.professions.find_one({"code": fields[1]})
        specializations = []
        for spec, traits in zip(*[iter(fields[2:8])] * 2):
            if spec == 0:
                continue
            bit_string = "{:3b}".format(traits)
            bit_string = bit_string.strip()
            bit_string = bit_string.zfill(6)
            indexes = [int(bit_string[i : i + 2], 2) - 1 for i in range(0, 6, 2)]
            indexes.reverse()
            spec_doc = await cog.db.specializations.find_one({"_id": spec})
            indexes = [t + i for t, i in zip(indexes, range(0, 9, 3)) if t >= 0]
            active_traits = []
            for i in indexes:
                active_traits.append(spec_doc["major_traits"][i])
            trait_docs = {}
            for trait in spec_doc["minor_traits"] + spec_doc["major_traits"]:
                trait_docs[trait] = await cog.db.traits.find_one({"_id": trait})
            specializations.append(
                {
                    "spec_doc": spec_doc,
                    "active_traits": active_traits,
                    "trait_docs": trait_docs,
                }
            )
        skill_ids = []
        skills = []
        if profession_doc["_id"] == "Ranger":
            for pet in [fields[18], fields[19]]:
                pet = await cog.db.pets.find_one({"_id": pet})
                skills.append(pet)
        if profession_doc["_id"] == "Revenant":
            for legend in [fields[18], fields[19]]:
                legend_doc = await cog.db.legends.find_one({"code": legend})
                skill_ids.append(legend_doc["swap"])
        else:
            palettes = []
            for skill in fields[8:18:2]:
                palettes.append(skill)
            for palette in palettes:
                for palette_id, skill_id in profession_doc["skills_by_palette"]:
                    if palette == palette_id:
                        skill_ids.append(skill_id)
                        break
        for skill_id in skill_ids:
            skills.append(await cog.db.skills.find_one({"_id": skill_id}))
        profession = profession_info(
            cog.gamedata,
            profession_doc["name"], [x["spec_doc"] for x in specializations]
        )
        return cls(cog, profession, specializations, skills, chatcode)

    @classmethod
    async def from_build_tab(cls, cog, build_tab):
        profession_doc = await cog.db.professions.find_one(
            {"_id": build_tab["build"]["profession"]}
        )

        async def get_skills(tab, terrestrial=True):
            skills_key = "skills"
            if not terrestrial:
                skills_key = f"aquatic_{skills_key}"
            skills = tab[skills_key]
            skill_docs = []
            skill_ids = []
            legend_docs = []
            swap_skill_docs = []
            pet_docs = []
            for skill in skills.values():
                if isinstance(skill, list):
                    skill_ids += skill
                    continue
                skill_ids.append(skill)
            for skill_id in skill_ids:
                skill_doc = await cog.db.skills.find_one({"_id": skill_id})
                if not skill_doc:
                    continue
                for palette_id, skill_id_2 in profession_doc["skills_by_palette"]:
                    if skill_id == skill_id_2:
                        skill_doc["palette_id"] = palette_id
                        break
                skill_docs.append(skill_doc)
            legends_key = "legends"
            if not terrestrial:
                legends_key = f"aquatic_{legends_key}"
            legends = tab.get(legends_key)
            if legends:
                for legend in legends:
                    if legend:
                        legend_doc = await cog.db.legends.find_one({"_id": legend})
                        if not legend_doc:
                            continue
                        swap_skill_docs.append(
                            await cog.db.skills.find_one({"_id": legend_doc["swap"]})
                        )
                        utility_palettes = []
                        for utility_skill in legend_doc["utilities"]:
                            for palette_id, skill_id_2 in profession_doc[
                                "skills_by_palette"
                            ]:
                                if utility_skill == skill_id_2:
                                    utility_palettes.append(palette_id)
                                    break
                        legend_doc["utility_palettes"] = utility_palettes
                        legend_docs.append(legend_doc)
            pets = tab.get("pets")
            if pets:
                key = "terrestrial" if terrestrial else "aquatic"
                for pet in pets[key]:
                    if pet:
                        pet_docs.append(await cog.db.pets.find_one({"_id": pet}))

            Skills = collections.namedtuple(
                "Skills", ["skill_docs", "legend_docs", "swap_skill_docs", "pet_docs"]
            )
            return Skills(skill_docs, legend_docs, swap_skill_docs, pet_docs)

        build = build_tab["build"]
        specializations = build["specializations"]
        if not specializations:
            return None
        specs = []
        for spec in specializations:
            if not spec:
                continue
            if spec["id"] == 0:
                continue
            spec_doc = await cog.db.specializations.find_one({"_id": spec["id"]})
            if not spec_doc:
                continue
            trait_docs = {}
            for trait in spec_doc["minor_traits"] + spec_doc["major_traits"]:
                trait_docs[trait] = await cog.db.traits.find_one({"_id": trait})
            specs.append(
                {
                    "spec_doc": spec_doc,
                    "trait_docs": trait_docs,
                    "active_traits": spec["traits"],
                }
            )
        profession = profession_info(
            cog.gamedata,
            build["profession"], [x["spec_doc"] for x in specs]
        )
        profession_code = profession_doc["code"]
        terrestrial = await get_skills(build)
        aquatic = await get_skills(build, False)
        fields = [13, profession_code]
        for spec in specs + [None] * (3 - len(specs)):
            if not spec:
                fields += [0] * 2
                continue
            fields.append(spec["spec_doc"]["_id"])
            bit_string = "0" * 6
            for trait in reversed(spec["active_traits"]):
                try:
                    index = spec["spec_doc"]["major_traits"].index(trait) % 3
                    index += 1
                except ValueError:
                    index = 0
                bit_string += f"{index:02b}"
            bit_string = bit_string.zfill(6)
            fields.append(int(bit_string, 2))
        terrestrial_palettes = [
            skill["palette_id"]
            for skill in terrestrial.skill_docs
            if "palette_id" in skill
        ]
        aquatic_palettes = [
            skill["palette_id"] for skill in aquatic.skill_docs if "palette_id" in skill
        ]
        terrestrial_palettes += [0] * (5 - len(terrestrial_palettes))
        aquatic_palettes += [0] * (5 - len(aquatic_palettes))
        palettes = list(itertools.chain(*zip(terrestrial_palettes, aquatic_palettes)))
        fields += palettes
        if profession_doc["_id"] == "Ranger":
            terrestrial_pets = [pet["_id"] for pet in terrestrial.pet_docs]
            aquatic_pets = [pet["_id"] for pet in aquatic.pet_docs]
            terrestrial_pets += [0] * (2 - len(terrestrial_pets))
            aquatic_pets += [0] * (2 - len(aquatic_pets))
            fields += terrestrial_pets
            fields += aquatic_pets
        if profession_doc["_id"] == "Revenant":
            terrestrial_legend_codes = [leg["code"] for leg in terrestrial.legend_docs]
            aquatic_legend_codes = [leg["code"] for leg in aquatic.legend_docs]
            terrestrial_legend_codes += [0] * (2 - len(terrestrial_legend_codes))
            aquatic_legend_codes += [0] * (2 - len(aquatic_legend_codes))
            fields += terrestrial_legend_codes + aquatic_legend_codes
            # TODO add inactive legend palettes
        fields += [0] * (28 - len(fields))
        code = struct.pack("8B10H4B6H", *fields)
        code = base64.b64encode(code)
        code = code.decode()
        code = f"[&{code}]"
        skills = terrestrial.skill_docs
        if profession_doc["_id"] == "Revenant":
            skills = terrestrial.swap_skill_docs
        if profession_doc["_id"] == "Ranger":
            skills = terrestrial.pet_docs + terrestrial.skill_docs

        return cls(cog, profession, specs, skills, code)

    def image_urls(self):
        urls = [skill["icon"] for skill in self.skills]
        for d in self.specializations:
            spec = d["spec_doc"]
            urls.append(spec["background"])
            for trait in spec["major_traits"] + spec["minor_traits"]:
                urls.append(d["trait_docs"][trait]["icon"])
        return urls

    def __render(self, filename, images):
        image = None
        draw = None
        skills_size = 64 if self.skills else 0
        for index, d in enumerate(self.specializations):
            spec_image = self.render_specialization(
                d["spec_doc"], d["active_traits"], d["trait_docs"], images
            )
            if not image:
                image = Image.new(
                    "RGBA",
                    (
                        spec_image.width,
                        skills_size + (spec_image.height * len(self.specializations)),
                    ),
                )
                draw = ImageDraw.ImageDraw(image)
            image.paste(spec_image, (0, skills_size + (spec_image.height * index)))
            draw.text(
                (5, (spec_image.height * index) + spec_image.height - 35 + skills_size),
                d["spec_doc"]["name"],
                fill="#FFFFFF",
                font=font(),
            )
        # try:
        crop_amount = 6
        if not image:
            image = Image.new("RGBA", (645, skills_size))
        for i, skill in enumerate(self.skills, start=0):
            skill_icon = Image.open(io.BytesIO(images[skill["icon"]]))
            skill_icon = skill_icon.resize((64, 64), Image.Resampling.LANCZOS)
            skill_icon = skill_icon.crop(
                (
                    crop_amount,
                    crop_amount,
                    skill_icon.width - crop_amount,
                    skill_icon.height - crop_amount,
                )
            )
            space_used = skill_icon.width * len(self.skills)
            empty_space = image.width - space_used
            spacing = empty_space // (len(self.skills) + 1)
            width = (i * skill_icon.width) + ((i + 1) * spacing)
            image.paste(skill_icon, ((width), 5))

        #   except Exception as e:
        #      self.cog.log.exception("Exception displayking skills: ",
        #                           exc_info=e)
        output = io.BytesIO()
        image.save(output, "png")
        output.seek(0)
        file = discord.File(output, filename)
        return file

    async def render(self, *, filename="specializations.png"):
        if not self.skills and not self.specializations:
            return None
        images = await download_images(self.cog.bot.session, self.image_urls())
        return await self.cog.bot.loop.run_in_executor(None, self.__render, filename, images)

    @staticmethod
    def render_specialization(specialization, active_traits, trait_docs, images):
        def get_trait_image(icon_url, size):
            image = Image.open(io.BytesIO(images[icon_url]))
            image = image.crop((4, 4, image.width - 4, image.height - 4))
            return image.resize((size, size), Image.Resampling.LANCZOS)

        background = Image.open(io.BytesIO(images[specialization["background"]]))
        background = background.crop((0, 121, 645, 256))
        draw = ImageDraw.ImageDraw(background)
        polygon_points = [120, 11, 167, 39, 167, 93, 120, 121, 73, 93, 73, 39, 120, 11]
        draw.line(polygon_points, fill=(183, 190, 195), width=3)
        mask = Image.new("RGBA", background.size, color=(0, 0, 0, 135))
        d = ImageDraw.ImageDraw(mask)
        d.polygon(polygon_points, fill=(0, 0, 0, 0))
        background.paste(mask, mask=mask)
        mask.close()
        column = 0
        size = (background.height - 18) // 3
        trait_mask = Image.new("RGBA", (size, size), color=(0, 0, 0, 135))
        for index, trait in enumerate(specialization["major_traits"]):
            trait_doc = trait_docs[trait]
            image = get_trait_image(trait_doc["icon"], size)
            if trait not in active_traits:
                image.paste(trait_mask, mask=trait_mask)
            background.paste(
                image, (272 + (column * 142), 6 + ((size + 3) * (index % 3))), image
            )
            if index and not (index + 1) % 3:
                column += 1
            image.close()
        trait_mask.close()
        minor_trait_mask = Image.new("RGBA", (size, size))
        d = ImageDraw.ImageDraw(minor_trait_mask)
        d.polygon(
            [13, 2, 25, 2, 35, 12, 35, 27, 21, 36, 17, 36, 3, 27, 3, 12],
            fill=(0, 0, 0, 255),
        )
        for index, trait in enumerate(specialization["minor_traits"]):
            trait_doc = trait_docs[trait]
            image = get_trait_image(trait_doc["icon"], size)
            background.paste(
                image, (272 - size - 32 + (index * 142), 6 + size + 3), minor_trait_mask
            )
            image.close()
        minor_trait_mask.close()
        return background
