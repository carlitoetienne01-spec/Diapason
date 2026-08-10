"""Dictation finalize API — polish + dictionary + voice-command routing."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field


class DictationFinalizeRequest(BaseModel):
    text: str = Field(..., description="Raw STT transcript")
    polish: bool = True
    llm_polish: Optional[bool] = Field(
        default=None,
        description="Override config; None = use [dictation].llm_polish",
    )
    email_mode: Optional[bool] = Field(
        default=None,
        description="Use email-aware LLM polish when llm_polish is on",
    )
    use_dictionary: Optional[bool] = Field(
        default=None,
        description="Apply user dictation dictionary on paste path",
    )


class DictionaryEntryIn(BaseModel):
    word: str
    original_word: str = ""
    replacements: List[str] = Field(default_factory=list)
    pronunciation: str = ""
    context: str = ""
    locale: str = ""
    id: str = ""
    usage_count: int = 0


class DictionaryLearnRequest(BaseModel):
    original: str = Field(..., description="Raw STT / before edit")
    corrected: str = Field(..., description="User-corrected text")
    locale: str = ""


def create_dictation_router() -> APIRouter:
    router = APIRouter(prefix="/v1/dictation", tags=["dictation"])

    @router.post("/finalize")
    def finalize(body: DictationFinalizeRequest) -> Dict[str, Any]:
        from diapason.desktop.voice_commands import finalize_dictation

        return finalize_dictation(
            body.text,
            polish=body.polish,
            llm_polish=body.llm_polish,
            email_mode=body.email_mode,
            use_dictionary=body.use_dictionary,
        )

    @router.post("/polish")
    def polish_only(body: DictationFinalizeRequest) -> Dict[str, Any]:
        from diapason.speech.dictate_polish import polish_pipeline

        use_dict = True if body.use_dictionary is None else bool(body.use_dictionary)
        use_llm = False if body.llm_polish is None else bool(body.llm_polish)
        text = polish_pipeline(
            body.text,
            polish=body.polish,
            use_dictionary=use_dict,
            llm_polish=use_llm,
            email_mode=bool(body.email_mode),
        )
        return {"text": text, "original": body.text}

    @router.get("/dictionary")
    def get_dictionary() -> Dict[str, Any]:
        from diapason.speech.dictation_dictionary import dictionary_to_api

        return dictionary_to_api()

    @router.post("/dictionary")
    def put_dictionary_entry(body: DictionaryEntryIn) -> Dict[str, Any]:
        from diapason.speech.dictation_dictionary import DictionaryEntry, upsert_entry

        entry = upsert_entry(
            DictionaryEntry(
                id=body.id,
                word=body.word,
                original_word=body.original_word,
                replacements=list(body.replacements or []),
                pronunciation=body.pronunciation,
                context=body.context,
                locale=body.locale,
                usage_count=body.usage_count,
            )
        )
        return {"ok": True, "entry": entry.__dict__}

    @router.post("/dictionary/learn")
    def learn_dictionary(body: DictionaryLearnRequest) -> Dict[str, Any]:
        """Learn replacements from an STT → corrected text pair."""
        from diapason.speech.dictation_dictionary import learn_from_correction

        entries = learn_from_correction(
            body.original, body.corrected, locale=body.locale or ""
        )
        return {
            "ok": True,
            "learned": len(entries),
            "entries": [e.__dict__ for e in entries],
        }

    return router
