#!/usr/bin/env python3
import re
from urllib.request import urlopen

from deemix.itemgen import generateTrackItem, generateAlbumItem, generatePlaylistItem, generateArtistItem, generateArtistDiscographyItem, generateArtistTopItem

__version__ = "2.0.16"
USER_AGENT_HEADER = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) " \
                    "Chrome/79.0.3945.130 Safari/537.36"

# Returns the Resolved URL, the Type and the ID
def parseLink(link):
    if 'deezer.page.link' in link: link = urlopen(url).url # Resolve URL shortner
    # Remove extra stuff
    if '?' in link: link = link[:link.find('?')]
    if '&' in link: link = link[:link.find('&')]
    if link.endswith('/'): link = link[:-1] #  Remove last slash if present

    type = None
    id = None

    if not 'deezer' in link: return (link, type, id) # return if not a deezer link

    if '/track' in link:
        type = 'track'
        id = re.search("\/track\/(.+)", link).group(1)
    elif '/playlist' in link:
        type = 'playlist'
        id = re.search("\/playlist\/(\d+)", link).group(1)
    elif '/album' in link:
        type = 'album'
        id = re.search("\/album\/(.+)", link).group(1)
    elif re.search("\/artist\/(\d+)\/top_track", link):
        type = 'artist_top'
        id = re.search("\/artist\/(\d+)\/top_track", link).group(1)
    elif re.search("\/artist\/(\d+)\/discography", link):
        type = 'artist_discography'
        id = re.search("\/artist\/(\d+)\/discography", link).group(1)
    elif '/artist' in link:
        type = 'artist'
        id = re.search("\/artist\/(\d+)", link).group(1)

    return (link, type, id)

def generateDownloadObject(dz, link, bitrate):
    (link, type, id) = parseLink(link)

    if type == None or id == None: return None

    if type == "track":
        return generateTrackItem(dz, id, bitrate)
    elif type == "album":
        return generateAlbumItem(dz, id, bitrate)
    elif type == "playlist":
        return generatePlaylistItem(dz, id, bitrate)
    elif type == "artist":
        return generateArtistItem(dz, id, bitrate)
    elif type == "artist_discography":
        return generateArtistDiscographyItem(dz, id, bitrate)
    elif type == "artist_top":
        return generateArtistTopItem(dz, id, bitrate)

    return None
