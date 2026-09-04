import json
import logging
import re
from typing import TypeVar
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


def extract_json_block(raw_text: str) -> str:
    """Extract a JSON object or array from markdown code fences or raw string."""
    cleaned = raw_text.strip()
    # Match ```json ... ``` or ``` ... ```
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", cleaned, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return cleaned


def validate_structured_output(raw_output: str | dict, schema_cls: type[T]) -> T:
    """Parse JSON and validate into the specified Pydantic model.
    
    Raises:
        ValueError: If JSON is invalid or fails schema validation.
    """
    if isinstance(raw_output, dict):
        data = raw_output
    elif isinstance(raw_output, str):
        json_str = extract_json_block(raw_output)
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as err:
            logger.error("Failed to decode JSON from model output: %s", err)
            raise ValueError(f"Model output is not valid JSON: {err}") from err
    else:
        raise ValueError(f"Unsupported model output type: {type(raw_output)}")

    try:
        return schema_cls.model_validate(data)
    except ValidationError as err:
        logger.error("Schema validation failed for %s: %s", schema_cls.__name__, err)
        raise ValueError(f"Schema validation failed for {schema_cls.__name__}: {err}") from err
