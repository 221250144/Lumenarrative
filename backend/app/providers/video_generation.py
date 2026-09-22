"""HappyHorse asynchronous API. A submission is deliberately never retried here."""
import base64
import hashlib
import ipaddress
import re
import socket
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit, urljoin

import httpx

from app.config import settings


class GenerationError(ValueError):
    """Only safe, user-facing messages; never retain provider bodies or signed URLs."""


class SubmissionRejected(GenerationError):
    """A definitive HTTP rejection; safe to create a fresh task after correction."""


def generation_base_url():
    base = settings.video_generation_base_url.strip().rstrip("/")
    if not base:
        base = settings.model_base_url.rstrip("/")
        if not base.endswith("/compatible-mode/v1"):
            raise GenerationError("请配置百炼图生视频 API 地址")
        base = base.removesuffix("/compatible-mode/v1") + "/api/v1"
    parts = urlsplit(base)
    if (
        parts.scheme != "https" or not parts.hostname
        or not parts.hostname.endswith(".aliyuncs.com")
        or parts.username or parts.password or parts.query or parts.fragment
        or parts.port not in (None, 443) or parts.path != "/api/v1"
    ):
        raise GenerationError("图生视频地址须为百炼 HTTPS /api/v1 地址")
    return base


class HappyHorseProvider:
    def __init__(self):
        self.base = generation_base_url()
        if not settings.model_api_key:
            raise GenerationError("尚未配置百炼 API Key")

    def _request(self, method, path, body=None):
        headers = {"Authorization": f"Bearer {settings.model_api_key}"}
        if method == "POST":
            headers["X-DashScope-Async"] = "enable"
        try:
            with httpx.Client(timeout=60, follow_redirects=False) as client:
                response = client.request(method, self.base + path, headers=headers, json=body)
            if response.status_code != 200:
                error_type = SubmissionRejected if method == "POST" and 400 <= response.status_code < 500 and response.status_code != 408 else GenerationError
                raise error_type(f"百炼视频生成接口返回 HTTP {response.status_code}，请检查模型权限、额度和服务状态")
            data = response.json()
            output = data.get("output")
            if not isinstance(output, dict):
                raise GenerationError("百炼视频生成接口未返回有效任务信息")
            return output
        except GenerationError:
            raise
        except Exception:
            raise GenerationError("百炼视频生成连接失败；提交结果可能尚未确认，请查看任务状态") from None

    def submit(self, prompt, reference_frame: Path, duration_s, resolution):
        if reference_frame.stat().st_size > 20 * 1024 * 1024:
            raise GenerationError("参考首帧超过 20MB")
        body = {
            "model": settings.video_generation_model,
            "input": {
                "prompt": prompt,
                "media": [{
                    "type": "first_frame",
                    "url": "data:image/jpeg;base64," + base64.b64encode(reference_frame.read_bytes()).decode("ascii"),
                }],
            },
            "parameters": {"resolution": resolution, "duration": duration_s, "watermark": True},
        }
        output = self._request("POST", "/services/aigc/video-generation/video-synthesis", body)
        task_id = output.get("task_id", "")
        if not isinstance(task_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", task_id):
            raise GenerationError("百炼未返回可恢复查询的任务编号；不会自动再次提交")
        return task_id

    def query(self, task_id):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", task_id):
            raise GenerationError("视频生成任务编号无效")
        return self._request("GET", "/tasks/" + task_id)


def validate_download_url(url):
    """Accept only public Alibaba OSS result hosts, including every redirect hop."""
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
        if (
            parts.scheme != "https" or parts.username or parts.password
            or parts.port not in (None, 443) or parts.fragment
            or not host.endswith(".aliyuncs.com")
            or not any(label.startswith("oss-") for label in host.split("."))
        ):
            raise ValueError()
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
            raise ValueError()
    except Exception:
        raise GenerationError("生成结果下载地址未通过安全校验") from None
    return url


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def download_video(url, target: Path):
    """No API credentials, no HTTP client URL logging, bounded atomic download."""
    opener = urllib.request.build_opener(_NoRedirect())
    temporary = target.with_suffix(".download")
    target.parent.mkdir(parents=True, exist_ok=True)
    limit = settings.max_upload_mb * 1024 * 1024
    try:
        for _ in range(4):
            validate_download_url(url)
            request = urllib.request.Request(url, headers={"User-Agent": "Xuguangji-video-generation/1"})
            try:
                response = opener.open(request, timeout=60)
            except urllib.error.HTTPError as error:
                if error.code in (301, 302, 303, 307, 308) and error.headers.get("Location"):
                    url = urljoin(url, error.headers["Location"])
                    error.close()
                    continue
                raise GenerationError("生成视频下载失败，可重试恢复下载") from None
            with response:
                length = response.headers.get("Content-Length")
                if length and int(length) > limit:
                    raise GenerationError("生成视频超过单文件大小限制")
                size, digest = 0, hashlib.sha256()
                with temporary.open("wb") as output:
                    while chunk := response.read(1024 * 1024):
                        size += len(chunk)
                        if size > limit:
                            raise GenerationError("生成视频超过单文件大小限制")
                        output.write(chunk)
                        digest.update(chunk)
                if not size:
                    raise GenerationError("生成视频为空，请重试下载")
            temporary.replace(target)
            return digest.hexdigest()
        raise GenerationError("生成视频下载重定向次数过多")
    except GenerationError:
        raise
    except Exception:
        raise GenerationError("生成视频下载失败，可重试恢复下载") from None
    finally:
        temporary.unlink(missing_ok=True)
