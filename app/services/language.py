DEFAULT_LANGUAGE = "en"

LANGUAGE_NAMES = {
    "en": "English",
    "ur": "Urdu",
    "hi": "Hindi",
    "ar": "Arabic",
    "pa": "Punjabi",
    "bn": "Bengali",
    "fr": "French",
    "es": "Spanish",
}

NON_ENGLISH = {
    "ur", "hi", "ar", "pa", "bn", "ta", "te", "mr", "gu",
    "fr", "es", "de", "tr", "fa", "ps", "sd", "ne",
}


def resolve_language(detected: str | None, session_lang: str | None = None) -> str:
    """Default English. Switch only when user clearly speaks another language."""
    code = (detected or "").lower().split("-")[0]

    if code in NON_ENGLISH:
        return code

    if session_lang and session_lang != DEFAULT_LANGUAGE and session_lang in NON_ENGLISH:
        return session_lang

    return DEFAULT_LANGUAGE
