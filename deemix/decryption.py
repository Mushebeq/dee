import binascii
from ssl import SSLError
from time import sleep

import logging

from Cryptodome.Cipher import Blowfish, AES
from Cryptodome.Hash import MD5

from requests import get
from requests.exceptions import ConnectionError as RequestsConnectionError, ReadTimeout
from urllib3.exceptions import SSLError as u3SSLError

from deemix import USER_AGENT_HEADER
from deemix.types.DownloadObjects import Single

logger = logging.getLogger('deemix')

def _md5(data):
    h = MD5.new()
    h.update(data.encode() if isinstance(data, str) else data)
    return h.hexdigest()

def generateBlowfishKey(trackId):
    SECRET = 'g4el58wc0zvf9na1'
    idMd5 = _md5(trackId)
    bfKey = ""
    for i in range(16):
        bfKey += chr(ord(idMd5[i]) ^ ord(idMd5[i + 16]) ^ ord(SECRET[i]))
    return bfKey

def generateStreamPath(sng_id, md5, media_version, media_format):
    urlPart = b'\xa4'.join(
        [md5.encode(), str(media_format).encode(), str(sng_id).encode(), str(media_version).encode()])
    md5val = _md5(urlPart)
    step2 = md5val.encode() + b'\xa4' + urlPart + b'\xa4'
    step2 = step2 + (b'.' * (16 - (len(step2) % 16)))
    urlPart = binascii.hexlify(AES.new(b'jo6aey6haid2Teih', AES.MODE_ECB).encrypt(step2))
    return urlPart.decode("utf-8")

def reverseStreamPath(urlPart):
    step2 = AES.new(b'jo6aey6haid2Teih', AES.MODE_ECB).decrypt(binascii.unhexlify(urlPart.encode("utf-8")))
    (_, md5, media_format, sng_id, media_version, _) = step2.split(b'\xa4')
    return (sng_id.decode('utf-8'), md5.decode('utf-8'), media_version.decode('utf-8'), media_format.decode('utf-8'))

def generateStreamURL(sng_id, md5, media_version, media_format):
    urlPart = generateStreamPath(sng_id, md5, media_version, media_format)
    return "https://e-cdns-proxy-" + md5[0] + ".dzcdn.net/mobile/1/" + urlPart

def generateUnencryptedStreamURL(sng_id, md5, media_version, media_format):
    urlPart = generateStreamPath(sng_id, md5, media_version, media_format)
    return "https://e-cdns-proxy-" + md5[0] + ".dzcdn.net/api/1/" + urlPart

def reverseStreamURL(url):
    urlPart = url[url.find("/1/")+3:]
    return reverseStreamPath(urlPart)

def streamUnencryptedTrack(outputStream, track, start=0, downloadObject=None, interface=None):
    headers= {'User-Agent': USER_AGENT_HEADER}
    chunkLength = start

    itemName = f"[{track.mainArtist.name} - {track.title}]"

    try:
        with get(track.downloadUrl, headers=headers, stream=True, timeout=10) as request:
            request.raise_for_status()

            complete = int(request.headers["Content-Length"])
            if complete == 0: raise DownloadEmpty
            if start != 0:
                responseRange = request.headers["Content-Range"]
                logger.info('%s downloading range %s', itemName, responseRange)
            else:
                logger.info('%s downloading %s bytes', itemName, complete)

            for chunk in request.iter_content(2048 * 3):
                outputStream.write(chunk)
                chunkLength += len(chunk)

                if downloadObject:
                    if isinstance(downloadObject, Single):
                        percentage = (chunkLength / (complete + start)) * 100
                        downloadObject.progressNext = percentage
                    else:
                        chunkProgres = (len(chunk) / (complete + start)) / downloadObject.size * 100
                        downloadObject.progressNext += chunkProgres
                    downloadObject.updateProgress(interface)

    except (SSLError, u3SSLError):
        logger.info('%s retrying from byte %s', itemName, chunkLength)
        streamUnencryptedTrack(outputStream, track, chunkLength, downloadObject, interface)
    except (RequestsConnectionError, ReadTimeout):
        sleep(2)
        streamUnencryptedTrack(outputStream, track, start, downloadObject, interface)

def streamTrack(outputStream, track, start=0, downloadObject=None, interface=None):
    headers= {'User-Agent': USER_AGENT_HEADER}
    chunkLength = start
    percentage = 0

    itemName = f"[{track.mainArtist.name} - {track.title}]"

    try:
        with get(track.downloadUrl, headers=headers, stream=True, timeout=10) as request:
            request.raise_for_status()
            blowfish_key = str.encode(generateBlowfishKey(str(track.id)))

            complete = int(request.headers["Content-Length"])
            if complete == 0: raise DownloadEmpty
            if start != 0:
                responseRange = request.headers["Content-Range"]
                logger.info('%s downloading range %s', itemName, responseRange)
            else:
                logger.info('%s downloading %s bytes', itemName, complete)

            for chunk in request.iter_content(2048 * 3):
                if len(chunk) >= 2048:
                    chunk = Blowfish.new(blowfish_key, Blowfish.MODE_CBC, b"\x00\x01\x02\x03\x04\x05\x06\x07").decrypt(chunk[0:2048]) + chunk[2048:]

                outputStream.write(chunk)
                chunkLength += len(chunk)

                if downloadObject:
                    if isinstance(downloadObject, Single):
                        percentage = (chunkLength / (complete + start)) * 100
                        downloadObject.progressNext = percentage
                    else:
                        chunkProgres = (len(chunk) / (complete + start)) / downloadObject.size * 100
                        downloadObject.progressNext += chunkProgres
                    downloadObject.updateProgress(interface)

    except (SSLError, u3SSLError):
        logger.info('%s retrying from byte %s', itemName, chunkLength)
        streamTrack(outputStream, track, chunkLength, downloadObject, interface)
    except (RequestsConnectionError, ReadTimeout):
        sleep(2)
        streamTrack(outputStream, track, start, downloadObject, interface)

class DownloadEmpty(Exception):
    pass
