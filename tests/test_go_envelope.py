import pytest

from krex._http import _normalize_go_payload
from krex.exceptions import KrexParseError


@pytest.mark.parametrize("wrapped", [False, True])
def test_standard_envelopes(wrapped):
    envelope = {
        "header": {"resultCode": "00", "resultMsg": "NORMAL SERVICE."},
        "body": {"items": {"item": [{"entrpsNm": "휴게소", "roadRouteNo": "001"}]},
                 "numOfRows": 1, "pageNo": 1, "totalCount": 210},
    }
    payload = {"response": envelope} if wrapped else envelope
    result = _normalize_go_payload(payload, params={})
    assert result.items == [{"entrpsNm": "휴게소", "roadRouteNo": "001"}]
    assert (result.page_no, result.num_of_rows, result.total_count) == (1, 1, 210)
    assert result.raw is payload


@pytest.mark.parametrize("payload", [{}, {"response": None}, {"header": []}])
def test_malformed_envelope_is_rejected(payload):
    with pytest.raises(KrexParseError):
        _normalize_go_payload(payload, params={})
