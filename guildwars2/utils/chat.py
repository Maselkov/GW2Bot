import re

zero_width_space = u'\u200b'
magic_space = " "
en_space = " "
tab = u"\u0009"

def embed_list_lines(embed,
                     lines,
                     field_name,
                     max_characters=1024,
                     inline=False):
    value = "\n".join(lines)
    if len(value) > max_characters:
        value = ""
        values = []
        for line in lines:
            if len(value) + len(line) > max_characters:
                values.append(value)
                value = ""
            value += line + "\n"
        if value:
            values.append(value)
        embed.add_field(name=field_name, value=values[0], inline=inline)
        for v in values[1:]:
            embed.add_field(name=zero_width_space, value=v, inline=inline)
    else:
        embed.add_field(name=field_name, value=value, inline=inline)
    return embed


def cleanup_xml_tags(text):
    return re.sub("<[^<]+>", "", text)
