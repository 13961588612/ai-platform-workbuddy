"""Tests for backend/src/api/response.py — unified API response format."""

from __future__ import annotations

import uuid

import pytest

from src.api.response import error, error_response, success, success_response


class TestSuccessResponse:
    """Tests for the success() helper."""

    def test_success_default(self):
        """success() with no args should have code=0, data=None, message='success'."""
        resp = success()
        assert resp["code"] == 0
        assert resp["data"] is None
        assert resp["message"] == "success"
        assert "traceId" in resp
        assert resp["traceId"] == ""

    def test_success_with_data(self):
        """success() should include the provided data payload."""
        data = {"user_id": 123, "name": "alice"}
        resp = success(data=data)
        assert resp["code"] == 0
        assert resp["data"] == data

    def test_success_with_custom_message(self):
        """success() should accept a custom message."""
        resp = success(message="created")
        assert resp["message"] == "created"

    def test_success_with_trace_id(self):
        """success() should include the provided traceId."""
        tid = str(uuid.uuid4())
        resp = success(trace_id=tid)
        assert resp["traceId"] == tid

    def test_success_data_can_be_list(self):
        """success() should handle list data."""
        resp = success(data=[1, 2, 3])
        assert resp["data"] == [1, 2, 3]


class TestErrorResponse:
    """Tests for the error() helper."""

    def test_error_basic(self):
        """error() should have non-zero code and the provided message."""
        resp = error(code=4001, message="Bad request")
        assert resp["code"] == 4001
        assert resp["message"] == "Bad request"
        assert resp["data"] is None
        assert "traceId" in resp

    def test_error_with_trace_id(self):
        """error() should include the provided traceId."""
        tid = str(uuid.uuid4())
        resp = error(code=5000, message="Internal error", trace_id=tid)
        assert resp["traceId"] == tid

    def test_error_with_data(self):
        """error() should support optional data payload."""
        resp = error(code=4001, message="Validation failed", data={"field": "email"})
        assert resp["data"] == {"field": "email"}


class TestSuccessResponseObject:
    """Tests for success_response() returning JSONResponse."""

    def test_success_response_status_code(self):
        """success_response() should return HTTP 200."""
        resp = success_response(data={"ok": True})
        assert resp.status_code == 200

    def test_success_response_content(self):
        """success_response() body should contain code=0."""
        resp = success_response(data={"ok": True}, message="done")
        import json
        body = json.loads(resp.body)
        assert body["code"] == 0
        assert body["data"] == {"ok": True}
        assert body["message"] == "done"


class TestErrorResponseObject:
    """Tests for error_response() returning JSONResponse."""

    def test_error_response_default_http_status(self):
        """error_response() should default to HTTP 400."""
        resp = error_response(code=4001, message="Bad")
        assert resp.status_code == 400

    def test_error_response_custom_http_status(self):
        """error_response() should accept a custom HTTP status."""
        resp = error_response(code=5000, message="Server error", http_status=500)
        assert resp.status_code == 500

    def test_error_response_content(self):
        """error_response() body should contain the error code and message."""
        resp = error_response(code=4001, message="Not found")
        import json
        body = json.loads(resp.body)
        assert body["code"] == 4001
        assert body["message"] == "Not found"


class TestTraceIdUniqueness:
    """Verify that trace IDs can be used as unique correlation identifiers."""

    def test_trace_id_is_string(self):
        """traceId field should always be a string."""
        resp = success(trace_id="abc-123")
        assert isinstance(resp["traceId"], str)

    def test_multiple_trace_ids_unique(self):
        """Generate multiple trace IDs and verify uniqueness."""
        ids = {str(uuid.uuid4()) for _ in range(100)}
        assert len(ids) == 100  # all unique
