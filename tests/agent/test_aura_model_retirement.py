"""Retired Gemini routes produce a model error, with no inference/network calls."""
import httpx

from agent.error_classifier import classify_api_error, FailoverReason
from agent.error_surface import build_error_surface_from_exception
from agent.gemini_native_adapter import gemini_http_error


def test_native_gemini_404_is_a_terminal_model_error():
    response = httpx.Response(404, request=httpx.Request('POST', 'https://generativelanguage.googleapis.com/v1beta/models/retired:generateContent'),
                              json={'error': {'code': 404, 'status': 'NOT_FOUND', 'message':
                                    'This model models/gemini-2.5-flash is no longer available to new users. '
                                    'Please update your code to use a newer model, such as gemini-3.8-flash.'}})
    error = gemini_http_error(response)
    verdict = classify_api_error(error, provider='gemini', model='gemini-2.5-flash')
    assert verdict.reason == FailoverReason.model_not_found and verdict.retryable is False
    surface = build_error_surface_from_exception(error, provider='gemini', model='gemini-2.5-flash')
    assert surface['code'] == 'model_not_found' and surface['retryable'] is False
    assert surface['layer'] == 'provider'


def test_bare_custom_endpoint_404_still_does_not_claim_a_retired_model():
    error = httpx.HTTPStatusError('Not Found', request=httpx.Request('POST', 'https://example.com/wrong-path'),
                                response=httpx.Response(404))
    verdict = classify_api_error(error, provider='custom', model='example')
    assert verdict.reason == FailoverReason.unknown
