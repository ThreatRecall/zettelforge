"""In-process llama-cpp-python GGUF provider (``local``).

Extracted from the previous ``llm_client._generate_local`` for RFC-002
Phase 1. Lazy-loads the GGUF model on first ``generate()`` call so the
registry can instantiate the provider without paying model-load cost at
import time.

RFC-011 adds a ``local_backend`` config option that selects between
``llama-cpp-python`` (default) and ``onnxruntime-genai`` as the in-process
inference engine via an internal ``LocalBackend`` protocol.
"""

from __future__ import annotations

import threading
from typing import Any

from zettelforge.log import get_logger

_logger = get_logger("zettelforge.llm_providers.local")

_DEFAULT_MODEL = "Qwen/Qwen2.5-3B-Instruct-GGUF"
_DEFAULT_FILENAME = "qwen2.5-3b-instruct-q4_k_m.gguf"
_DEFAULT_ONNX_MODEL = "microsoft/Phi-3-mini-4k-instruct-onnx"
_DEFAULT_ONNX_FILENAME = "phi3-mini-4k-instruct-q4.onnx"
_DEFAULT_N_CTX = 4096

_PREVIEW_CHARS = 240


# ---------------------------------------------------------------------------
# Internal backend protocol
# ---------------------------------------------------------------------------


class _LocalBackend:
    """Internal protocol for local inference backends.

    Each backend implements ``generate()`` with the same signature so
    :class:`LocalProvider` can dispatch transparently.
    """

    def generate(
        self,
        prompt: str,
        max_tokens: int = 400,
        temperature: float = 0.1,
        system: str | None = None,
        json_mode: bool = False,
    ) -> str:
        """Generate text. Returns empty string on recoverable failure."""
        ...  # pragma: no cover


# ---------------------------------------------------------------------------
# LlamaCppBackend (existing in-process GGUF)
# ---------------------------------------------------------------------------


class LlamaCppBackend(_LocalBackend):
    """llama-cpp-python GGUF backend.

    Args:
        model: HuggingFace repo id (e.g. ``"Qwen/Qwen2.5-3B-Instruct-GGUF"``).
        filename: Specific quantized file within the repo.
        n_ctx: Context window size in tokens.
        **_: Accept and ignore extra kwargs so the registry can pass
            fields like ``api_key`` or ``timeout`` that only apply to
            other providers without breaking instantiation.
    """

    name = "llama-cpp-python"

    def __init__(
        self,
        model: str = "",
        filename: str = "",
        n_ctx: int = _DEFAULT_N_CTX,
        **_: Any,
    ) -> None:
        self._model_id = model or _DEFAULT_MODEL
        self._filename = filename or _DEFAULT_FILENAME
        self._n_ctx = n_ctx
        self._llm: Any = None
        self._lock = threading.Lock()

    def _get_llm(self) -> Any:
        if self._llm is None:
            with self._lock:
                if self._llm is None:
                    try:
                        from llama_cpp import Llama
                    except ImportError as exc:
                        raise ImportError(
                            "Local LLM requires llama-cpp-python. "
                            "Install with: pip install zettelforge[local]"
                        ) from exc

                    self._llm = Llama.from_pretrained(
                        repo_id=self._model_id,
                        filename=self._filename,
                        n_ctx=self._n_ctx,
                        n_gpu_layers=0,
                        verbose=False,
                    )
                    _logger.debug("local_llm_loaded", model=self._model_id)
        return self._llm

    def generate(
        self,
        prompt: str,
        max_tokens: int = 400,
        temperature: float = 0.1,
        system: str | None = None,
        json_mode: bool = False,
    ) -> str:
        llm = self._get_llm()

        messages: list[dict[str, str]] = []
        # llama-cpp-python has no response_format; steer via system prompt.
        if json_mode:
            json_hint = "\n\nIMPORTANT: Respond with valid JSON only. No markdown, no commentary."
            system = (system + json_hint) if system else json_hint.strip()
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        output = llm.create_chat_completion(
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return str(output["choices"][0]["message"]["content"]).strip()


# ---------------------------------------------------------------------------
# OnnxGenAIBackend (in-process ONNX runtime)
# ---------------------------------------------------------------------------


class OnnxGenAIBackend(_LocalBackend):
    """ONNX Runtime GenAI backend.

    Args:
        model: HuggingFace repo id (e.g. ``"microsoft/Phi-3-mini-4k-instruct-onnx"``).
        filename: Specific ONNX model file within the repo.
        n_ctx: Context window size in tokens.
        provider: Execution provider (``"cpu"``, ``"cuda"``, ``"rocm"``,
            ``"dml"``, ``"openvino"``, ``"coreml"``). Default: ``"cpu"``.
        **_: Accept and ignore extra kwargs for registry compatibility.
    """

    name = "onnxruntime-genai"

    def __init__(
        self,
        model: str = "",
        filename: str = "",
        n_ctx: int = _DEFAULT_N_CTX,
        provider: str = "cpu",
        **_: Any,
    ) -> None:
        self._model_id = model or _DEFAULT_ONNX_MODEL
        self._filename = filename or _DEFAULT_ONNX_FILENAME
        self._n_ctx = n_ctx
        self._provider = provider
        self._model_obj: Any = None
        self._tokenizer: Any = None
        self._lock = threading.Lock()

    def _load(self) -> None:
        if self._model_obj is not None:
            return
        with self._lock:
            if self._model_obj is not None:
                return
            try:
                import onnxruntime_genai as og  # type: ignore[import-untyped]
            except ImportError as exc:
                raise ImportError(
                    "ONNX GenAI backend requires onnxruntime-genai. "
                    "Install with: pip install zettelforge[local-onnx]"
                ) from exc

            _logger.debug(
                "onnx_model_loading",
                model=self._model_id,
                filename=self._filename,
                provider=self._provider,
            )
            self._model_obj = og.Model.from_pretrained(
                self._model_id,
                filename=self._filename,
                provider=self._provider,
            )
            self._tokenizer = og.Tokenizer(self._model_obj)
            _logger.debug("onnx_model_loaded", model=self._model_id)

    def generate(
        self,
        prompt: str,
        max_tokens: int = 400,
        temperature: float = 0.1,
        system: str | None = None,
        json_mode: bool = False,
    ) -> str:
        self._load()
        import onnxruntime_genai as og  # type: ignore[import-untyped]

        # Build full prompt (ONNX GenAI has no chat template API at SDK level,
        # so we construct the prompt directly -- same approach as llama-cpp).
        full_prompt = prompt
        if system:
            full_prompt = f"{system}\n\n{full_prompt}"
        if json_mode:
            json_hint = "IMPORTANT: Respond with valid JSON only. No markdown, no commentary."
            full_prompt = f"{json_hint}\n\n{full_prompt}"

        input_ids = self._tokenizer.encode(full_prompt)

        params = og.GeneratorParams(self._model_obj)
        params.set_search_options(
            max_length=len(input_ids) + max_tokens,
            temperature=temperature,
        )
        params.input_ids = input_ids

        generator = og.Generator(self._model_obj, params)
        try:
            output_ids: list[int] = []
            for _ in range(max_tokens):
                token = generator.generate_next_token()
                if token == self._tokenizer.eos_token_id:
                    break
                output_ids.append(token)
            return self._tokenizer.decode(output_ids).strip()
        finally:
            del generator


# ---------------------------------------------------------------------------
# LocalProvider (dispatcher)
# ---------------------------------------------------------------------------


class LocalProvider:
    """In-process LLM provider that dispatches to a selected backend.

    Args:
        model: HuggingFace repo id (e.g. ``"Qwen/Qwen2.5-3B-Instruct-GGUF"``).
        filename: Specific quantized file within the repo.
        n_ctx: Context window size in tokens.
        backend: Backend engine name (``"llama-cpp-python"`` or
            ``"onnxruntime-genai"``).
        **_: Accept and ignore extra kwargs so the registry can pass
            fields like ``api_key`` or ``timeout`` that only apply to
            other providers without breaking instantiation.
    """

    name = "local"

    def __init__(
        self,
        model: str = "",
        filename: str = "",
        n_ctx: int = _DEFAULT_N_CTX,
        backend: str = "llama-cpp-python",
        **_: Any,
    ) -> None:
        self._model_id = model or _DEFAULT_MODEL
        self._filename = filename or _DEFAULT_FILENAME
        self._n_ctx = n_ctx
        self._backend_name = backend
        self._impl: _LocalBackend | None = None
        self._lock = threading.Lock()

    def _get_impl(self) -> _LocalBackend:
        if self._impl is None:
            with self._lock:
                if self._impl is None:
                    if self._backend_name == "onnxruntime-genai":
                        self._impl = OnnxGenAIBackend(
                            model=self._model_id,
                            filename=self._filename,
                            n_ctx=self._n_ctx,
                        )
                    else:
                        self._impl = LlamaCppBackend(
                            model=self._model_id,
                            filename=self._filename,
                            n_ctx=self._n_ctx,
                        )
                    _logger.debug(
                        "local_llm_backend_selected",
                        backend=self._backend_name,
                    )
        return self._impl

    # --- backward-compat shim for tests that set provider._llm directly ---

    @property
    def _llm(self) -> Any:
        impl = self._get_impl()
        if hasattr(impl, "_llm"):
            return impl._llm
        raise AttributeError(f"Backend '{self._backend_name}' has no '_llm' attribute")

    @_llm.setter
    def _llm(self, value: Any) -> None:
        impl = self._get_impl()
        if hasattr(impl, "_llm"):
            impl._llm = value
        else:
            raise AttributeError(f"Backend '{self._backend_name}' has no '_llm' attribute")

    # --- generate() ---

    def generate(
        self,
        prompt: str,
        max_tokens: int = 400,
        temperature: float = 0.1,
        system: str | None = None,
        json_mode: bool = False,
    ) -> str:
        return self._get_impl().generate(
            prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            json_mode=json_mode,
        )
