from pydantic import BaseModel


class CompletionResponse(BaseModel):
    content: str
    input_tokens: int = 0
    output_tokens: int = 0
    provider: str
    model: str
    from_mock: bool = False
