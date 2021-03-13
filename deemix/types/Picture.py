class Picture:
    def __init__(self, md5="", type="", url=None):
        self.md5 = md5
        self.type = type
        self.staticUrl = url

    def generatePictureURL(self, size, format):
        if self.staticUrl: return self.staticUrl

        url = "https://e-cdns-images.dzcdn.net/images/{}/{}/{}x{}".format(
            self.type,
            self.md5,
            size, size
        )

        if format.startswith("jpg"):
            if '-' in format:
                quality = format[4:]
            else:
                quality = 80
            format = 'jpg'
            return url + f'-000000-{quality}-0-0.jpg'
        if format == 'png':
            return url + '-none-100-0-0.png'

        return url+'.jpg'
