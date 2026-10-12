"""Builds world.json (the map and the country lookup) from Natural Earth's
public-domain 1:110m land and country outlines. Run once by hand; the plugin only
reads the result.

    curl -LO https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_land.geojson
    curl -LO https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_admin_0_countries.geojson
    python tools/make_world.py ne_110m_land.geojson ne_110m_admin_0_countries.geojson > world.json
"""
import json
import sys

from PIL import Image, ImageDraw

NORTH, SOUTH = 78, -58          # the map leaves out the poles: the station never goes past 52°
SHORT = {"United States of America": "United States", "Dem. Rep. Congo": "DR Congo",
         "Central African Rep.": "Central Africa", "Bosnia and Herz.": "Bosnia", "Dominican Rep.": "Dominican Rep",
         "Eq. Guinea": "Equatorial Guinea", "S. Sudan": "South Sudan", "W. Sahara": "Western Sahara",
         "Solomon Is.": "Solomon Islands", "Falkland Is.": "Falklands", "Fr. S. Antarctic Lands": "Kerguelen",
         "N. Cyprus": "Cyprus", "Côte d'Ivoire": "Ivory Coast", "Timor-Leste": "East Timor"}


def polygons(feature):
    geometry = feature["geometry"]
    return geometry["coordinates"] if geometry["type"] == "MultiPolygon" else [geometry["coordinates"]]


def land(path, width=64, height=32, k=10):
    image = Image.new("L", (width * k, height * k))
    draw = ImageDraw.Draw(image)
    xy = lambda lon, lat: ((lon + 180) / 360 * width * k, (NORTH - lat) / (NORTH - SOUTH) * height * k)
    for feature in json.load(open(path))["features"]:
        for polygon in polygons(feature):
            draw.polygon([xy(*point) for point in polygon[0]], fill=255)
            for hole in polygon[1:]:
                draw.polygon([xy(*point) for point in hole], fill=0)
    small = image.resize((width, height), Image.BOX)
    return ["".join("#" if small.getpixel((x, y)) > 100 else "." for x in range(width)) for y in range(height)]


def countries(path, k=4):
    """A 1° grid (360 × 180, north-west first): each cell the country under its middle, run-length coded."""
    image = Image.new("I", (360 * k, 180 * k))
    draw = ImageDraw.Draw(image)
    names = []
    xy = lambda lon, lat: ((lon + 180) * k, (90 - lat) * k)
    for feature in json.load(open(path))["features"]:
        name = feature["properties"]["NAME"]
        if name == "Antarctica":
            continue
        names.append(SHORT.get(name, name))
        for polygon in polygons(feature):
            draw.polygon([xy(*point) for point in polygon[0]], fill=len(names))
    small = image.resize((360, 180), Image.NEAREST)
    rows = []
    for y in range(180):
        runs, last, count = [], None, 0
        for x in range(360):
            value = small.getpixel((x, y))
            if value == last:
                count += 1
            else:
                if last is not None:
                    runs.append(f"{last}x{count}")
                last, count = value, 1
        runs.append(f"{last}x{count}")
        rows.append(",".join(runs))
    return names, rows


if __name__ == "__main__":
    names, rows = countries(sys.argv[2])
    json.dump({"source": "Natural Earth 1:110m (public domain)", "map_north": NORTH, "map_south": SOUTH,
               "land": land(sys.argv[1]), "names": names, "countries": rows}, sys.stdout, separators=(",", ":"))
