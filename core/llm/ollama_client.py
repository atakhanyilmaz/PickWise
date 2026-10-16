"""Small loopback-only Ollama client. No downloads or generated-code execution."""

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import ProxyHandler, Request, build_opener

from pydantic import BaseModel, ValidationError


class ModelUnavailable(RuntimeError):
    pass


class InvalidModelOutput(ValueError):
    pass


class OllamaClient:
    def __init__(
        self, model="gemma4:e2b", base_url="http://127.0.0.1:11434", timeout=120
    ):
        url = urlparse(base_url)
        if (
            url.scheme != "http"
            or url.hostname not in ("127.0.0.1", "localhost", "::1")
            or url.username
            or url.password
            or url.query
            or url.fragment
            or url.path not in ("", "/")
        ):
            raise ValueError("Only local loopback Ollama endpoints are supported")
        self.model, self.base_url, self.timeout = model, base_url.rstrip("/"), timeout
        self._metadata = None

    def _request(self, path, payload=None):
        body = json.dumps(payload).encode() if payload is not None else None
        request = Request(
            self.base_url + path,
            data=body,
            headers={"Content-Type": "application/json"},
        )
        try:
            with build_opener(ProxyHandler({})).open(
                request, timeout=self.timeout
            ) as response:
                return json.load(response)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            raise ModelUnavailable(
                f"Local Ollama request failed: {type(exc).__name__}"
            ) from exc

    def metadata(self):
        if self._metadata is None:
            tags = self._request("/api/tags").get("models", [])
            tag = next(
                (
                    item
                    for item in tags
                    if item.get("name") == self.model or item.get("model") == self.model
                ),
                None,
            )
            if tag is None:
                raise ModelUnavailable(f"Model is not installed: {self.model}")
            show = self._request("/api/show", {"model": self.model})
            if (
                show.get("remote_host")
                or show.get("remote_model")
                or tag.get("remote_host")
            ):
                raise ModelUnavailable("Cloud-backed models are not supported")
            details, info = show.get("details", {}), show.get("model_info", {})
            architecture = info.get("general.architecture", details.get("family", ""))
            if "gemma" not in architecture.lower():
                raise ModelUnavailable("Configured model is not identified as Gemma")
            self._metadata = {
                "model_tag": self.model,
                "model_digest": tag.get("digest"),
                "architecture": architecture,
                "quantization": details.get("quantization_level"),
                "parameter_size": details.get("parameter_size"),
                "ollama_version": self._request("/api/version").get("version"),
                "runtime": "ollama",
                "endpoint": self.base_url,
                "temperature": 0,
                "seed": 0,
                "num_ctx": 8192,
                "think": False,
            }
        return dict(self._metadata)

    def structured(
        self, schema: type[BaseModel], system: str, data: dict, prompt_version: str
    ):
        metadata = self.metadata()
        metadata["prompt_version"] = prompt_version
        metadata["output_mode"] = "json_with_pydantic_validation"
        response = self._request(
            "/api/chat",
            {
                "model": self.model,
                "stream": False,
                "think": False,
                "format": "json",
                "messages": [
                    {
                        "role": "system",
                        "content": system
                        + "\nYanıt JSON şeması:\n"
                        + json.dumps(schema.model_json_schema(), ensure_ascii=False),
                    },
                    {"role": "user", "content": json.dumps(data, ensure_ascii=False)},
                ],
                "options": {
                    "temperature": 0,
                    "seed": 0,
                    "num_ctx": 8192,
                    "num_predict": 1400,
                },
                "keep_alive": "5m",
            },
        )
        if not response.get("done") or response.get("done_reason") == "length":
            raise InvalidModelOutput("Model response did not finish")
        try:
            parsed = schema.model_validate_json(response["message"]["content"])
        except (KeyError, TypeError, ValidationError) as exc:
            raise InvalidModelOutput(
                f"Model response violates the output schema: {exc}"
            ) from exc
        metadata.update(
            {
                key: response.get(key)
                for key in ("total_duration", "prompt_eval_count", "eval_count")
            }
        )
        return parsed, metadata
