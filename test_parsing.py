import unittest
from pydantic import ValidationError
from typing import List

# Mocking parts of app.py for testing without full dependencies
class AnalystResponse:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

class ReviewerResponse:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

# Use the actual classes if we can import them, but we saw it fails due to missing dependencies in the env
# So I'll just test the logic by trying to import them and catching the error if it's just missing deps.

class TestPydanticModels(unittest.TestCase):
    def test_analyst_response_validation(self):
        try:
            from app import AnalystResponse
        except ImportError:
            self.skipTest("Dependencies not installed in this environment")

        valid_data = {
            "should_proceed": True,
            "issue_type": "code_request",
            "analysis": "Test analysis",
            "files_to_change": ["file1.py"],
            "plan": ["Step 1"],
            "coder_instructions": "Do something",
            "risks": ["Risk 1"],
            "estimated_complexity": "low"
        }
        model = AnalystResponse(**valid_data)
        self.assertEqual(model.should_proceed, True)

        invalid_data = valid_data.copy()
        del invalid_data["should_proceed"]
        with self.assertRaises(ValidationError):
            AnalystResponse(**invalid_data)

    def test_reviewer_response_validation(self):
        try:
            from app import ReviewerResponse
        except ImportError:
            self.skipTest("Dependencies not installed in this environment")

        valid_data = {
            "approved": True,
            "score": 8,
            "positives": ["Good"],
            "issues": [],
            "suggestions": [],
            "project_compliance": True,
            "security_ok": True,
            "verdict": "APPROVE",
            "labels": ["enhancement"]
        }
        model = ReviewerResponse(**valid_data)
        self.assertEqual(model.verdict, "APPROVE")

        invalid_data = valid_data.copy()
        invalid_data["score"] = "not an int"
        with self.assertRaises(ValidationError):
            ReviewerResponse(**invalid_data)

if __name__ == "__main__":
    unittest.main()
