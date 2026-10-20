"""
The LLM backend: the only code that talks to a language model.

Everything else (prompt.py, the evals) uses the small LLMBackend interface:

    backend.check()                       is the model ready? (BackendUnavailable if not)
    backend.generate_spec(sentence, previous_errors=None, previous_output=None, reference=None)
                                          one LLM call -> Reply (raw JSON text + token counts)
    backend.load() / backend.release()    load the model / free its (GPU) memory

The system prompt (prompts/spec_writer.md) and the JSON schema the reply must
follow are built here once, for every backend. A backend only implements how
to send messages and a schema to its model (_chat). Only Ollama, running
locally, is implemented.

Standard library only: no SDKs, no API keys.
"""

import json
import os
import time
import urllib.error
import urllib.request

import spec

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
SYSTEM_PROMPT_PATH = os.path.join(PROJECT_DIR, "prompts", "spec_writer.md")

DEFAULT_MODEL = "qwen3:8b"

# The spec fields the LLM writes: what is in the shot. The render settings
# (colour_mode, lighting, resolution, samples) keep their defaults.
LLM_FIELDS = ("description", "box", "background_colour", "camera")
# The LLM may leave these out. It sets the backdrop only when the sentence
# names one; otherwise code sets a neutral one (grounding.neutral_backdrop).
LLM_OPTIONAL = ("background_colour",)

# Sent back to the model when its spec fails validation.
FIX_REQUEST = (
    "Your JSON failed validation:\n{errors}\n"
    "Reply with the complete corrected JSON object. Fix only these problems "
    "and keep everything else the same."
)


class BackendUnavailable(Exception):
    """The model can't be used right now. The message says how to fix it."""


class Reply:
    """One LLM call: the raw text it returned, plus what it cost."""

    def __init__(self, text, prompt_tokens=None, output_tokens=None, seconds=0.0,
                 load_seconds=0.0, note=None):
        self.text = text
        self.prompt_tokens = prompt_tokens
        self.output_tokens = output_tokens
        self.seconds = seconds            # wall-clock time of the call
        self.load_seconds = load_seconds  # part of that spent loading the model
        self.note = note                  # anything unusual, for the log


def output_schema():
    """The JSON schema the LLM's reply must follow.

    The "spec" part comes straight from spec.FIELDS, the same table the
    validator uses. The model decides is_box, shape and unsupported first, so
    it has already set aside what it can't render before it writes the spec.
    """
    return {
        "type": "object",
        "properties": {
            "is_box": {
                "type": "boolean",
                "description": "false if the main object is clearly not a box (a bottle, jar, tube, ...).",
            },
            "shape": {
                "type": "string",
                "description": 'The real shape of the main object, in one or two words: "box" for any '
                               'box, carton or case; otherwise e.g. "bottle", "jar", "tube", "can".',
            },
            "unsupported": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Everything requested that the renderer can't draw, a few words each.",
            },
            "spec": spec.json_schema(only=LLM_FIELDS, optional=LLM_OPTIONAL),
        },
        "required": ["is_box", "shape", "unsupported", "spec"],
        "additionalProperties": False,
    }


def system_prompt():
    with open(SYSTEM_PROMPT_PATH, encoding="utf-8") as f:
        template = f.read()
    return template.replace("<<SCHEMA>>", json.dumps(output_schema(), indent=1))


class LLMBackend:
    name = "base"

    def __init__(self, model):
        self.model = model

    def generate_spec(self, sentence, previous_errors=None, previous_output=None, reference=None):
        """Ask the model for a spec. On a retry, pass its previous reply and the
        exact validation errors so it can fix them. `reference` is the
        grounding block (table rows for this sentence); it goes in the user
        message after the sentence, so the system prompt stays the same for
        every sentence. Returns a Reply."""
        request = f"{sentence}\n\n{reference}" if reference else sentence
        messages = [
            {"role": "system", "content": system_prompt()},
            {"role": "user", "content": request},
        ]
        if previous_errors:
            errors = "\n".join(f"- {e}" for e in previous_errors)
            messages += [
                {"role": "assistant", "content": previous_output or ""},
                {"role": "user", "content": FIX_REQUEST.format(errors=errors)},
            ]
        return self._chat(messages, output_schema())

    def describe(self):
        """A short line for the terminal, e.g. 'qwen3:8b via Ollama (local)'."""
        return self.model

    def settings(self):
        """Generation settings, recorded in log.json."""
        return {}

    def check(self):
        pass

    def load(self):
        """Load the model ahead of time. Returns seconds spent loading."""
        return 0.0

    def release(self):
        """Free the model's memory. Returns True once it is gone."""
        return True

    def _chat(self, messages, schema):
        raise NotImplementedError


class OllamaBackend(LLMBackend):
    """A model served by Ollama on this machine (https://ollama.com)."""

    name = "ollama"

    # 127.0.0.1 rather than localhost: on Windows "localhost" tries IPv6 first
    # and adds about 2 s to every request before falling back.
    DEFAULT_URL = "http://127.0.0.1:11434"

    TEMPERATURE = 0.2
    # Context window in tokens. Ollama silently drops the start of a prompt
    # that doesn't fit, which would cut off the system prompt, so it is set
    # explicitly and every reply is checked against it.
    NUM_CTX = 4096
    # A spec is about 200 tokens. The cap stops a runaway reply.
    NUM_PREDICT = 512
    TIMEOUT = 300  # seconds; a cold start loads ~5 GB from disk

    def __init__(self, model=DEFAULT_MODEL, url=None):
        super().__init__(model)
        self.url = (url or os.environ.get("OLLAMA_URL") or self.DEFAULT_URL).rstrip("/")
        self.can_think = None  # filled in by check()

    def describe(self):
        return f"{self.model} via Ollama (local, {self.url})"

    def settings(self):
        return {"url": self.url, "temperature": self.TEMPERATURE, "think": False,
                "num_ctx": self.NUM_CTX, "num_predict": self.NUM_PREDICT}

    def _options(self):
        # The same options on every request, so Ollama never reloads the
        # model just because the context size changed.
        return {"temperature": self.TEMPERATURE, "num_ctx": self.NUM_CTX,
                "num_predict": self.NUM_PREDICT}

    def check(self):
        self._request("GET", "/api/version", timeout=5)
        info = self._request("POST", "/api/show", {"model": self.model}, timeout=30)
        self.can_think = "thinking" in info.get("capabilities", [])

    def load(self):
        # An empty message list just loads the model.
        start = time.perf_counter()
        self._request("POST", "/api/chat", {"model": self.model, "messages": [],
                                            "options": self._options()})
        return time.perf_counter() - start

    def release(self, timeout=15):
        # keep_alive 0 tells Ollama to unload the model now. The model runner
        # can outlive the API reply, so wait until /api/ps no longer lists it.
        self._request("POST", "/api/chat", {"model": self.model, "messages": [], "keep_alive": 0})
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            loaded = self._request("GET", "/api/ps", timeout=5).get("models", [])
            if not any(m.get("name") == self.model or m.get("model") == self.model for m in loaded):
                return True
            time.sleep(0.25)
        return False

    def _chat(self, messages, schema):
        body = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            # Structured output: Ollama constrains the reply to this schema.
            "format": schema,
            "options": self._options(),
        }
        if self.can_think is not False:
            # qwen3 thinks out loud before answering by default. Turn it off:
            # only the JSON is wanted, and thinking would be slow.
            body["think"] = False
        start = time.perf_counter()
        data = self._request("POST", "/api/chat", body)
        seconds = time.perf_counter() - start

        text = data.get("message", {}).get("content", "")
        note = None
        # Belt and braces: if a model still wraps a <think> block around the
        # answer, keep only what follows it.
        if "</think>" in text:
            text = text.split("</think>", 1)[1]
            note = "removed a <think> block from the reply"
        if data.get("done_reason") == "length":
            note = f"the reply hit the {self.NUM_PREDICT}-token limit and was cut off"

        prompt_tokens = data.get("prompt_eval_count")
        if prompt_tokens and prompt_tokens > self.NUM_CTX - self.NUM_PREDICT:
            raise RuntimeError(
                f"The prompt used {prompt_tokens} of the model's {self.NUM_CTX}-token context, so "
                f"Ollama may have cut it off. Shorten prompts/spec_writer.md or raise NUM_CTX."
            )
        return Reply(
            text=text.strip(),
            prompt_tokens=prompt_tokens,
            output_tokens=data.get("eval_count"),
            seconds=seconds,
            load_seconds=data.get("load_duration", 0) / 1e9,  # Ollama reports nanoseconds
            note=note,
        )

    def _request(self, method, path, body=None, timeout=TIMEOUT):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(
            self.url + path, data=data, method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            try:
                detail = json.loads(detail).get("error", detail)
            except ValueError:
                pass
            if e.code == 404 and "not found" in detail:
                raise BackendUnavailable(
                    f"The model {self.model} isn't installed in Ollama.\n"
                    f"Download it with:  ollama pull {self.model}\n"
                    f"(Installed models: ollama list)"
                ) from None
            raise RuntimeError(f"Ollama returned an error (HTTP {e.code}): {detail}") from None
        except urllib.error.URLError as e:
            if isinstance(e.reason, TimeoutError):
                raise RuntimeError(f"Ollama didn't answer within {timeout} s.") from None
            raise BackendUnavailable(
                f"Can't reach Ollama at {self.url} ({e.reason}).\n"
                f"Ollama doesn't seem to be running. To start it, either:\n"
                f"  - open \"Ollama\" from the Start menu (it runs in the system tray), or\n"
                f"  - run  ollama serve  in another terminal and leave it open.\n"
                f"Then try again."
            ) from None
        except TimeoutError:
            raise RuntimeError(f"Ollama didn't answer within {timeout} s.") from None


class BrokenFirstReply(LLMBackend):
    """For testing the repair loop with a real model (prompt.py --break-first-reply).

    Wraps a real backend. The model's first reply is corrupted before it is
    validated: roughness is set out of range and the bevel is made far too
    big for the box. The validator rejects it, and the real model receives
    its own (corrupted) reply plus the real error messages, and must fix them.
    """

    def __init__(self, inner):
        super().__init__(inner.model)
        self.inner = inner
        self.name = inner.name
        self.calls = 0

    def generate_spec(self, sentence, previous_errors=None, previous_output=None, reference=None):
        self.calls += 1
        reply = self.inner.generate_spec(sentence, previous_errors, previous_output, reference)
        if self.calls == 1:
            data = json.loads(reply.text)
            box = data["spec"]["box"]
            box["roughness"] = 1.4
            box["bevel_cm"] = box["width_cm"]
            reply.text = json.dumps(data, indent=2)
            reply.note = "first reply corrupted on purpose (--break-first-reply)"
        return reply

    def describe(self):
        return self.inner.describe()

    def settings(self):
        return self.inner.settings()

    def check(self):
        self.inner.check()

    def load(self):
        return self.inner.load()

    def release(self):
        return self.inner.release()
