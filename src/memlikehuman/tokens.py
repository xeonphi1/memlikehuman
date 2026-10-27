"""Budget only the returned context string, never claim to budget the host conversation."""


class TokenCounter:
    def __init__(self, model: str | None = None):
        self.encoding = None
        if model:
            try:
                import tiktoken

                self.encoding = tiktoken.encoding_for_model(model)
            except (ImportError, KeyError, OSError, ValueError):
                pass
        self.method = (
            "exact_text_tokenizer" if self.encoding else "conservative_utf8_bytes_estimate"
        )

    def count(self, text: str) -> int:
        if self.encoding:
            return len(self.encoding.encode(text, disallowed_special=()))
        # Deliberately conservative for CJK and unknown models; not a universal tokenizer guarantee.
        return len(text.encode("utf-8"))
