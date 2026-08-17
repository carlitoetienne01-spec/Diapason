"""Tests for the calculator tool."""

from __future__ import annotations

import math

import pytest

from diapason.tools.calculator import CalculatorTool, safe_eval


class TestSafeEval:
    def test_addition(self):
        assert safe_eval("2 + 3") == 5

    def test_subtraction(self):
        assert safe_eval("10 - 3") == 7

    def test_multiplication(self):
        assert safe_eval("4 * 5") == 20

    def test_division(self):
        assert safe_eval("10 / 4") == 2.5

    def test_floor_division(self):
        assert safe_eval("floor(10/3)") == 3

    def test_modulo(self):
        assert safe_eval("10 % 3") == 1

    def test_power(self):
        assert safe_eval("2^10") == 1024

    def test_negative(self):
        assert safe_eval("-5 + 3") == -2

    def test_nested_expressions(self):
        assert safe_eval("(2 + 3) * (4 - 1)") == 15

    def test_sqrt(self):
        assert safe_eval("sqrt(16)") == 4.0

    def test_log(self):
        assert abs(safe_eval("ln(e)") - 1.0) < 1e-10

    def test_pi_constant(self):
        assert abs(safe_eval("pi") - math.pi) < 1e-10

    def test_trig(self):
        assert abs(safe_eval("sin(0)")) < 1e-10
        assert abs(safe_eval("cos(0)") - 1.0) < 1e-10

    def test_division_by_zero(self):
        # Was: asserted ``== math.inf``, describing the Rust backend rather
        # than requiring anything. Dividing by zero has no answer, and the
        # caller's own "division by zero" branch was unreachable while this
        # returned a float.
        with pytest.raises(ZeroDivisionError):
            safe_eval("1 / 0")

    def test_syntax_error(self):
        with pytest.raises(ValueError):
            safe_eval("2 +")

    def test_unsupported_string_constant(self):
        with pytest.raises(ValueError):
            safe_eval("'hello'")

    def test_unknown_function(self):
        with pytest.raises(ValueError, match="Unknown function"):
            safe_eval("exec(1)")

    def test_unknown_variable(self):
        with pytest.raises(ValueError, match="unknown variable"):
            safe_eval("x + 1")


class TestCalculatorTool:
    def test_spec(self):
        tool = CalculatorTool()
        assert tool.spec.name == "calculator"
        assert tool.spec.category == "math"

    def test_basic_math(self):
        tool = CalculatorTool()
        result = tool.execute(expression="2 + 3 * 4")
        assert result.success is True
        assert result.content == "14.0"

    def test_empty_expression(self):
        tool = CalculatorTool()
        result = tool.execute(expression="")
        assert result.success is False

    def test_no_expression(self):
        tool = CalculatorTool()
        result = tool.execute()
        assert result.success is False

    def test_division_by_zero_error(self):
        """A tool result the model reads as a number will be reported as one.

        ``success=True`` with content ``"inf"`` is how the assistant came to
        answer "inf" to « je partage la note entre 0 personnes » instead of
        saying the question has no answer.
        """
        tool = CalculatorTool()
        result = tool.execute(expression="1/0")
        assert result.success is False
        assert "division by zero" in result.content

    @pytest.mark.parametrize(
        "expression",
        ["0/0", "10/(5-5)", "log(0)", "1e308*10"],
    )
    def test_no_result_is_ever_infinite_or_nan(self, expression):
        """Every route to a non-finite float, not just ZeroDivisionError.

        Overflow and log(0) never raise — they arrive as inf/nan through the
        ordinary success path, which is why a guard on the value itself is
        needed alongside the exception handlers.
        """
        result = CalculatorTool().execute(expression=expression)
        assert result.success is False
        assert result.content.lower().strip() not in {"inf", "-inf", "nan"}

    def test_ordinary_arithmetic_still_succeeds(self):
        """The guard must not turn real answers into failures."""
        for expression, expected in (("2+2", 4.0), ("3/4", 0.75), ("sqrt(16)", 4.0)):
            result = CalculatorTool().execute(expression=expression)
            assert result.success is True, expression
            assert float(result.content) == expected

    def test_invalid_expression_error(self):
        tool = CalculatorTool()
        result = tool.execute(expression="import os")
        assert result.success is False

    def test_openai_function_format(self):
        tool = CalculatorTool()
        fn = tool.to_openai_function()
        assert fn["function"]["name"] == "calculator"
        assert "expression" in fn["function"]["parameters"]["properties"]
