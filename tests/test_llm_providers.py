"""Unit tests for the RFC-002 Phase 1 provider infrastructure.

Covers the registry contract, the built-in providers' behaviour, and
the refactored ``generate()`` delegation path. RFC-011 adds tests for
the ``OnnxGenAIBackend`` and ``LocalProvider`` backend dispatching.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from zettelforge.llm_providers import (
    LocalProvider,
    MockProvider,
    OllamaProvider,
    available,
    registry,
)
from zettelforge.llm_providers.base import LLMProvider
from zettelforge.llm_providers.local_provider import (
    LlamaCppBackend,
    OnnxGenAIBackend,
)


@pytest.fixture(autouse=True)
def reset_registry_instances():
    """Clear cached provider instances between tests.

    Registrations created when ``zettelforge.llm_providers`` is imported
    are preserved; only cached singleton instances are reset.
    """
    registry.reset()
    yield
    registry.reset()


# ---- Protocol contract -------------------------------------------------------


class TestLLMProviderProtocol:
    def test_local_satisfies_protocol(self):
        assert isinstance(LocalProvider(model="x"), LLMProvider)

    def test_ollama_satisfies_protocol(self):
        assert isinstance(OllamaProvider(model="x"), LLMProvider)

    def test_mock_satisfies_protocol(self):
        assert isinstance(MockProvider(), LLMProvider)

    def test_builtins_registered(self):
        names = available()
        assert "local" in names
        assert "ollama" in names
        assert "mock" in names


# ---- Registry ----------------------------------------------------------------


class TestRegistry:
    def test_get_returns_singleton(self):
        a = registry.get("mock")
        b = registry.get("mock")
        assert a is b

    def test_get_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            registry.get("definitely-not-a-provider")

    def test_register_duplicate_raises(self):
        with pytest.raises(ValueError, match="already registered"):
            registry.register("local", LocalProvider)

    def test_reset_clears_instances_not_registrations(self):
        registry.get("mock")
        registry.reset()
        # A fresh instance is created after reset.
        fresh = registry.get("mock")
        assert isinstance(fresh, MockProvider)
        assert "mock" in available()


# ---- MockProvider ------------------------------------------------------------


class TestMockProvider:
    def test_returns_canned_response(self):
        mock = MockProvider(responses=["hello"])
        assert mock.generate("anything") == "hello"

    def test_cycles_through_responses(self):
        mock = MockProvider(responses=["a", "b"])
        assert mock.generate("q1") == "a"
        assert mock.generate("q2") == "b"
        assert mock.generate("q3") == "a"  # cycles

    def test_records_every_call(self):
        mock = MockProvider()
        mock.generate("ask", max_tokens=10, temperature=0.5, system="sys", json_mode=True)
        assert len(mock.calls) == 1
        call = mock.calls[0]
        assert call == {
            "prompt": "ask",
            "max_tokens": 10,
            "temperature": 0.5,
            "system": "sys",
            "json_mode": True,
        }

    def test_default_response_list(self):
        mock = MockProvider()
        assert mock.generate("") == "mock response"


# ---- OllamaProvider ----------------------------------------------------------

# The ollama SDK is not a core dependency -- skip this class when it is
# unavailable (e.g. the minimal CI environment without zettelforge[local]).
pytest.importorskip("ollama", reason="ollama SDK not installed")


class TestOllamaProvider:
    """Verify OllamaProvider wraps the ollama SDK Client correctly.

    The provider instantiates ``ollama.Client(host=<url>)`` so that
    configuring ``llm.url`` actually directs requests to the intended
    server. Tests patch the ``Client`` class and inspect the call made
    on the returned instance.
    """

    def test_generate_calls_ollama_with_expected_args(self):
        provider = OllamaProvider(model="qwen2.5:3b", url="http://host:11434")
        with patch("ollama.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value
            mock_client.generate.return_value = {"response": "ok"}

            result = provider.generate(
                "hello", max_tokens=50, temperature=0.2, system="sys", json_mode=True
            )

            assert result == "ok"
            mock_client_cls.assert_called_once_with(host="http://host:11434", timeout=60.0)
            args, kwargs = mock_client.generate.call_args
            assert kwargs["model"] == "qwen2.5:3b"
            assert kwargs["prompt"] == "hello"
            assert kwargs["system"] == "sys"
            assert kwargs["format"] == "json"
            assert kwargs["options"] == {"temperature": 0.2, "num_predict": 50}

    def test_generate_omits_system_when_absent(self):
        provider = OllamaProvider(model="qwen2.5:3b")
        with patch("ollama.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value
            mock_client.generate.return_value = {"response": "ok"}
            provider.generate("hello")
            _, kwargs = mock_client.generate.call_args
            assert "system" not in kwargs
            assert "format" not in kwargs

    def test_generate_empty_response_returns_empty_string(self):
        provider = OllamaProvider(model="qwen2.5:3b")
        with patch("ollama.Client") as mock_client_cls:
            mock_client = mock_client_cls.return_value
            mock_client.generate.return_value = {}
            assert provider.generate("prompt") == ""

    def test_generate_routes_through_configured_host(self):
        """``llm.url`` is honoured via ``ollama.Client(host=...)``."""
        provider = OllamaProvider(model="qwen2.5:3b", url="http://gpu-box:11434")
        with patch("ollama.Client") as mock_client_cls:
            mock_client_cls.return_value.generate.return_value = {"response": "ok"}
            provider.generate("hello")
            mock_client_cls.assert_called_once_with(host="http://gpu-box:11434", timeout=60.0)

    def test_timeout_threads_through_to_client(self):
        """[RFC-010] Configured timeout must reach ``ollama.Client``.

        Before RFC-010, ``OllamaProvider.__init__`` dropped ``timeout`` into
        ``**_`` and the client inherited an effectively-unbounded default,
        causing the 66.5s `remember()` tail observed in the 2026-04-24
        Vigil audit.
        """
        provider = OllamaProvider(model="qwen2.5:3b", timeout=7.5)
        with patch("ollama.Client") as mock_client_cls:
            mock_client_cls.return_value.generate.return_value = {"response": "ok"}
            provider.generate("hello")
            mock_client_cls.assert_called_once_with(host="http://localhost:11434", timeout=7.5)

    def test_unknown_kwargs_ignored_at_construction(self):
        # The registry forwards kwargs meant for other providers; they
        # must be accepted silently. Note: ``timeout`` is now a first-class
        # parameter (RFC-010) but ``**_`` still absorbs anything else.
        provider = OllamaProvider(
            model="qwen2.5:3b",
            api_key="ignored",
            timeout=120.0,
            max_retries=5,
        )
        assert provider.name == "ollama"


# ---- LlamaCppBackend (RFC-011) -----------------------------------------------


class TestLlamaCppBackend:
    def test_constructs_with_defaults(self):
        backend = LlamaCppBackend()
        assert backend._model_id == "Qwen/Qwen2.5-3B-Instruct-GGUF"
        assert backend._filename == "qwen2.5-3b-instruct-q4_k_m.gguf"
        assert backend._n_ctx == 4096

    def test_constructs_with_custom_values(self):
        backend = LlamaCppBackend(
            model="org/custom-model",
            filename="custom-q4.gguf",
            n_ctx=8192,
        )
        assert backend._model_id == "org/custom-model"
        assert backend._filename == "custom-q4.gguf"
        assert backend._n_ctx == 8192

    def test_unknown_kwargs_ignored(self):
        backend = LlamaCppBackend(
            model="x",
            api_key="ignored",
            timeout=120.0,
        )
        assert backend.name == "llama-cpp-python"

    def test_json_mode_appends_instruction_when_no_system(self):
        backend = LlamaCppBackend()
        fake_llm = _FakeLlamaCpp()
        backend._llm = fake_llm
        backend.generate("prompt", json_mode=True)
        messages = fake_llm.last_messages
        assert messages[0]["role"] == "system"
        assert "JSON" in messages[0]["content"]

    def test_json_mode_extends_existing_system(self):
        backend = LlamaCppBackend()
        fake_llm = _FakeLlamaCpp()
        backend._llm = fake_llm
        backend.generate("prompt", system="Base prompt.", json_mode=True)
        system = fake_llm.last_messages[0]["content"]
        assert system.startswith("Base prompt.")
        assert "JSON" in system

    def test_generate_strips_output(self):
        backend = LlamaCppBackend()
        fake_llm = _FakeLlamaCpp()
        backend._llm = fake_llm
        result = backend.generate("hello")
        assert result == "out"  # _FakeLlamaCpp returns "  out  "

    def test_cannot_set_llm_on_not_initialized(self):
        """_llm setter raises if backend has no _llm attribute."""
        backend = LlamaCppBackend()
        backend._llm = _FakeLlamaCpp()
        assert backend._llm is not None


# ---- OnnxGenAIBackend (RFC-011) ----------------------------------------------


class _FakeOnnxGenAI:
    """Minimal stand-in for onnxruntime_genai module used by OnnxGenAIBackend tests."""

    class Model:
        @classmethod
        def from_pretrained(cls, repo_id, filename=None, provider=None):
            return cls()

    class Tokenizer:
        def __init__(self, model):
            self.model = model
            self.eos_token_id = 2

        def encode(self, text):
            # Return a fake token list: number of tokens based on length
            return list(range(10))

        def decode(self, tokens):
            return "decoded output"

    class GeneratorParams:
        def __init__(self, model):
            self.model = model
            self.input_ids = None

        def set_search_options(self, max_length, temperature):
            self.max_length = max_length
            self.temperature = temperature

    class Generator:
        def __init__(self, model, params):
            self.model = model
            self.params = params
            self._call_count = 0

        def generate_next_token(self):
            self._call_count += 1
            if self._call_count >= 5:
                return 2  # eos_token_id
            return 42

        def __del__(self):
            pass


class TestOnnxGenAIBackend:
    def test_constructs_with_defaults(self):
        backend = OnnxGenAIBackend()
        assert backend._model_id == "microsoft/Phi-3-mini-4k-instruct-onnx"
        assert backend._filename == "phi3-mini-4k-instruct-q4.onnx"
        assert backend._n_ctx == 4096
        assert backend._provider == "cpu"

    def test_constructs_with_custom_values(self):
        backend = OnnxGenAIBackend(
            model="org/onnx-model",
            filename="model-q4.onnx",
            n_ctx=8192,
            provider="rocm",
        )
        assert backend._model_id == "org/onnx-model"
        assert backend._filename == "model-q4.onnx"
        assert backend._n_ctx == 8192
        assert backend._provider == "rocm"

    def test_unknown_kwargs_ignored(self):
        backend = OnnxGenAIBackend(
            model="x",
            api_key="ignored",
            timeout=120.0,
        )
        assert backend.name == "onnxruntime-genai"

    def test_generate_with_mock_sdk(self, monkeypatch):
        backend = OnnxGenAIBackend(model="test/model", filename="test.onnx")

        # Patch the onnxruntime_genai module at import time in _load()
        import types
        fake_module = types.ModuleType("onnxruntime_genai")
        fake_module.Model = _FakeOnnxGenAI.Model
        fake_module.Tokenizer = _FakeOnnxGenAI.Tokenizer
        fake_module.GeneratorParams = _FakeOnnxGenAI.GeneratorParams
        fake_module.Generator = _FakeOnnxGenAI.Generator
        monkeypatch.setitem(__import__("sys").modules, "onnxruntime_genai", fake_module)

        result = backend.generate("hello", max_tokens=100)
        assert result == "decoded output"

    def test_generate_with_system_prompt(self, monkeypatch):
        backend = OnnxGenAIBackend(model="test/model", filename="test.onnx")

        import types
        fake_module = types.ModuleType("onnxruntime_genai")
        fake_module.Model = _FakeOnnxGenAI.Model
        fake_module.Tokenizer = _FakeOnnxGenAI.Tokenizer
        fake_module.GeneratorParams = _FakeOnnxGenAI.GeneratorParams
        fake_module.Generator = _FakeOnnxGenAI.Generator
        monkeypatch.setitem(__import__("sys").modules, "onnxruntime_genai", fake_module)

        result = backend.generate(
            "hello", max_tokens=100, system="You are a helpful assistant."
        )
        assert result == "decoded output"

    def test_import_error_raised_when_sdk_missing(self):
        backend = OnnxGenAIBackend(model="test/model", filename="test.onnx")
        with pytest.raises(ImportError, match="onnxruntime-genai"):
            backend.generate("hello")

    def test_name_property(self):
        backend = OnnxGenAIBackend()
        assert backend.name == "onnxruntime-genai"


# ---- LiteLLMProvider (RFC-012) -------------------------------------------------


class _FakeLiteLLM:
    """Minimal stand-in for the litellm module used by LiteLLMProvider tests."""

    @staticmethod
    def completion(
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
        timeout: float,
        num_retries: int,
        **kwargs: object,
    ) -> dict:
        return {
            "choices": [{"message": {"content": "  lorem ipsum  "}}],
            "model": model,
        }


class TestLiteLLMProvider:
    def test_constructs_with_defaults(self):
        from zettelforge.llm_providers.litellm_provider import LiteLLMProvider

        provider = LiteLLMProvider()
        assert provider._model == "gpt-4o-mini"
        assert provider._api_key == ""
        assert provider._timeout == 60.0
        assert provider._max_retries == 2

    def test_constructs_with_custom_values(self):
        from zettelforge.llm_providers.litellm_provider import LiteLLMProvider

        provider = LiteLLMProvider(
            model="claude-sonnet-4-20250514",
            api_key="sk-test",
            timeout=120.0,
            max_retries=5,
        )
        assert provider._model == "claude-sonnet-4-20250514"
        assert provider._api_key == "sk-test"
        assert provider._timeout == 120.0
        assert provider._max_retries == 5

    def test_unknown_kwargs_ignored(self):
        from zettelforge.llm_providers.litellm_provider import LiteLLMProvider

        provider = LiteLLMProvider(
            model="gpt-4o",
            url="ignored",
            filename="ignored",
        )
        assert provider.name == "litellm"

    def test_name_property(self):
        from zettelforge.llm_providers.litellm_provider import LiteLLMProvider

        assert LiteLLMProvider().name == "litellm"

    def test_import_error_raised_when_sdk_missing(self):
        from zettelforge.llm_providers.litellm_provider import LiteLLMProvider

        provider = LiteLLMProvider(model="gpt-4o")
        with pytest.raises(ImportError, match="litellm"):
            provider.generate("hello")

    def test_generate_with_mock_completion(self, monkeypatch):
        from zettelforge.llm_providers.litellm_provider import LiteLLMProvider

        import types
        mock_module = types.ModuleType("litellm")
        mock_module.completion = _FakeLiteLLM.completion
        monkeypatch.setitem(__import__("sys").modules, "litellm", mock_module)

        provider = LiteLLMProvider(model="gpt-4o-mini")
        result = provider.generate("hello")
        assert result == "lorem ipsum"

    def test_generate_passes_api_key(self, monkeypatch):
        from zettelforge.llm_providers.litellm_provider import LiteLLMProvider

        import types

        calls: list[dict] = []

        def _completion(**kwargs: object) -> dict:
            calls.append(kwargs)
            return {"choices": [{"message": {"content": "ok"}}]}

        mock_module = types.ModuleType("litellm")
        mock_module.completion = _completion
        monkeypatch.setitem(__import__("sys").modules, "litellm", mock_module)

        provider = LiteLLMProvider(model="gpt-4o", api_key="sk-test-key")
        provider.generate("hello")
        assert len(calls) == 1
        assert calls[0]["api_key"] == "sk-test-key"

    def test_generate_passes_system_prompt(self, monkeypatch):
        from zettelforge.llm_providers.litellm_provider import LiteLLMProvider

        import types

        calls: list[dict] = []

        def _completion(**kwargs: object) -> dict:
            calls.append(kwargs)
            return {"choices": [{"message": {"content": "ok"}}]}

        mock_module = types.ModuleType("litellm")
        mock_module.completion = _completion
        monkeypatch.setitem(__import__("sys").modules, "litellm", mock_module)

        provider = LiteLLMProvider(model="gpt-4o")
        provider.generate("hello", system="You are a helpful assistant.")
        assert len(calls) == 1
        messages = calls[0]["messages"]
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "You are a helpful assistant."
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == "hello"

    def test_generate_passes_json_mode(self, monkeypatch):
        from zettelforge.llm_providers.litellm_provider import LiteLLMProvider

        import types

        calls: list[dict] = []

        def _completion(**kwargs: object) -> dict:
            calls.append(kwargs)
            return {"choices": [{"message": {"content": '{"key": "value"}'}}]}

        mock_module = types.ModuleType("litellm")
        mock_module.completion = _completion
        monkeypatch.setitem(__import__("sys").modules, "litellm", mock_module)

        provider = LiteLLMProvider(model="gpt-4o")
        result = provider.generate("hello", json_mode=True)
        assert len(calls) == 1
        assert calls[0]["response_format"] == {"type": "json_object"}
        assert result == '{"key": "value"}'

    def test_generate_omits_api_key_when_empty(self, monkeypatch):
        from zettelforge.llm_providers.litellm_provider import LiteLLMProvider

        import types

        calls: list[dict] = []

        def _completion(**kwargs: object) -> dict:
            calls.append(kwargs)
            return {"choices": [{"message": {"content": "ok"}}]}

        mock_module = types.ModuleType("litellm")
        mock_module.completion = _completion
        monkeypatch.setitem(__import__("sys").modules, "litellm", mock_module)

        provider = LiteLLMProvider(model="gpt-4o")  # no api_key
        provider.generate("hello")
        assert "api_key" not in calls[0]

    def test_satisfies_llm_provider_protocol(self):
        from zettelforge.llm_providers.litellm_provider import LiteLLMProvider

        assert isinstance(LiteLLMProvider(model="x"), LLMProvider)

    def test_litellm_provider_registered(self):
        # litellm may not be installed, but the registration attempt
        # at import time in __init__.py should be graceful.
        names = available()
        # If SDK is available, litellm should be in the list.
        # If not, it's silently skipped — no crash.
        import importlib

        try:
            importlib.import_module("litellm")
            assert "litellm" in names
        except ImportError:
            assert "litellm" not in names


# ---- LocalProvider dispatching (RFC-011) --------------------------------------


class TestLocalProviderBackendDispatching:
    def test_default_backend_is_llama_cpp(self):
        provider = LocalProvider()
        impl = provider._get_impl()
        assert isinstance(impl, LlamaCppBackend)

    def test_onnxruntime_backend_selected(self):
        provider = LocalProvider(backend="onnxruntime-genai")
        impl = provider._get_impl()
        assert isinstance(impl, OnnxGenAIBackend)

    def test_explicit_llama_cpp_backend(self):
        provider = LocalProvider(backend="llama-cpp-python")
        impl = provider._get_impl()
        assert isinstance(impl, LlamaCppBackend)

    def test_generate_delegates_to_llama_cpp(self):
        provider = LocalProvider()
        fake_llm = _FakeLlamaCpp()
        # Inject fake via backward-compat _llm setter
        provider._llm = fake_llm
        result = provider.generate("hello")
        assert result == "out"

    def test_unknown_kwargs_ignored_at_construction(self):
        provider = LocalProvider(
            model="Qwen/Qwen2.5-3B-Instruct-GGUF",
            filename="qwen2.5-3b-instruct-q4_k_m.gguf",
            api_key="ignored",
            timeout=120.0,
        )
        assert provider.name == "local"

    def test_json_mode_appends_instruction_when_no_system(self):
        provider = LocalProvider()
        fake_llm = _FakeLlamaCpp()
        provider._llm = fake_llm
        provider.generate("prompt", json_mode=True)
        messages = fake_llm.last_messages
        assert messages[0]["role"] == "system"
        assert "JSON" in messages[0]["content"]

    def test_json_mode_extends_existing_system(self):
        provider = LocalProvider()
        fake_llm = _FakeLlamaCpp()
        provider._llm = fake_llm
        provider.generate("prompt", system="Base prompt.", json_mode=True)
        system = fake_llm.last_messages[0]["content"]
        assert system.startswith("Base prompt.")
        assert "JSON" in system


# ---- generate() delegation (llm_client) --------------------------------------


class TestGenerateDelegatesToProvider:
    def test_generate_uses_configured_provider(self):
        from zettelforge.llm_client import generate

        canned = MockProvider(responses=["from mock"])
        with patch.dict(os.environ, {"ZETTELFORGE_LLM_PROVIDER": "mock"}):
            with patch("zettelforge.llm_providers.registry.get", return_value=canned):
                result = generate("hi")
        assert result == "from mock"
        assert canned.calls[0]["prompt"] == "hi"

    def test_generate_returns_empty_on_recoverable_failure(self):
        from zettelforge.llm_client import generate

        class _Flaky:
            name = "flaky"

            def generate(self, *a, **kw):  # noqa: D401 -- test stub
                raise RuntimeError("transient")

        with patch.dict(
            os.environ,
            {"ZETTELFORGE_LLM_PROVIDER": "flaky", "ZETTELFORGE_LLM_FALLBACK": ""},
        ):
            with patch(
                "zettelforge.llm_providers.registry.get",
                side_effect=[_Flaky(), _Flaky()],
            ):
                # No fallback configured + primary="flaky" is not "local",
                # so the implicit fallback also does not kick in.
                result = generate("hi")
        assert result == ""

    def test_generate_propagates_import_error(self):
        from zettelforge.llm_client import generate

        with patch.dict(os.environ, {"ZETTELFORGE_LLM_PROVIDER": "local"}):
            with patch(
                "zettelforge.llm_providers.registry.get",
                side_effect=ImportError("missing sdk"),
            ):
                with pytest.raises(ImportError):
                    generate("hi")


# ---- Config (RFC-002 extensions) ---------------------------------------------


class TestLLMConfigRepr:
    def test_api_key_is_redacted(self):
        from zettelforge.config import LLMConfig

        cfg = LLMConfig(api_key="***")
        text = repr(cfg)
        assert "***" not in text
        assert "***" in text

    def test_empty_api_key_shows_empty_string(self):
        from zettelforge.config import LLMConfig

        cfg = LLMConfig()
        assert "api_key=''" in repr(cfg)


class TestEnvRefResolution:
    def test_resolves_env_var(self, monkeypatch):
        from zettelforge.config import _resolve_env_refs

        monkeypatch.setenv("MY_TEST_KEY", "sk-abc")
        assert _resolve_env_refs("${MY_TEST_KEY}") == "sk-abc"

    def test_missing_env_var_becomes_empty(self, monkeypatch):
        from zettelforge.config import _resolve_env_refs

        monkeypatch.delenv("DEFINITELY_NOT_SET_9X", raising=False)
        assert _resolve_env_refs("${DEFINITELY_NOT_SET_9X}") == ""

    def test_literal_strings_unchanged(self):
        from zettelforge.config import _resolve_env_refs

        assert _resolve_env_refs("plain") == "plain"
        assert _resolve_env_refs("") == ""


# ---- Test helpers ------------------------------------------------------------


class _FakeLlamaCpp:
    """Minimal stand-in for llama_cpp.Llama used by LocalProvider tests."""

    def __init__(self) -> None:
        self.last_messages: list[dict[str, str]] = []

    def create_chat_completion(
        self,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
    ) -> dict:
        self.last_messages = messages
        return {"choices": [{"message": {"content": "  out  "}}]}
