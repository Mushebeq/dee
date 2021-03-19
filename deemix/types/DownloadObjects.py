class IDownloadObject:
    def __init__(self, type=None, id=None, bitrate=None, title=None, artist=None, cover=None, explicit=False, size=None, dictItem=None):
        if dictItem:
            self.type = dictItem['type']
            self.id = dictItem['id']
            self.bitrate = dictItem['bitrate']
            self.title = dictItem['title']
            self.artist = dictItem['artist']
            self.cover = dictItem['cover']
            self.explicit = dictItem.get('explicit', False)
            self.size = dictItem['size']
            self.downloaded = dictItem['downloaded']
            self.failed = dictItem['failed']
            self.progress = dictItem['progress']
            self.errors = dictItem['errors']
            self.files = dictItem['files']
        else:
            self.type = type
            self.id = id
            self.bitrate = bitrate
            self.title = title
            self.artist = artist
            self.cover = cover
            self.explicit = explicit
            self.size = size
            self.downloaded = 0
            self.failed = 0
            self.progress = 0
            self.errors = []
            self.files = []
        self.uuid = f"{self.type}_{self.id}_{self.bitrate}"
        self.ack = None
        self.__type__ = None

    def toDict(self):
        return {
            'type': self.type,
            'id': self.id,
            'bitrate': self.bitrate,
            'uuid': self.uuid,
            'title': self.title,
            'artist': self.artist,
            'cover': self.cover,
            'explicit': self.explicit,
            'size': self.size,
            'downloaded': self.downloaded,
            'failed': self.failed,
            'progress': self.progress,
            'errors': self.errors,
            'files': self.files,
            'ack': self.ack,
            '__type__': self.__type__
        }

    def getResettedDict(self):
        item = self.toDict()
        item['downloaded'] = 0
        item['failed'] = 0
        item['progress'] = 0
        item['errors'] = []
        item['files'] = []
        return item

    def getSlimmedDict(self):
        light = self.toDict()
        propertiesToDelete = ['single', 'collection', 'convertable']
        for property in propertiesToDelete:
            if property in light:
                del light[property]
        return light

class Single(IDownloadObject):
    def __init__(self, type=None, id=None, bitrate=None, title=None, artist=None, cover=None, explicit=False, trackAPI_gw=None, trackAPI=None, albumAPI=None, dictItem=None):
        if dictItem:
            super().__init__(dictItem=dictItem)
            self.single = dictItem['single']
        else:
            super().__init__(type, id, bitrate, title, artist, cover, explicit, 1)
            self.single = {
                'trackAPI_gw': trackAPI_gw,
                'trackAPI': trackAPI,
                'albumAPI': albumAPI
            }
        self.__type__ = "Single"

    def toDict(self):
        item = super().toDict()
        item['single'] = self.single
        return item

class Collection(IDownloadObject):
    def __init__(self, type=None, id=None, bitrate=None, title=None, artist=None, cover=None, explicit=False, size=None, tracks_gw=None, albumAPI=None, playlistAPI=None, dictItem=None):
        if dictItem:
            super().__init__(dictItem=dictItem)
            self.collection = dictItem['collection']
        else:
            super().__init__(type, id, bitrate, title, artist, cover, explicit, size)
            self.collection = {
                'tracks_gw': tracks_gw,
                'albumAPI': albumAPI,
                'playlistAPI': playlistAPI
            }
        self.__type__ = "Collection"

    def toDict(self):
        item = super().toDict()
        item['collection'] = self.collection
        return item

class Convertable(Collection):
    def __init__(self, type=None, id=None, bitrate=None, title=None, artist=None, cover=None, explicit=False, size=None, plugin=None, conversion_data=None, dictItem=None):
        if dictItem:
            super().__init__(dictItem=dictItem)
            self.plugin = dictItem['plugin']
            self.conversion_data = dictItem['conversion_data']
        else:
            super().__init__(type, id, bitrate, title, artist, cover, explicit, size)
            self.plugin = plugin
            self.conversion_data = conversion_data
        self.__type__ = "Convertable"

    def toDict(self):
        item = super().toDict()
        item['plugin'] = self.plugin
        item['conversion_data'] = self.conversion_data
        return item
