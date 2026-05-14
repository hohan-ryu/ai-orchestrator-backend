from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class UsageRecord:
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    call_type: str          # "complete" | "embed"
    timestamp: datetime = field(default_factory=datetime.utcnow)


class TokenTracker:
    def __init__(self) -> None:
        self._records: list[UsageRecord] = []

    def record(
        self,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        call_type: str = "complete",
    ) -> None:
        self._records.append(
            UsageRecord(provider, model, input_tokens, output_tokens, call_type)
        )

    @property
    def total_calls(self) -> int:
        return len(self._records)

    @property
    def total_input_tokens(self) -> int:
        return sum(r.input_tokens for r in self._records)

    @property
    def total_output_tokens(self) -> int:
        return sum(r.output_tokens for r in self._records)

    @property
    def mock_calls(self) -> int:
        return sum(1 for r in self._records if r.provider == "mock")

    def summary(self) -> dict:
        by_provider: dict = {}
        for r in self._records:
            entry = by_provider.setdefault(
                r.provider, {"calls": 0, "input_tokens": 0, "output_tokens": 0}
            )
            entry["calls"] += 1
            entry["input_tokens"] += r.input_tokens
            entry["output_tokens"] += r.output_tokens
        return {
            "total_calls": self.total_calls,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "mock_calls": self.mock_calls,
            "by_provider": by_provider,
        }

    def reset(self) -> None:
        self._records.clear()
