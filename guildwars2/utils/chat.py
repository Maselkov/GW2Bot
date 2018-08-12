import re

zero_width_space = u'\u200b'


def embed_list_lines(embed, lines, field_name, max_characters=1024):
    value = "\n".join(lines)
    if len(value) > 1024:
        value = ""
        values = []
        for line in lines:
            if len(value) + len(line) > 1024:
                values.append(value)
                value = ""
            value += line + "\n"
        if value:
            values.append(value)
        embed.add_field(name=field_name, value=values[0], inline=False)
        for v in values[1:]:
            embed.add_field(name=zero_width_space, value=v, inline=False)
    else:
        embed.add_field(name=field_name, value=value, inline=False)
    return embed


def cleanup_xml_tags(text):
    return re.sub("<[^<]+>", "", text)
