from typing import Protocol


class MediaSourceAdapter(Protocol):
    def capabilities(self) -> dict: ...
    def list_assets(self) -> list: ...
    def import_asset(self, external_id: str): ...


class LocalUploadAdapter:
    def capabilities(self):
        return {
            "id": "local_upload",
            "name": "本地文件上传",
            "status": "available",
            "upload": True,
            "list_assets": False,
            "import_asset": False,
        }

    def list_assets(self):
        raise NotImplementedError("通过项目素材列表查看已上传文件")

    def import_asset(self, external_id):
        raise NotImplementedError("请使用文件上传接口")


class Insta360Adapter:
    def capabilities(self):
        return {
            "id": "insta360",
            "name": "影石 SDK",
            "status": "unavailable",
            "upload": False,
            "list_assets": False,
            "import_asset": False,
            "reason": "尚未取得并验证设备、授权与兼容 SDK；影石导出视频可作为普通文件上传。",
        }

    def list_assets(self):
        raise NotImplementedError("SDK 未接入")

    def import_asset(self, external_id):
        raise NotImplementedError("SDK 未接入")
