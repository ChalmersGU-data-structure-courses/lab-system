import googleapiclient.discovery


class Documents:
    default_scopes = ["documents"]

    def __init__(self, token):
        self.docs = googleapiclient.discovery.build(
            "docs", "v1", credentials=token, cache_discovery=False
        )

    def batch_update(self, id, requests):
        self.docs.documents().batchUpdate(
            documentId=id, body={"requests": requests}
        ).execute()

    @staticmethod
    def request_replace(key, value):
        return {
            "replaceAllText": {
                "containsText": {
                    "text": key,
                    "matchCase": "true",
                },
                "replaceText": value,
            }
        }

    @staticmethod
    def request_replace_image(image_id, uri):
        return {
            "replaceImage": {
                "imageObjectId": image_id,
                "uri": uri,
            }
        }
